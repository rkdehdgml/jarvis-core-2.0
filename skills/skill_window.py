from math import ceil, sqrt

from core.skill_base import Skill, SkillResult


class WindowSkill(Skill):
    """현재 활성 창을 최소화/전체화면 전환하거나 모든 창을 정렬한다 (Windows, pygetwindow)."""

    name = "window"
    description = "창을 최소화/전체화면/정렬한다"
    triggers = ["최소화", "정렬", "전체 화면"]
    examples = ["창 최소화", "전체 화면", "창 정렬해줘"]

    def can_handle(self, intent: str, text: str) -> float:
        if "최소화" in text:
            return 0.9
        if "정렬" in text:
            return 0.9
        if "전체" in text and "화면" in text:
            return 0.85
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        try:
            import pygetwindow as gw
        except ImportError:
            return SkillResult(
                speech="창 제어 기능을 사용할 수 없습니다 (pygetwindow 미설치).",
                success=False,
            )

        try:
            if "최소화" in text:
                active = gw.getActiveWindow()
                if active is None:
                    return SkillResult(speech="활성화된 창이 없습니다.", success=False)
                active.minimize()
                return SkillResult(speech="창을 최소화했습니다", success=True)

            if "전체" in text and "화면" in text:
                active = gw.getActiveWindow()
                if active is None:
                    return SkillResult(speech="활성화된 창이 없습니다.", success=False)
                active.maximize()
                return SkillResult(speech="전체 화면으로 전환했습니다", success=True)

            if "정렬" in text:
                windows = [w for w in gw.getAllWindows() if w.visible and w.title]
                if not windows:
                    return SkillResult(speech="정렬할 창이 없습니다.", success=False)
                self._tile(windows)
                return SkillResult(speech="창을 정렬했습니다", success=True)

            return SkillResult(speech="어떤 창 작업인지 알 수 없습니다.", success=False)
        except Exception:
            return SkillResult(speech="창 제어에 실패했습니다.", success=False)

    def _tile(self, windows: list) -> None:
        import ctypes

        user32 = ctypes.windll.user32
        screen_w = user32.GetSystemMetrics(0)
        screen_h = user32.GetSystemMetrics(1)

        n = len(windows)
        cols = ceil(sqrt(n))
        rows = ceil(n / cols)
        cell_w = screen_w // cols
        cell_h = screen_h // rows

        for i, window in enumerate(windows):
            col, row = i % cols, i // cols
            try:
                window.moveTo(col * cell_w, row * cell_h)
                window.resizeTo(cell_w, cell_h)
            except Exception:
                continue
