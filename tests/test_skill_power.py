"""skill_power 검증 — 실제 전원 명령은 절대 실행하지 않는다.

execute() 검증은 전부 unittest.mock.patch("skills.skill_power.run_command")로
run_command를 가짜로 대체해 실행하므로, shutdown.exe / rundll32.exe가 호출될
경로가 원천적으로 차단된다. can_handle() 검증은 순수 점수 계산이라 실행과 무관.

실행: python -m tests.test_skill_power  (프로젝트 루트에서)
"""
from unittest.mock import patch

from commands.windows_bridge import CommandResult
from skills.skill_power import PowerSkill


def test_can_handle() -> None:
    s = PowerSkill()
    # app_control 영역 — 반드시 0.0으로 양보.
    assert s.can_handle("", "크롬 꺼줘") == 0.0
    assert s.can_handle("", "그냥 좀 꺼줘") == 0.0
    # 전원 종료 — 기기 키워드 동반.
    assert s.can_handle("", "컴퓨터 꺼줘") == 0.9
    assert s.can_handle("", "시스템 종료해줘") == 0.9
    assert s.can_handle("", "PC 꺼줘") == 0.9
    # 재시작 / 절전.
    assert s.can_handle("", "재시작해줘") == 0.9
    assert s.can_handle("", "재부팅해줘") == 0.9
    assert s.can_handle("", "절전모드로 바꿔줘") == 0.9
    # 무관 문장.
    assert s.can_handle("", "오늘 날씨 어때") == 0.0


def test_execute_dispatches_correct_command_id() -> None:
    s = PowerSkill()
    fake = CommandResult(ok=True, stdout="", stderr="", exit_code=0)

    cases = {
        "컴퓨터 종료해줘": "POWER_SHUTDOWN",
        "재시작해줘": "POWER_RESTART",
        "절전모드로 바꿔줘": "POWER_SLEEP",
    }
    for text, expected_id in cases.items():
        with patch("skills.skill_power.run_command", return_value=fake) as mock:
            result = s.execute(text, {})
        mock.assert_called_once_with(expected_id)
        assert result.success is True
        assert result.data["command_id"] == expected_id


def test_execute_failure_propagates() -> None:
    s = PowerSkill()
    fail = CommandResult(ok=False, stdout="", stderr="boom", exit_code=-1)
    with patch("skills.skill_power.run_command", return_value=fail) as mock:
        result = s.execute("컴퓨터 종료해줘", {})
    mock.assert_called_once_with("POWER_SHUTDOWN")
    assert result.success is False
    assert result.speech == "명령 실행에 실패했습니다."


def test_execute_unresolvable_does_not_call_run_command() -> None:
    s = PowerSkill()
    with patch("skills.skill_power.run_command") as mock:
        result = s.execute("아무말", {})
    assert mock.call_count == 0, "해석 불가 텍스트인데 run_command가 호출됨"
    assert result.success is False


def main() -> None:
    test_can_handle()
    test_execute_dispatches_correct_command_id()
    test_execute_failure_propagates()
    test_execute_unresolvable_does_not_call_run_command()
    print("test_skill_power 통과")


if __name__ == "__main__":
    main()
