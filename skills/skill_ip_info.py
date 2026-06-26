import re

import requests

from core.skill_base import Skill, SkillResult

_IPV4_PATTERN = re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}")
_TRIGGERS = ["IP", "아이피", "아이피 주소", "내 IP"]


class IpInfoSkill(Skill):
    """ip-api.com으로 내 공개 IP 또는 특정 IP의 위치·ISP 정보를 조회한다."""

    name = "ip_info"
    description = "내 공개 IP 주소 또는 특정 IP의 위치·ISP 정보를 조회한다"
    triggers = _TRIGGERS
    examples = [
        "내 IP 주소가 뭐야",
        "아이피 정보 알려줘",
        "8.8.8.8 아이피 어디꺼야",
    ]

    def can_handle(self, intent: str, text: str) -> float:
        upper = text.upper()
        if any(t.upper() in upper for t in _TRIGGERS):
            return 0.85
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        match = _IPV4_PATTERN.search(text)
        target = match.group(0) if match else ""

        try:
            resp = requests.get(f"http://ip-api.com/json/{target}", timeout=5)
            info = resp.json()
        except (requests.RequestException, ValueError):
            return SkillResult(speech="IP 정보를 조회하지 못했습니다.", success=False)

        if info.get("status") != "success":
            return SkillResult(speech="IP 정보를 조회하지 못했습니다.", success=False)

        ip = info.get("query", "")
        country = info.get("country", "")
        region = info.get("regionName", "")
        city = info.get("city", "")
        isp = info.get("isp", "")

        location = " ".join(p for p in (country, region, city) if p)
        speech = f"조회한 IP는 {ip}이며, 위치는 {location}, ISP는 {isp}입니다."

        return SkillResult(
            speech=speech,
            success=True,
            data={"ip": ip, "country": country, "city": city, "isp": isp},
        )
