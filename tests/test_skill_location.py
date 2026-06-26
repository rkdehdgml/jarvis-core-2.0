"""skill_location 검증: can_handle 점수 + 실제 네트워크 호출로 IP 미노출 확인.

실행: python -m tests.test_skill_location  (프로젝트 루트에서)
"""
import re

from skills.skill_location import LocationSkill

_IPV4 = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")


def main() -> None:
    skill = LocationSkill()

    # can_handle: 트리거 포함 → 0.85, 다른 스킬 영역/무관 → 0.0
    assert skill.can_handle("", "내 위치가 어디야") >= 0.4
    assert skill.can_handle("", "IP 주소 알려줘") == 0.0
    assert skill.can_handle("", "오늘 점심 뭐 먹지") == 0.0
    print("[can_handle] OK")

    # execute: 실제 네트워크 호출
    result = skill.execute("내 위치 알려줘", {})
    print("[execute]", result.speech, "| success=", result.success)

    assert result.success, "위치 조회 성공해야 함 (네트워크 필요)"
    assert not _IPV4.search(result.speech), "speech에 IP 주소가 노출되면 안 됨"
    assert "city" in result.data or "country" in result.data, "data에 위치 키 필요"

    print("\nskill_location 검증 통과")


if __name__ == "__main__":
    main()
