"""Playwright 기반 웹 수집·검색 확인 스킬 (읽기 전용).

skill_agent.py(클로드 내장 WebFetch — 정적 HTML만)가 다루지 못하는 자바스크립트
렌더링·로그인·필터·페이지네이션이 필요한 사이트에서, 실제 브라우저(Chromium)로
검색·수집·필터링·확인을 수행한다. 구매·결제·삭제 같은 되돌릴 수 없는 액션은
core/web_collector.py가 요소 텍스트 키워드 매칭으로 최선의 노력을 다해 차단한다
(완벽한 보장은 아니다 — 다르게 표기된 컨트롤은 통과할 수 있다. 이 스킬의 범위 밖).

트리거 예시:
  "네이버 부동산에서 대전 서구 아파트 매물 수집해줘"
  "당근마켓에서 노트북 검색해서 10만원 이하로 모아줘"
  "쿠팡에서 무선청소기 검색해서 리뷰 4점 이상만 모아줘"
"""
import logging

from core.skill_base import Skill, SkillResult
from core.status_events import broadcaster
from core.web_collector import WebCollectorEngine

logger = logging.getLogger(__name__)

_STRONG = ["브라우저로 수집", "브라우저에서 검색", "사이트에서 직접 수집", "웹사이트에서 수집", "브라우저로 검색"]
# skill_agent.py의 WebFetch(정적 HTML)로는 다루지 못하는, 실제 렌더링/상호작용이
# 흔히 필요한 사이트 카테고리 키워드 — 확장 가능한 리스트.
_SITE_KEYWORDS = ["부동산", "쇼핑몰", "중고거래", "당근마켓", "번개장터", "쿠팡", "지도"]
_ACTION_KEYWORDS = [
    "수집해줘", "수집해서", "검색해줘", "검색해서",
    "찾아줘", "필터링해줘", "필터해서", "모아줘", "모아서",
]


class WebCollectorSkill(Skill):
    """Playwright로 실제 브라우저를 띄워 임의 사이트를 탐색하며 정보를 검색·수집·필터링한다."""

    name = "web_collector"
    description = "Playwright로 실제 브라우저를 띄워 임의 사이트를 탐색하며 정보를 검색·수집·필터링한다"
    triggers = ["브라우저로 수집", "웹사이트에서 수집", "사이트에서 검색"]
    examples = [
        "당근마켓에서 노트북 검색해서 10만원 이하로 모아줘",
        "네이버 부동산에서 대전 서구 아파트 매물 수집해줘",
        "쿠팡에서 무선청소기 검색해서 리뷰 4점 이상만 모아줘",
    ]

    def can_handle(self, intent: str, text: str) -> float:
        if any(t in text for t in _STRONG):
            return 0.95
        # skill_agent.py의 _STRONG_TRIGGERS(0.9)와 겹치는 "수집해줘" 등이 있을 때,
        # 사이트 이름까지 함께 언급되면(실제 브라우저 렌더링이 필요할 가능성이 높음)
        # 이 스킬이 우선하도록 더 높은 점수를 준다.
        if any(s in text for s in _SITE_KEYWORDS) and any(a in text for a in _ACTION_KEYWORDS):
            return 0.93
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        tts_callback = None
        try:
            from voice import tts as _tts
            tts_callback = _tts.speak
        except Exception:
            pass

        broadcaster.emit(state="streaming")
        engine = WebCollectorEngine(on_chunk=tts_callback)
        try:
            result = engine.run(task=text)
        except Exception as e:
            logger.error(f"웹 수집 엔진 오류: {e}")
            return SkillResult(
                speech=f"웹 수집 중 오류가 발생했습니다: {e}",
                success=False,
                data={"task": text},
            )
        return SkillResult(speech=result, success=True, data={"task": text})
