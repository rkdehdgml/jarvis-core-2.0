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
from contextlib import asynccontextmanager

import psutil
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core import chat_history
from core.context import ConversationContext
from core.dispatcher import Dispatcher
from core.input_channel import normalize_input
from core.registry import SkillRegistry
from core.router import Router
from core.status_events import StatusEvent, broadcaster

logger = logging.getLogger(__name__)

_registry = SkillRegistry()
_router = Router(_registry)
_dispatcher = Dispatcher(_registry)
_chat_context = ConversationContext()
_clients: set[WebSocket] = set()
_loop: asyncio.AbstractEventLoop | None = None

# 채팅/음성 상태 변화가 없어도 엔진/CPU/메모리/사용량을 이 주기로 비동기 push한다.
_SYSTEM_INFO_INTERVAL_SECONDS = 3

for _turn in chat_history.load_history():
    _chat_context.add_turn(
        user=_turn["user"],
        jarvis=_turn["jarvis"],
        channel=_turn.get("channel", "chat"),
        timestamp=_turn.get("timestamp"),
    )


class ChatRequest(BaseModel):
    text: str


class ChatResponse(BaseModel):
    speech: str
    success: bool
    cleared: bool = False


class HistoryTurn(BaseModel):
    role: str
    text: str
    timestamp: float


def _event_to_dict(event: StatusEvent) -> dict:
    """상태 이벤트를 WebSocket 페이로드로 변환한다.

    엔진/CPU/메모리/사용량은 채팅 상태와 무관하게 매번 새로 측정해 함께 보낸다.
    프론트엔드가 페이지 로드 시 한 번만 동기적으로 받던 값을, 모든 push마다
    (상태 변화든 주기적 틱이든) 최신값으로 비동기 갱신할 수 있게 하기 위함.
    """
    descriptor = _engine_descriptor()
    return {
        "state": event.state,
        "lastResponse": event.last_response,
        "timestamp": event.timestamp,
        "engineInfo": {
            "provider": descriptor["provider"],
            "model": descriptor["model"],
            "connected": descriptor["connected"],
        },
        "systemInfo": _system_info(),
        "usageToday": descriptor["usagePercent"],
    }


def _engine_descriptor() -> dict:
    """ai_chat 스킬이 실제로 쓰고 있는 엔진(GroqEngine 또는 ClaudeCodeEngine)의
    describe()를 가져온다. 어느 엔진이 활성인지는 skill_ai_chat.py의 import
    한 줄로 결정되므로, 여기서는 그 결과만 그대로 중계한다.
    """
    for skill in _registry.get_all_skills():
        if skill.name == "ai_chat":
            engine = getattr(skill, "_engine", None)
            if engine is not None and hasattr(engine, "describe"):
                return engine.describe()
            break
    return {"provider": "알 수 없음", "model": "-", "connected": False, "usagePercent": 0}


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


async def _system_info_loop() -> None:
    """채팅/음성 상태 변화가 없을 때도 엔진/CPU/메모리/사용량을 주기적으로 push한다."""
    while True:
        await asyncio.sleep(_SYSTEM_INFO_INTERVAL_SECONDS)
        await _broadcast(broadcaster.get_current())


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _loop
    _loop = asyncio.get_running_loop()
    broadcaster.subscribe(_on_status_event)
    system_info_task = asyncio.create_task(_system_info_loop())
    logger.info("UI 서버: 상태 브로드캐스터 구독 시작")
    yield
    system_info_task.cancel()
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
        "activeSkills": [s.name for s in _registry.get_all_skills()],
    }


_CLEAR_COMMAND = "/clear"


def _handle_chat(text: str) -> ChatResponse:
    if text.strip().lower() == _CLEAR_COMMAND:
        # 스킬 라우팅을 거치지 않고 바로 처리한다 — Dispatcher를 타면
        # broadcaster.emit(state="responded", ...)이 같이 발생해 WebSocket으로도
        # "지웠습니다" 턴이 push되면서, 지금 막 비운 conversationLog에 그 턴이
        # 다시 쌓이는 경쟁 상태가 생긴다. 그래서 이 명령은 라우터 이전에 가로챈다.
        _chat_context.clear()
        chat_history.clear_history()
        return ChatResponse(speech="대화 기록을 지웠습니다.", success=True, cleared=True)

    event = normalize_input(text, channel="chat")
    skill = _router.route(event.text)
    result = _dispatcher.dispatch(skill, event.text, _chat_context, channel=event.channel)
    # Dispatcher가 broadcaster.emit(state="responded", ...)을 이미 호출하므로
    # 연결된 모든 WebSocket 클라이언트에 동일한 응답이 자동으로 push된다.

    last_turn = _chat_context.get_history(1)[0]
    chat_history.append_turn(
        {
            "user": last_turn.user,
            "jarvis": last_turn.jarvis,
            "channel": last_turn.channel,
            "timestamp": last_turn.timestamp,
        }
    )

    return ChatResponse(speech=result.speech, success=result.success)


@app.post("/api/chat", response_model=ChatResponse)
async def post_chat(req: ChatRequest) -> ChatResponse:
    """채팅 입력을 받아 처리한다. channel="chat"이므로 TTS는 호출되지 않는다."""
    return await asyncio.to_thread(_handle_chat, req.text)


@app.get("/api/history", response_model=list[HistoryTurn])
def get_history() -> list[HistoryTurn]:
    """디스크에서 복원된(서버 재시작에도 살아남는) 대화 기록을 반환한다.

    프론트엔드가 페이지 로드 시 한 번 불러와 conversationLog 초기값으로 쓴다.
    """
    turns: list[HistoryTurn] = []
    for turn in _chat_context.get_history():
        turns.append(HistoryTurn(role="user", text=turn.user, timestamp=turn.timestamp))
        turns.append(HistoryTurn(role="jarvis", text=turn.jarvis, timestamp=turn.timestamp))
    return turns
