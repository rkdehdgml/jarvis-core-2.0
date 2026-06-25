"""Groq API 토큰 사용량을 날짜별로 누적 기록한다.

Claude Code CLI는 $ 비용으로 과금되지만(core/usage.py), Groq 무료 티어는 비용이
아니라 토큰 한도(TPD, tokens per day)로 제한된다. GroqEngine이 호출마다(재시도
포함, 실제로 소비된 만큼) record_tokens()로 오늘 누적 토큰 수를
data/groq_usage.json에 저장하고, GroqEngine.describe()가 get_today_percent()로
TPD 대비 사용량(%)을 실어 UI에 보낸다.

TPD 값은 console.groq.com/docs/rate-limits의 llama-3.3-70b-versatile 무료 티어
기준(2026-06 확인, 100,000 tokens/day) — Groq가 한도를 바꾸면 같이 갱신해야 한다.
"""
import json
import logging
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

_USAGE_PATH = Path(__file__).parent.parent / "data" / "groq_usage.json"

# Groq 무료 티어 llama-3.3-70b-versatile의 TPD(하루 토큰 한도).
_DAILY_TOKEN_LIMIT = 100_000


def _load() -> dict:
    try:
        return json.loads(_USAGE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(data: dict) -> None:
    _USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _USAGE_PATH.write_text(json.dumps(data), encoding="utf-8")


def record_tokens(total_tokens: int) -> None:
    """Groq 호출 1건의 토큰 사용량을 오늘 날짜에 누적한다."""
    today = date.today().isoformat()
    data = _load()
    if data.get("date") != today:
        data = {"date": today, "tokens": 0}
    data["tokens"] = data.get("tokens", 0) + total_tokens
    _save(data)


def get_today_tokens() -> int:
    """오늘 누적 토큰 수를 반환한다(날짜가 바뀌었으면 0)."""
    today = date.today().isoformat()
    data = _load()
    if data.get("date") != today:
        return 0
    return data.get("tokens", 0)


def get_today_percent() -> int:
    """오늘 누적 토큰을 TPD 한도 대비 퍼센트(0~100)로 반환한다."""
    percent = (get_today_tokens() / _DAILY_TOKEN_LIMIT) * 100
    return max(0, min(100, round(percent)))
