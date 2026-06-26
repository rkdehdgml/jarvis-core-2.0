import os

from core.skill_base import Skill, SkillResult

# 자주 쓰는 앱 이름 → Windows 실행 명령 매핑
_APP_COMMANDS = {
    "크롬": "chrome",
    "메모장": "notepad",
    "계산기": "calc",
    "탐색기": "explorer",
    "워드": "winword",
    "엑셀": "excel",
}


class AppLaunchSkill(Skill):
    """"크롬 열어", "메모장 실행" 같은 명령으로 Windows 앱을 실행한다."""

    name = "app_launch"
    description = "이름을 말하면 해당 Windows 앱을 실행한다"
    triggers = ["열어", "실행", "켜줘"]
    examples = ["크롬 열어", "메모장 실행", "계산기 켜줘"]

    def can_handle(self, intent: str, text: str) -> float:
        has_trigger = any(t in text for t in self.triggers)
        has_known_app = any(app in text for app in _APP_COMMANDS)
        if has_trigger and has_known_app:
            return 0.9
        if has_trigger:
            return 0.5
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        app_name = next((app for app in _APP_COMMANDS if app in text), None)

        if app_name is None:
            return SkillResult(
                speech="어떤 앱을 실행할지 알 수 없습니다.",
                success=False,
            )

        command = _APP_COMMANDS[app_name]
        try:
            os.startfile(command)
        except Exception:
            return SkillResult(
                speech=f"{app_name} 실행에 실패했습니다.",
                success=False,
            )

        return SkillResult(
            speech=f"{app_name} 실행했습니다",
            success=True,
            data={"app": app_name, "command": command},
        )
