"""commands/specs/power_specs.py — 전원 제어(종료/재시작/절전) 명령 스펙.

전부 Windows 내장 바이너리(shutdown.exe / rundll32.exe)에 위임하므로
외부 패키지 의존성이 없다. registry.register()로 COMMAND_MAP에 병합된다.
"""
from __future__ import annotations

from commands.registry import CommandSpec

SPECS: dict[str, CommandSpec] = {
    "POWER_SHUTDOWN": CommandSpec(
        command_id="POWER_SHUTDOWN",
        description="시스템 종료",
        bridge="exe",
        binary="shutdown.exe",
        build_args=lambda kw: ["/s", "/t", "0"],
    ),
    "POWER_RESTART": CommandSpec(
        command_id="POWER_RESTART",
        description="시스템 재시작",
        bridge="exe",
        binary="shutdown.exe",
        build_args=lambda kw: ["/r", "/t", "0"],
    ),
    "POWER_SLEEP": CommandSpec(
        command_id="POWER_SLEEP",
        description="절전 모드 진입",
        bridge="exe",
        binary="rundll32.exe",
        build_args=lambda kw: ["powrprof.dll,SetSuspendState", "0,1,0"],
    ),
}
