"""UIA + Claude Vision 하이브리드 화면 제어 에이전트 스킬 (전략 A).

모든 화면 제어 요청에서 두 레이어를 동시에 사용한다:
  - UIA (pyuiautomation): 버튼·입력창·체크박스 등 요소의 정확한 좌표·상태 추출
  - Vision (Claude): 스크린샷 + SoM 번호 오버레이로 맥락·레이아웃 이해

UIA가 커버하지 못하는 영역(웹 콘텐츠, 이미지, 게임 등)은 Vision이 자동으로 보완.

트리거 예시:
  "화면 제어로 네이버 부동산 켜서 대전 서구 아파트 수집해줘"
  "직접 제어해서 크롬으로 유튜브 자비스 검색해줘"
  "화면 에이전트로 엑셀 열고 데이터 입력해줘"
  "설정 창에서 다크모드 켜줘"
"""
import logging

from core.hybrid_screen import HybridScreenEngine
from core.skill_base import Skill, SkillResult

logger = logging.getLogger(__name__)

_STRONG = ["화면 제어", "화면 에이전트", "직접 제어", "화면으로 제어", "스크린 에이전트", "컴퓨터 제어"]
_OPEN   = ["켜서", "열어서", "직접 열어", "직접 켜서", "실행해서", "실행하고"]
# "켜서"/"열어서"류로 앱을 연 뒤 화면에서 직접 눈으로 확인 가능한 동작을 시키는
# 문장 - "크롬 켜서 대전날씨 검색해줘"가 skill_weather(0.85)에 뺏기지 않고
# 실제 화면 제어(0.91)로 라우팅되도록 검색/입력/클릭류 동사까지 포함한다.
_ACTION = [
    "수집해줘", "수집해서", "저장해줘", "긁어줘", "스크래핑",
    "검색해줘", "검색해서", "찾아줘", "찾아봐줘",
    "입력해줘", "입력해서", "클릭해줘", "눌러줘",
]


class ScreenAgentSkill(Skill):
    """UIA + Claude Vision 하이브리드로 화면을 정밀 인식하고 직접 제어하는 에이전트."""

    name = "screen_agent"
    description = "UIA 요소 트리 + Claude Vision으로 화면을 정밀 인식하고 마우스·키보드를 제어한다"
    triggers = ["화면 제어", "화면 에이전트", "직접 제어", "컴퓨터 제어"]
    examples = [
        "화면 제어로 네이버 부동산 켜서 대전 서구 아파트 수집해줘",
        "직접 제어해서 크롬으로 유튜브 자비스 검색해줘",
        "화면 에이전트로 엑셀 열고 데이터 입력해줘",
        "설정 창에서 다크모드 켜줘",
    ]

    def can_handle(self, intent: str, text: str) -> float:
        if any(t in text for t in _STRONG):
            return 0.95
        if any(o in text for o in _OPEN) and any(a in text for a in _ACTION):
            return 0.91
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        tts_callback = None
        try:
            from voice import tts as _tts
            tts_callback = _tts.speak
        except Exception:
            pass

        engine = HybridScreenEngine(on_chunk=tts_callback)
        result = engine.run(task=text)
        return SkillResult(speech=result, success=True, data={"task": text})
