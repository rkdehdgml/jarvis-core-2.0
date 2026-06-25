"""실시간 웹 검색 — DuckDuckGo(기본, 무료/키 불필요) 또는 Brave Search(선택, 키 필요).

skills/skill_web_search.py가 이 모듈로 검색한 뒤 결과를 GroqEngine에 컨텍스트로
넘긴다. 비용 0원이 목적이라 기본은 DuckDuckGo이고, .env에 BRAVE_SEARCH_API_KEY가
있을 때만 Brave로 전환한다.
"""
import logging
import os

import requests
from ddgs import DDGS

logger = logging.getLogger(__name__)

_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
_BRAVE_TIMEOUT = 10
_BODY_PREVIEW_LENGTH = 200


class SearchEngine:
    """search()로 검색하고 format_results()로 Groq에 넘길 텍스트를 만든다."""

    def __init__(self) -> None:
        self.brave_api_key = os.getenv("BRAVE_SEARCH_API_KEY")
        self.use_brave = bool(self.brave_api_key)
        logger.info(f"검색 엔진: {'Brave Search' if self.use_brave else 'DuckDuckGo'}")

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        """query를 검색해 [{"title", "body", "url"}, ...]를 반환한다.

        네트워크 오류/타임아웃 등 모든 예외를 잡아 빈 리스트로 반환한다
        (예외로 죽지 않음 — 호출 측은 항상 list를 받는다고 가정해도 된다).
        """
        try:
            if self.use_brave:
                return self._search_brave(query, max_results)
            return self._search_duckduckgo(query, max_results)
        except Exception as e:
            logger.error(f"검색 실패 ({'brave' if self.use_brave else 'duckduckgo'}): {e}")
            return []

    def format_results(self, results: list[dict]) -> str:
        """검색 결과를 Groq 프롬프트에 넣을 텍스트로 변환한다."""
        if not results:
            return "검색 결과를 찾을 수 없습니다."

        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"[{i}] {r['title']}")
            lines.append(f"    {r['body'][:_BODY_PREVIEW_LENGTH]}")
            lines.append(f"    출처: {r['url']}")
        return "\n".join(lines)

    def _search_duckduckgo(self, query: str, max_results: int) -> list[dict]:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return [
            {"title": r.get("title", ""), "body": r.get("body", ""), "url": r.get("href", "")}
            for r in results
        ]

    def _search_brave(self, query: str, max_results: int) -> list[dict]:
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.brave_api_key,
        }
        params = {"q": query, "count": max_results}
        response = requests.get(
            _BRAVE_URL, headers=headers, params=params, timeout=_BRAVE_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()
        web_results = data.get("web", {}).get("results", [])
        return [
            {
                "title": r.get("title", ""),
                "body": r.get("description", ""),
                "url": r.get("url", ""),
            }
            for r in web_results
        ]
