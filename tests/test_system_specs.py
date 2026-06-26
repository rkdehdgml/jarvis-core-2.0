"""시스템 상태 스펙(system_specs) 검증 — 순수 dict 조회라 위험이 없다.

COMMAND_MAP에 SYSTEM_STATUS_QUERY가 등록되고 powershell 브릿지인지만 확인한다.
run_command()를 호출하지 않으므로 PowerShell이 실제로 돌지 않는다.

실행: python -m tests.test_system_specs  (프로젝트 루트에서)
"""
from commands.registry import register, COMMAND_MAP
from commands.specs import system_specs


def _ensure_registered() -> None:
    if "SYSTEM_STATUS_QUERY" not in COMMAND_MAP:
        register(system_specs.SPECS)


def test_registered() -> None:
    _ensure_registered()
    assert "SYSTEM_STATUS_QUERY" in COMMAND_MAP, "SYSTEM_STATUS_QUERY 미등록"


def test_bridge() -> None:
    _ensure_registered()
    spec = COMMAND_MAP["SYSTEM_STATUS_QUERY"]
    assert spec.bridge == "powershell", "bridge가 powershell이 아님"
    assert spec.script, "powershell 브릿지인데 script가 비어 있음"


def main() -> None:
    test_registered()
    test_bridge()
    print("test_system_specs 통과")


if __name__ == "__main__":
    main()
