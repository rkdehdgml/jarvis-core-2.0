from core.engines.claude_cli_engine import ClaudeCliEngine
from core.skill_base import Skill, SkillResult

_TRIGGERS = ["하는 방법", "하는법", "어떻게 하는지", "방법 알려줘", "방법이 뭐야"]

_SYSTEM_PROMPT = (
    "너는 자비스야. 사용자가 질문한 작업을 수행하는 방법을 한국어로 명확하고 "
    "간결하게, 번호를 붙인 단계별 목록(1. 2. 3. ...)으로 설명해줘. 너무 길게 "
    "늘어놓지 말고 핵심 단계만 담아."
)


class HowToSkill(Skill):
    """절차/하우투 질문을 가로채 단계별 설명을 강제하는 system 프롬프트로 답한다."""

    name = "howto"
    description = "특정 작업을 어떻게 하는지 단계별로 설명한다"
    triggers = _TRIGGERS
    examples = [
        "라면 맛있게 끓이는 방법 알려줘",
        "파이썬 설치하는 방법이 뭐야",
        "엑셀에서 표 만드는 법 알려줘",
    ]

    def __init__(self) -> None:
        self._engine = ClaudeCliEngine()

    def can_handle(self, intent: str, text: str) -> float:
        if any(t in text for t in _TRIGGERS):
            return 0.75
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        speech = self._engine.generate(text, system=_SYSTEM_PROMPT)
        return SkillResult(speech=speech, success=True, data={})
