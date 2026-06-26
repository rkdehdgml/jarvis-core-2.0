"""skill_ip_info 검증: 실제 ip-api.com 네트워크 호출 1회 포함.

실행: python -m tests.test_skill_ip_info  (프로젝트 루트에서, 인터넷 연결 필요)
"""
import re

from skills.skill_ip_info import IpInfoSkill

_IPV4_PATTERN = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")


def main() -> None:
    skill = IpInfoSkill()

    assert skill.can_handle("", "내 IP 주소 뭐야") >= 0.4, "트리거 매칭 실패"
    assert skill.can_handle("", "점심 뭐 먹지") == 0.0, "무관 문장은 0.0이어야 함"
    print("[can_handle] 통과")

    result = skill.execute("내 IP 주소 알려줘", {})
    assert result.success, f"내 IP 조회 실패: {result.speech}"
    assert _IPV4_PATTERN.match(result.data["ip"]), f"IPv4 형식 아님: {result.data['ip']}"
    print("[내 IP]", result.speech)

    result = skill.execute("8.8.8.8 IP 정보 알려줘", {})
    assert result.success, f"8.8.8.8 조회 실패: {result.speech}"
    assert result.data["ip"] == "8.8.8.8", f"대상 IP 불일치: {result.data['ip']}"
    assert "미국" in result.speech or "United States" in result.speech, (
        f"위치 정보 누락: {result.speech}"
    )
    print("[8.8.8.8]", result.speech)

    print("\nskill_ip_info 검증 통과")


if __name__ == "__main__":
    main()
