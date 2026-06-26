"""skill_schedule 검증: 등록/조회 동작과 날짜/시간 파싱.

실행: python -m tests.test_skill_schedule  (프로젝트 루트에서)

실제 data/schedule.json을 더럽히지 않도록 테스트 전 내용을 백업하고
끝나면 원래대로 복원한다.
"""
from datetime import date, timedelta
from pathlib import Path

from skills.skill_schedule import ScheduleSkill

_SCHEDULE_PATH = Path(__file__).parent.parent / "data" / "schedule.json"


def main() -> None:
    # --- 백업 (없으면 None) ---
    backup = None
    if _SCHEDULE_PATH.exists():
        backup = _SCHEDULE_PATH.read_text(encoding="utf-8")
    # 테스트는 깨끗한 상태에서 시작.
    _SCHEDULE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SCHEDULE_PATH.write_text("[]", encoding="utf-8")

    try:
        skill = ScheduleSkill()

        # --- can_handle ---
        assert skill.can_handle("내일 일정 추가해줘", "") >= 0.4
        assert skill.can_handle("스케줄 알려줘", "") >= 0.4
        assert skill.can_handle("오늘 날씨 어때", "") == 0.0

        # --- 등록: "내일 3시" 파싱 검증 ---
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        r = skill.execute("내일 3시에 테스트회의999 일정 추가해줘", {})
        assert r.success
        assert r.data["date"] == tomorrow, f"날짜 불일치: {r.data['date']} != {tomorrow}"
        assert r.data["time"] == "15:00", f"시간 불일치: {r.data['time']}"
        assert "테스트회의999" in r.data["title"], f"제목 누락: {r.data['title']!r}"

        # --- 조회: 이번주 범위 검증 ---
        # "내일"이 이번주를 벗어날 수 있으므로(예: 일요일 실행) "오늘"로
        # 안전하게 한 건 더 등록해 이번주 조회에 확실히 포함시킨다.
        skill.execute("오늘 테스트회의999 일정 추가해줘", {})
        q = skill.execute("이번주 일정 알려줘", {})
        assert q.success
        assert "테스트회의999" in q.speech, f"이번주 조회에 항목 누락: {q.speech!r}"

        print("[can_handle] 통과")
        print("[등록]", r.speech)
        print("[이번주 조회]", q.speech.replace("\n", " | "))
        print("\nskill_schedule 검증 통과")
    finally:
        # --- 복원 ---
        if backup is None:
            _SCHEDULE_PATH.unlink(missing_ok=True)
        else:
            _SCHEDULE_PATH.write_text(backup, encoding="utf-8")


if __name__ == "__main__":
    main()
