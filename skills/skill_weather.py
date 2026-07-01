import re

from core.engines.claude_cli_engine import ClaudeCliEngine
from core.skill_base import Skill, SkillResult
from core.weather_client import WeatherClient

_PUNCTUATION = re.compile(r"[?!.,~]")

_STRONG_KEYWORDS = [
    "날씨",
    "기온",
    "미세먼지",
    "체감온도",
    "강수확률",
    "우산",
    "비올까",
    "비 올까",
    "눈올까",
    "눈 올까",
]

_ADDRESS_PATTERNS = ["자비스야", "자비스"]
_FILLER_WORDS = [
    *_STRONG_KEYWORDS,
    "어때",
    "알려줘",
    "말해줘",
    "얼마야",
    "얼마",
    "몇 도",
    "몇도",
    "오늘",
    "지금",
    "현재",
]

_SYSTEM_PROMPT = (
    "너는 자비스야. 아래 날씨 데이터를 바탕으로 사용자에게 자연스럽고 간결하게 "
    "대답해줘. 주어진 수치만 사용하고 새로운 정보를 지어내지 마."
)


class WeatherSkill(Skill):
    """Open-Meteo로 현재 날씨(기온/습도/강수/풍속)를 조회해 Claude CLI로 자연스럽게 답한다."""

    name = "weather"
    description = "현재 날씨(기온, 습도, 강수 등)를 조회해서 알려준다"
    triggers = _STRONG_KEYWORDS
    examples = ["오늘 대전 날씨 어때", "서울 기온 알려줘", "부산 날씨"]

    def __init__(self) -> None:
        self._weather = WeatherClient()
        self._engine = ClaudeCliEngine()

    def can_handle(self, intent: str, text: str) -> float:
        if any(k in text for k in _STRONG_KEYWORDS):
            return 0.85
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        location = self._extract_location(text) or self._weather.DEFAULT_LOCATION
        weather = self._weather.get_current(location)

        if weather is None:
            return SkillResult(
                speech=f"'{location}' 지역의 날씨를 찾지 못했습니다. 다른 지역명으로 다시 말씀해주시겠어요?",
                success=False,
                data={"location": location},
            )

        formatted = self._weather.format_current(weather)
        prompt = f"사용자 질문: {text}\n\n날씨 데이터:\n{formatted}"
        speech = self._engine.generate(prompt, system=_SYSTEM_PROMPT)

        return SkillResult(
            speech=speech,
            success=True,
            data={"location": weather["location"], "temperature": weather["temperature"]},
            follow_up=False,
        )

    def _extract_location(self, text: str) -> str:
        """사용자 발화에서 지역명을 뽑아낸다(없으면 빈 문자열).

        "내가 지금 여수를 갈건데 우산이 필요할까?"처럼 자유롭게 말하는 문장은
        필러 단어를 다 나열해서 걷어내기보다, 알고 있는 도시명이 문장에 그대로
        들어있는지부터 찾는 쪽이 훨씬 안정적이다(알려진 도시면 바로 반환).
        모르는 지명일 때만 기존의 필러 단어 제거 방식으로 추정한다.
        """
        for city in WeatherClient.KNOWN_CITIES:
            if city in text:
                return city

        query = text
        for pattern in _ADDRESS_PATTERNS:
            query = query.replace(pattern, "")
        for pattern in _FILLER_WORDS:
            query = query.replace(pattern, "")
        query = _PUNCTUATION.sub("", query)
        return " ".join(query.split())
