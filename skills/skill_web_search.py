import re

from core.engines.claude_cli_engine import ClaudeCliEngine
from core.search_engine import SearchEngine
from core.skill_base import Skill, SkillResult

_PUNCTUATION = re.compile(r"[?!.,~]")

# 검색을 강하게 암시하는 단어 — 단독으로도 임계값(0.4)을 넘긴다.
# "날씨"는 여기 없다 — skill_weather.py가 Open-Meteo로 더 정확하게 처리한다.
# "뉴스"는 여기 없다 — skill_news.py가 NewsAPI로 더 정확하게 처리한다.
_STRONG_KEYWORDS = ["환율", "주가", "검색해줘", "찾아줘", "검색", "찾아"]

# 일반 대화에도 흔히 쓰이는 단어 — 단독으론 임계값 밑(0.3)으로 둬서 애매하면 AI 폴백이
# 이기게 하고, _STRONG_KEYWORDS와 같이 나올 때만 점수를 보탠다.
# (skill_window.py가 "창" 한 글자만으로 "곱창집"까지 가로채던 버그를 막 고친 직후라,
#  여기서도 같은 실수를 반복하지 않으려고 일부러 단계를 나눴다.)
_WEAK_KEYWORDS = ["오늘", "지금", "최신", "어때", "알려줘", "얼마", "몇 도", "경기", "결과"]

# 다른 스킬과 겹치는 것을 막는 명시적 제외 키워드.
_EXCLUDE_KEYWORDS = ["볼륨", "메모"]

_ADDRESS_PATTERNS = ["자비스야", "자비스"]
_REQUEST_SUFFIXES = [
    "검색해줘",
    "찾아봐줘",
    "찾아줘",
    "알아봐줘",
    "알려줘",
    "말해줘",
    "얼마야",
    "어때",
    "얼마",
]

_MAX_RESULTS = 5

_SYSTEM_PROMPT = (
    "너는 자비스야. 아래 검색 결과를 바탕으로 사용자에게 자연스럽고 간결하게 대답해줘. "
    "검색 결과에 있는 정보만 활용하고, 모르는 건 모른다고 해. "
    "출처 URL은 굳이 읽어주지 않아도 돼."
)


class WebSearchSkill(Skill):
    """날씨/뉴스/환율 등 실시간 정보를 웹에서 검색해 Claude CLI로 요약·답변한다."""

    name = "web_search"
    description = "실시간 웹 정보(날씨, 뉴스, 환율 등)를 검색해서 알려준다"
    triggers = _STRONG_KEYWORDS
    examples = ["최신 AI 뉴스 검색해줘", "환율 얼마야", "삼성전자 주가 찾아줘"]

    def __init__(self) -> None:
        self._search = SearchEngine()
        self._engine = ClaudeCliEngine()

    def can_handle(self, intent: str, text: str) -> float:
        if any(k in text for k in _EXCLUDE_KEYWORDS):
            return 0.0
        if any(k in text for k in _STRONG_KEYWORDS):
            return 0.8
        if any(k in text for k in _WEAK_KEYWORDS):
            return 0.3
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        query = self._extract_query(text)
        results = self._search.search(query, max_results=_MAX_RESULTS)

        if not results:
            return SkillResult(
                speech="검색 결과를 찾지 못했습니다. 다시 질문해주시겠어요?",
                success=True,
                data={
                    "query": query,
                    "results_count": 0,
                    "search_engine": "brave" if self._search.use_brave else "duckduckgo",
                },
            )

        formatted = self._search.format_results(results)
        prompt = f"사용자 질문: {text}\n\n검색 결과:\n{formatted}"
        speech = self._engine.generate(prompt, system=_SYSTEM_PROMPT)

        return SkillResult(
            speech=speech,
            success=True,
            data={
                "query": query,
                "results_count": len(results),
                "search_engine": "brave" if self._search.use_brave else "duckduckgo",
            },
            follow_up=False,
        )

    def _extract_query(self, text: str) -> str:
        """사용자 발화에서 호칭/요청형 어미를 떼고 검색 핵심어만 남긴다."""
        query = text
        for pattern in _ADDRESS_PATTERNS:
            query = query.replace(pattern, "")
        for pattern in _REQUEST_SUFFIXES:
            query = query.replace(pattern, "")
        query = _PUNCTUATION.sub("", query)
        query = " ".join(query.split())
        return query if query else text
