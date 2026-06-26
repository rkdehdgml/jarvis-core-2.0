import re
import urllib.parse

import requests

from core.skill_base import Skill, SkillResult

_SEARCH_API = "https://ko.wikipedia.org/w/api.php"
_SUMMARY_API = "https://ko.wikipedia.org/api/rest_v1/page/summary/"
# 위키미디어 API는 User-Agent가 없으면 403을 반환한다.
_HEADERS = {"User-Agent": "jarvis-core/1.0 (personal assistant)"}

_PUNCTUATION = re.compile(r"[?!.,~]")
_TRIGGERS = ["위키백과", "위키"]
_FILLER_WORDS = [
    *_TRIGGERS,
    "에서",
    "으로",
    "로",
    "검색해줘",
    "검색해",
    "검색",
    "찾아줘",
    "찾아",
    "알려줘",
    "설명해줘",
    "설명해",
    "설명",
    "자비스야",
    "자비스",
]

_MAX_EXTRACT_LEN = 500


class WikipediaSkill(Skill):
    """위키백과(MediaWiki REST API)에서 검색해 요약 설명을 알려준다.

    'wikipedia' 파이썬 패키지(유지보수 중단)는 쓰지 않고 requests로 직접 호출한다.
    '위키'/'위키백과'를 명시적으로 말했을 때만 반응하도록 좁게 설계 — 일반 질문은
    AI 폴백(ai_chat)에 양보한다.
    """

    name = "wikipedia"
    description = "위키백과에서 검색해 요약 설명을 알려준다"
    triggers = _TRIGGERS
    examples = [
        "위키백과에서 아인슈타인 찾아줘",
        "이순신 위키 검색해줘",
        "위키백과로 양자역학 설명해줘",
    ]

    def can_handle(self, intent: str, text: str) -> float:
        if any(t in text for t in _TRIGGERS):
            return 0.85
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        query = self._extract_query(text)
        if not query:
            return SkillResult(
                speech="위키백과에서 무엇을 찾아드릴까요?",
                success=False,
            )

        try:
            title = self._search_title(query)
            if not title:
                return SkillResult(
                    speech=f"'{query}'에 대한 위키백과 문서를 찾지 못했습니다.",
                    success=False,
                )
            extract = self._fetch_summary(title)
        except (requests.RequestException, ValueError, KeyError):
            return SkillResult(
                speech="위키백과 조회 중 오류가 발생했습니다.",
                success=False,
            )

        if not extract:
            return SkillResult(
                speech=f"'{query}'에 대한 위키백과 문서를 찾지 못했습니다.",
                success=False,
            )

        if len(extract) > _MAX_EXTRACT_LEN:
            extract = extract[:_MAX_EXTRACT_LEN] + "..."

        return SkillResult(
            speech=f"위키백과에 따르면, {extract}",
            success=True,
            data={"title": title, "extract": extract},
        )

    def _extract_query(self, text: str) -> str:
        query = text
        for word in _FILLER_WORDS:
            query = query.replace(word, "")
        query = _PUNCTUATION.sub("", query)
        return " ".join(query.split())

    def _search_title(self, query: str) -> str:
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
            "srlimit": 1,
        }
        resp = requests.get(_SEARCH_API, params=params, headers=_HEADERS, timeout=5)
        resp.raise_for_status()
        results = resp.json()["query"]["search"]
        if not results:
            return ""
        return results[0]["title"]

    def _fetch_summary(self, title: str) -> str:
        url = _SUMMARY_API + urllib.parse.quote(title)
        resp = requests.get(url, headers=_HEADERS, timeout=5)
        resp.raise_for_status()
        return resp.json().get("extract", "")
