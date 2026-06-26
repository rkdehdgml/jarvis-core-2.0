"""commands/specs/browser_specs.py — 브라우저로 URL을 여는 명령 스펙.

설계 문서(§4)는 PowerShell `Start-Process <url>`을 제안하지만 그대로 쓰지 않는다:
windows_bridge.run_command()는 bridge="powershell"일 때 spec.script(고정 문자열)만
실행하고 **kwargs를 반영하지 못하며, 음성 입력 문자열을 PowerShell -Command에 끼워
넣으면 명령어 주입 취약점이 생긴다. 그래서 bridge="exe", binary="explorer.exe"를
쓴다 — `explorer.exe <URL>`은 기본 브라우저로 URL을 여는 표준 방법이고, 인자를
리스트로 subprocess.run([binary, *args])에 넘기므로(셸 미경유) 주입 위험이 없다.
"""
from __future__ import annotations

from commands.registry import CommandSpec

SPECS: dict[str, CommandSpec] = {
    "BROWSER_OPEN_URL": CommandSpec(
        command_id="BROWSER_OPEN_URL",
        description="기본 브라우저로 URL을 연다",
        bridge="exe",
        binary="explorer.exe",
        build_args=lambda kw: [kw["url"]],
    ),
}
