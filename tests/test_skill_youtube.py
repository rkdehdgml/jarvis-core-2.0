"""skill_youtube 검증 — 재생 경로는 패치, 다운로드 경로는 실제 호출.

실행: python -m tests.test_skill_youtube
"""
from unittest.mock import patch

from skills.skill_youtube import YoutubeSkill, _DOWNLOAD_DIR
from commands.windows_bridge import CommandResult


def main() -> None:
    skill = YoutubeSkill()

    # --- can_handle ---
    assert skill.can_handle("", "유튜브에서 고양이 영상 보여줘") >= 0.4
    assert skill.can_handle("", "오늘 점심 뭐 먹을까") == 0.0

    ok = CommandResult(ok=True, stdout="", stderr="", exit_code=0)

    # --- 재생 경로(브라우저가 실제로 열리지 않게 패치) ---
    with patch("skills.skill_youtube.run_command", return_value=ok) as mock:
        result = skill.execute("유튜브에서 테스트 영상 보여줘", {})
        mock.assert_called_once()
        assert mock.call_args.args[0] == "BROWSER_OPEN_URL"
        called_url = mock.call_args.kwargs["url"]
        assert called_url.startswith(
            "https://www.youtube.com/results?search_query="
        )
        assert result.success is True

    # --- 다운로드 경로(실제 yt-dlp 호출, 짧은 검색어 1개) ---
    result = skill.execute("유튜브에서 me at the zoo 다운로드해줘", {})
    assert _DOWNLOAD_DIR.exists(), "다운로드 디렉터리가 생성돼야 한다"
    print("[다운로드 결과]", result.speech, result.success)

    print("test_skill_youtube 통과")


if __name__ == "__main__":
    main()
