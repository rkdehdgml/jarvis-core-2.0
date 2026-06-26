"""skill_wikipedia 검증 (실제 네트워크 호출 포함).

실행: python -m tests.test_skill_wikipedia  (프로젝트 루트에서)
"""
from skills.skill_wikipedia import WikipediaSkill


def main() -> None:
    skill = WikipediaSkill()

    # can_handle
    assert skill.can_handle("", "위키백과에서 아인슈타인 찾아줘") >= 0.4
    assert skill.can_handle("", "아인슈타인이 누구야") == 0.0
    assert skill.can_handle("", "오늘 점심 뭐 먹지") == 0.0
    print("[can_handle] 통과")

    # 정상 검색
    result = skill.execute("위키백과에서 아인슈타인 찾아줘", {})
    print("[execute 아인슈타인]", result.success, "|", result.speech[:60])
    assert result.success, "아인슈타인 검색이 실패함"
    assert "아인슈타인" in result.speech
    assert result.data["title"], "title이 비어있음"

    # 존재하지 않을 검색어 — 예외 없이 SkillResult 반환되는지 확인
    result2 = skill.execute("위키백과에서 asdkfjqwoeiruqwoirjqwoeasd123 찾아줘", {})
    print("[execute 없는검색어]", result2.success, "|", result2.speech[:60])
    assert isinstance(result2.speech, str) and result2.speech

    # 검색어 비었을 때
    result3 = skill.execute("위키백과 검색해줘", {})
    print("[execute 빈검색어]", result3.success, "|", result3.speech)
    assert not result3.success

    print("\nskill_wikipedia 검증 통과")


if __name__ == "__main__":
    main()
