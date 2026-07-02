"""FastAPI + WebSocket 로컬 웹서버.

core/status_events.py 의 StatusBroadcaster 가 발행하는 이벤트를
프론트엔드에 실시간으로 중계만 한다. 본체 로직은 건드리지 않는다.

실행:
    uvicorn ui.server:app --host 127.0.0.1 --port 8765

main.py 와 같은 프로세스에서 띄우려면 main.py 에서 uvicorn.Server를
별도 스레드/asyncio 태스크로 실행하면 된다 (이 파일은 건드리지 않음).
"""
import asyncio
import json
import logging
import os
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
_broadcast_queue: asyncio.Queue | None = None

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
        "extra": event.extra,
    }


def _engine_descriptor() -> dict:
    """ai_chat 스킬이 쓰고 있는 엔진(ClaudeCliEngine)의 describe()를 가져온다."""
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


_HOOK_MESSAGE_TYPES = ("tool_action", "output")


async def _broadcast_raw(payload: dict) -> None:
    """훅(jarvis_send.py)이 보낸 원본 페이로드를 모든 클라이언트에 그대로 중계한다."""
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

    call_soon_threadsafe로 asyncio Queue에 이벤트를 넣어 _broadcast_drainer가
    처리하도록 한다. run_coroutine_threadsafe보다 신뢰성이 높다.
    """
    if _loop is None or _broadcast_queue is None:
        return
    _loop.call_soon_threadsafe(_broadcast_queue.put_nowait, event)


async def _broadcast_drainer() -> None:
    """asyncio Queue에서 이벤트를 꺼내 WebSocket으로 중계한다.

    백그라운드 스레드(버스 추적 등)가 put한 이벤트를 이벤트 루프 컨텍스트에서
    안전하게 처리한다.
    """
    assert _broadcast_queue is not None
    while True:
        event = await _broadcast_queue.get()
        await _broadcast(event)


async def _system_info_loop() -> None:
    """채팅/음성 상태 변화가 없을 때도 엔진/CPU/메모리/사용량을 주기적으로 push한다."""
    while True:
        await asyncio.sleep(_SYSTEM_INFO_INTERVAL_SECONDS)
        await _broadcast(broadcaster.get_current())


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _loop, _broadcast_queue
    _loop = asyncio.get_running_loop()
    _broadcast_queue = asyncio.Queue()
    broadcaster.subscribe(_on_status_event)
    drainer_task = asyncio.create_task(_broadcast_drainer())
    system_info_task = asyncio.create_task(_system_info_loop())
    logger.info("UI 서버: 상태 브로드캐스터 구독 시작")
    yield
    drainer_task.cancel()
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
            # 브라우저 클라이언트는 보통 메시지를 보내지 않지만, 훅(jarvis_send.py)은
            # {"type": "tool_action"|"output", "value": ...}를 보내고 바로 끊는다 —
            # 수신 즉시 파싱해 다른 클라이언트에 브로드캐스트한다.
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("type") in _HOOK_MESSAGE_TYPES:
                await _broadcast_raw(data)
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


@app.get("/api/config")
def get_config() -> dict:
    """카카오 JS 앱 키 등 프론트엔드가 필요한 공개 설정값을 반환한다."""
    config: dict = {"kakaoJsKey": os.getenv("KAKAO_JS_API_KEY", "")}
    # 데스크톱 브라우저 Geolocation은 GPS 없이 IP 기반 추정이라 오차가 크다.
    # .env에 KAKAO_DEFAULT_LAT/KAKAO_DEFAULT_LNG를 설정하면 Geolocation 대신 이 좌표를 사용한다.
    lat = os.getenv("KAKAO_DEFAULT_LAT")
    lng = os.getenv("KAKAO_DEFAULT_LNG")
    if lat and lng:
        config["defaultOrigin"] = {"lat": float(lat), "lng": float(lng)}
    return config


def _ip_geocode() -> dict | None:
    """공개 IP로 현재 위치를 도시 수준으로 추정한다 (ip-api.com, 무료·키 불필요)."""
    import requests as _requests
    try:
        r = _requests.get(
            "http://ip-api.com/json/?lang=en&fields=status,lat,lon",
            timeout=5,
        )
        data = r.json()
        if data.get("status") == "success":
            return {"lat": data["lat"], "lng": data["lon"]}
    except Exception as exc:
        logger.warning(f"IP 지오코딩 실패: {exc}")
    return None


class NavigateRequest(BaseModel):
    destination: str
    origin: dict | None = None       # {"lat": float, "lng": float} — 프론트엔드 Geolocation 결과
    originName: str | None = None    # 발화로 명시한 출발지 장소명 ("대전역에서 …")
    routeType: str = "RECOMMEND"
    # 사용자가 후보 중 하나를 선택한 경우 — 이 값이 있으면 geocoding 없이 그대로 사용
    destinationLat: float | None = None
    destinationLng: float | None = None


@app.post("/api/navigate")
async def post_navigate(req: NavigateRequest) -> dict:
    """목적지명 + 출발지(장소명 or 좌표 or IP 추정) + 경로 종류를 받아 카카오맵 경로를 반환한다.

    목적지 결정:
    - destinationLat/Lng 있음 → 사용자가 후보 선택 완료 → 그대로 사용
    - 없음 → geocode_candidates 호출:
        1개 → 바로 경로 탐색
        2개 이상 → {"candidates": [...]} 반환해 프론트엔드가 사용자에게 선택 요청

    출발지 결정 우선순위:
    1. originName 있음 → 카카오 로컬 API로 geocode
    2. origin 좌표 있음 → 그대로 사용 (Geolocation or .env 기본값)
    3. 둘 다 없음 → 공개 IP로 도시 수준 추정
    """
    from core import kakao_map_client

    # ── 목적지 결정 ──────────────────────────────────────────────────────────
    if req.destinationLat is not None and req.destinationLng is not None:
        dest: dict = {"lat": req.destinationLat, "lng": req.destinationLng, "name": req.destination}
    else:
        candidates = await asyncio.to_thread(kakao_map_client.geocode_candidates, req.destination)
        if not candidates:
            return {"error": f"'{req.destination}' 위치를 찾을 수 없습니다."}
        if len(candidates) > 1:
            return {"candidates": candidates}
        dest = candidates[0]

    if req.originName:
        origin_geo = await asyncio.to_thread(kakao_map_client.geocode, req.originName)
        if not origin_geo:
            return {"error": f"출발지 '{req.originName}'를 찾을 수 없습니다."}
        origin: dict = {"lat": origin_geo["lat"], "lng": origin_geo["lng"]}
    elif req.origin:
        origin = req.origin
    else:
        ip_loc = await asyncio.to_thread(_ip_geocode)
        if not ip_loc:
            return {"error": "현재 위치를 확인할 수 없습니다. '대전역에서 서울까지 경로'처럼 출발지를 직접 말씀해 주세요."}
        origin = ip_loc

    route = await asyncio.to_thread(
        kakao_map_client.directions,
        float(origin["lat"]),
        float(origin["lng"]),
        dest["lat"],
        dest["lng"],
        req.routeType,
    )
    if not route:
        return {"error": "경로를 찾을 수 없습니다."}

    dist_km = route["distance"] / 1000
    dur_min = route["duration"] // 60

    return {
        "destination": dest,
        "origin": origin,
        "routeType": req.routeType,
        "distance": route["distance"],
        "duration": route["duration"],
        "distanceText": f"{dist_km:.1f}km",
        "durationText": f"{dur_min}분",
        "vertexes": route["vertexes"],
        "fareToll": route["fare_toll"],
        "fareTaxi": route["fare_taxi"],
    }


class PoiCategoryItem(BaseModel):
    categoryCode: str | None = None
    keyword: str | None = None
    categoryName: str = "장소"


class PoiRequest(BaseModel):
    categories: list[PoiCategoryItem] = []  # 다중 카테고리 (우선)
    # 하위 호환: 단일 카테고리 필드
    categoryCode: str | None = None
    keyword: str | None = None
    vertexes: list[list[float]] = []  # [[lng, lat], ...] — 경로 없으면 IP 기반 검색


@app.post("/api/navigate/poi")
async def post_navigate_poi(req: PoiRequest) -> dict:
    """경로(또는 현재 위치) 주변 POI를 검색한다.

    vertexes 있음 → 경로 따라 샘플 검색 (500m → 2km → 5km 단계적 확장)
    vertexes 없음 → IP 지오코딩으로 현재 도시 기준 검색

    반환: {"results": [{"categoryCode", "categoryName", "pois", "searchRadiusM", "onRoute"}, ...]}
    """
    from core import kakao_map_client

    vertexes = req.vertexes
    if not vertexes:
        ip_loc = await asyncio.to_thread(_ip_geocode)
        if ip_loc:
            vertexes = [[ip_loc["lng"], ip_loc["lat"]]]

    # categories 미지정 시 단일 카테고리 필드로 구성
    categories = req.categories or [
        PoiCategoryItem(categoryCode=req.categoryCode, keyword=req.keyword, categoryName="장소")
    ]

    async def _search_one(cat: PoiCategoryItem) -> dict:
        pois, radius = await asyncio.to_thread(
            kakao_map_client.search_pois_along_route,
            vertexes,
            cat.categoryCode,
            cat.keyword,
        )
        return {
            "categoryCode": cat.categoryCode or "",
            "categoryName": cat.categoryName,
            "pois": pois,
            "searchRadiusM": radius,
            "onRoute": radius <= 500,
        }

    results = await asyncio.gather(*[_search_one(c) for c in categories])
    # 결과 없는 카테고리 필터링
    found = [r for r in results if r["pois"]]

    if not found:
        names = "·".join(c.categoryName for c in categories)
        return {"results": [], "error": f"경로 반경 5km 내에서 {names}을 찾지 못했습니다."}

    return {"results": found}


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
