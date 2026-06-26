"""skill_browser 검증 — can_handle 충돌 회피가 핵심.

실행: python -m tests.test_skill_browser
"""
from unittest.mock import patch

from skills.skill_browser import BrowserSkill
from commands.windows_bridge import CommandResult


def main() -> None:
    skill = BrowserSkill()

    # --- can_handle 충돌 회피 ---
    assert skill.can_handle("", "지메일 열어줘") >= 0.4
    assert skill.can_handle("", "구글에서 라면 맛집 검색해줘") >= 0.4
    assert skill.can_handle("", "쿠팡 열어줘") >= 0.4
    assert skill.can_handle("", "https://example.com 열어줘") >= 0.4
    # app_launch 영역 — 절대 가로채면 안 된다.
    assert skill.can_handle("", "크롬 열어줘") == 0.0
    # web_search 영역 — 절대 가로채면 안 된다.
    assert skill.can_handle("", "오늘 날씨 검색해줘") == 0.0
    # 무관 문장.
    assert skill.can_handle("", "오늘 점심 뭐 먹을까") == 0.0

    ok = CommandResult(ok=True, stdout="", stderr="", exit_code=0)

    # --- 사이트 바로가기 execute ---
    with patch("skills.skill_browser.run_command", return_value=ok) as mock:
        result = skill.execute("지메일 열어줘", {})
        mock.assert_called_once_with(
            "BROWSER_OPEN_URL", url="https://mail.google.com"
        )
        assert result.success is True

    # --- 구글 검색 execute ---
    with patch("skills.skill_browser.run_command", return_value=ok) as mock:
        result = skill.execute("구글에서 라면 맛집 검색해줘", {})
        assert mock.call_count == 1
        called_url = mock.call_args.kwargs["url"]
        assert called_url.startswith("https://www.google.com/search?q=")
        assert result.success is True

    # --- 네이버 검색 execute (홈페이지 바로가기보다 검색이 우선해야 함) ---
    with patch("skills.skill_browser.run_command", return_value=ok) as mock:
        result = skill.execute("네이버에서 라면 맛집 검색해줘", {})
        assert mock.call_count == 1
        called_url = mock.call_args.kwargs["url"]
        assert called_url.startswith("https://search.naver.com/search.naver?query=")
        assert result.success is True

    # --- 네이버 홈페이지 바로가기 (검색 의도 없을 때) ---
    with patch("skills.skill_browser.run_command", return_value=ok) as mock:
        result = skill.execute("네이버 열어줘", {})
        mock.assert_called_once_with("BROWSER_OPEN_URL", url="https://www.naver.com")
        assert result.success is True

    print("test_skill_browser 통과")


if __name__ == "__main__":
    main()
