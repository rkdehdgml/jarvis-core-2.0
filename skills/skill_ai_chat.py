from core.skill_base import Skill, SkillResult
# [ROLLBACK] from core.engines.claude_code import ClaudeCodeEngine as Engine
from core.engines.groq_engine import GroqEngine as Engine


class AiChatSkill(Skill):
    """어떤 스킬도 처리하지 못한 입력을 AI 엔진(Engine)에게 위임하는 최후의 폴백."""

    name = "ai_chat"
    description = "다른 스킬이 처리하지 못한 자연어 요청을 AI로 응답한다"
    triggers = []
    examples = []

    def __init__(self) -> None:
        self._engine = Engine()

    def can_handle(self, intent: str, text: str) -> float:
        # 항상 낮은 점수 → Router 임계값에 못 미쳐 폴백으로만 선택됨
        return 0.1

    def execute(self, text: str, context: dict) -> SkillResult:
        response = self._engine.ask(text)
        return SkillResult(speech=response, success=True)
