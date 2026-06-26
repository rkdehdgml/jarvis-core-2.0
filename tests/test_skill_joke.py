"""skill_joke 검증: can_handle 스코어링 + execute 실제 호출(한국어 농담).

실행: python -m tests.test_skill_joke  (프로젝트 루트에서)
"""
import os
import re

from skills.skill_joke import JokeSkill

_HANGUL = re.compile(r"[가-힣]")


def main() -> None:
    skill = JokeSkill()

    # can_handle: 트리거 단어가 있으면 0.4 이상, 무관한 문장은 0.0
    score_hit = skill.can_handle("", "농담 하나 해줘")
    score_miss = skill.can_handle("", "오늘 날씨 어때")
    print(f"can_handle('농담 하나 해줘') = {score_hit}")
    print(f"can_handle('오늘 날씨 어때') = {score_miss}")
    assert score_hit >= 0.4, "트리거 단어 포함 문장은 0.4 이상이어야 함"
    assert score_miss == 0.0, "무관한 문장은 0.0이어야 함"

    # execute: 실제 호출
    has_key = bool(os.getenv("GROQ_API_KEY"))
    print(f"GROQ_API_KEY 존재 여부: {has_key}")

    result = skill.execute("농담 하나 해줘", {})
    print(f"[원문] {result.data.get('original')}")
    print(f"[한국어 농담] {result.speech}")
    assert result.success, "execute는 success=True여야 함"
    assert result.speech, "speech는 빈 문자열이 아니어야 함"

    if has_key:
        assert _HANGUL.search(result.speech), "키가 있으면 응답에 한국어 문자가 포함되어야 함"

    print("\nskill_joke 검증 통과")


if __name__ == "__main__":
    main()
