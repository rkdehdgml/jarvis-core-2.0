"""UIA + Claude Vision 하이브리드로 현재 화면을 분석하는 스킬.

"지금 화면 봐줘", "화면 분석해줘" 등 분석 요청에 반응한다.
screen_agent(화면 제어)와 달리 화면을 '보고 설명'하는 데 집중한다.
HybridScreenEngine.capture_and_describe()로:
  1. UIA 요소 트리 수집 (요소 종류·이름·상태)
  2. 스크린샷 + SoM 번호 오버레이 생성
  3. Claude Vision에 두 정보 동시 전달 → 한국어 설명
"""
from core.hybrid_screen import HybridScreenEngine
from core.skill_base import Skill, SkillResult

_TRIGGERS = [
    "화면 봐줘",
    "화면 분석",
    "지금 화면",
    "스크린 분석",
    "화면 설명",
    "화면 뭐야",
    "화면에 뭐가",
    "지금 뭐가 열려",
    "화면 캡처",
]


class ComputerUseSkill(Skill):
    """UIA + Vision 하이브리드로 현재 화면을 캡처하고 내용을 설명한다."""

    name = "computer_use"
    description = "UIA 요소 트리 + Claude Vision으로 현재 화면을 분석해 한국어로 설명한다"
    triggers = _TRIGGERS
    examples = [
        "지금 화면 봐줘",
        "화면 분석해줘",
        "화면에 뭐가 있는지 설명해줘",
        "지금 뭐가 열려 있어?",
    ]

    def can_handle(self, intent: str, text: str) -> float:
        if any(t in text for t in _TRIGGERS):
            return 0.9
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        engine = HybridScreenEngine()
        result = engine.capture_and_describe(question=text)
        return SkillResult(speech=result, success=True)
