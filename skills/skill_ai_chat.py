from core.engines.claude_cli_engine import ClaudeCliEngine
from core.skill_base import Skill, SkillResult


class AiChatSkill(Skill):
    """어떤 스킬도 처리하지 못한 입력을 Claude Code CLI에 위임한다."""

    name = "ai_chat"
    description = "다른 스킬이 처리하지 못한 자연어 요청을 Claude Code CLI로 응답한다"
    triggers = []
    examples = []

    def __init__(self) -> None:
        self._engine = ClaudeCliEngine()

    def can_handle(self, intent: str, text: str) -> float:
        return 0.1

    def execute(self, text: str, context: dict) -> SkillResult:
        response = self._engine.ask(text)
        return SkillResult(speech=response, success=True)
