"""jarvis-core2.0 WebSocket 메시지 전송 유틸리티.

Claude Code 훅에서 호출:
  python hooks/jarvis_send.py <type> <message>

type 예시:
  tool_action  — PreToolUse/PostToolUse 툴 동작 알림 (UI 진행 표시)
  output       — Stop 훅 최종 응답 알림

UI 서버(port 8765)가 꺼져 있어도 조용히 종료 — 훅 실패로 Claude 실행을 막지 않는다.
"""
import asyncio
import json
import sys


async def send(msg_type: str, value: str) -> None:
    try:
        import websockets  # type: ignore
        uri = "ws://127.0.0.1:8765/ws"
        async with websockets.connect(uri, open_timeout=2) as ws:
            await ws.send(json.dumps({"type": msg_type, "value": value[:500]}))
            await asyncio.sleep(0.05)
    except Exception:
        pass


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(0)
    asyncio.run(send(sys.argv[1], " ".join(sys.argv[2:])))
