"""일정(약속/이벤트)을 로컬 JSON에 등록하고 조회하는 스킬.

Google Calendar 등 외부 연동은 의도적으로 하지 않는다 — data/schedule.json
하나만 읽고 쓴다. 자연어 날짜 파싱도 일부러 좁게 제한한다("오늘"/"내일"/"모레"
와 "N월 N일" 패턴만 지원). 더 복잡한 표현은 범위 밖.
"""
import json
import re
from datetime import date, timedelta
from pathlib import Path

from core.skill_base import Skill, SkillResult

_SCHEDULE_PATH = Path(__file__).parent.parent / "data" / "schedule.json"

_TRIGGERS = ["일정", "스케줄", "약속"]
_ADD_WORDS = ["추가", "등록", "잡아줘", "잡아"]
_TIME_RE = re.compile(r"(\d{1,2})시\s*(\d{1,2})?분?")
_DATE_RE = re.compile(r"(\d{1,2})월\s*(\d{1,2})일")

# 제목에서 걷어낼 동사/조사 (긴 것부터 제거해 부분 잔여물 방지).
_NOISE_WORDS = [
    "추가해줘", "등록해줘", "잡아줘", "알려줘", "뭐있어", "뭐 있어",
    "추가", "등록", "잡아", "오늘", "내일", "모레", "이번주", "이번 주",
    "에", "에서", "시에",
]


def _load() -> list[dict]:
    try:
        return json.loads(_SCHEDULE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(items: list[dict]) -> None:
    _SCHEDULE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SCHEDULE_PATH.write_text(
        json.dumps(items, ensure_ascii=False), encoding="utf-8"
    )


def _extract_date(text: str) -> tuple[str, str]:
    """(ISO 날짜 문자열, 텍스트에서 매칭된 원본 조각) 반환. 조각은 제목 정리용."""
    today = date.today()
    m = _DATE_RE.search(text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        resolved = date(today.year, month, day)
        return resolved.isoformat(), m.group(0)
    if "모레" in text:
        return (today + timedelta(days=2)).isoformat(), "모레"
    if "내일" in text:
        return (today + timedelta(days=1)).isoformat(), "내일"
    if "오늘" in text:
        return today.isoformat(), "오늘"
    return today.isoformat(), ""


def _extract_time(text: str) -> tuple[str | None, str]:
    """(HH:MM 또는 None, 매칭된 원본 조각) 반환.

    "오후"가 있거나, "오전" 없이 1~11시면 일과 시간대(PM)로 본다 — 한국어로
    "3시에 회의"는 거의 항상 오후 3시를 뜻하기 때문. "오전"이 명시되거나
    이미 12 이상이면 그대로 둔다.
    """
    m = _TIME_RE.search(text)
    if not m:
        return None, ""
    hour = int(m.group(1))
    minute = int(m.group(2)) if m.group(2) else 0
    is_am = "오전" in text
    is_pm = "오후" in text
    if hour < 12 and (is_pm or (not is_am and 1 <= hour <= 11)):
        hour += 12
    return f"{hour:02d}:{minute:02d}", m.group(0)


def _extract_title(text: str, date_frag: str, time_frag: str) -> str:
    title = text
    for frag in (date_frag, time_frag):
        if frag:
            title = title.replace(frag, " ")
    for word in _TRIGGERS + _NOISE_WORDS:
        title = title.replace(word, " ")
    title = re.sub(r"\s+", " ", title).strip()
    return title or "일정"


def _format_item(item: dict) -> str:
    if item.get("time"):
        return f"{item['date']} {item['time']} {item['title']}"
    return f"{item['date']} {item['title']}"


class ScheduleSkill(Skill):
    name = "schedule"
    description = "일정(약속/이벤트)을 로컬에 등록하고 조회한다"
    triggers = _TRIGGERS
    examples = [
        "내일 3시에 회의 일정 추가해줘",
        "오늘 일정 뭐있어",
        "이번주 일정 알려줘",
    ]

    def can_handle(self, intent: str, text: str) -> float:
        haystack = f"{intent} {text}"
        if any(t in haystack for t in self.triggers):
            return 0.85
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        if any(w in text for w in _ADD_WORDS):
            return self._add(text)
        return self._query(text)

    def _add(self, text: str) -> SkillResult:
        iso_date, date_frag = _extract_date(text)
        time_str, time_frag = _extract_time(text)
        title = _extract_title(text, date_frag, time_frag)

        item = {"date": iso_date, "time": time_str, "title": title}
        items = _load()
        items.append(item)
        _save(items)

        when = f"{iso_date} {time_str}".strip() if time_str else iso_date
        return SkillResult(
            speech=f"{when} {title} 일정을 등록했습니다.",
            success=True,
            data=item,
        )

    def _query(self, text: str) -> SkillResult:
        today = date.today()
        items = sorted(_load(), key=lambda i: (i["date"], i.get("time") or ""))

        if "오늘" in text:
            label = "오늘"
            matched = [i for i in items if i["date"] == today.isoformat()]
        elif "이번주" in text or "이번 주" in text:
            label = "이번주"
            monday = today - timedelta(days=today.weekday())
            sunday = monday + timedelta(days=6)
            matched = [
                i for i in items
                if monday.isoformat() <= i["date"] <= sunday.isoformat()
            ]
        else:
            label = "앞으로의"
            matched = [i for i in items if i["date"] >= today.isoformat()]

        if not matched:
            return SkillResult(
                speech="해당 기간에 등록된 일정이 없습니다.",
                success=True,
                data={"items": []},
            )

        lines = "\n".join(_format_item(i) for i in matched)
        speech = f"{label} 일정은 다음과 같습니다.\n{lines}"
        return SkillResult(speech=speech, success=True, data={"items": matched})
