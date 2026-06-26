"""commands/registry.py — OS 위임 명령어의 중앙 카탈로그.

`COMMAND_MAP`은 `command_id -> CommandSpec` 단일 dict이며, 각 카테고리별
`commands/specs/*.py`가 자신의 SPECS를 `register()`로 등록한다. "기존 카테고리에
명령 추가 = specs 파일 한 곳만 수정", "새 카테고리 추가 = 이 파일 하단에 import +
register() 한 줄 추가"가 확장 규약이다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

BridgeKind = Literal["exe", "powershell", "ffmpeg"]


@dataclass(frozen=True)
class CommandSpec:
    command_id: str
    description: str
    bridge: BridgeKind
    binary: str | None = None
    script: str | None = None
    build_args: Callable[[dict], list[str]] | None = None
    timeout: int = 15


COMMAND_MAP: dict[str, CommandSpec] = {}


def register(specs: dict[str, CommandSpec]) -> None:
    """specs의 모든 CommandSpec을 COMMAND_MAP에 병합한다.

    이미 존재하는 command_id가 들어오면 조용히 덮어쓰지 않고 ValueError로
    즉시 실패시킨다 — 카테고리 간 command_id 충돌을 빌드 시점에 잡기 위함.
    """
    for command_id, spec in specs.items():
        if command_id in COMMAND_MAP:
            raise ValueError(f"중복 command_id: {command_id}")
        COMMAND_MAP[command_id] = spec


from commands.specs import power_specs

register(power_specs.SPECS)

from commands.specs import browser_specs

register(browser_specs.SPECS)

from commands.specs import system_specs

register(system_specs.SPECS)

from commands.specs import capture_specs

register(capture_specs.SPECS)

# 향후 카테고리 추가 시 여기에 import + register() 한 줄씩 추가
