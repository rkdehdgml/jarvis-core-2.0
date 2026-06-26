"""tests/test_skill_screenshot.py — skill_screenshot 검증 (plain assert).

실제로 화면을 캡처한다 — 부작용 없는 안전한 동작이라 mock 없이 직접 실행한다.
`python -m tests.test_skill_screenshot`로 실행.
"""
from pathlib import Path

from skills.skill_screenshot import ScreenshotSkill


def test_can_handle():
    skill = ScreenshotSkill()
    assert skill.can_handle("", "스크린샷 찍어줘") >= 0.4
    assert skill.can_handle("", "화면 캡처해줘") >= 0.4
    assert skill.can_handle("", "오늘 날씨 어때") == 0.0
    print("[OK] can_handle 점수 검증 통과")


def test_execute_captures_real_file():
    skill = ScreenshotSkill()
    result = skill.execute("스크린샷 찍어줘", {})

    if not result.success:
        raise AssertionError(
            f"스크린샷 실행 실패 — speech={result.speech!r}, "
            f"stderr={result.data.get('stderr')!r}"
        )

    path = Path(result.data["path"])
    assert path.exists(), f"저장된 파일이 존재하지 않습니다: {path}"
    size = path.stat().st_size
    assert size > 0, f"저장된 파일 크기가 0입니다: {path}"
    print(f"[OK] 실제 캡처 통과 - 경로={path}, 크기={size} bytes")


def main():
    test_can_handle()
    test_execute_captures_real_file()
    print("모든 테스트 통과 (test_skill_screenshot)")


if __name__ == "__main__":
    main()
