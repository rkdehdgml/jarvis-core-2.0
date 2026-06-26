"""skill_system_status 검증.

can_handle()은 순수 점수 계산이라 안전하다. execute()는 읽기 전용 조회(SYSTEM_STATUS_QUERY)라
실제 PowerShell을 호출해도 부작용이 없다 — 단, 방화벽/권한 등으로 실패할 경우에도 예외 없이
success=False로 우아하게 끝나는지까지 확인한다.

실행: python -m tests.test_skill_system_status  (프로젝트 루트에서)
"""
from commands.registry import register, COMMAND_MAP
from commands.specs import system_specs
from skills.skill_system_status import SystemStatusSkill


def _ensure_registered() -> None:
    if "SYSTEM_STATUS_QUERY" not in COMMAND_MAP:
        register(system_specs.SPECS)


def test_can_handle() -> None:
    s = SystemStatusSkill()
    assert s.can_handle("", "시스템 상태 알려줘") >= 0.4
    # skill_system_info 영역 — 양보해야 한다.
    assert s.can_handle("", "CPU 얼마나 써") == 0.0
    assert s.can_handle("", "메모리 얼마나 써") == 0.0
    # 무관 문장.
    assert s.can_handle("", "오늘 날씨 어때") == 0.0


def test_execute() -> None:
    _ensure_registered()
    s = SystemStatusSkill()
    result = s.execute("시스템 상태 알려줘", {})
    print("[system_status]", result.success, "|", result.speech)
    if result.success:
        assert "메모리" in result.speech
        assert "드라이브" in result.speech
        assert "GB" in result.speech
    else:
        # PowerShell 호출이 환경상 실패해도 예외 없이 우아하게 끝나야 한다.
        assert result.speech == "시스템 상태를 조회하지 못했습니다."


def main() -> None:
    test_can_handle()
    test_execute()
    print("test_skill_system_status 통과")


if __name__ == "__main__":
    main()
