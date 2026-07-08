"""ListenState 전환 헬퍼(4-C) 배선 검증.

_transition()이 상태에 맞는 broadcaster 이벤트를 emit하는지만 확인한다.
실제 음성 루프(_run_voice_loop)는 마이크/모델이 필요해 자동 테스트 대상
밖 — 수동 검증으로 남긴다(계획 문서 "수동 검증" 절 참고).

실행: python -m tests.test_listen_state (프로젝트 루트에서)
"""
import main as jarvis_main
from core.status_events import broadcaster


def test_transition_to_idle_emits_idle() -> None:
    events = []
    original_emit = broadcaster.emit
    broadcaster.emit = lambda **kwargs: events.append(kwargs)
    try:
        result = jarvis_main._transition(jarvis_main.ListenState.IDLE)
    finally:
        broadcaster.emit = original_emit

    assert result is jarvis_main.ListenState.IDLE
    assert events == [{"state": "idle"}], f"IDLE 전환은 'idle' 이벤트를 emit해야 함, got {events!r}"


def test_transition_to_conversing_emits_listening() -> None:
    events = []
    original_emit = broadcaster.emit
    broadcaster.emit = lambda **kwargs: events.append(kwargs)
    try:
        result = jarvis_main._transition(jarvis_main.ListenState.CONVERSING)
    finally:
        broadcaster.emit = original_emit

    assert result is jarvis_main.ListenState.CONVERSING
    assert events == [{"state": "listening"}], (
        f"CONVERSING 전환은 'listening' 이벤트를 emit해야 함, got {events!r}"
    )


def main() -> None:
    tests = [
        test_transition_to_idle_emits_idle,
        test_transition_to_conversing_emits_listening,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print("\nListenState 전환 배선 검증 통과")


if __name__ == "__main__":
    main()
