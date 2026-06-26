import re
import urllib.parse
from pathlib import Path

from core.skill_base import Skill, SkillResult
from commands.windows_bridge import run_command

# 검색어에서 떼어낼 필러.
_QUERY_FILLERS = [
    "유튜브에서",
    "유튜브",
    "에서",
    "틀어줘",
    "재생해줘",
    "재생",
    "보여줘",
    "열어줘",
    "다운로드해줘",
    "다운로드",
    "다운받아줘",
    "다운받아",
    "받아줘",
    "줘",
]

_DOWNLOAD_WORDS = ["다운로드", "다운받아", "받아줘"]

_PUNCTUATION = re.compile(r"[?!.,~]")

_DOWNLOAD_DIR = Path(__file__).parent.parent / "data" / "youtube_downloads"


class YoutubeSkill(Skill):
    """유튜브에서 영상을 검색해 브라우저로 열거나(재생), 다운로드한다."""

    name = "youtube"
    description = "유튜브에서 영상을 검색해 브라우저로 열거나(재생), 다운로드한다"
    triggers = ["유튜브"]
    examples = [
        "유튜브에서 고양이 영상 보여줘",
        "유튜브 노래 틀어줘",
        "이 영상 유튜브에서 다운로드해줘",
    ]

    command_ids = ("BROWSER_OPEN_URL",)

    def can_handle(self, intent: str, text: str) -> float:
        if "유튜브" in text:
            return 0.85
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        query = self._extract_query(text)

        if any(w in text for w in _DOWNLOAD_WORDS):
            return self._download(query)
        return self._play(query)

    def _play(self, query: str) -> SkillResult:
        encoded = urllib.parse.quote(query)
        url = f"https://www.youtube.com/results?search_query={encoded}"
        result = run_command("BROWSER_OPEN_URL", url=url)
        speech = (
            f"유튜브에서 {query}를 검색해서 열었습니다."
            if result.ok
            else "유튜브 열기에 실패했습니다."
        )
        return SkillResult(speech=speech, success=result.ok, data={"url": url})

    def _download(self, query: str) -> SkillResult:
        try:
            import yt_dlp

            _DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
            ydl_opts = {
                "outtmpl": str(_DOWNLOAD_DIR / "%(title)s.%(ext)s"),
                "format": "best",
                "quiet": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([f"ytsearch1:{query}"])
        except Exception:
            return SkillResult(speech="다운로드에 실패했습니다.", success=False)

        return SkillResult(
            speech=f"{query} 영상을 다운로드했습니다.",
            success=True,
            data={"dir": str(_DOWNLOAD_DIR)},
        )

    def _extract_query(self, text: str) -> str:
        query = text
        for filler in _QUERY_FILLERS:
            query = query.replace(filler, "")
        query = _PUNCTUATION.sub("", query)
        query = " ".join(query.split())
        return query
