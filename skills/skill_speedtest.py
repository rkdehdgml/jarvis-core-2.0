"""skills/skill_speedtest.py — 인터넷 다운로드 속도 측정.

speedtest-cli(PyPI `speedtest`)는 마지막 릴리즈가 2021-04-08로 사실상 유지보수가
끊긴 abandonware라 의존하지 않는다. 대신 별도 키 없이 안정적으로 동작하는
Cloudflare 공개 스피드테스트 엔드포인트에서 일정 크기를 다운로드하며 걸린 시간으로
Mbps를 계산한다. 측정만 하는 읽기 전용 동작이고, 어떤 실패도 예외로 던지지 않고
실패 SkillResult로 변환한다.
"""
import time

from core.skill_base import Skill, SkillResult

_DOWNLOAD_BYTES = 10_000_000  # 10MB
_DOWNLOAD_URL = f"https://speed.cloudflare.com/__down?bytes={_DOWNLOAD_BYTES}"
_TIMEOUT = 30


class SpeedtestSkill(Skill):
    """인터넷 다운로드 속도를 측정한다."""

    name = "speedtest"
    description = "인터넷 다운로드/업로드 속도를 측정한다"
    triggers = ["인터넷 속도", "속도 측정", "속도 테스트", "와이파이 속도"]
    examples = ["인터넷 속도 측정해줘", "와이파이 속도 얼마나 빨라", "속도 테스트 해줘"]

    def can_handle(self, intent: str, text: str) -> float:
        for trigger in self.triggers:
            if trigger in text:
                return 0.85
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        try:
            import requests

            start = time.perf_counter()
            downloaded = 0
            with requests.get(_DOWNLOAD_URL, stream=True, timeout=_TIMEOUT) as resp:
                resp.raise_for_status()
                for chunk in resp.iter_content(chunk_size=65536):
                    downloaded += len(chunk)
            elapsed = time.perf_counter() - start

            if elapsed <= 0 or downloaded <= 0:
                return SkillResult(speech="인터넷 속도 측정에 실패했습니다.", success=False)

            mbps = (downloaded * 8) / elapsed / 1_000_000
            return SkillResult(
                speech=f"다운로드 속도는 약 {mbps:.1f}Mbps입니다.",
                success=True,
                data={"download_mbps": round(mbps, 1)},
            )
        except Exception:
            return SkillResult(speech="인터넷 속도 측정에 실패했습니다.", success=False)
