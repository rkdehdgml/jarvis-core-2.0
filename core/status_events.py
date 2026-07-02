import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Literal

logger = logging.getLogger(__name__)

State = Literal["idle", "listening", "processing", "streaming", "responded", "navigation_request"]


@dataclass
class StatusEvent:
    """본체의 현재 상태를 나타내는 이벤트.

    Attributes:
        state: 본체 상태 (idle | listening | processing | responded | navigation_request).
        last_response: 가장 최근 응답 텍스트. responded 상태가 아니면 None일 수 있음.
        timestamp: 이벤트 발생 시각 (Unix epoch).
        extra: 상태별 추가 데이터 (예: navigation_request 시 destination/routeType).
    """
    state: State
    last_response: str | None
    timestamp: float
    extra: dict = field(default_factory=dict)


Subscriber = Callable[[StatusEvent], None]


class StatusBroadcaster:
    """본체 상태 변화를 구독자(WebSocket 등)에게 전달한다.

    UI 레이어가 아직 없어도 콘솔 로그로 상태 변화를 확인할 수 있다.
    UI 서버(STEP 10)는 이 클래스를 구독해 WebSocket으로 중계하기만 하면 된다.
    """

    def __init__(self) -> None:
        self._subscribers: list[Subscriber] = []
        self._current: StatusEvent = StatusEvent(
            state="idle", last_response=None, timestamp=time.time()
        )

    def subscribe(self, callback: Subscriber) -> None:
        """상태 변화를 받을 콜백을 등록한다."""
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Subscriber) -> None:
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def emit(self, state: State, last_response: str | None = None, extra: dict | None = None) -> None:
        """상태 변화를 발행한다. 모든 구독자에게 즉시 전달된다."""
        event = StatusEvent(
            state=state,
            last_response=last_response,
            timestamp=time.time(),
            extra=extra or {},
        )
        self._current = event

        logger.info(f"[상태] {state}" + (f" — {last_response}" if last_response else ""))

        for callback in self._subscribers:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"상태 구독자 콜백 오류: {e}")

    def get_current(self) -> StatusEvent:
        """가장 최근 상태를 반환한다. (예: /api/status REST 스냅샷용)"""
        return self._current


# 본체 전역에서 공유하는 단일 브로드캐스터 인스턴스.
# main.py, Dispatcher, voice/* 가 모두 이 인스턴스를 import해 emit() 호출.
broadcaster = StatusBroadcaster()
