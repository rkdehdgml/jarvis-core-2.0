from core.skill_base import Skill, SkillResult
from commands.windows_bridge import run_command

# "종료"/"꺼줘"가 전원 종료를 뜻하려면 반드시 동반되어야 하는 기기 키워드.
# 이게 없으면 skill_app_control(앱 종료)에 양보한다.
_DEVICE_WORDS = ["컴퓨터", "시스템", "PC", "노트북"]


class PowerSkill(Skill):
    """컴퓨터를 종료/재시작/절전 모드로 전환한다."""

    name = "power"
    description = "컴퓨터를 종료/재시작/절전 모드로 전환한다"
    triggers = ["재시작", "재부팅", "절전", "종료", "꺼줘"]
    examples = ["컴퓨터 종료해줘", "재시작해줘", "절전모드로 바꿔줘"]

    # 문서화용: 이 스킬이 호출할 수 있는 command_id 목록 (§2 관례).
    command_ids = ("POWER_SHUTDOWN", "POWER_RESTART", "POWER_SLEEP")

    def can_handle(self, intent: str, text: str) -> float:
        # 재시작/재부팅, 절전은 다른 스킬과 겹치지 않아 단독으로 안전하게 발동.
        if "재시작" in text or "재부팅" in text:
            return 0.9
        if "절전" in text:
            return 0.9
        # "종료"/"꺼줘"는 app_control과 겹친다 — 기기 키워드가 같이 있을 때만 전원 종료.
        if "종료" in text or "꺼줘" in text:
            if any(d in text for d in _DEVICE_WORDS):
                return 0.9
            # 모호한 "꺼줘"는 전원 종료로 오해하면 안 되므로 양보(0.0).
            return 0.0
        return 0.0

    def _resolve_command_id(self, text: str) -> str | None:
        if "재시작" in text or "재부팅" in text:
            return "POWER_RESTART"
        if "절전" in text:
            return "POWER_SLEEP"
        if ("종료" in text or "꺼줘" in text) and any(d in text for d in _DEVICE_WORDS):
            return "POWER_SHUTDOWN"
        return None

    def execute(self, text: str, context: dict) -> SkillResult:
        command_id = self._resolve_command_id(text)
        if command_id is None:
            return SkillResult(speech="어떤 동작인지 알 수 없습니다.", success=False)

        result = run_command(command_id)

        _SPEECH = {
            "POWER_SHUTDOWN": "시스템을 종료합니다.",
            "POWER_RESTART": "시스템을 재시작합니다.",
            "POWER_SLEEP": "절전 모드로 전환합니다.",
        }
        speech = _SPEECH[command_id] if result.ok else "명령 실행에 실패했습니다."

        return SkillResult(
            speech=speech,
            success=result.ok,
            data={"command_id": command_id},
        )
