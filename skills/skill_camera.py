"""skills/skill_camera.py — 웹캠/IP 카메라 한 프레임 캡처 스킬.

두 가지 경로를 가진다(§4):
  1. 로컬 웹캠 — ffmpeg dshow 캡처를 commands.windows_bridge.run_command()로 위임.
  2. IP/모바일 카메라 스트림 — 순수 Python(opencv-python)으로 직접 처리.
     네트워크 스트림은 OS 위임이 필요 없으므로 windows_bridge를 거치지 않는다.
"""
from __future__ import annotations

import logging
import re
import subprocess
from datetime import datetime

from core.skill_base import Skill, SkillResult
from commands.windows_bridge import run_command
from commands.specs.capture_specs import CAPTURES_DIR

logger = logging.getLogger(__name__)

_URL_PATTERN = re.compile(r"https?://\S+")


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


def _timestamped_path():
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return CAPTURES_DIR / f"camera_{stamp}.png"


class CameraSkill(Skill):
    """웹캠 또는 IP 카메라 스트림에서 한 프레임을 캡처한다."""

    name = "camera"
    description = "웹캠으로 사진을 찍거나, IP 카메라 스트림에서 한 프레임을 캡처한다"
    triggers = ["사진 찍어줘", "웹캠", "카메라로 찍어"]
    examples = [
        "웹캠으로 사진 찍어줘",
        "카메라로 찍어줘",
        "http://192.168.0.10:8080/video 카메라 캡처해줘",
    ]

    command_ids = ("CAPTURE_CAMERA",)

    def can_handle(self, intent: str, text: str) -> float:
        if any(trigger in text for trigger in self.triggers):
            return 0.85
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        url_match = _URL_PATTERN.search(text)
        if url_match:
            return self._capture_stream(url_match.group(0))
        return self._capture_webcam()

    def _capture_stream(self, url: str) -> SkillResult:
        try:
            import cv2
        except ImportError:
            return SkillResult(
                speech="카메라 스트림 기능을 사용할 수 없습니다 (opencv-python 미설치).",
                success=False,
            )

        output_path = _timestamped_path()
        cap = None
        try:
            cap = cv2.VideoCapture(url)
            ret, frame = cap.read()
            if not ret or frame is None:
                return SkillResult(
                    speech="카메라 스트림에서 영상을 가져오지 못했습니다.",
                    success=False,
                )
            cv2.imwrite(str(output_path), frame)
        except Exception as exc:  # noqa: BLE001 — 예외를 절대 밖으로 던지지 않는다
            logger.exception("IP 카메라 스트림 캡처 중 오류")
            return SkillResult(
                speech=f"카메라 스트림 캡처 중 오류가 발생했습니다: {exc}",
                success=False,
            )
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:  # noqa: BLE001
                    pass

        return SkillResult(
            speech=f"사진을 찍었습니다. 위치: {output_path}",
            success=True,
            data={"path": str(output_path)},
        )

    def _capture_webcam(self) -> SkillResult:
        devices = _list_dshow_devices("video")
        if not devices:
            return SkillResult(speech="웹캠 장치를 찾을 수 없습니다.", success=False)

        output_path = _timestamped_path()
        result = run_command(
            "CAPTURE_CAMERA",
            output_path=str(output_path),
            video_device=devices[0],
        )
        if not result.ok:
            return SkillResult(
                speech="웹캠으로 사진을 찍지 못했습니다.",
                success=False,
                data={"stderr": result.stderr},
            )

        return SkillResult(
            speech=f"사진을 찍었습니다. 위치: {output_path}",
            success=True,
            data={"path": str(output_path)},
        )
