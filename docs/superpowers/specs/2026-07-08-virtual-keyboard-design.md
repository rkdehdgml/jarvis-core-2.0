# 4-B. 가상 키보드 출력 설계

> TODO.md 우선순위 4 항목 중 4-B 구현을 위한 설계 문서. 작성일: 2026-07-08.
> WhisperFlow 원리(STT 결과 → 클립보드 → 붙여넣기 → 터미널 입력)를 Windows로
> 이식하되, "Claude CLI 터미널에 직접 주입" 부분은 이 아키텍처와 맞지 않아
> 범용 "포커스된 창에 타이핑" 기능으로 범위를 좁혔다(사용자 승인 완료).

## 배경 및 범위 결정

TODO.md 원래 설계는 `voice/virtual_keyboard.py`에 `type_text()`와
`inject_to_claude_terminal()` 두 함수를 두는 안이었다. 그러나:

- jarvis-core는 `claude -p ...`를 서브프로세스로 1회 호출하는 방식(`core/engines/`)이라
  사용자가 들여다보는 인터랙티브 Claude 터미널 세션이 애초에 없다 —
  `inject_to_claude_terminal()`이 가정하는 "열려 있는 Claude 터미널 창"이 실제로
  쓰일 상황이 없어 제외한다.
- `voice/`는 CLAUDE.md에 명시된 대로 오디오 I/O 전용 경계다. 클립보드/키보드
  자동화는 오디오가 아니라 OS 자동화이므로, 기존 관례(`skills/skill_window.py`가
  `pygetwindow`를, `skills/skill_clipboard.py`가 `pyperclip`을 스킬 파일 안에서
  직접 지연 import)를 따라 `skills/skill_virtual_keyboard.py` 하나에 로직을 담는다.
  별도 `voice/virtual_keyboard.py` 모듈은 만들지 않는다.

## 컴포넌트

### `skills/skill_virtual_keyboard.py` (신규)

`Skill` 서브클래스 하나. `pyperclip`/`pyautogui`는 기존 관례(`skill_clipboard.py`,
`skill_window.py`)와 동일하게 `execute()` 안에서 지연 import하고, `ImportError`
시 "가상 키보드 기능을 사용할 수 없습니다" 류의 실패 `SkillResult`를 반환한다.

**라우팅 (`can_handle`)**: 트리거 단어 "입력해줘"/"입력해"/"타이핑해줘"/"타이핑해"
중 하나라도 있으면 0.85. `skill_screen_agent.py`는 이 단어들을 `_ACTION`에 갖고
있지만 `_OPEN`("켜서"/"열어서" 등)과 **함께** 있을 때만 반응하므로(코드 확인
완료), 단독 "~입력해줘"는 겹치지 않는다.

**텍스트 소스 결정 (`_extract_text_to_type`, 우선순위 순 시도)**:

1. `"라고 입력해"` 패턴 — "라고" 앞부분을 그대로 사용
   (예: "안녕하세요라고 입력해줘" → `"안녕하세요"`)
2. 트리거/지시어 노이즈 단어(`"입력해줘"`, `"입력해"`, `"타이핑해줘"`, `"타이핑해"`,
   `"이거"`, `"이 내용"`, `"방금 말한 거"`, `"엔터"`)를 제거하고 남는 텍스트가
   있으면 그것 (`skill_clipboard.py`의 `_COPY_NOISE_WORDS` 제거 패턴과 동일한 방식)
3. 1·2 모두 빈 문자열이면 `context["history"]`의 마지막 턴(`Turn.jarvis`) — 직전
   자비스 응답. `Dispatcher._run()`이 `skill.execute()` 반환 **후**에
   `context.add_turn()`을 호출하므로, `execute()` 시점의 `history[-1]`은 정확히
   "이 명령 직전" 턴이다(오프바이원 없음, `core/dispatcher.py:67-71` 확인).
4. 1·2·3 모두 없으면(첫 턴이라 기록이 없는 경우 등) 실패 응답
   `"입력할 내용이 없습니다"`, `success=False`

**타이핑 동작 (`_type_text`)**:

```python
pyperclip.copy(text)
time.sleep(0.05)
pyautogui.hotkey('ctrl', 'v')
if "엔터" in original_text:
    time.sleep(0.05)
    pyautogui.press('enter')
```

Enter는 기본적으로 누르지 않는다 — 붙여넣은 텍스트가 검색창/폼일 때 의도치
않게 제출되는 것을 막기 위함(사용자 승인 완료). 발화에 "엔터"가 포함된 경우에만
누른다.

**성공 응답**: `SkillResult(speech="입력했습니다", success=True, data={"text": text})`.
`pyautogui`/`pyperclip` 호출이 던지는 예외는 `skill_window.py`/`skill_clipboard.py`와
동일하게 넓게 잡아 `"입력에 실패했습니다"` 실패 응답으로 변환한다(포커스된 창이
붙여넣기를 지원하지 않는 경우 등 사용자가 통제할 수 없는 실패가 프로그램을
죽이면 안 되므로).

## 오류/엣지 케이스

- **포커스 앱이 붙여넣기를 지원하지 않는 창(예: 바탕화면)**: `pyautogui.hotkey`
  자체는 예외를 던지지 않고 그냥 키 입력만 보낸다 — 아무 일도 안 일어난 것처럼
  보일 수 있다. 이는 WhisperFlow 이식 범위에서 근본적으로 감지 불가능한
  한계이므로(어느 창이 포커스인지, 그 창이 텍스트 입력을 받는지 OS 자동화만으로는
  확실히 알 수 없음) 설계에서 처리하지 않고 알려진 제약으로 남긴다.
- **되돌릴 수 없는 액션 안전장치 필요 여부**: `hybrid_screen.py`/`web_collector.py`의
  `_IRREVERSIBLE_ACTION_KEYWORDS` 같은 차단 로직은 여기서는 불필요 — 단순 텍스트
  붙여넣기이지 클릭/구매/삭제가 아니다. Enter를 명시적으로 요청했을 때만 누르는
  것으로 충분한 안전장치로 판단.

## 테스트 방침

`pytest` 없음 — `tests/`의 assert 기반 스크립트 컨벤션을 따른다.
`pyautogui`/`pyperclip` 실제 호출 없이 `_extract_text_to_type()`(순수 함수, 부작용
없음)의 우선순위 로직만 단위 테스트한다 — 실제 클립보드/키 입력 부분은 하드웨어
의존적이라 자동 테스트 대상에서 제외하고 수동 검증으로 남긴다.

- `"안녕하세요라고 입력해줘"` → `"안녕하세요"`
- `"오늘 날씨 입력해줘"` (노이즈 제거 후 텍스트 남는 케이스) → `"오늘 날씨"`
- `"입력해줘"` (노이즈만 있고 남는 게 없음) + history에 직전 자비스 응답 있음
  → 그 응답 텍스트
- `"입력해줘"` + history 비어있음 → `None`(또는 실패를 나타내는 값) →
  `execute()`가 실패 `SkillResult` 반환하는지 별도 검증
- `can_handle()`: "입력해줘"만 있으면 0.85, "켜서 ... 입력해줘"(screen_agent
  영역)에서는 이 스킬도 0.85를 반환하지만 screen_agent가 0.91로 더 높아 Router가
  screen_agent를 선택함을 확인(두 스킬 다 같은 텍스트에 점수를 매길 수 있는 건
  정상 — Router가 최고점을 고르므로 충돌 아님)

## 영향받는 파일 요약

| 파일 | 변경 내용 |
|------|-----------|
| `skills/skill_virtual_keyboard.py` | 신규 — 가상 키보드 스킬 전체 |
| `tests/test_skill_virtual_keyboard.py` | 신규 — `_extract_text_to_type()` 우선순위 로직 테스트 |
