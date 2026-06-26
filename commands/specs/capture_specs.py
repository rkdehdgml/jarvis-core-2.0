"""commands/specs/capture_specs.py — 스크린샷/화면녹화/음성녹음/웹캠 캡처 명령 스펙.

스크린샷은 bridge="powershell"이라 windows_bridge.run_command()가 kwargs를
스크립트에 반영하지 못한다(고정 script 문자열만 실행) — 그래서 항상 고정된
임시 파일(SCREENSHOT_TMP_PATH)에 저장하고, 호출한 스킬이 그 파일을 타임스탬프
이름으로 옮기는 2단계 구조를 쓴다.

화면녹화/음성녹음/웹캠 캡처는 bridge="ffmpeg"(exe 브릿지를 통해 실행)라
build_args(kwargs)가 정상적으로 동작한다 — output_path/duration/device 이름을
호출 시점에 동적으로 넘길 수 있다. device 이름(마이크/카메라의 실제 dshow
장치명)은 머신마다 달라서 이 파일에서 하드코딩하지 않는다 — 호출하는 스킬이
`ffmpeg -f dshow -list_devices true -i dummy`로 직접 조회해서 kwargs로 넘겨야
한다.
"""
from __future__ import annotations

from pathlib import Path

from commands.registry import CommandSpec

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CAPTURES_DIR = _PROJECT_ROOT / "data" / "captures"
CAPTURES_DIR.mkdir(parents=True, exist_ok=True)

# 스크린샷 전용 고정 임시 경로 (powershell 브릿지가 kwargs를 못 받기 때문).
SCREENSHOT_TMP_PATH = CAPTURES_DIR / "_screenshot_tmp.png"

_SCREENSHOT_SCRIPT = f"""
Add-Type -AssemblyName System.Windows.Forms,System.Drawing
$bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bitmap = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
$bitmap.Save('{SCREENSHOT_TMP_PATH}', [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose()
$bitmap.Dispose()
""".strip()

SPECS: dict[str, CommandSpec] = {
    "CAPTURE_SCREENSHOT": CommandSpec(
        command_id="CAPTURE_SCREENSHOT",
        description="전체 화면을 스크린샷으로 캡처해 고정 임시 경로에 저장",
        bridge="powershell",
        script=_SCREENSHOT_SCRIPT,
        timeout=15,
    ),
    # kwargs: output_path(str), duration(int, 초 — 호출 스킬이 60 이하로 clamp할 것),
    #         audio_device(str, dshow 오디오 장치명)
    "CAPTURE_SCREEN_RECORD": CommandSpec(
        command_id="CAPTURE_SCREEN_RECORD",
        description="화면(gdigrab) + 마이크(dshow)를 함께 녹화",
        bridge="ffmpeg",
        build_args=lambda kw: [
            "-y",
            "-f", "gdigrab",
            "-framerate", "15",
            "-i", "desktop",
            "-f", "dshow",
            "-i", f"audio={kw['audio_device']}",
            "-t", str(kw["duration"]),
            kw["output_path"],
        ],
        timeout=120,
    ),
    # kwargs: output_path(str), duration(int, 초 — 60 이하로 clamp), audio_device(str)
    "CAPTURE_VOICE_RECORD": CommandSpec(
        command_id="CAPTURE_VOICE_RECORD",
        description="마이크(dshow) 음성만 녹음",
        bridge="ffmpeg",
        build_args=lambda kw: [
            "-y",
            "-f", "dshow",
            "-i", f"audio={kw['audio_device']}",
            "-t", str(kw["duration"]),
            kw["output_path"],
        ],
        timeout=120,
    ),
    # kwargs: output_path(str), video_device(str, dshow 비디오 장치명)
    "CAPTURE_CAMERA": CommandSpec(
        command_id="CAPTURE_CAMERA",
        description="웹캠(dshow)에서 한 프레임을 캡처",
        bridge="ffmpeg",
        build_args=lambda kw: [
            "-y",
            "-f", "dshow",
            "-i", f"video={kw['video_device']}",
            "-frames:v", "1",
            kw["output_path"],
        ],
        timeout=15,
    ),
}
