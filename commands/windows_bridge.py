"""commands/windows_bridge.py — OS 위임의 유일한 통로.

같은 Windows 프로세스 안에서 subprocess로 외부 바이너리(shutdown.exe 등),
PowerShell, ffmpeg를 호출하는 래퍼. `ClaudeCodeEngine`/`GroqEngine`과 동일하게
"절대 예외를 밖으로 던지지 않는다 — 실패하면 CommandResult(ok=False)로 반환한다"
원칙을 따른다(OS 위임은 실패 모드가 많기 때문: 바이너리 없음/권한 없음/타임아웃 등).

환경변수 정책은 claude_code.py의 화이트리스트와 반대다: 현재 프로세스의
os.environ을 통째로 상속하되 ANTHROPIC_API_KEY만 제거한 뒤 자식에게 넘긴다
("신규 코드는 ANTHROPIC_API_KEY를 subprocess에 주입하지 않는다"는 결정사항).
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass

from commands.registry import COMMAND_MAP

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int


def _build_safe_env() -> dict:
    """os.environ을 복사하고 ANTHROPIC_API_KEY를 제거한 dict를 반환한다."""
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    return env


def run_command(command_id: str, **kwargs) -> CommandResult:
    """COMMAND_MAP[command_id]를 찾아 bridge 종류에 맞는 내부 함수로 위임한다.

    command_id가 없거나 실행 자체가 실패해도 예외를 던지지 않고
    CommandResult(ok=False)로 반환한다.
    """
    spec = COMMAND_MAP.get(command_id)
    if spec is None:
        return CommandResult(
            ok=False,
            stdout="",
            stderr=f"알 수 없는 command_id: {command_id}",
            exit_code=-1,
        )

    args = spec.build_args(kwargs) if spec.build_args is not None else []

    if spec.bridge == "exe":
        if spec.binary is None:
            return CommandResult(
                ok=False,
                stdout="",
                stderr=f"{command_id}에 binary가 지정되지 않았습니다.",
                exit_code=-1,
            )
        return _run_exe(spec.binary, args, spec.timeout)

    if spec.bridge == "powershell":
        if spec.script is None:
            return CommandResult(
                ok=False,
                stdout="",
                stderr=f"{command_id}에 script가 지정되지 않았습니다.",
                exit_code=-1,
            )
        return _run_powershell(spec.script, spec.timeout)

    if spec.bridge == "ffmpeg":
        return _run_ffmpeg(args, spec.timeout)

    return CommandResult(
        ok=False,
        stdout="",
        stderr=f"알 수 없는 bridge 종류: {spec.bridge}",
        exit_code=-1,
    )


def _run_exe(binary: str, args: list[str], timeout: int) -> CommandResult:
    """PATH에 있는 실행 파일을 안전하게 호출한다."""
    if shutil.which(binary) is None:
        return CommandResult(
            ok=False,
            stdout="",
            stderr=f"{binary}를 찾을 수 없습니다. PATH에 설치되어 있는지 확인해주세요.",
            exit_code=-1,
        )

    try:
        proc = subprocess.run(
            [binary, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_build_safe_env(),
        )
    except subprocess.TimeoutExpired:
        return CommandResult(
            ok=False,
            stdout="",
            stderr=f"{binary} 실행이 {timeout}초 안에 끝나지 않아 시간 초과되었습니다.",
            exit_code=-1,
        )
    except OSError as exc:
        return CommandResult(
            ok=False,
            stdout="",
            stderr=f"{binary} 실행 중 오류가 발생했습니다: {exc}",
            exit_code=-1,
        )
    except Exception as exc:  # noqa: BLE001 — 예외를 절대 밖으로 던지지 않는다
        logger.exception("%s 실행 중 예상치 못한 오류", binary)
        return CommandResult(
            ok=False,
            stdout="",
            stderr=f"{binary} 실행 중 예상치 못한 오류가 발생했습니다: {exc}",
            exit_code=-1,
        )

    return CommandResult(
        ok=proc.returncode == 0,
        stdout=proc.stdout,
        stderr=proc.stderr,
        exit_code=proc.returncode,
    )


def _run_powershell(script: str, timeout: int) -> CommandResult:
    """인라인 PowerShell 스크립트를 안전하게 실행한다."""
    if shutil.which("powershell.exe") is None:
        return CommandResult(
            ok=False,
            stdout="",
            stderr="powershell.exe를 찾을 수 없습니다. PATH에 설치되어 있는지 확인해주세요.",
            exit_code=-1,
        )

    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_build_safe_env(),
        )
    except subprocess.TimeoutExpired:
        return CommandResult(
            ok=False,
            stdout="",
            stderr=f"PowerShell 실행이 {timeout}초 안에 끝나지 않아 시간 초과되었습니다.",
            exit_code=-1,
        )
    except OSError as exc:
        return CommandResult(
            ok=False,
            stdout="",
            stderr=f"PowerShell 실행 중 오류가 발생했습니다: {exc}",
            exit_code=-1,
        )
    except Exception as exc:  # noqa: BLE001 — 예외를 절대 밖으로 던지지 않는다
        logger.exception("PowerShell 실행 중 예상치 못한 오류")
        return CommandResult(
            ok=False,
            stdout="",
            stderr=f"PowerShell 실행 중 예상치 못한 오류가 발생했습니다: {exc}",
            exit_code=-1,
        )

    return CommandResult(
        ok=proc.returncode == 0,
        stdout=proc.stdout,
        stderr=proc.stderr,
        exit_code=proc.returncode,
    )


def _run_ffmpeg(args: list[str], timeout: int) -> CommandResult:
    """ffmpeg.exe 호출 래퍼 — 결국 exe 호출이라 _run_exe에 위임한다."""
    return _run_exe("ffmpeg.exe", args, timeout)
