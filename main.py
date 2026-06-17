"""jarvis-core 진입점.

기본값은 음성 모드다: "자비스"(Hey Jarvis) 웨이크워드 대기 → STT → 라우팅/실행 → TTS.
--text 플래그를 주면 마이크 없이 콘솔 텍스트로 동일한 파이프라인을 탈 수 있다
(디버그용이자, 마이크 인식이 막혔을 때의 수동 대체 경로).
"""
import argparse
import logging

from core.context import ConversationContext
from core.dispatcher import Dispatcher
from core.input_channel import normalize_input
from core.registry import SkillRegistry
from core.router import Router
from core.status_events import broadcaster
from voice.text_input import get_input

_EXIT_WORD = "종료"


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

        event = normalize_input(text, channel="voice")
        skill = router.route(event.text)
        result = dispatcher.dispatch(skill, event.text, context, channel=event.channel)
        print(result.speech)


def _run_voice_loop(router: Router, dispatcher: Dispatcher, context: ConversationContext) -> None:
    # 모델 로딩이 무거워 음성 모드를 실제로 쓸 때만 import한다.
    from voice import stt, tts, wakeword

    print('자비스가 준비됐습니다. "자비스"라고 부르면 명령을 받습니다. (Ctrl+C로 종료)')
    broadcaster.emit(state="idle")

    listen_directly = False
    try:
        while True:
            if not listen_directly:
                wakeword.wait_for_wakeword()

            broadcaster.emit(state="listening")
            text = stt.listen()

            if not text:
                listen_directly = False
                broadcaster.emit(state="idle")
                continue

            if text == _EXIT_WORD:
                tts.speak("자비스를 종료합니다.")
                broadcaster.emit(state="idle")
                break

            event = normalize_input(text, channel="voice")
            skill = router.route(event.text)
            result = dispatcher.dispatch(skill, event.text, context, channel=event.channel)

            tts.speak(result.speech)

            # follow_up이면 웨이크워드 없이 바로 다음 발화를 듣는다.
            listen_directly = result.follow_up
            if not listen_directly:
                broadcaster.emit(state="idle")
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
