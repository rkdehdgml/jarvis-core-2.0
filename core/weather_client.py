"""Open-Meteo로 위치 기반 현재 날씨를 가져온다 (무료, API 키 불필요).

geocoding-api.open-meteo.com 에 짧은 한국어 지명("대전", "서울")을 그대로 넣으면
실제로 찾는 광역시 대신 동명의 시골 마을이나 심지어 북한 지역까지 잡히고,
"서울"은 결과가 0건이다(실측 확인됨). 그래서 잘 알려진 도시는 로마자 이름으로
먼저 검색하고(이마저도 "Jeju" 단독 검색은 에티오피아가 1위로 잡힘), 검색
결과를 국가코드 KR로 필터링한 뒤 인구가 가장 많은 후보를 고르는 방식으로
신뢰도를 높였다.
"""
import logging

import requests

logger = logging.getLogger(__name__)

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_TIMEOUT = 10
_GEOCODE_CANDIDATES = 10

_DEFAULT_LOCATION = "서울"

# 한국어 지명 그대로 검색하면 결과가 0건이거나(예: "서울", "평창", "담양") 동명의
# 작은 마을/타국 지역이 먼저 잡히는 경우가 많아(실측 확인됨), 로마자 이름으로
# 검색한다. 여기 없는 지명은 _geocode()가 빈 결과를 받아 None을 반환한다 —
# 시/군 단위로 다시 말해달라고 안내하는 쪽이 잘못된 위치로 추측하는 것보다 낫다.
_ROMANIZED_CITIES = {
    "서울": "Seoul",
    "부산": "Busan",
    "대구": "Daegu",
    "인천": "Incheon",
    "광주": "Gwangju",
    "대전": "Daejeon",
    "울산": "Ulsan",
    "세종": "Sejong",
    "수원": "Suwon",
    "고양": "Goyang",
    "용인": "Yongin",
    "성남": "Seongnam",
    "청주": "Cheongju",
    "전주": "Jeonju",
    "천안": "Cheonan",
    "안산": "Ansan",
    "안양": "Anyang",
    "포항": "Pohang",
    "창원": "Changwon",
    "진주": "Jinju",
    "구미": "Gumi",
    "경주": "Gyeongju",
    "춘천": "Chuncheon",
    "원주": "Wonju",
    "강릉": "Gangneung",
    "제주": "Jeju",
    "여수": "Yeosu",
    "순천": "Suncheon",
    "목포": "Mokpo",
    "군산": "Gunsan",
    "평창": "Pyeongchang",
    "거제": "Geoje",
    "통영": "Tongyeong",
    "양산": "Yangsan",
    "공주": "Gongju",
    "충주": "Chungju",
    "제천": "Jecheon",
    "동해": "Donghae",
    "속초": "Sokcho",
    "나주": "Naju",
    "광양": "Gwangyang",
    "정읍": "Jeongeup",
    "남원": "Namwon",
    "안동": "Andong",
    "경산": "Gyeongsan",
    "밀양": "Miryang",
    "익산": "Iksan",
    "보령": "Boryeong",
    "서산": "Seosan",
    "당진": "Dangjin",
    "논산": "Nonsan",
}

# WMO 날씨 코드 → 한국어 (Open-Meteo 공식 코드표 기준).
_WEATHER_CODE_KO = {
    0: "맑음",
    1: "대체로 맑음",
    2: "구름 약간",
    3: "흐림",
    45: "안개",
    48: "착빙성 안개",
    51: "약한 이슬비",
    53: "보통 이슬비",
    55: "강한 이슬비",
    56: "약한 착빙성 이슬비",
    57: "강한 착빙성 이슬비",
    61: "약한 비",
    63: "보통 비",
    65: "강한 비",
    66: "약한 착빙성 비",
    67: "강한 착빙성 비",
    71: "약한 눈",
    73: "보통 눈",
    75: "강한 눈",
    77: "싸락눈",
    80: "약한 소나기",
    81: "보통 소나기",
    82: "강한 소나기",
    85: "약한 소낙눈",
    86: "강한 소낙눈",
    95: "뇌우",
    96: "약한 우박을 동반한 뇌우",
    99: "강한 우박을 동반한 뇌우",
}


class WeatherClient:
    """get_current(location)으로 현재 날씨를 가져온다. 실패 시 None(예외 없음)."""

    DEFAULT_LOCATION = _DEFAULT_LOCATION
    # 길이 내림차순 — skill_weather.py가 문장에서 지명을 부분 문자열로 찾을 때
    # "안산"이 "안산시"보다 먼저 매칭되는 식의 사고를 피하려고 길게 정렬해둔다.
    KNOWN_CITIES = tuple(sorted(_ROMANIZED_CITIES, key=len, reverse=True))

    def get_current(self, location: str) -> dict | None:
        location = location.strip() or _DEFAULT_LOCATION
        coords = self._geocode(location)
        if coords is None:
            logger.warning(f"위치를 찾지 못했습니다: {location}")
            return None

        lat, lon = coords
        try:
            response = requests.get(
                _FORECAST_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": (
                        "temperature_2m,relative_humidity_2m,apparent_temperature,"
                        "precipitation,weather_code,wind_speed_10m"
                    ),
                    "timezone": "Asia/Seoul",
                },
                timeout=_TIMEOUT,
            )
            response.raise_for_status()
            current = response.json().get("current", {})
        except Exception as e:
            logger.error(f"날씨 조회 실패 ({location}): {e}")
            return None

        if not current:
            return None

        code = current.get("weather_code")
        return {
            "location": location,
            "temperature": current.get("temperature_2m"),
            "feels_like": current.get("apparent_temperature"),
            "humidity": current.get("relative_humidity_2m"),
            "precipitation": current.get("precipitation"),
            "wind_speed": current.get("wind_speed_10m"),
            "condition": _WEATHER_CODE_KO.get(code, f"알 수 없음(코드 {code})"),
        }

    def format_current(self, weather: dict) -> str:
        """get_current()의 반환값을 Groq 프롬프트에 넣을 텍스트로 변환한다."""
        return (
            f"{weather['location']} 현재 날씨\n"
            f"- 날씨: {weather['condition']}\n"
            f"- 기온: {weather['temperature']}°C (체감 {weather['feels_like']}°C)\n"
            f"- 습도: {weather['humidity']}%\n"
            f"- 강수량: {weather['precipitation']}mm\n"
            f"- 풍속: {weather['wind_speed']}km/h"
        )

    def _geocode(self, location: str) -> tuple[float, float] | None:
        search_name = _ROMANIZED_CITIES.get(location, location)
        try:
            response = requests.get(
                _GEOCODE_URL,
                params={"name": search_name, "count": _GEOCODE_CANDIDATES, "format": "json"},
                timeout=_TIMEOUT,
            )
            response.raise_for_status()
            results = response.json().get("results", [])
        except Exception as e:
            logger.error(f"지오코딩 실패 ({search_name}): {e}")
            return None

        kr_results = [r for r in results if r.get("country_code") == "KR"]
        if not kr_results:
            return None

        best = max(kr_results, key=lambda r: r.get("population") or 0)
        return best["latitude"], best["longitude"]
