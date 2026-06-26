"""skills/skill_voice_record.py — 마이크로 음성만 녹음해서 저장하는 스킬.

실제 녹음은 commands/registry.py의 CAPTURE_VOICE_RECORD(ffmpeg dshow) 커맨드를
windows_bridge.run_command()로 위임한다(§core는 안 건드리고 commands 레이어 재사용).

마이크 dshow 장치명은 머신마다 다르므로 _list_dshow_devices()로 ffmpeg에 직접
조회한다 — 이건 "녹음"이 아니라 "조회" 동작이라 windows_bridge를 거치지 않고
subprocess를 직접 쓴다. 실제 녹음 동작만 run_command()를 통한다.

출력 포맷은 .wav (ffmpeg 기본 인코더 pcm_s16le, 외부 코덱 라이브러리 불필요)로
저장한다.
"""
from __future__ import annotations

import re
import subprocess
from datetime import datetime

from core.skill_base import Skill, SkillResult
from commands.windows_bridge import run_command
from commands.specs.capture_specs import CAPTURES_DIR

_DEFAULT_DURATION = 10
_MAX_DURATION = 60  # CAPTURE_VOICE_RECORD의 timeout=120 고정값 때문에 clamp.


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


def _parse_duration(text: str) -> int:
    """텍스트에서 녹음 길이(초)를 추출한다. 못 찾으면 기본 10초. 항상 60초로 clamp."""
    minutes = re.search(r"(\d+)\s*분", text)
    if minutes:
        seconds = int(minutes.group(1)) * 60
    else:
        m = re.search(r"(\d+)\s*초", text)
        seconds = int(m.group(1)) if m else _DEFAULT_DURATION
    return max(1, min(seconds, _MAX_DURATION))


class VoiceRecordSkill(Skill):
    """마이크로 음성만 녹음해서 저장한다."""

    name = "voice_record"
    description = "마이크로 음성만 녹음해서 저장한다"
    triggers = ["음성 녹음", "목소리 녹음", "녹음해줘"]
    examples = ["음성 녹음해줘", "목소리 좀 녹음해줘", "10초 동안 녹음해줘"]

    # 문서화용: 이 스킬이 호출할 수 있는 command_id 목록 (§2 관례).
    command_ids = ("CAPTURE_VOICE_RECORD",)

    def can_handle(self, intent: str, text: str) -> float:
        if any(t in text for t in self.triggers):
            return 0.85
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        duration = _parse_duration(text)

        devices = _list_dshow_devices("audio")
        if not devices:
            return SkillResult(speech="마이크 장치를 찾을 수 없습니다.", success=False)

        audio_device = devices[0]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = CAPTURES_DIR / f"voice_record_{timestamp}.wav"

        result = run_command(
            "CAPTURE_VOICE_RECORD",
            output_path=str(output_path),
            duration=duration,
            audio_device=audio_device,
        )

        if result.ok:
            return SkillResult(
                speech=f"{duration}초 동안 음성을 녹음했습니다. 위치: {output_path}",
                success=True,
                data={"path": str(output_path)},
            )
        return SkillResult(
            speech="음성 녹음에 실패했습니다.",
            success=False,
            data={"stderr": result.stderr},
        )
