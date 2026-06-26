"""skill_howto 검증.

실행: python -m tests.test_skill_howto  (프로젝트 루트에서)
"""
import os
import re

from skills.skill_howto import HowToSkill

_HANGUL = re.compile(r"[가-힣]")
_NUMBERED = re.compile(r"\b1[.)]")


def _load_env() -> None:
    """간단한 .env 파서 — GROQ_API_KEY를 환경변수로 로드(이미 있으면 유지)."""
    if os.getenv("GROQ_API_KEY"):
        return
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def main() -> None:
    skill = HowToSkill()

    # can_handle
    assert skill.can_handle("", "라면 끓이는 방법 알려줘") >= 0.4
    assert skill.can_handle("", "오늘 날씨 어때") == 0.0
    print("[can_handle] 통과")

    _load_env()
    assert os.getenv("GROQ_API_KEY"), "GROQ_API_KEY가 .env에 없습니다"

    result = skill.execute("라면 맛있게 끓이는 방법 알려줘", {})
    print("[execute] success =", result.success)
    print("[execute] speech =", result.speech)

    assert result.success, "execute가 success=True를 반환해야 함"
    assert result.speech.strip(), "speech가 비어있으면 안 됨"
    assert _HANGUL.search(result.speech), "speech에 한국어 문자가 포함되어야 함"

    if _NUMBERED.search(result.speech):
        print("[참고] 번호 매김 패턴 감지됨")
    else:
        print("[참고] 번호 매김 패턴 미감지 (Groq 응답 형식 편차 — 실패 아님)")

    print("\nskill_howto 검증 통과")


if __name__ == "__main__":
    main()
