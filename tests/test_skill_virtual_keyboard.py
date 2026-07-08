"""가상 키보드 스킬(4-B) 배선 검증.

_extract_text_to_type()는 순수 함수라 실제 클립보드/키 입력 없이 검증하고,
_type_text()는 pyautogui/pyperclip을 모킹해 호출 배선만 검증한다.

실행: python -m tests.test_skill_virtual_keyboard (프로젝트 루트에서)
"""
import pyautogui
import pyperclip

import skills.skill_virtual_keyboard as skill_module
from core.context import Turn
from skills.skill_virtual_keyboard import VirtualKeyboardSkill, _extract_text_to_type


def _context_with_history(jarvis_text: str | None) -> dict:
    history = [Turn(user="이전 질문", jarvis=jarvis_text)] if jarvis_text else []
    return {"history": history, "data": {}}


def test_extract_uses_rago_quotation_pattern() -> None:
    result = _extract_text_to_type("안녕하세요라고 입력해줘", _context_with_history(None))
    assert result == "안녕하세요", f"'라고' 앞부분을 그대로 써야 함, got {result!r}"


def test_extract_uses_rago_pattern_with_different_phrasing() -> None:
    """'라고 입력해'로 문자열을 고정 매칭하면 '라고 입력하고'처럼 조사가 다른
    자연스러운 문장(엔터 요청과 결합된 경우 등)을 놓친다 — 계획 자체 리뷰 중
    발견. 반드시 '라고' 하나만으로 매칭해야 한다."""
    result = _extract_text_to_type(
        "안녕하세요라고 입력하고 엔터 쳐줘", _context_with_history(None)
    )
    assert result == "안녕하세요", (
        f"'라고 입력하고'처럼 뒤에 다른 조사가 와도 '라고' 앞부분을 써야 함, got {result!r}"
    )


def test_extract_uses_remaining_text_after_noise_removal() -> None:
    result = _extract_text_to_type("오늘 날씨 입력해줘", _context_with_history(None))
    assert result == "오늘 날씨", f"노이즈 제거 후 남는 텍스트를 써야 함, got {result!r}"


def test_extract_falls_back_to_last_jarvis_response() -> None:
    result = _extract_text_to_type("입력해줘", _context_with_history("직전 응답 텍스트"))
    assert result == "직전 응답 텍스트", f"history 폴백이 동작해야 함, got {result!r}"


def test_extract_returns_none_when_nothing_available() -> None:
    result = _extract_text_to_type("입력해줘", _context_with_history(None))
    assert result is None, f"텍스트도 history도 없으면 None이어야 함, got {result!r}"


def test_can_handle_scores_trigger_words() -> None:
    skill = VirtualKeyboardSkill()
    assert skill.can_handle("", "이거 입력해줘") == 0.85
    assert skill.can_handle("", "타이핑해줘") == 0.85
    assert skill.can_handle("", "오늘 날씨 알려줘") == 0.0


def test_type_text_pastes_via_clipboard_without_enter() -> None:
    calls = []
    original_copy = pyperclip.copy
    original_hotkey = pyautogui.hotkey
    original_press = pyautogui.press

    pyperclip.copy = lambda text: calls.append(("copy", text))
    pyautogui.hotkey = lambda *keys: calls.append(("hotkey", keys))
    pyautogui.press = lambda key: calls.append(("press", key))
    try:
        skill_module._type_text("안녕하세요", press_enter=False)
    finally:
        pyperclip.copy = original_copy
        pyautogui.hotkey = original_hotkey
        pyautogui.press = original_press

    assert ("copy", "안녕하세요") in calls, "클립보드에 복사해야 함"
    assert ("hotkey", ("ctrl", "v")) in calls, "Ctrl+V로 붙여넣어야 함"
    assert not any(c[0] == "press" for c in calls), "press_enter=False면 Enter를 누르면 안 됨"


def test_type_text_presses_enter_when_requested() -> None:
    calls = []
    original_copy = pyperclip.copy
    original_hotkey = pyautogui.hotkey
    original_press = pyautogui.press

    pyperclip.copy = lambda text: calls.append(("copy", text))
    pyautogui.hotkey = lambda *keys: calls.append(("hotkey", keys))
    pyautogui.press = lambda key: calls.append(("press", key))
    try:
        skill_module._type_text("안녕하세요", press_enter=True)
    finally:
        pyperclip.copy = original_copy
        pyautogui.hotkey = original_hotkey
        pyautogui.press = original_press

    assert ("press", "enter") in calls, "press_enter=True면 Enter를 눌러야 함"


def test_execute_returns_failure_when_nothing_to_type() -> None:
    skill = VirtualKeyboardSkill()
    result = skill.execute("입력해줘", {"history": [], "data": {}})
    assert result.success is False
    assert result.speech == "입력할 내용이 없습니다."


def test_execute_types_and_reports_success() -> None:
    calls = []
    original_type_text = skill_module._type_text
    skill_module._type_text = lambda text, press_enter: calls.append((text, press_enter))
    try:
        skill = VirtualKeyboardSkill()
        result = skill.execute("안녕하세요라고 입력해줘", {"history": [], "data": {}})
    finally:
        skill_module._type_text = original_type_text

    assert result.success is True
    assert result.speech == "입력했습니다"
    assert calls == [("안녕하세요", False)]


def test_execute_presses_enter_when_text_contains_enter_keyword() -> None:
    """'라고 입력하고 엔터 쳐줘'처럼 자연스러운 조사 변형에서도 텍스트 추출과
    엔터 감지가 둘 다 정확해야 한다 (Task 1의 '라고' 매칭 수정과 맞물린 케이스)."""
    calls = []
    original_type_text = skill_module._type_text
    skill_module._type_text = lambda text, press_enter: calls.append((text, press_enter))
    try:
        skill = VirtualKeyboardSkill()
        skill.execute("안녕하세요라고 입력하고 엔터 쳐줘", {"history": [], "data": {}})
    finally:
        skill_module._type_text = original_type_text

    assert calls == [("안녕하세요", True)], (
        f"텍스트는 '안녕하세요', press_enter는 True로 넘겨야 함, got {calls!r}"
    )


def main() -> None:
    tests = [
        test_extract_uses_rago_quotation_pattern,
        test_extract_uses_rago_pattern_with_different_phrasing,
        test_extract_uses_remaining_text_after_noise_removal,
        test_extract_falls_back_to_last_jarvis_response,
        test_extract_returns_none_when_nothing_available,
        test_can_handle_scores_trigger_words,
        test_type_text_pastes_via_clipboard_without_enter,
        test_type_text_presses_enter_when_requested,
        test_execute_returns_failure_when_nothing_to_type,
        test_execute_types_and_reports_success,
        test_execute_presses_enter_when_text_contains_enter_keyword,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print("\n가상 키보드 스킬 배선 검증 통과")


if __name__ == "__main__":
    main()
