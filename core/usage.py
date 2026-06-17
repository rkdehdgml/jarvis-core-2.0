"""Claude Code CLI 호출 비용을 날짜별로 누적 기록한다.

엔진 호출마다 ClaudeCodeEngine이 record_cost()를 호출해 data/usage.json에
오늘 누적 비용(USD)을 저장하고, ui/server.py는 get_today_percent()로
일일 기준치 대비 사용량(%)을 조회해 /api/status에 실어 보낸다.
"""
import json
import logging
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

_USAGE_PATH = Path(__file__).parent.parent / "data" / "usage.json"

# 사용량 게이지(0~100%)의 기준이 되는 일일 비용 한도(USD).
_DAILY_BUDGET_USD = 1.0


def _load() -> dict:
    try:
        return json.loads(_USAGE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(data: dict) -> None:
    _USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _USAGE_PATH.write_text(json.dumps(data), encoding="utf-8")


def record_cost(cost_usd: float) -> None:
    """Claude Code 호출 1건의 비용을 오늘 날짜에 누적한다."""
    today = date.today().isoformat()
    data = _load()
    if data.get("date") != today:
        data = {"date": today, "cost_usd": 0.0}
    data["cost_usd"] = data.get("cost_usd", 0.0) + cost_usd
    _save(data)


def get_today_percent() -> int:
    """오늘 누적 비용을 일일 기준치 대비 퍼센트(0~100)로 반환한다."""
    today = date.today().isoformat()
    data = _load()
    if data.get("date") != today:
        return 0
    percent = (data.get("cost_usd", 0.0) / _DAILY_BUDGET_USD) * 100
    return max(0, min(100, round(percent)))
