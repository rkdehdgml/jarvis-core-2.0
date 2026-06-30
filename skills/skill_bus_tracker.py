"""대전광역시 버스 실시간 도착정보 조회 및 추적 스킬.

사용 예:
  "샘머리아파트정류장 버스 정보 알려줘"   → 해당 정류장 버스 목록 조회
  "버스 알려줘"                          → 기본 정류소 전체 버스 조회
  "갈마역 버스 알려줘"                   → 저장된 정류소 이름으로 조회
  "8001378 버스 알려줘"                  → 정류소 ID로 직접 조회
  "① 추적해줘" / "1번 추적"             → 목록 첫 번째 버스 추적 시작
  "102번 추적해줘"                       → 102번 버스(가장 빠른 차) 추적
  "두 번째 102번 추적해줘"               → 102번 버스 두 번째 차 추적
  "911 버스 추적해줘"                    → 911번 버스 직접 추적 (기준 정류소 자동 사용)
  "911번 버스 위치 정보 알려줘"          → 911번 버스 도착까지 반복 추적
  "911번 버스 현재 위치는 어디야"        → 911번 버스 현재 위치 1회 조회
  "버스 추적 중단"                       → 추적 중지
  "정류소 저장 갈마역 8001234"           → 정류소 ID 저장
"""
import json
import logging
import re
import threading
from pathlib import Path

from dotenv import load_dotenv

from core.bus_client import get_arrivals
from core.busstop_client import bis_name_from_id, search_stops
from core.buspos_client import get_bus_positions
from core.skill_base import Skill, SkillResult

load_dotenv()
logger = logging.getLogger(__name__)

_STRIP_WORDS = re.compile(
    r"버스|알려줘|알려|정류소|정류장|도착|추적|해줘|줘|좀|어디|몇|지금|실시간|위치|정보|현재"
)

_CONFIG_PATH = Path(__file__).parent.parent / "data" / "bus_config.json"
_POLL_SEC    = 30   # 폴링 간격(초)
_ALERT_STOPS = 2    # STATUS_POS 이 값 이하면 "곧 도착" 알림

_tracker: threading.Thread | None = None
_stop_event = threading.Event()


# ── 설정 파일 ──────────────────────────────────────────────────────────────────

def _load_config() -> dict:
    if _CONFIG_PATH.exists():
        try:
            return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"stops": []}


def _save_config(cfg: dict) -> None:
    _CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _extract_name_from_query(text: str) -> str:
    """쿼리 텍스트에서 정류소 이름 후보를 추출한다."""
    cleaned = _STRIP_WORDS.sub(" ", text).strip()
    tokens = [t for t in cleaned.split() if len(t) >= 2]
    return tokens[0] if tokens else ""


def _search_stop_by_name(name: str) -> tuple[str, str] | None:
    """정류소 이름 → (stop_id, stop_name) 역조회.

    1차: 공식 정류소 검색 API
    2차: DuckDuckGo 웹 검색 fallback
    """
    try:
        stops = search_stops(name)
        if stops:
            for s in stops:
                if s.get("id") and s.get("name"):
                    logger.info(f"정류소 API 검색 성공: '{name}' → {s['id']} ({s['name']})")
                    return s["id"], s["name"]
    except Exception as exc:
        logger.debug(f"정류소 API 검색 오류: {exc}")

    try:
        from ddgs import DDGS
        queries = [
            f"대전 {name} 버스정류소 BIS",
            f"대전광역시 {name} 버스 정류장 정류소",
        ]
        all_text_parts: list[str] = []
        with DDGS() as ddgs:
            for q in queries:
                try:
                    results = list(ddgs.text(q, max_results=8))
                    for r in results:
                        all_text_parts.append(r.get("body", "") + " " + r.get("title", ""))
                except Exception:
                    pass

        all_text = " ".join(all_text_parts)
        candidates = sorted(
            set(re.findall(r"\b(8\d{5,7})\b", all_text))
            | set(re.findall(r"\b(\d{7,8})\b", all_text))
        )
        name_tokens = name.split() or [name]
        for cid in candidates[:15]:
            arrivals = get_arrivals(cid)
            if not arrivals:
                continue
            stop_name = arrivals[0].get("stop_name", "")
            if name in stop_name or any(t in stop_name for t in name_tokens):
                logger.info(f"정류소 웹 검색 성공: '{name}' → {cid} ({stop_name})")
                return cid, stop_name
    except Exception as exc:
        logger.debug(f"정류소 웹 검색 실패: {exc}")

    return None


# ── 도착 정보 포매팅 ───────────────────────────────────────────────────────────

def _format_arrivals(arrivals: list[dict], stop_name: str) -> str:
    if not arrivals:
        return f"{stop_name} 정류소에 현재 도착 예정인 버스가 없습니다."

    lines = [f"[{stop_name}] 도착 예정 버스 목록"]
    for i, b in enumerate(arrivals, 1):
        eta = b["eta_min"]
        pos = b["status_pos"]
        eta_str = "곧 도착" if eta <= 1 else f"{eta}분 후"
        pos_str = f"{pos}정류장 전" if pos > 0 else "도착 중"
        circle = "①②③④⑤⑥⑦⑧⑨⑩"[i - 1] if i <= 10 else str(i)
        lines.append(
            f"  {circle} {b['route_no']}번 버스 - {eta_str} ({pos_str}) - {b['destination']}"
        )
    lines.append("\n추적할 버스를 말씀해주세요. (예: '① 추적해줘', '102번 추적해줘', '두 번째 추적해줘')")
    return "\n".join(lines)


# ── 버스 선택 파싱 ─────────────────────────────────────────────────────────────

_CIRCLE = "①②③④⑤⑥⑦⑧⑨⑩"
_KOR_NUM = {"첫": 1, "둘": 2, "셋": 3, "넷": 4, "다섯": 5,
            "일": 1, "이": 2, "삼": 3, "사": 4, "오": 5}


def _parse_selection(text: str, arrivals: list[dict]) -> dict | None:
    """사용자 입력에서 선택한 버스 항목을 찾는다."""
    for i, ch in enumerate(_CIRCLE, 1):
        if ch in text and i <= len(arrivals):
            return arrivals[i - 1]

    for kor, idx in _KOR_NUM.items():
        if kor in text and idx <= len(arrivals):
            return arrivals[idx - 1]

    m = re.search(r"(\d+)\s*번째", text)
    if m:
        idx = int(m.group(1))
        if 1 <= idx <= len(arrivals):
            return arrivals[idx - 1]

    m_route = re.search(r"([A-Za-z가-힣]?\d+[A-Za-z]?)\s*번", text)
    if m_route:
        route_no = m_route.group(1)
        same_route = [b for b in arrivals if b["route_no"] == route_no]
        if same_route:
            for kor, idx in _KOR_NUM.items():
                if kor in text and idx <= len(same_route):
                    return same_route[idx - 1]
            return same_route[0]

    return None


# ── 백그라운드 추적 스레드 ─────────────────────────────────────────────────────

def _announce(msg: str) -> None:
    """TTS + 콘솔 출력 + WebSocket 브로드캐스트."""
    try:
        print(f"\n[자비스 버스] {msg}", flush=True)
    except Exception:
        pass
    try:
        from voice import tts as _tts
        _tts.speak(msg)
    except Exception:
        pass
    try:
        from core.status_events import broadcaster
        broadcaster.emit(state="responded", last_response=msg)
    except Exception:
        pass


def _get_bus_node(route_cd: str, car_reg_no: str) -> tuple[str, str]:
    """busposinfo API로 차량의 현재 정류소 ID와 이름을 조회한다. 실패 시 ('', '') 반환."""
    if not route_cd:
        return "", ""
    try:
        positions = get_bus_positions(route_cd)
        for p in positions:
            if p["plate_no"] == car_reg_no:
                node_id = p["bus_node_id"]
                name = bis_name_from_id(node_id) or ""
                return node_id, name
    except Exception:
        pass
    return "", ""


def _tracking_loop(
    bus_stop_id: str,
    stop_name: str,
    route_no: str,
    car_reg_no: str,
    route_cd: str = "",
) -> None:
    global _tracker
    prev_pos: int | None = None
    prev_node_id: str = ""

    _announce(f"{route_no}번 버스 추적을 시작합니다.")

    while not _stop_event.is_set():
        arrivals = get_arrivals(bus_stop_id)

        target = next(
            (b for b in arrivals if b["car_reg_no"] == car_reg_no), None
        )

        if target is None:
            _announce(f"{route_no}번 버스가 {stop_name} 정류소에 도착했습니다. 추적을 종료합니다.")
            break

        pos = target["status_pos"]
        eta = target["eta_min"]
        eta_str = "곧 도착" if eta <= 1 else f"{eta}분 후"
        pos_str = f"{pos}정류장 전" if pos > 0 else "도착 직전"

        cur_node_id, cur_node_name = _get_bus_node(route_cd, car_reg_no)
        loc_info = f" / 현재 {cur_node_name} 정류소" if cur_node_name else ""

        if prev_pos is None:
            # 첫 폴링: 초기 현황 1회만 알림
            _announce(f"[버스 현황] {route_no}번 버스 — {pos_str}{loc_info}, {eta_str} 도착 예정.")
        elif pos != prev_pos:
            # 위치 변경: 이전 → 현재 정류소 이동 중 표시
            if prev_node_id and cur_node_id and prev_node_id != cur_node_id:
                prev_name = bis_name_from_id(prev_node_id) or "이전 정류소"
                move_info = (
                    f" ({prev_name}에서 {cur_node_name}으로 이동 중)"
                    if cur_node_name
                    else f" ({prev_name} 통과 중)"
                )
            elif cur_node_name:
                move_info = f" (현재 {cur_node_name} 정류소)"
            else:
                move_info = ""

            if pos <= _ALERT_STOPS:
                _announce(f"[버스 알림] {route_no}번 버스 {pos}정류장 앞{move_info} — {eta_str} 도착 예정.")
            else:
                _announce(f"[버스 알림] {route_no}번 버스 이동 중{move_info} — {pos_str}, {eta_str} 도착 예정.")
        # pos == prev_pos: 위치 변동 없음 → 중복 알림 생략

        if cur_node_id:
            prev_node_id = cur_node_id
        prev_pos = pos
        _stop_event.wait(_POLL_SEC)

    _tracker = None


def _start_tracking(bus_stop_id: str, stop_name: str, bus: dict) -> str:
    global _tracker, _stop_event

    if _tracker and _tracker.is_alive():
        _stop_event.set()
        _tracker.join(timeout=3)

    _stop_event = threading.Event()
    _tracker = threading.Thread(
        target=_tracking_loop,
        args=(bus_stop_id, stop_name, bus["route_no"], bus["car_reg_no"],
              bus.get("route_cd", "")),
        daemon=True,
    )
    _tracker.start()

    eta = bus["eta_min"]
    pos = bus["status_pos"]
    eta_str = "곧 도착" if eta <= 1 else f"{eta}분 후"
    return (
        f"{bus['route_no']}번 버스({bus['destination']} 방향) 추적을 시작합니다.\n"
        f"현재 {pos}정류장 전, {eta_str} 도착 예정.\n"
        f"버스가 이동할 때마다 알려드립니다. 도착하면 자동으로 알림이 종료됩니다."
    )


# ── 스킬 ──────────────────────────────────────────────────────────────────────

_QUERY_WORDS  = ["버스", "정류장", "정류소", "도착"]
_TRACK_WORDS  = ["추적", "알림"]
_STOP_WORDS   = ["중단", "그만", "취소", "종료"]
_SELECT_WORDS = list(_CIRCLE) + ["번째", "추적", "타"]
_SAVE_WORDS   = ["저장", "등록", "추가"]

# 1회 위치 조회: "현재 위치는 어디야", "어디 있어", "지금 어디야"
_LOC_WORDS = ["현재 위치", "어디", "지금 어디", "몇 정류장"]

# 반복 추적: "위치 정보 알려줘", "추적해줘"
_TRACK_ROUTE_WORDS = ["위치 정보", "추적"]

# "102번", "911번 버스", "911 버스" 모두 매칭
_ROUTE_PATTERN = re.compile(r"([A-Za-z가-힣]?\d+[A-Za-z]?)\s*(?:번|버스)")


def _extract_route_no(text: str) -> str | None:
    """텍스트에서 버스 노선 번호 추출. 예: '911 버스' → '911', '102번' → '102'"""
    m = _ROUTE_PATTERN.search(text)
    return m.group(1) if m else None


class BusTrackerSkill(Skill):
    name        = "bus_tracker"
    description = "대전광역시 버스 실시간 도착정보 조회 및 특정 버스 위치 추적"
    triggers    = ["버스", "정류소", "버스 추적", "버스 알려줘"]
    examples    = [
        "샘머리아파트정류장 버스 정보 알려줘",
        "버스 알려줘",
        "갈마역 버스 알려줘",
        "8001378 버스 알려줘",
        "① 추적해줘",
        "102번 추적해줘",
        "911 버스 위치 정보 알려줘",
        "911번 버스 현재 위치는 어디야",
        "버스 추적 중단",
        "정류소 저장 갈마역 8001234",
    ]

    def can_handle(self, intent: str, text: str) -> float:
        # 추적 중단
        if any(w in text for w in _STOP_WORDS) and "추적" in text:
            return 0.93

        # 정류소 저장
        if any(w in text for w in _SAVE_WORDS) and "정류" in text:
            return 0.92

        route_no = _extract_route_no(text)

        # 버스번호 + 반복 추적 요청
        if route_no and any(w in text for w in _TRACK_ROUTE_WORDS):
            return 0.93

        # 버스번호 + 1회 위치 조회
        if route_no and any(w in text for w in _LOC_WORDS):
            return 0.92

        # 원문자 + 추적
        circle_in = any(ch in text for ch in _CIRCLE)
        if circle_in and "추적" in text:
            return 0.88
        if "번째" in text and "추적" in text:
            return 0.88
        if circle_in:
            return 0.55

        # 버스 + 추적/알림
        if "버스" in text and any(w in text for w in _TRACK_WORDS):
            return 0.92

        # 버스 도착정보 조회
        if any(w in text for w in _QUERY_WORDS):
            return 0.85

        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        bus_state: dict = context.get("data", {}).get("bus_state", {})

        # ── 추적 중단 ──────────────────────────────────────────────────────
        if any(w in text for w in _STOP_WORDS) and "추적" in text:
            return self._stop_tracking()

        # ── 정류소 저장 ────────────────────────────────────────────────────
        if any(w in text for w in _SAVE_WORDS) and "정류" in text:
            return self._save_stop(text)

        route_no = _extract_route_no(text)

        # ── 버스번호 + 반복 추적 ("위치 정보 알려줘", "추적해줘") ──────────
        if route_no and any(w in text for w in _TRACK_ROUTE_WORDS):
            return self._handle_track_by_route(route_no, context)

        # ── 버스번호 + 1회 위치 조회 ("현재 위치", "어디야") ───────────────
        if route_no and any(w in text for w in _LOC_WORDS):
            return self._handle_location(route_no, context)

        # ── 버스 선택 (이전 조회 결과가 있을 때) ──────────────────────────
        if bus_state.get("arrivals") and any(w in text for w in _SELECT_WORDS):
            return self._handle_selection(text, bus_state, context)

        # ── 도착정보 조회 ──────────────────────────────────────────────────
        return self._handle_query(text, context)

    # ── 세부 핸들러 ────────────────────────────────────────────────────────

    def _handle_query(self, text: str, context: dict) -> SkillResult:
        stop_id, stop_name = self._extract_stop(text)

        if not stop_id:
            name_candidate = _extract_name_from_query(text)
            if name_candidate:
                found = _search_stop_by_name(name_candidate)
                if found:
                    stop_id, stop_name = found
                    cfg = _load_config()
                    if not any(s.get("id") == stop_id for s in cfg.get("stops", [])):
                        cfg.setdefault("stops", []).append(
                            {"name": stop_name, "id": stop_id}
                        )
                        _save_config(cfg)
                        logger.info(f"정류소 자동 저장: {stop_name} ({stop_id})")

            if not stop_id:
                stops = _load_config().get("stops", [])
                if not stops:
                    hint = (
                        f"'{name_candidate}' 정류소를 웹에서 검색했지만 ID를 찾지 못했습니다.\n\n"
                        if name_candidate else ""
                    )
                    return SkillResult(
                        speech=(
                            hint
                            + "정류소 ID를 직접 저장해주세요.\n"
                            "방법 1 - 카카오버스 앱에서 정류소 검색 후 ID 확인\n"
                            "방법 2 - 저장 명령어: '정류소 저장 [이름] [ID]'\n"
                            "  예: '정류소 저장 샘머리아파트 8001234'"
                        ),
                        success=False,
                    )
                if len(stops) == 1:
                    stop_id   = stops[0]["id"]
                    stop_name = stops[0]["name"]
                else:
                    names = ", ".join(s["name"] for s in stops)
                    return SkillResult(
                        speech=f"어느 정류소를 조회할까요? 저장된 정류소: {names}",
                        success=True,
                    )

        arrivals = get_arrivals(stop_id)
        if not arrivals:
            return SkillResult(
                speech=f"{stop_name} 정류소 정보를 가져오지 못했습니다. 정류소 ID를 확인해주세요.",
                success=False,
            )

        context.setdefault("data", {})["bus_state"] = {
            "stop_id":   stop_id,
            "stop_name": stop_name,
            "arrivals":  arrivals,
        }

        return SkillResult(
            speech=_format_arrivals(arrivals, stop_name),
            success=True,
            follow_up=True,
        )

    def _handle_selection(self, text: str, bus_state: dict, context: dict) -> SkillResult:
        arrivals  = bus_state["arrivals"]
        stop_id   = bus_state["stop_id"]
        stop_name = bus_state["stop_name"]

        bus = _parse_selection(text, arrivals)
        if not bus:
            return SkillResult(
                speech="어느 버스를 추적할지 잘 모르겠습니다. '① 추적해줘' 또는 '102번 추적해줘' 형식으로 말씀해주세요.",
                success=False,
                follow_up=True,
            )

        fresh = get_arrivals(stop_id)
        target = next(
            (b for b in fresh if b["car_reg_no"] == bus["car_reg_no"]),
            bus,
        )

        context["data"]["bus_state"] = {}
        msg = _start_tracking(stop_id, stop_name, target)
        return SkillResult(speech=msg, success=True, follow_up=False)

    def _handle_track_by_route(self, route_no: str, context: dict) -> SkillResult:
        """'X번 버스 추적해줘' / 'X번 버스 위치 정보 알려줘' 처리.

        기준 정류소에서 해당 노선 버스를 찾아 도착할 때까지 반복 알림.
        """
        bus_state = context.get("data", {}).get("bus_state", {})
        stop_id = bus_state.get("stop_id", "")
        stop_name = bus_state.get("stop_name", "")
        buses: list[dict] = []

        if stop_id:
            arrivals = get_arrivals(stop_id)
            buses = [b for b in arrivals if b["route_no"] == route_no]
            if not buses:
                # 컨텍스트 정류소에 없으면 저장된 정류소 전체 탐색
                stop_id, stop_name, buses = self._find_route_in_stops(route_no)
        else:
            stop_id, stop_name, buses = self._find_route_in_stops(route_no)

        if not stop_id:
            return SkillResult(
                speech=(
                    f"{route_no}번 버스를 추적하려면 기준 정류소가 필요합니다.\n"
                    "정류소를 먼저 저장해주세요. 예: '정류소 저장 샘머리아파트 8001913'"
                ),
                success=False,
            )

        if not buses:
            return SkillResult(
                speech=f"{route_no}번 버스가 {stop_name} 정류소 근방에 현재 없습니다.",
                success=True,
            )

        context.setdefault("data", {})["bus_state"] = {}
        msg = _start_tracking(stop_id, stop_name, buses[0])
        return SkillResult(speech=msg, success=True, follow_up=False)

    def _find_route_in_stops(self, route_no: str) -> tuple[str, str, list[dict]]:
        """저장된 정류소 목록에서 해당 노선 버스가 있는 첫 번째 정류소 반환.

        Returns: (stop_id, stop_name, buses) — 정류소 없으면 ("", "", [])
        """
        stops = _load_config().get("stops", [])
        if not stops:
            return "", "", []

        for s in stops:
            arr = get_arrivals(s["id"])
            buses = [b for b in arr if b["route_no"] == route_no]
            if buses:
                return s["id"], s["name"], buses

        # 버스가 어느 정류소에도 없음 — 정류소는 있으나 해당 노선 없음
        return stops[0]["id"], stops[0]["name"], []

    def _handle_location(self, route_no: str, context: dict) -> SkillResult:
        """'X번 버스 현재 위치는 어디야' 처리 — 1회 현재 위치 조회."""
        stops = _load_config().get("stops", [])
        if not stops:
            return SkillResult(
                speech=(
                    f"{route_no}번 버스 위치를 조회하려면 기준 정류소가 필요합니다.\n"
                    "정류소를 저장해주세요. 예: '정류소 저장 샘머리아파트 8001913'"
                ),
                success=False,
            )

        route_cd = ""
        arrivals_map: dict[str, tuple[str, list[dict]]] = {}
        for stop in stops:
            arr = get_arrivals(stop["id"])
            route_buses = [b for b in arr if b["route_no"] == route_no]
            arrivals_map[stop["id"]] = (stop["name"], route_buses)
            if not route_cd and route_buses:
                route_cd = route_buses[0].get("route_cd", "")

        if not route_cd:
            return SkillResult(
                speech=f"{route_no}번 버스가 저장된 정류소 근방에 현재 없습니다.",
                success=True,
            )

        positions = get_bus_positions(route_cd)

        # plate_no → (stop_name, arrival) 인덱스
        plate_to_arrival: dict[str, tuple[str, dict]] = {}
        for _sid, (sname, route_buses) in arrivals_map.items():
            for b in route_buses:
                if b["car_reg_no"] not in plate_to_arrival:
                    plate_to_arrival[b["car_reg_no"]] = (sname, b)

        lines = [f"[{route_no}번 버스 현재 위치]"]

        if positions:
            # plate_to_arrival에 있는 버스만 표시 — 이미 정류소를 지나간 버스 제외
            approaching = [p for p in positions if p["plate_no"] in plate_to_arrival]
            if not approaching:
                return SkillResult(
                    speech=f"{route_no}번 버스가 저장된 정류소에 아직 도착하지 않은 차량이 없습니다.",
                    success=True,
                )
            for i, p in enumerate(approaching[:3], 1):
                node_name = bis_name_from_id(p["bus_node_id"]) or f"정류소({p['bus_node_id']})"
                ref_stop, b = plate_to_arrival[p["plate_no"]]
                eta = b["eta_min"]
                pos_n = b["status_pos"]
                eta_str = "곧 도착 예정" if eta <= 1 else f"{eta}분 후 도착 예정"
                pos_str = f"{pos_n}정류장 전" if pos_n > 0 else "도착 직전"
                lines.append(
                    f"  {i}호차: {node_name} 정류소에 있습니다"
                    f" ({ref_stop}까지 {pos_str}, {eta_str})"
                )
        else:
            # busposinfo 실패 시 도착 정보만으로 표시
            found_any = False
            for _sid, (sname, route_buses) in arrivals_map.items():
                if not route_buses:
                    continue
                found_any = True
                for i, b in enumerate(route_buses, 1):
                    eta = b["eta_min"]
                    pos_n = b["status_pos"]
                    eta_str = "곧 도착" if eta <= 1 else f"{eta}분 후"
                    pos_str = f"{pos_n}정류장 전" if pos_n > 0 else "도착 직전"
                    lines.append(
                        f"  {i}호차: {sname}까지 {pos_str} ({eta_str} 도착 예정)"
                    )
            if not found_any:
                return SkillResult(
                    speech=f"{route_no}번 버스가 저장된 정류소 근방에 현재 없습니다.",
                    success=True,
                )

        return SkillResult(speech="\n".join(lines), success=True)

    def _stop_tracking(self) -> SkillResult:
        global _stop_event, _tracker
        if _tracker and _tracker.is_alive():
            _stop_event.set()
            return SkillResult(speech="버스 추적을 중단했습니다.", success=True)
        return SkillResult(speech="현재 추적 중인 버스가 없습니다.", success=True)

    def _save_stop(self, text: str) -> SkillResult:
        m = re.search(r"저장\s+(.+?)\s+(\d+)", text)
        if not m:
            return SkillResult(
                speech="저장 형식: '정류소 저장 [이름] [ID]'\n예: '정류소 저장 갈마역 8001234'",
                success=False,
            )
        name, stop_id = m.group(1).strip(), m.group(2).strip()
        cfg = _load_config()
        cfg["stops"] = [s for s in cfg.get("stops", []) if s.get("id") != stop_id]
        cfg["stops"].append({"name": name, "id": stop_id})
        _save_config(cfg)
        return SkillResult(
            speech=f"'{name}' 정류소(ID: {stop_id})를 저장했습니다.",
            success=True,
        )

    def _extract_stop(self, text: str) -> tuple[str, str]:
        """텍스트에서 정류소 ID 또는 저장된 이름 추출."""
        m = re.search(r"\b(\d{6,})\b", text)
        if m:
            stop_id = m.group(1)
            return stop_id, stop_id

        # "정류장"/"정류소" 접미사를 제거한 정규화 텍스트 (예: "샘머리아파트정류장" → "샘머리아파트")
        clean_text = re.sub(r"\s*(정류장|정류소)\s*", " ", text).strip()

        cfg = _load_config()
        for stop in cfg.get("stops", []):
            sname = stop["name"]
            clean_sname = re.sub(r"\s*(정류장|정류소)\s*", "", sname).strip()
            if sname in text or (
                clean_sname and (clean_sname in text or clean_sname in clean_text)
            ):
                return stop["id"], stop["name"]

        return "", ""
