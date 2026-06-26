import re
import subprocess
from datetime import datetime

from core.skill_base import Skill, SkillResult
from commands.windows_bridge import run_command
from commands.specs.capture_specs import CAPTURES_DIR

_TRIGGERS = ["화면 녹화", "화면녹화", "화면 좀 녹화"]
_DEFAULT_DURATION = 10
_MAX_DURATION = 60


def _list_dshow_devices(kind: str) -> list[str]:
    """kind: 'audio' 또는 'video'. ffmpeg -list_devices 출력(stderr)을 파싱해 장치명 리스트 반환."""
    try:
        proc = subprocess.run(
            ["ffmpeg", "-f", "dshow", "-list_devices", "true", "-i", "dummy"],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    devices = []
    for line in proc.stderr.splitlines():
        if f"({kind})" in line and '"' in line:
            name = line.split('"')[1]
            devices.append(name)
    return devices


def _extract_duration(text: str) -> int:
    m = re.search(r"(\d+)\s*분", text)
    if m:
        return min(int(m.group(1)) * 60, _MAX_DURATION)
    m = re.search(r"(\d+)\s*초", text)
    if m:
        return min(int(m.group(1)), _MAX_DURATION)
    return _DEFAULT_DURATION


class ScreenRecordSkill(Skill):
    """화면과 마이크 음성을 함께 녹화해서 영상으로 저장한다."""

    name = "screen_record"
    description = "화면과 마이크 음성을 함께 녹화해서 영상으로 저장한다"
    triggers = _TRIGGERS
    examples = ["화면 녹화해줘", "10초 동안 화면녹화 해줘", "화면 좀 녹화해줘"]

    command_ids = ("CAPTURE_SCREEN_RECORD",)

    def can_handle(self, intent: str, text: str) -> float:
        if any(t in text for t in _TRIGGERS):
            return 0.85
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        duration = _extract_duration(text)

        audio_devices = _list_dshow_devices("audio")
        if not audio_devices:
            return SkillResult(speech="마이크 장치를 찾을 수 없습니다.", success=False)
        audio_device = audio_devices[0]

        CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = CAPTURES_DIR / f"screen_record_{timestamp}.mp4"

        result = run_command(
            "CAPTURE_SCREEN_RECORD",
            output_path=str(output_path),
            duration=duration,
            audio_device=audio_device,
        )

        if result.ok:
            return SkillResult(
                speech=f"{duration}초 동안 화면을 녹화했습니다. 위치: {output_path}",
                success=True,
                data={"path": str(output_path)},
            )
        return SkillResult(
            speech="화면 녹화에 실패했습니다.",
            success=False,
            data={"stderr": result.stderr},
        )
