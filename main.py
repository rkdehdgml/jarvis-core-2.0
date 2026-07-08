"""jarvis-core 진입점.

기본값은 음성 모드다: "자비스"(Hey Jarvis) 웨이크워드 대기 → STT → 라우팅/실행 → TTS.
--text 플래그를 주면 마이크 없이 콘솔 텍스트로 동일한 파이프라인을 탈 수 있다
(디버그용이자, 마이크 인식이 막혔을 때의 수동 대체 경로).

웹 대시보드(ui/server.py)는 기본으로 같은 프로세스 내 데몬 스레드에서 실행된다.
같은 프로세스이므로 core/status_events.py 의 broadcaster를 공유하며,
음성/텍스트 루프에서 emit()한 이벤트가 WebSocket을 통해 브라우저에 실시간 반영된다.
--no-web 플래그로 웹 서버 없이 실행할 수 있다.
"""
import argparse
from enum import Enum, auto
import logging
import sys
import threading

import uvicorn

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
_DEACTIVATE_PHRASES = ("자비스오프", "자비스종료")
_CLEAR_HISTORY_VERBS = ("지워줘", "지워주세요", "삭제해줘", "비워줘", "초기화해줘")
_CLEAR_HISTORY_TARGETS = ("채팅", "대화", "기록", "목록")

_WEB_HOST = "127.0.0.1"
_WEB_PORT = 8765


class ListenState(Enum):
    """main.py가 실제로 관찰 가능한 음성 루프 상태만 다룬다.

    WhisperFlow 원형의 BOOT_WAIT(모델 로딩)/SPEECH(VAD 발화 경계)는
    각각 wakeword.py/stt.py 내부에 갇혀 있어 main.py 레벨에서 구분할 수
    없다 — 이 두 파일을 건드리는 건 이번 리팩토링 범위 밖(설계 문서 참고).
    """
    IDLE = auto()        # 웨이크워드/박수 트리거 대기 중
    CONVERSING = auto()  # 깨어난 뒤 명령을 듣고 처리하는 중, 재웨이크워드 불필요


def _transition(state: ListenState) -> ListenState:
    """상태를 기록하고 대응하는 broadcaster 이벤트를 emit한 뒤 그대로 반환한다."""
    broadcaster.emit(state="idle" if state is ListenState.IDLE else "listening")
    return state


def _is_deactivate_command(text: str) -> bool:
    normalized = text.replace(" ", "")
    return any(normalized.startswith(phrase) for phrase in _DEACTIVATE_PHRASES)


def _is_clear_history_command(text: str) -> bool:
    has_verb = any(v in text for v in _CLEAR_HISTORY_VERBS)
    has_target = any(t in text for t in _CLEAR_HISTORY_TARGETS)
    return has_verb and has_target


def _clear_history(context: ConversationContext) -> None:
    """대화 맥락과 기록 파일을 함께 비운다.

    웹 대시보드가 같은 프로세스에서 실행되므로 broadcaster 공유로 음성 결과가
    자동으로 웹에 반영된다. 단, 웹 챗의 ConversationContext(ui/server.py의
    _chat_context)는 별도 인스턴스라 브라우저에서 /clear 입력 또는 새로고침으로
    반영된다.
    """
    context.clear()
    clear_history()


def _start_webserver() -> None:
    """uvicorn을 백그라운드 데몬 스레드로 실행한다.

    같은 프로세스 내 실행이므로 core/status_events.py 의 broadcaster 인스턴스를
    공유한다. 음성 루프에서 emit()한 이벤트가 ui/server.py 의 _on_status_event
    콜백을 통해 WebSocket 클라이언트에 자동 전달된다.

    uvicorn.Server를 직접 사용하고 install_signal_handlers를 비활성화한다.
    서브스레드에서 signal.signal()을 호출하면 Python의 기본 SIGINT 핸들러
    (KeyboardInterrupt)를 덮어써 Ctrl+C가 메인 스레드에 전달되지 않는 문제를 방지.
    """
    config = uvicorn.Config(
        "ui.server:app",
        host=_WEB_HOST,
        port=_WEB_PORT,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # 시그널 핸들러 탈취 방지
    server.run()


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


def _speak_with_clap_interrupt(text: str) -> None:
    """TTS 재생 중 박수 2번을 감지하면 즉시 중단한다.

    speak()가 정상 종료하든 중단되든, finally에서 stop_event를 set하고
    워처 스레드를 join해 마이크 스트림을 반드시 정리한다 — 다음 stt.listen()이
    새 입력 스트림을 열기 전에 겹치지 않도록 하기 위함.

    voice.tts/voice.clap_detector는 voice.stt(무거운 STT 스택)를 끌어오므로
    _run_voice_loop()와 마찬가지로 여기서 지연 import한다.
    """
    from voice import tts
    from voice.clap_detector import wait_for_double_clap

    stop_event = threading.Event()

    def _watch() -> None:
        if wait_for_double_clap(stop_event):
            tts.stop()

    watcher = threading.Thread(
        target=_watch, name="_speak_with_clap_interrupt-watcher", daemon=True
    )
    watcher.start()
    try:
        tts.speak(text)
    finally:
        stop_event.set()
        watcher.join()


def _run_voice_loop(router: Router, dispatcher: Dispatcher, context: ConversationContext) -> None:
    # 모델 로딩이 무거워 음성 모드를 실제로 쓸 때만 import한다.
    from voice import stt, tts, wakeword

    print(
        '자비스가 준비됐습니다. "자비스" 또는 박수 2번으로 음성인식을 켜고, '
        '"자비스 오프"/"자비스 종료"로 끌 수 있습니다. (Ctrl+C로 프로그램 종료)'
    )
    state = _transition(ListenState.IDLE)

    try:
        while True:
            if state is ListenState.IDLE:
                trigger = wakeword.wait_for_activation()
                logger.info(f"음성인식 활성화 (트리거: {trigger})")
                state = ListenState.CONVERSING

            # 이 시점에서 state는 항상 CONVERSING이다 — 매 반복 stt.listen() 전에
            # "listening"을 emit해야 하는 기존 동작(반복마다 무조건 emit)을
            # 그대로 유지하기 위해 매번 호출한다. 방금 IDLE→CONVERSING으로
            # 전환됐든, 이미 CONVERSING이던 반복이든 동일하게 emit된다.
            state = _transition(state)
            text = stt.listen()

            if not text:
                continue

            if _is_deactivate_command(text):
                tts.speak("음성인식을 종료합니다.")
                state = _transition(ListenState.IDLE)
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

            _speak_with_clap_interrupt(result.speech)
            if context.get("sleep_requested"):
                context.set("sleep_requested", False)
                state = _transition(ListenState.IDLE)
                continue
    except KeyboardInterrupt:
        print("\n자비스를 종료합니다.")
        broadcaster.emit(state="idle")


def main() -> None:
    # Windows 콘솔 코드페이지(cp949 등)로 인코딩 불가한 문자(위키백과 요약의 IPA 발음
    # 기호 등)가 스킬 응답에 섞여 들어오면 print()가 UnicodeEncodeError로 죽는다 —
    # 크래시 대신 '?'로 대체해 항상 응답을 표시하게 한다.
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
    # stdin이 실제 콘솔(interactive tty)일 때는 input()이 Windows 콘솔 API를 통해
    # 인코딩과 무관하게 정상적으로 읽으므로 이 설정은 영향이 없다. stdin이 파이프로
    # 리다이렉트된 경우(자동화 스크립트·CI 등)에만 적용되며, 이때 기본 로케일
    # 코드페이지(cp949)로 UTF-8 바이트를 읽으면 한글이 깨져 "종료" 같은 명령도
    # 문자열 일치에 실패하는 문제를 방지한다.
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="jarvis-core")
    parser.add_argument(
        "--text", action="store_true", help="마이크 없이 콘솔 텍스트 입출력으로 실행"
    )
    parser.add_argument(
        "--no-web", action="store_true", help="웹 대시보드 없이 실행"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if not args.no_web:
        web_thread = threading.Thread(
            target=_start_webserver, daemon=True, name="jarvis-web"
        )
        web_thread.start()
        print(f"웹 대시보드: http://{_WEB_HOST}:{_WEB_PORT}")

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
