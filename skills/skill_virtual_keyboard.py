"""가상 키보드 출력 — 지정한 텍스트(또는 직전 자비스 응답)를 현재 포커스된
창에 클립보드 붙여넣기 방식으로 입력한다 (WhisperFlow의 pbcopy + AppleScript
붙여넣기 메커니즘을 Windows로 이식, Claude 터미널 특화 부분은 이 아키텍처와
맞지 않아 제외).
"""
import time

from core.skill_base import Skill, SkillResult

_TRIGGERS = ("입력해줘", "입력해", "타이핑해줘", "타이핑해")
_NOISE_WORDS = (
    "입력해줘", "입력해", "타이핑해줘", "타이핑해",
    "이거", "이 내용", "방금 말한 거", "엔터",
)


def _extract_text_to_type(text: str, context: dict) -> str | None:
    """발화에서 타이핑할 텍스트를 우선순위대로 결정한다.

    1. "라고" 앞부분 (예: "안녕하세요라고 입력해줘" → "안녕하세요"). "라고"
       하나만으로 매칭한다 — "라고 입력해"처럼 뒤 문자열까지 고정하면
       "라고 입력하고 엔터 쳐줘"처럼 조사가 다른 자연스러운 문장을 놓친다.
    2. 트리거/지시어 노이즈 단어를 제거하고 남는 텍스트
    3. 1·2가 모두 비면 직전 자비스 응답(context["history"]의 마지막 턴)
    4. 셋 다 없으면 None
    """
    if "라고" in text:
        candidate = text.split("라고")[0].strip()
        if candidate:
            return candidate

    candidate = text
    for noise in _NOISE_WORDS:
        candidate = candidate.replace(noise, "")
    candidate = candidate.strip()
    if candidate:
        return candidate

    history = context.get("history", [])
    if history:
        last_response = history[-1].jarvis
        if last_response:
            return last_response

    return None


class VirtualKeyboardSkill(Skill):
    """텍스트를 현재 포커스된 창에 클립보드 붙여넣기 방식으로 입력한다."""

    name = "virtual_keyboard"
    description = "지정한 텍스트나 직전 자비스 응답을 현재 포커스된 창에 타이핑한다"
    triggers = list(_TRIGGERS)
    examples = ["안녕하세요라고 입력해줘", "방금 대답 입력해줘", "이거 타이핑해줘"]

    def can_handle(self, intent: str, text: str) -> float:
        if any(t in text for t in _TRIGGERS):
            return 0.85
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        try:
            import pyautogui  # noqa: F401 (설치 확인용)
            import pyperclip  # noqa: F401
        except ImportError:
            return SkillResult(
                speech="가상 키보드 기능을 사용할 수 없습니다 (pyautogui/pyperclip 미설치).",
                success=False,
            )

        to_type = _extract_text_to_type(text, context)
        if not to_type:
            return SkillResult(speech="입력할 내용이 없습니다.", success=False)

        try:
            _type_text(to_type, press_enter=("엔터" in text))
        except Exception:
            return SkillResult(speech="입력에 실패했습니다.", success=False)

        return SkillResult(speech="입력했습니다", success=True, data={"text": to_type})


def _type_text(text: str, press_enter: bool) -> None:
    """text를 클립보드에 복사한 뒤 Ctrl+V로 현재 포커스된 창에 붙여넣는다."""
    import pyautogui
    import pyperclip

    pyperclip.copy(text)
    time.sleep(0.05)
    pyautogui.hotkey("ctrl", "v")
    if press_enter:
        time.sleep(0.05)
        pyautogui.press("enter")
