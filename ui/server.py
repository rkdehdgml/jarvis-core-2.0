"""FastAPI + WebSocket 로컬 웹서버.

core/status_events.py 의 StatusBroadcaster 가 발행하는 이벤트를
프론트엔드에 실시간으로 중계만 한다. 본체 로직은 건드리지 않는다.

실행:
    uvicorn ui.server:app --host 127.0.0.1 --port 8765

main.py 와 같은 프로세스에서 띄우려면 main.py 에서 uvicorn.Server를
별도 스레드/asyncio 태스크로 실행하면 된다 (이 파일은 건드리지 않음).
"""
import asyncio
import logging
import shutil
from contextlib import asynccontextmanager

import psutil
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.context import ConversationContext
from core.dispatcher import Dispatcher
from core.input_channel import normalize_input
from core.registry import SkillRegistry
from core.router import Router
from core.status_events import StatusEvent, broadcaster
from core.usage import get_today_percent

logger = logging.getLogger(__name__)

_registry = SkillRegistry()
_router = Router(_registry)
_dispatcher = Dispatcher(_registry)
_chat_context = ConversationContext()
_clients: set[WebSocket] = set()
_loop: asyncio.AbstractEventLoop | None = None


class ChatRequest(BaseModel):
    text: str


class ChatResponse(BaseModel):
    speech: str
    success: bool


def _event_to_dict(event: StatusEvent) -> dict:
    return {
        "state": event.state,
        "lastResponse": event.last_response,
        "timestamp": event.timestamp,
    }


def _check_engine() -> bool:
    """Claude Code CLI가 PATH에서 발견되는지로 엔진 연결 여부를 판단한다."""
    return shutil.which("claude") is not None


def _system_info() -> dict:
    return {
        "cpuPercent": psutil.cpu_percent(interval=None),
        "memoryPercent": psutil.virtual_memory().percent,
    }


async def _broadcast(event: StatusEvent) -> None:
    payload = _event_to_dict(event)
    dead: list[WebSocket] = []
    for ws in _clients:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _clients.discard(ws)


def _on_status_event(event: StatusEvent) -> None:
    """StatusBroadcaster가 호출하는 동기 콜백.

    emit()이 어느 스레드에서 호출되든 안전하게 이벤트 루프에 브로드캐스트를
    예약한다 (main.py의 동기 루프와 uvicorn의 asyncio 루프가 분리되어 있을 수 있음).
    """
    if _loop is None:
        return
    asyncio.run_coroutine_threadsafe(_broadcast(event), _loop)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _loop
    _loop = asyncio.get_running_loop()
    broadcaster.subscribe(_on_status_event)
    logger.info("UI 서버: 상태 브로드캐스터 구독 시작")
    yield
    broadcaster.unsubscribe(_on_status_event)


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    _clients.add(websocket)

    # 연결 즉시 현재 상태를 한 번 보낸다.
    await websocket.send_json(_event_to_dict(broadcaster.get_current()))

    try:
        while True:
            # 클라이언트는 보통 메시지를 보내지 않지만, 연결 유지를 위해 수신 대기.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(websocket)


@app.get("/api/status")
def get_status() -> dict:
    """현재 상태 스냅샷을 REST로 조회한다."""
    event = broadcaster.get_current()
    return {
        **_event_to_dict(event),
        "engineStatus": _check_engine(),
        "activeSkills": [s.name for s in _registry.get_all_skills()],
        "systemInfo": _system_info(),
        "usageToday": get_today_percent(),
    }


def _handle_chat(text: str) -> ChatResponse:
    event = normalize_input(text, channel="chat")
    skill = _router.route(event.text)
    result = _dispatcher.dispatch(skill, event.text, _chat_context, channel=event.channel)
    # Dispatcher가 broadcaster.emit(state="responded", ...)을 이미 호출하므로
    # 연결된 모든 WebSocket 클라이언트에 동일한 응답이 자동으로 push된다.
    return ChatResponse(speech=result.speech, success=result.success)


@app.post("/api/chat", response_model=ChatResponse)
async def post_chat(req: ChatRequest) -> ChatResponse:
    """채팅 입력을 받아 처리한다. channel="chat"이므로 TTS는 호출되지 않는다."""
    return await asyncio.to_thread(_handle_chat, req.text)
