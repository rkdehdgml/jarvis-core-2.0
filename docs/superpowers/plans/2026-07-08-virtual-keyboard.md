# 4-B 가상 키보드 출력 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "~라고 입력해줘" 같은 발화로, 지정한 텍스트(또는 직전 자비스 응답)를 현재 포커스된 창에 클립보드 붙여넣기 방식으로 입력하는 새 스킬을 추가한다.

**Architecture:** `skills/skill_virtual_keyboard.py` 한 파일에 `VirtualKeyboardSkill`(Skill 서브클래스), 텍스트 소스를 결정하는 순수 함수 `_extract_text_to_type()`, 실제 붙여넣기를 수행하는 `_type_text()`를 둔다. `pyautogui`/`pyperclip`은 `skill_window.py`/`skill_clipboard.py` 관례와 동일하게 `execute()` 안에서 지연 import한다. 별도 `voice/` 모듈은 만들지 않는다.

**Tech Stack:** Python 3.10+, `pyperclip`(이미 의존성), `pyautogui`(이미 의존성). 테스트는 `pytest` 없이 `tests/`의 assert 기반 스크립트 컨벤션(`python -m tests.<module>`)을 따른다.

## Global Constraints

- Claude CLI 터미널 특화 기능(`inject_to_claude_terminal`)은 구현하지 않는다 — 범용 "포커스된 창에 타이핑"만 구현 (스펙 결정 사항).
- `pyautogui`/`pyperclip`은 `execute()`/`_type_text()` 안에서 지연 import한다 — 모듈 최상단 import 금지 (`skill_window.py`/`skill_clipboard.py` 관례).
- Enter는 발화에 "엔터"가 포함된 경우에만 누른다 — 기본은 붙여넣기만 (의도치 않은 폼 제출 방지).
- `_extract_text_to_type()`는 부작용 없는 순수 함수로 유지한다 — 실제 클립보드/키 입력(`_type_text`)과 분리해 하드웨어 없이 테스트 가능해야 한다.

---

### Task 1: 텍스트 소스 결정 로직 + 스킬 스켈레톤

**Files:**
- Create: `skills/skill_virtual_keyboard.py`
- Test: `tests/test_skill_virtual_keyboard.py` (신규 — Task 2도 이 파일에 이어서 씀)

**Interfaces:**
- Produces: `skills.skill_virtual_keyboard._extract_text_to_type(text: str, context: dict) -> str | None`,
  `skills.skill_virtual_keyboard.VirtualKeyboardSkill` (`name`, `triggers`, `can_handle(intent, text) -> float`)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_skill_virtual_keyboard.py`를 새로 만든다 (아직 `skills.skill_virtual_keyboard`
모듈이 없어 `ModuleNotFoundError`로 실패해야 정상):

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m tests.test_skill_virtual_keyboard`
Expected: `ModuleNotFoundError: No module named 'skills.skill_virtual_keyboard'`

- [ ] **Step 3: 최소 구현**

`skills/skill_virtual_keyboard.py`를 새로 만든다:

```python
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
        raise NotImplementedError  # Task 2에서 구현
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m tests.test_skill_virtual_keyboard`
Expected: 6개 테스트 모두 `[OK]`, 마지막 줄 `가상 키보드 스킬 배선 검증 통과`

- [ ] **Step 5: 커밋**

```bash
git add skills/skill_virtual_keyboard.py tests/test_skill_virtual_keyboard.py
git commit -m "feat: 가상 키보드 스킬 - 텍스트 소스 결정 로직 + 스켈레톤 (4-B)"
```

---

### Task 2: 타이핑 실행 + `execute()`

**Files:**
- Modify: `skills/skill_virtual_keyboard.py`
- Test: `tests/test_skill_virtual_keyboard.py` (Task 1 파일에 이어서 추가)

**Interfaces:**
- Consumes: `_extract_text_to_type(text: str, context: dict) -> str | None` (Task 1에서 생산)
- Produces: `skills.skill_virtual_keyboard._type_text(text: str, press_enter: bool) -> None`,
  `VirtualKeyboardSkill.execute(text: str, context: dict) -> SkillResult` (완성)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_skill_virtual_keyboard.py`에 추가 (파일 상단 import에
`import pyautogui`, `import pyperclip`, `skills.skill_virtual_keyboard as skill_module` 추가):

```python
import pyautogui
import pyperclip

import skills.skill_virtual_keyboard as skill_module


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
```

`main()`의 `tests` 리스트에 다섯 테스트를 추가한다.

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m tests.test_skill_virtual_keyboard`
Expected: `AttributeError: module 'skills.skill_virtual_keyboard' has no attribute '_type_text'`
(또는 `execute()`가 `NotImplementedError`를 던짐)

- [ ] **Step 3: `_type_text()` + `execute()` 구현**

`skills/skill_virtual_keyboard.py`의 `VirtualKeyboardSkill.execute()`를 교체하고,
파일 끝에 `_type_text()`를 추가한다:

```python
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
```

(`execute()`는 기존 `raise NotImplementedError` 줄을 이 구현으로 교체한다.
`_type_text()`는 클래스 밖, 모듈 최하단에 둔다.)

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m tests.test_skill_virtual_keyboard`
Expected: 11개 테스트 모두 `[OK]`, 마지막 줄 `가상 키보드 스킬 배선 검증 통과`

- [ ] **Step 5: 레지스트리 로딩 확인**

Run:
```powershell
python -c "from core.registry import SkillRegistry; r = SkillRegistry(); r.load(); print([s.name for s in r.get_all_skills() if s.name == 'virtual_keyboard'])"
```
Expected: `['virtual_keyboard']` — `SkillRegistry`가 `skills/skill_*.py`를 자동 스캔하므로
새 파일이 등록 없이 인식되는지 확인 (CLAUDE.md의 핵심 설계 원칙 검증).

- [ ] **Step 6: 커밋**

```bash
git add skills/skill_virtual_keyboard.py tests/test_skill_virtual_keyboard.py
git commit -m "feat: 가상 키보드 스킬 - 타이핑 실행 + execute() 완성 (4-B)"
```

---

## 수동 검증 (실 하드웨어)

자동 테스트는 전부 모킹 기반이라 실제 클립보드/키 입력 동작은 별도로 확인이
필요하다:

1. `python main.py --text`로 기동, 메모장을 열고 포커스한 채로 "안녕하세요라고
   입력해줘"를 입력 — 메모장에 "안녕하세요"가 타이핑되는지 확인.
2. 자비스가 뭔가 대답한 직후 "입력해줘"만 입력 — 직전 응답이 타이핑되는지 확인.
3. "안녕하세요라고 입력하고 엔터 쳐줘" — 붙여넣기 후 Enter가 눌리는지 확인.
4. 화면 제어 트리거와의 충돌 확인: "화면 제어로 켜서 안녕하세요 입력해줘" 류
   문장이 `screen_agent`(0.91~0.95)로 라우팅되고 `virtual_keyboard`(0.85)로
   새지 않는지 확인.

## 영향받는 파일 요약

| 파일 | 변경 내용 |
|------|-----------|
| `skills/skill_virtual_keyboard.py` | 신규 — 가상 키보드 스킬 전체 (Task 1, 2) |
| `tests/test_skill_virtual_keyboard.py` | 신규 — 배선 테스트 전체 (Task 1, 2) |
