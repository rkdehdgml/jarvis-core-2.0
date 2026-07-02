"""ui/server.py 훅 메시지 WebSocket 브로드캐스트 검증 (plain assert 스크립트).

FastAPI TestClient로 실제 uvicorn 기동 없이 두 WebSocket 클라이언트를 연결해,
한쪽이 보낸 tool_action 메시지를 다른 쪽이 그대로 수신하는지 확인한다.

실행: python -m tests.test_ui_hook_broadcast  (프로젝트 루트에서)
"""
from fastapi.testclient import TestClient

from ui.server import app


def main() -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as browser_ws, \
             client.websocket_connect("/ws") as hook_ws:
            # 연결 직후 각자 현재 상태 스냅샷을 한 번씩 받는다 (기존 동작).
            browser_ws.receive_json()
            hook_ws.receive_json()

            hook_ws.send_text('{"type": "tool_action", "value": "웹 검색 중: 날씨"}')

            received = browser_ws.receive_json()
            assert received["type"] == "tool_action", received
            assert received["value"] == "웹 검색 중: 날씨", received

            # 알 수 없는 타입은 무시되어 아무 것도 도착하지 않아야 한다 —
            # output 타입으로 한 번 더 보내 정상 케이스만 확인.
            hook_ws.send_text('{"type": "output", "value": "작업 완료"}')
            received2 = browser_ws.receive_json()
            assert received2["type"] == "output", received2
            assert received2["value"] == "작업 완료", received2

    print("\ntest_ui_hook_broadcast 검증 통과")


if __name__ == "__main__":
    main()
