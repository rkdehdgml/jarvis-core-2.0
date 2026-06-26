from datetime import datetime
import shutil

from core.skill_base import Skill, SkillResult
from commands.windows_bridge import run_command
from commands.specs.capture_specs import SCREENSHOT_TMP_PATH, CAPTURES_DIR

_TRIGGERS = ["스크린샷", "화면 캡처", "화면 캡쳐", "캡처해줘", "화면 저장"]


class ScreenshotSkill(Skill):
    """현재 화면을 캡처해서 이미지로 저장한다."""

    name = "screenshot"
    description = "현재 화면을 캡처해서 이미지로 저장한다"
    triggers = _TRIGGERS
    examples = ["스크린샷 찍어줘", "화면 캡처해줘", "지금 화면 저장해줘"]

    # 문서화용: 이 스킬이 호출하는 command_id 목록.
    command_ids = ("CAPTURE_SCREENSHOT",)

    def can_handle(self, intent: str, text: str) -> float:
        if any(t in text for t in _TRIGGERS):
            return 0.85
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        result = run_command("CAPTURE_SCREENSHOT")
        if not result.ok:
            return SkillResult(
                speech="스크린샷 캡처에 실패했습니다.",
                success=False,
                data={"stderr": result.stderr},
            )

        # powershell 브릿지가 항상 고정 임시 경로에 저장한다 — 타이밍 이슈로
        # 파일이 아직 안 만들어졌을 수 있으니 존재를 확인하고 우아하게 처리.
        if not SCREENSHOT_TMP_PATH.exists():
            return SkillResult(
                speech="스크린샷 파일을 찾지 못했습니다.",
                success=False,
                data={"stderr": result.stderr},
            )

        dest = CAPTURES_DIR / f"screenshot_{datetime.now():%Y%m%d_%H%M%S}.png"
        shutil.move(str(SCREENSHOT_TMP_PATH), str(dest))

        return SkillResult(
            speech=f"스크린샷을 저장했습니다. 위치: {dest}",
            success=True,
            data={"path": str(dest)},
        )
