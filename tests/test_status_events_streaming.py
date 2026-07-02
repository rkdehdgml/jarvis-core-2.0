"""status_events.py streaming 상태 추가 검증 (plain assert 스크립트).

실행: python -m tests.test_status_events_streaming  (프로젝트 루트에서)
"""
from core.status_events import StatusBroadcaster


def main() -> None:
    broadcaster = StatusBroadcaster()
    received = []
    broadcaster.subscribe(received.append)

    broadcaster.emit(state="streaming")

    assert len(received) == 1, received
    assert received[0].state == "streaming", received[0].state
    assert broadcaster.get_current().state == "streaming"

    print("\ntest_status_events_streaming 검증 통과")


if __name__ == "__main__":
    main()
