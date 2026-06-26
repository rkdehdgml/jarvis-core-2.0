from datetime import datetime, timedelta, timezone

from core.skill_base import Skill, SkillResult

# 한국 표준시(KST)는 일광절약시간제가 없어 고정 +9 오프셋이 항상 정확하다.
# zoneinfo("Asia/Seoul")는 Windows에 IANA tzdata가 없으면 실패하므로 의존하지 않는다.
_KST = timezone(timedelta(hours=9))

_WEEKDAYS_KR = ["월", "화", "수", "목", "금", "토", "일"]

_TRIGGERS = [
    "몇 시",
    "몇시",
    "오늘 날짜",
    "며칠",
    "요일",
    "무슨 요일",
    "지금 시간",
    "현재 시간",
    "날짜",
    "시각",
]

_WEEKDAY_KEYWORDS = ["요일"]
_DATE_KEYWORDS = ["날짜", "며칠"]
_TIME_KEYWORDS = ["몇 시", "몇시", "시각", "시간", "시"]


class DatetimeSkill(Skill):
    """표준 라이브러리로 KST 기준 현재 날짜/시간/요일을 한국어로 알려준다."""

    name = "datetime"
    description = "현재 날짜, 시간, 요일을 알려준다"
    triggers = _TRIGGERS
    examples = ["지금 몇 시야", "오늘 며칠이야", "오늘 무슨 요일이야"]

    def can_handle(self, intent: str, text: str) -> float:
        if any(k in text for k in _TRIGGERS):
            return 0.85
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        now = datetime.now(_KST)
        weekday = _WEEKDAYS_KR[now.weekday()]

        date_part = f"{now.month}월 {now.day}일"
        weekday_part = f"{weekday}요일"
        hour = now.hour
        meridiem = "오전" if hour < 12 else "오후"
        hour12 = hour % 12 or 12
        time_part = f"{meridiem} {hour12}시 {now.minute}분"

        want_weekday = any(k in text for k in _WEEKDAY_KEYWORDS)
        want_date = any(k in text for k in _DATE_KEYWORDS)
        want_time = any(k in text for k in _TIME_KEYWORDS)

        if want_weekday and not (want_date or want_time):
            speech = f"오늘은 {weekday_part}입니다."
        elif want_date and not (want_weekday or want_time):
            speech = f"오늘은 {date_part} {weekday_part}입니다."
        elif want_time and not (want_weekday or want_date):
            speech = f"지금은 {time_part}입니다."
        else:
            speech = f"오늘은 {now.year}년 {date_part} {weekday_part}, 현재 시각은 {time_part}입니다."

        return SkillResult(
            speech=speech,
            success=True,
            data={"datetime_iso": now.isoformat()},
            follow_up=False,
        )
