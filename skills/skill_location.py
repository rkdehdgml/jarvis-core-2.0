import logging

import requests

from core.skill_base import Skill, SkillResult

_logger = logging.getLogger(__name__)

_API_URL = "http://ip-api.com/json/"
_TIMEOUT = 5

_TRIGGERS = ["내 위치", "현재 위치", "여기 어디", "위치 알려줘", "지금 어디"]


class LocationSkill(Skill):
    """IP 기반으로 현재 위치(도시/지역/국가)를 추정해 알려준다.

    IP 주소 자체는 응답에 노출하지 않고 도시/지역/국가만 자연스럽게 말해준다.
    (IP 주소·ISP를 노출하는 질문은 별도의 skill_ip_info가 담당한다.)
    """

    name = "location"
    description = "IP 기반으로 현재 위치(도시/지역/국가)를 추정해 알려준다"
    triggers = _TRIGGERS
    examples = ["내 위치가 어디야", "지금 여기 어디야", "현재 위치 알려줘"]

    def can_handle(self, intent: str, text: str) -> float:
        if any(t in text for t in _TRIGGERS):
            return 0.85
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        try:
            resp = requests.get(_API_URL, timeout=_TIMEOUT)
            info = resp.json()
        except Exception as exc:  # noqa: BLE001 - 어떤 실패도 밖으로 던지지 않는다
            _logger.warning("위치 조회 실패: %s", exc)
            return SkillResult(speech="현재 위치를 확인하지 못했습니다.", success=False)

        if info.get("status") != "success":
            return SkillResult(speech="현재 위치를 확인하지 못했습니다.", success=False)

        country = info.get("country", "")
        region = info.get("regionName", "")
        city = info.get("city", "")

        place = " ".join(p for p in (country, region, city) if p)
        speech = (
            f"현재 위치는 {place} 근처로 추정됩니다. "
            "(IP 기반 추정이라 정확하지 않을 수 있어요)"
        )

        return SkillResult(
            speech=speech,
            success=True,
            data={"country": country, "region": region, "city": city},
        )
