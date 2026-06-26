"""commands/ 기반 레이어 검증: COMMAND_MAP 등록/중복 방지, windows_bridge의
예외 안전성 + 환경변수(ANTHROPIC_API_KEY) 격리.

실행: python -m tests.test_commands_registry  (프로젝트 루트에서)
"""
import os

from commands.registry import COMMAND_MAP, register, CommandSpec
from commands.windows_bridge import run_command, _run_exe, _run_powershell


def main() -> None:
    # 1) 초기 COMMAND_MAP은 비어 있어야 한다 (아직 어떤 spec도 등록 안 됨).
    assert COMMAND_MAP == {}, f"초기 COMMAND_MAP이 비어 있지 않음: {COMMAND_MAP}"
    print("[1] 초기 COMMAND_MAP 빈 dict 확인")

    # 2) 가짜 CommandSpec 2개 등록 → COMMAND_MAP에 정상 추가.
    spec_a = CommandSpec(
        command_id="TEST_A", description="테스트 A", bridge="exe", binary="echo",
    )
    spec_b = CommandSpec(
        command_id="TEST_B", description="테스트 B", bridge="powershell", script="exit 0",
    )
    register({"TEST_A": spec_a, "TEST_B": spec_b})
    assert COMMAND_MAP["TEST_A"] is spec_a
    assert COMMAND_MAP["TEST_B"] is spec_b
    print("[2] register()로 spec 2개 정상 등록 확인")

    # 3) 같은 command_id 재등록 시 ValueError.
    raised = False
    try:
        register({"TEST_A": spec_a})
    except ValueError as exc:
        raised = True
        assert "TEST_A" in str(exc), f"에러 메시지에 command_id 없음: {exc}"
    assert raised, "중복 command_id인데 ValueError가 발생하지 않음"
    print("[3] 중복 command_id ValueError 확인")

    # 4) 존재하지 않는 command_id로 run_command → 예외 없이 ok=False.
    result = run_command("DOES_NOT_EXIST_123")
    assert result.ok is False
    assert result.exit_code == -1
    assert "DOES_NOT_EXIST_123" in result.stderr
    print("[4] 미존재 command_id → ok=False 확인")

    # 5) 존재하지 않는 가짜 바이너리로 _run_exe → ok=False + 한국어 안내.
    result = _run_exe("definitely_not_a_real_binary_xyz.exe", [], timeout=5)
    assert result.ok is False
    assert "찾을 수 없습니다" in result.stderr, f"한국어 안내 문구 없음: {result.stderr}"
    print("[5] 미존재 바이너리 → ok=False + 한국어 안내 확인")

    # 6) _run_powershell로 'exit 0' 실행 → ok=True (이 머신에 PowerShell 존재 전제).
    result = _run_powershell("exit 0", timeout=10)
    assert result.ok is True, f"PowerShell 'exit 0'이 실패함: {result.stderr}"
    print("[6] _run_powershell('exit 0') → ok=True 확인")

    # 7) 환경변수 격리: ANTHROPIC_API_KEY가 자식 프로세스로 전달되지 않아야 한다.
    os.environ["ANTHROPIC_API_KEY"] = "fake-test-key-12345"
    try:
        result = _run_powershell("Write-Output $env:ANTHROPIC_API_KEY", timeout=10)
        assert result.ok is True, f"PowerShell 실행 실패: {result.stderr}"
        assert "fake-test-key-12345" not in result.stdout, (
            f"ANTHROPIC_API_KEY가 자식 프로세스로 누출됨: {result.stdout!r}"
        )
    finally:
        del os.environ["ANTHROPIC_API_KEY"]
    print("[7] ANTHROPIC_API_KEY 자식 프로세스 격리 확인")

    print("\ntest_commands_registry 검증 통과")


if __name__ == "__main__":
    main()
