"""가상 키보드 스킬(4-B) 배선 검증.

_extract_text_to_type()는 순수 함수라 실제 클립보드/키 입력 없이 검증하고,
_type_text()는 pyautogui/pyperclip을 모킹해 호출 배선만 검증한다.

실행: python -m tests.test_skill_virtual_keyboard (프로젝트 루트에서)
"""
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


def main() -> None:
    tests = [
        test_extract_uses_rago_quotation_pattern,
        test_extract_uses_rago_pattern_with_different_phrasing,
        test_extract_uses_remaining_text_after_noise_removal,
        test_extract_falls_back_to_last_jarvis_response,
        test_extract_returns_none_when_nothing_available,
        test_can_handle_scores_trigger_words,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print("\n가상 키보드 스킬 배선 검증 통과")


if __name__ == "__main__":
    main()
