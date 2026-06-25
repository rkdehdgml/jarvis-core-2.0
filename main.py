"""jarvis-core 진입점.

기본값은 음성 모드다: "자비스"(Hey Jarvis) 웨이크워드 대기 → STT → 라우팅/실행 → TTS.
--text 플래그를 주면 마이크 없이 콘솔 텍스트로 동일한 파이프라인을 탈 수 있다
(디버그용이자, 마이크 인식이 막혔을 때의 수동 대체 경로).
"""
import argparse
import logging

from core.chat_history import clear_history
from core.context import ConversationContext
from core.dispatcher import Dispatcher
from core.input_channel import normalize_input
from core.registry import SkillRegistry
from core.router import Router
from core.status_events import broadcaster
from voice.text_input import get_input

logger = logging.getLogger(__name__)

_EXIT_WORD = "종료"
# "자비스 오프"/"자비스 종료"(공백 유무·뒤에 "해줘" 등이 붙는 것은 허용)로 상시 음성인식을
# 해제한다. "자비스 크롬 종료해줘"처럼 사이에 다른 말이 끼면 startswith가 막아주므로
# skill_app_control의 "종료" 트리거와 충돌하지 않는다.
_DEACTIVATE_PHRASES = ("자비스오프", "자비스종료")

# "채팅 목록 지워줘"류 음성 명령 — 동사와 대상이 같이 있어야 매치된다("이 파일
# 지워줘"처럼 대상이 없는 일반 삭제 요청과 구분하기 위함).
_CLEAR_HISTORY_VERBS = ("지워줘", "지워주세요", "삭제해줘", "비워줘", "초기화해줘")
_CLEAR_HISTORY_TARGETS = ("채팅", "대화", "기록", "목록")


def _is_deactivate_command(text: str) -> bool:
    normalized = text.replace(" ", "")
    return any(normalized.startswith(phrase) for phrase in _DEACTIVATE_PHRASES)


def _is_clear_history_command(text: str) -> bool:
    has_verb = any(v in text for v in _CLEAR_HISTORY_VERBS)
    has_target = any(t in text for t in _CLEAR_HISTORY_TARGETS)
    return has_verb and has_target


def _clear_history(context: ConversationContext) -> None:
    """현재 프로세스의 대화 맥락과, 웹 대시보드가 읽는 공유 기록 파일을 함께 비운다.

    main.py와 ui/server.py는 별도 프로세스라 메모리는 공유하지 않지만,
    data/chat_history.json은 둘 다 같은 파일을 보므로 "채팅 목록"을 지운다는
    말의 의미를 지키려면 이 파일도 같이 비워야 한다. 단, 이미 열려 있는 웹
    브라우저 탭은 새로고침하기 전까진 실시간으로 반영되지 않는다(두 프로세스
    사이에 별도 통신 채널이 없음 — 알려진 제약).
    """
    context.clear()
    clear_history()


def _run_text_loop(router: Router, dispatcher: Dispatcher, context: ConversationContext) -> None:
    print(f"자비스가 준비됐습니다. ('{_EXIT_WORD}'을 입력하면 종료)")
    broadcaster.emit(state="idle")

    while True:
        broadcaster.emit(state="listening")
        text = get_input()

        if not text:
            continue
        if text == _EXIT_WORD:
            print("자비스를 종료합니다.")
            broadcaster.emit(state="idle")
            break

        if _is_clear_history_command(text):
            _clear_history(context)
            print("대화 기록을 지웠습니다.")
            continue

        event = normalize_input(text, channel="voice")
        skill = router.route(event.text)
        result = dispatcher.dispatch(skill, event.text, context, channel=event.channel)
        print(result.speech)


def _run_voice_loop(router: Router, dispatcher: Dispatcher, context: ConversationContext) -> None:
    # 모델 로딩이 무거워 음성 모드를 실제로 쓸 때만 import한다.
    from voice import stt, tts, wakeword

    print(
        '자비스가 준비됐습니다. "자비스" 또는 박수 2번으로 음성인식을 켜고, '
        '"자비스 오프"/"자비스 종료"로 끌 수 있습니다. (Ctrl+C로 프로그램 종료)'
    )
    broadcaster.emit(state="idle")

    # 활성화(웨이크워드/박수) 후에는 follow_up 여부와 무관하게 상시 듣는다.
    # 해제는 오직 _is_deactivate_command 발화로만 일어난다.
    active = False
    try:
        while True:
            if not active:
                trigger = wakeword.wait_for_activation()
                logger.info(f"음성인식 활성화 (트리거: {trigger})")
                active = True

            broadcaster.emit(state="listening")
            text = stt.listen()

            if not text:
                # 상시 모드: 침묵/타임아웃이어도 비활성화하지 않고 계속 듣는다.
                continue

            if _is_deactivate_command(text):
                tts.speak("음성인식을 종료합니다.")
                active = False
                broadcaster.emit(state="idle")
                continue

            if text == _EXIT_WORD:
                tts.speak("자비스를 종료합니다.")
                broadcaster.emit(state="idle")
                break

            if _is_clear_history_command(text):
                _clear_history(context)
                tts.speak("대화 기록을 지웠습니다.")
                continue

            event = normalize_input(text, channel="voice")
            skill = router.route(event.text)
            result = dispatcher.dispatch(skill, event.text, context, channel=event.channel)

            tts.speak(result.speech)
    except KeyboardInterrupt:
        print("\n자비스를 종료합니다.")
        broadcaster.emit(state="idle")


def main() -> None:
    parser = argparse.ArgumentParser(description="jarvis-core")
    parser.add_argument(
        "--text", action="store_true", help="마이크 없이 콘솔 텍스트 입출력으로 실행"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    registry = SkillRegistry()
    router = Router(registry)
    dispatcher = Dispatcher(registry)
    context = ConversationContext()

    if args.text:
        _run_text_loop(router, dispatcher, context)
    else:
        _run_voice_loop(router, dispatcher, context)


if __name__ == "__main__":
    main()
