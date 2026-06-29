"""대전광역시 버스 실시간 도착정보 조회 및 추적 스킬.

사용 예:
  "버스 알려줘"                    → 기본 정류소 전체 버스 조회
  "갈마역 버스 알려줘"              → 저장된 정류소 이름으로 조회
  "8001378 버스 알려줘"            → 정류소 ID로 직접 조회
  "① 추적해줘" / "1번 추적"        → 목록 첫 번째 버스 추적 시작
  "102번 추적해줘"                  → 102번 버스(가장 빠른 차) 추적
  "두 번째 102번 추적해줘"          → 102번 버스 두 번째 차 추적
  "버스 추적 중단"                  → 추적 중지
  "정류소 저장 갈마역 8001234"      → 정류소 ID 저장
"""
import json
import logging
import re
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

from core.bus_client import get_arrivals
from core.skill_base import Skill, SkillResult

load_dotenv()
logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent / "data" / "bus_config.json"
_POLL_SEC    = 30   # 폴링 간격(초)
_ALERT_STOPS = 2    # STATUS_POS 이 값 이하면 "곧 도착" 알림

# 활성 추적 스레드 (전역 — 프로세스당 1개)
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


def _find_stop(name_or_id: str) -> tuple[str, str] | None:
    """이름 또는 ID로 저장된 정류소 검색 → (stop_id, stop_name) 반환."""
    cfg = _load_config()
    target = name_or_id.strip()
    for s in cfg.get("stops", []):
        if target in (s.get("id", ""), s.get("name", "")):
            return s["id"], s["name"]
    # 숫자만이면 ID로 직접 사용
    if re.fullmatch(r"\d+", target):
        return target, target
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
    # ① ~ ⑩ 기호
    for i, ch in enumerate(_CIRCLE, 1):
        if ch in text and i <= len(arrivals):
            return arrivals[i - 1]

    # "첫 번째", "두 번째" 등
    for kor, idx in _KOR_NUM.items():
        if kor in text and idx <= len(arrivals):
            return arrivals[idx - 1]

    # "1번째", "2번", 숫자 단독 (단, 버스번호와 구분 필요)
    m = re.search(r"(\d+)\s*번째", text)
    if m:
        idx = int(m.group(1))
        if 1 <= idx <= len(arrivals):
            return arrivals[idx - 1]

    # "102번 추적" — 노선 번호 기반 (가장 빠른 차)
    # "두 번째 102번" — 노선 번호 두 번째 차
    m_route = re.search(r"([A-Za-z가-힣]?\d+[A-Za-z]?)\s*번", text)
    if m_route:
        route_no = m_route.group(1)
        same_route = [b for b in arrivals if b["route_no"] == route_no]
        if same_route:
            # "두 번째" 같은 수식어 확인
            for kor, idx in _KOR_NUM.items():
                if kor in text and idx <= len(same_route):
                    return same_route[idx - 1]
            return same_route[0]  # 기본: 가장 빠른 차

    return None


# ── 백그라운드 추적 스레드 ─────────────────────────────────────────────────────

def _announce(msg: str) -> None:
    """TTS + 콘솔 출력."""
    print(f"\n[자비스 버스] {msg}")
    try:
        from voice import tts as _tts
        _tts.speak(msg)
    except Exception:
        pass
    try:
        from core.status_events import broadcaster
        broadcaster.emit(state="responded", text=msg)
    except Exception:
        pass


def _tracking_loop(
    bus_stop_id: str,
    stop_name: str,
    route_no: str,
    car_reg_no: str,
) -> None:
    global _tracker
    prev_pos: int | None = None

    _announce(f"{route_no}번 버스 추적을 시작합니다.")

    while not _stop_event.is_set():
        arrivals = get_arrivals(bus_stop_id)

        # 추적 중인 차량 찾기 (차량번호로 특정)
        target = next(
            (b for b in arrivals if b["car_reg_no"] == car_reg_no), None
        )

        if target is None:
            # 목록에서 사라짐 → 도착 완료 또는 운행 종료
            _announce(f"{route_no}번 버스가 정류소에 도착했습니다. 추적을 종료합니다.")
            break

        pos = target["status_pos"]
        eta = target["eta_min"]

        if prev_pos is not None and pos != prev_pos:
            # 정류장 이동 감지
            if pos <= _ALERT_STOPS:
                _announce(f"{route_no}번 버스가 {pos}정류장 앞입니다. {eta}분 후 도착 예정.")
            else:
                _announce(f"{route_no}번 버스 이동 — {pos}정류장 전, {eta}분 후 도착 예정.")

        prev_pos = pos
        _stop_event.wait(_POLL_SEC)

    _tracker = None


def _start_tracking(
    bus_stop_id: str, stop_name: str, bus: dict
) -> str:
    global _tracker, _stop_event

    # 기존 추적 중단
    if _tracker and _tracker.is_alive():
        _stop_event.set()
        _tracker.join(timeout=3)

    _stop_event = threading.Event()
    _tracker = threading.Thread(
        target=_tracking_loop,
        args=(bus_stop_id, stop_name, bus["route_no"], bus["car_reg_no"]),
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

_QUERY_WORDS   = ["버스", "정류장", "정류소", "도착"]
_TRACK_WORDS   = ["추적", "알려줘", "알림"]
_STOP_WORDS    = ["중단", "그만", "취소", "종료"]
_SELECT_WORDS  = list(_CIRCLE) + ["번째", "추적", "타"]
_SAVE_WORDS    = ["저장", "등록", "추가"]
_NUM_PATTERN   = re.compile(r"[A-Za-z가-힣]?\d+[A-Za-z]?번")


class BusTrackerSkill(Skill):
    name        = "bus_tracker"
    description = "대전광역시 버스 실시간 도착정보 조회 및 특정 버스 위치 추적"
    triggers    = ["버스", "정류소", "버스 추적", "버스 알려줘"]
    examples    = [
        "버스 알려줘",
        "갈마역 버스 알려줘",
        "8001378 버스 알려줘",
        "① 추적해줘",
        "102번 추적해줘",
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

        # 버스 선택/추적 (이전 대화에서 이미 목록 조회한 상태)
        if any(w in text for w in _SELECT_WORDS) and "버스" not in text:
            # 숫자 또는 원문자 포함 시
            return 0.0  # 다른 대화일 수 있어 컨텍스트로 판단

        # 버스 + 추적
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

        # ── 버스 선택 (이전 조회 결과가 있을 때) ─────────────────────────
        if bus_state.get("arrivals") and any(w in text for w in _SELECT_WORDS):
            return self._handle_selection(text, bus_state, context)

        # ── 도착정보 조회 ──────────────────────────────────────────────────
        return self._handle_query(text, context)

    # ── 세부 핸들러 ────────────────────────────────────────────────────────

    def _handle_query(self, text: str, context: dict) -> SkillResult:
        stop_id, stop_name = self._extract_stop(text)
        if not stop_id:
            stops = _load_config().get("stops", [])
            if not stops:
                return SkillResult(
                    speech=(
                        "조회할 정류소가 없습니다.\n"
                        "정류소를 저장하려면: '정류소 저장 [이름] [ID]'\n"
                        "예: '정류소 저장 갈마역 8001234'\n\n"
                        "정류소 ID는 대전 BIS 앱이나 data.go.kr Swagger UI에서 확인하세요."
                    ),
                    success=False,
                )
            # 저장된 정류소가 하나면 자동 선택
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

        # 컨텍스트에 상태 저장 (버스 선택 대기)
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

    def _handle_selection(
        self, text: str, bus_state: dict, context: dict
    ) -> SkillResult:
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

        # 추적 전 최신 정보 다시 조회 (선택 후 시간이 지났을 수 있음)
        fresh = get_arrivals(stop_id)
        target = next(
            (b for b in fresh if b["car_reg_no"] == bus["car_reg_no"]),
            bus,  # 최신 조회 실패 시 이전 정보 사용
        )

        context["data"]["bus_state"] = {}  # 선택 완료 후 상태 초기화
        msg = _start_tracking(stop_id, stop_name, target)
        return SkillResult(speech=msg, success=True, follow_up=False)

    def _stop_tracking(self) -> SkillResult:
        global _stop_event, _tracker
        if _tracker and _tracker.is_alive():
            _stop_event.set()
            return SkillResult(speech="버스 추적을 중단했습니다.", success=True)
        return SkillResult(speech="현재 추적 중인 버스가 없습니다.", success=True)

    def _save_stop(self, text: str) -> SkillResult:
        # "정류소 저장 갈마역 8001234"
        m = re.search(r"저장\s+(.+?)\s+(\d+)", text)
        if not m:
            return SkillResult(
                speech="저장 형식: '정류소 저장 [이름] [ID]'\n예: '정류소 저장 갈마역 8001234'",
                success=False,
            )
        name, stop_id = m.group(1).strip(), m.group(2).strip()
        cfg = _load_config()
        # 중복 제거 후 추가
        cfg["stops"] = [s for s in cfg.get("stops", []) if s.get("id") != stop_id]
        cfg["stops"].append({"name": name, "id": stop_id})
        _save_config(cfg)
        return SkillResult(
            speech=f"'{name}' 정류소(ID: {stop_id})를 저장했습니다.",
            success=True,
        )

    def _extract_stop(self, text: str) -> tuple[str, str]:
        """텍스트에서 정류소 ID 또는 저장된 이름 추출."""
        # 숫자 ID 직접 포함 (예: "8001378 버스")
        m = re.search(r"\b(\d{6,})\b", text)
        if m:
            stop_id = m.group(1)
            return stop_id, stop_id

        # 저장된 정류소 이름 매칭
        cfg = _load_config()
        for stop in cfg.get("stops", []):
            if stop["name"] in text:
                return stop["id"], stop["name"]

        return "", ""
