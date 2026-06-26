"""skill_news 검증.

실행: python -m tests.test_skill_news  (프로젝트 루트에서)

- can_handle: 뉴스 발화는 임계값 이상, 무관 문장은 0.0
- .env에 NEWSAPI_KEY가 있으면 실제 호출, 없으면 "키 없을 때 안전 동작"을 검증
- skill_web_search의 _STRONG_KEYWORDS에서 "뉴스"가 빠졌는지 확인
"""
import os

from dotenv import load_dotenv

from skills.skill_news import NewsSkill

load_dotenv()


def main() -> None:
    skill = NewsSkill()

    # can_handle
    assert skill.can_handle("", "오늘 뉴스 알려줘") >= 0.4, "뉴스 발화 점수가 임계값 미만"
    assert skill.can_handle("", "계산기 켜줘") == 0.0, "무관 문장이 0.0이 아님"
    print("[can_handle] 통과")

    # 키 존재 여부 분기
    key = os.getenv("NEWSAPI_KEY")
    print(f"[.env] NEWSAPI_KEY 존재: {bool(key)}")

    if key:
        result = skill.execute("오늘 뉴스 알려줘", {})
        print(f"[execute] success={result.success}")
        print(f"[execute] speech=\n{result.speech}")
        if result.success:
            assert result.data["count"] > 0, "성공인데 count가 0"
            print("[execute] 실제 호출 성공, count =", result.data["count"])
        else:
            print("[execute] 키는 있으나 호출 실패(네트워크/쿼터 가능) — 안내 문구 확인")
    else:
        # 키 없을 때 안전 동작 검증 (핵심)
        saved = os.environ.pop("NEWSAPI_KEY", None)
        try:
            result = skill.execute("오늘 뉴스 알려줘", {})
        finally:
            if saved is not None:
                os.environ["NEWSAPI_KEY"] = saved
        assert result.success is False, "키 없을 때 success가 False가 아님"
        assert ".env" in result.speech and "NEWSAPI_KEY" in result.speech, \
            "안내 문구에 .env/NEWSAPI_KEY가 없음"
        print(f"[execute] 키 없음 → 예외 없이 success=False, 안내: {result.speech}")

    # skill_web_search에서 "뉴스" 제거 확인
    import skills.skill_web_search as ws
    assert "뉴스" not in ws._STRONG_KEYWORDS, "_STRONG_KEYWORDS에 아직 '뉴스'가 있음"
    print("[web_search] _STRONG_KEYWORDS에서 '뉴스' 제거 확인:", ws._STRONG_KEYWORDS)

    print("\ntest_skill_news 통과")


if __name__ == "__main__":
    main()
