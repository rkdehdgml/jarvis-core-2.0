"""전원 제어 스펙(power_specs) 검증 — 실제 명령은 절대 실행하지 않는다.

이 테스트는 COMMAND_MAP 등록 여부와 build_args 결과(순수 람다 호출)만 확인하므로
shutdown.exe / rundll32.exe를 호출하지 않는다 — run_command()를 부르지 않는다.

실행: python -m tests.test_power_specs  (프로젝트 루트에서)
"""
from commands.registry import COMMAND_MAP


def test_registered() -> None:
    for cid in ("POWER_SHUTDOWN", "POWER_RESTART", "POWER_SLEEP"):
        assert cid in COMMAND_MAP, f"{cid} 가 COMMAND_MAP에 등록되지 않음"


def test_build_args() -> None:
    assert COMMAND_MAP["POWER_SHUTDOWN"].build_args({}) == ["/s", "/t", "0"]
    assert COMMAND_MAP["POWER_RESTART"].build_args({}) == ["/r", "/t", "0"]
    assert COMMAND_MAP["POWER_SLEEP"].build_args({}) == [
        "powrprof.dll,SetSuspendState",
        "0,1,0",
    ]


def test_binaries() -> None:
    assert COMMAND_MAP["POWER_SHUTDOWN"].binary == "shutdown.exe"
    assert COMMAND_MAP["POWER_RESTART"].binary == "shutdown.exe"
    assert COMMAND_MAP["POWER_SLEEP"].binary == "rundll32.exe"


def main() -> None:
    test_registered()
    test_build_args()
    test_binaries()
    print("test_power_specs 통과")


if __name__ == "__main__":
    main()
