import re
import urllib.parse

from core.skill_base import Skill, SkillResult
from commands.windows_bridge import run_command

# 사이트 이름 → URL 바로가기.
_SITE_SHORTCUTS = {
    "지메일": "https://mail.google.com",
    "구글맵": "https://maps.google.com",
    "구글 지도": "https://maps.google.com",
    "구글드라이브": "https://drive.google.com",
    "인스타그램": "https://www.instagram.com",
    "페이스북": "https://www.facebook.com",
    "트위터": "https://twitter.com",
    "쿠팡": "https://www.coupang.com",
    "네이버쇼핑": "https://shopping.naver.com",
    "네이버": "https://www.naver.com",
}

_URL_PATTERN = re.compile(r"https?://\S+|www\.\S+")

# 검색어에서 떼어낼 필러 — "구글에서 라면 맛집 검색해줘" → "라면 맛집".
_QUERY_FILLERS = [
    "구글에서",
    "구글",
    "네이버에서",
    "네이버",
    "검색해줘",
    "검색해",
    "검색",
    "찾아줘",
    "찾아봐줘",
    "찾아",
    "에서",
    "해줘",
    "줘",
]

_PUNCTUATION = re.compile(r"[?!.,~]")


class BrowserSkill(Skill):
    """URL이나 자주 쓰는 사이트를 브라우저로 열고, 구글 검색도 처리한다."""

    name = "browser"
    description = "URL이나 자주 쓰는 사이트(지메일/구글맵/SNS/쇼핑 등)를 브라우저로 연다"
    triggers = ["브라우저", "지메일", "쿠팡", "구글"]
    examples = ["지메일 열어줘", "쿠팡 열어줘", "구글에서 라면 맛집 검색해줘"]

    command_ids = ("BROWSER_OPEN_URL",)

    def can_handle(self, intent: str, text: str) -> float:
        # URL이 직접 들어 있으면 확실히 이 스킬이다.
        if _URL_PATTERN.search(text):
            return 0.85
        # 알려진 사이트 바로가기 이름이 있으면 발동.
        if any(site in text for site in _SITE_SHORTCUTS):
            return 0.85
        # "구글"/"네이버" + "검색"이 둘 다 있으면 검색 의도.
        if ("구글" in text or "네이버" in text) and "검색" in text:
            return 0.85
        if "브라우저" in text:
            return 0.85
        # 일반 단어("검색해줘"/"열어줘"/"찾아줘")만으로는 점수를 주지 않는다 —
        # web_search/app_launch와 충돌하기 때문.
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        target, label = self._resolve_target(text)

        if target is None:
            return SkillResult(
                speech="어떤 사이트를 열지 알 수 없습니다.",
                success=False,
            )

        result = run_command("BROWSER_OPEN_URL", url=target)

        speech = (
            f"{label}을 열었습니다." if result.ok else "브라우저 열기에 실패했습니다."
        )
        return SkillResult(
            speech=speech,
            success=result.ok,
            data={"url": target},
        )

    def _resolve_target(self, text: str) -> tuple[str | None, str]:
        """(열 URL, 사용자에게 읽어줄 이름) 튜플을 반환한다."""
        url_match = _URL_PATTERN.search(text)
        if url_match:
            url = url_match.group(0)
            if not url.startswith("http"):
                url = "https://" + url
            return url, url

        # 검색 의도가 있으면 "네이버"/"구글"이 _SITE_SHORTCUTS에도 걸려 있어도
        # 홈페이지 바로가기보다 검색을 먼저 처리한다.
        if "검색" in text:
            if "네이버" in text:
                query = self._extract_query(text)
                encoded = urllib.parse.quote(query)
                return f"https://search.naver.com/search.naver?query={encoded}", f"네이버에서 {query}"
            if "구글" in text:
                query = self._extract_query(text)
                encoded = urllib.parse.quote(query)
                return f"https://www.google.com/search?q={encoded}", f"구글에서 {query}"

        for site, url in _SITE_SHORTCUTS.items():
            if site in text:
                return url, site

        return None, ""

    def _extract_query(self, text: str) -> str:
        query = text
        for filler in _QUERY_FILLERS:
            query = query.replace(filler, "")
        query = _PUNCTUATION.sub("", query)
        query = " ".join(query.split())
        return query
