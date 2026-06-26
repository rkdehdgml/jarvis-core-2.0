"""skill_datetime 검증 (plain assert 스크립트).

실행: python -m tests.test_skill_datetime  (프로젝트 루트에서)
"""
from datetime import datetime, timedelta, timezone

from skills.skill_datetime import DatetimeSkill

_KST = timezone(timedelta(hours=9))
_WEEKDAYS_KR = ["월", "화", "수", "목", "금", "토", "일"]


def main() -> None:
    skill = DatetimeSkill()
    assert skill.name == "datetime"

    # can_handle: 시간 관련 문장은 임계값 이상, 무관한 문장은 0.0
    assert skill.can_handle("", "지금 몇 시야") >= 0.4, "시간 질문은 0.4 이상이어야 함"
    assert skill.can_handle("", "오늘 점심 뭐 먹지") == 0.0, "무관한 문장은 0.0이어야 함"

    # execute: 날짜 질문에 실제 오늘 날짜(월/일 숫자)가 포함되는지
    now = datetime.now(_KST)
    res_date = skill.execute("오늘 며칠이야", {})
    assert res_date.success
    assert f"{now.month}월" in res_date.speech, f"월이 누락됨: {res_date.speech}"
    assert f"{now.day}일" in res_date.speech, f"일이 누락됨: {res_date.speech}"
    assert "datetime_iso" in res_date.data

    # execute: 요일 질문에 한국어 요일 글자가 포함되는지
    res_wd = skill.execute("오늘 무슨 요일이야", {})
    assert res_wd.success
    assert any(wd in res_wd.speech for wd in _WEEKDAYS_KR), f"요일 글자가 없음: {res_wd.speech}"
    # 실제 오늘 요일과 일치하는지도 확인
    expected_wd = _WEEKDAYS_KR[now.weekday()]
    assert expected_wd in res_wd.speech, f"오늘 요일({expected_wd})이 응답에 없음: {res_wd.speech}"

    print("[date]", res_date.speech)
    print("[weekday]", res_wd.speech)
    print("[time]", skill.execute("지금 몇 시야", {}).speech)
    print("\nskill_datetime 검증 통과")


if __name__ == "__main__":
    main()
