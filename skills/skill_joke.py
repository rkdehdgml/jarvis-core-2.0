"""짧은 농담을 들려주는 스킬.

pyjokes로 영어 농담 원문을 가져온 뒤, ClaudeCliEngine.generate()로 자연스럽고
짧은 한국어 농담으로 번역/현지화해서 들려준다.
"""
import pyjokes

from core.engines.claude_cli_engine import ClaudeCliEngine
from core.skill_base import Skill, SkillResult

_TRIGGERS = ["농담", "썰렁한 농담", "유머", "개그", "재밌는 얘기"]

_SYSTEM_PROMPT = (
    "너는 자비스야. 아래 영어 농담을 자연스럽고 짧은 한국어 농담으로 바꿔서 "
    "들려줘. 원문의 펀치라인 느낌을 살리되 한국어 화법에 맞게 다듬어. "
    "부가 설명 없이 농담 자체만 말해."
)


class JokeSkill(Skill):
    """pyjokes로 영어 농담을 가져와 Claude CLI로 한국어 농담으로 다듬어 들려준다."""

    name = "joke"
    description = "짧은 농담을 들려준다"
    triggers = _TRIGGERS
    examples = ["농담 하나 해줘", "썰렁한 농담 해줘", "재밌는 얘기 해줘"]

    def __init__(self) -> None:
        self._engine = ClaudeCliEngine()

    def can_handle(self, intent: str, text: str) -> float:
        if any(t in text for t in _TRIGGERS):
            return 0.85
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        original = pyjokes.get_joke(language="en", category="neutral")
        speech = self._engine.generate(original, system=_SYSTEM_PROMPT)
        return SkillResult(
            speech=speech,
            success=True,
            data={"original": original},
        )
