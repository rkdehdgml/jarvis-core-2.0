"""최신 뉴스 헤드라인을 NewsAPI.org로 조회해 알려주는 스킬.

주제어가 없으면 한국 톱 헤드라인(top-headlines, country=kr), 주제어가 있으면
해당 주제로 한국어 기사를 최신순 검색(everything)한다.

API 키는 .env의 NEWSAPI_KEY를 execute() 안에서 lazy하게 읽는다 —
core/engines/groq_engine.py의 GROQ_API_KEY lazy-check와 같은 패턴으로,
키가 없는 환경에서도 SkillRegistry 로딩이 깨지지 않게 하기 위함이다.
"""
import os
import re

import requests

from core.skill_base import Skill, SkillResult

_TOP_HEADLINES_URL = "https://newsapi.org/v2/top-headlines"
_EVERYTHING_URL = "https://newsapi.org/v2/everything"
_TIMEOUT = 5
_MAX_ARTICLES = 5

_PUNCTUATION = re.compile(r"[?!.,~]")

# 주제어 추출 시 걷어낼 트리거·조사·동사.
_FILLER_WORDS = [
    "뉴스",
    "속보",
    "헤드라인",
    "알려줘",
    "검색해줘",
    "찾아줘",
    "있어",
    "오늘",
    "최신",
]


class NewsSkill(Skill):
    """NewsAPI.org로 최신 뉴스 헤드라인을 검색해 한국어로 알려준다."""

    name = "news"
    description = "최신 뉴스 헤드라인을 검색해 알려준다"
    triggers = ["뉴스", "속보", "헤드라인"]
    examples = ["오늘 뉴스 알려줘", "최신 IT 뉴스 검색해줘", "속보 있어?"]

    def can_handle(self, intent: str, text: str) -> float:
        # web_search의 일반 검색(0.8)보다 의도적으로 높게 잡아, 뉴스 발화는 항상 이긴다.
        if any(k in text for k in self.triggers):
            return 0.88
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        key = os.getenv("NEWSAPI_KEY")
        if not key:
            return SkillResult(
                speech="뉴스 기능을 사용하려면 .env 파일에 NEWSAPI_KEY를 설정해주세요.",
                success=False,
            )

        topic = self._extract_topic(text)

        if topic:
            url = _EVERYTHING_URL
            params = {
                "q": topic,
                "language": "ko",
                "sortBy": "publishedAt",
                "apiKey": key,
            }
        else:
            url = _TOP_HEADLINES_URL
            params = {"country": "kr", "apiKey": key}

        try:
            resp = requests.get(url, params=params, timeout=_TIMEOUT)
            payload = resp.json()
        except (requests.RequestException, ValueError):
            return SkillResult(speech="뉴스를 가져오지 못했습니다.", success=False)

        if payload.get("status") != "ok":
            return SkillResult(speech="뉴스를 가져오지 못했습니다.", success=False)

        articles = payload.get("articles") or []
        titles = [a["title"] for a in articles[:_MAX_ARTICLES] if a.get("title")]
        if not titles:
            return SkillResult(speech="뉴스를 가져오지 못했습니다.", success=False)

        lines = [f"{i}. {t}" for i, t in enumerate(titles, start=1)]
        prefix = f"'{topic}' 관련 최신 뉴스입니다.\n" if topic else "오늘의 주요 뉴스입니다.\n"
        speech = prefix + "\n".join(lines)

        return SkillResult(
            speech=speech,
            success=True,
            data={"count": len(titles), "topic": topic or None},
        )

    def _extract_topic(self, text: str) -> str:
        """사용자 발화에서 트리거·조사·동사를 떼고 남는 주제어를 반환한다."""
        query = text
        for word in _FILLER_WORDS:
            query = query.replace(word, "")
        query = _PUNCTUATION.sub("", query)
        return " ".join(query.split())
