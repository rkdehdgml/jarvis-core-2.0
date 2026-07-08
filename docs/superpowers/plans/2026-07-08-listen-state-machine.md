# 4-C Always-Listen 상태 머신 리팩토링 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `main.py`의 `_run_voice_loop()`이 쓰는 `active: bool` 플래그를 `ListenState` Enum(`IDLE`/`CONVERSING`)으로 교체하고, 흩어진 `broadcaster.emit(state="idle")` 호출을 `_transition()` 헬퍼 하나로 모은다. 순수 가독성 리팩토링 — 동작은 바뀌지 않는다.

**Architecture:** `main.py`에 `ListenState(Enum)`과 `_transition(state: ListenState) -> ListenState` 헬퍼를 추가하고, `_run_voice_loop()` 안의 `active = True/False` 대입을 전부 `state = _transition(ListenState.CONVERSING/IDLE)` 호출로 바꾼다. `voice/stt.py`, `voice/wakeword.py`는 건드리지 않는다(BOOT_WAIT/SPEECH는 이 파일들 안에서만 관찰 가능해 이번 범위 밖 — 설계 문서 참고).

**Tech Stack:** Python 3.10+ `enum.Enum`. 테스트는 `pytest` 없이 `tests/`의 assert 기반 스크립트 컨벤션(`python -m tests.<module>`)을 따른다.

## Global Constraints

- `voice/stt.py`, `voice/wakeword.py`는 수정하지 않는다 — BOOT_WAIT/SPEECH 상태는 구현하지 않는다 (스펙 결정 사항).
- 사용자가 관찰하는 동작(웨이크워드→명령→응답→재대기 흐름)은 리팩토링 전후 동일해야 한다.
- 기존 `broadcaster.emit(state="idle")` 3곳(비활성화·종료·sleep_requested)과 루프 상단 `broadcaster.emit(state="listening")`을 `_transition()` 호출로 통합한다 — 중복 emit을 만들지 않는다.

---

### Task 1: `ListenState` + `_transition()` + `_run_voice_loop()` 배선

**Files:**
- Modify: `main.py`
- Test: `tests/test_listen_state.py` (신규)

**Interfaces:**
- Produces: `main.ListenState` (`IDLE`, `CONVERSING`), `main._transition(state: ListenState) -> ListenState`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_listen_state.py`를 새로 만든다 (아직 `main.ListenState`가 없어
`AttributeError`로 실패해야 정상):

```python
"""ListenState 전환 헬퍼(4-C) 배선 검증.

_transition()이 상태에 맞는 broadcaster 이벤트를 emit하는지만 확인한다.
실제 음성 루프(_run_voice_loop)는 마이크/모델이 필요해 자동 테스트 대상
밖 — 수동 검증으로 남긴다(계획 문서 "수동 검증" 절 참고).

실행: python -m tests.test_listen_state (프로젝트 루트에서)
"""
import main as jarvis_main
from core.status_events import broadcaster


def test_transition_to_idle_emits_idle() -> None:
    events = []
    original_emit = broadcaster.emit
    broadcaster.emit = lambda **kwargs: events.append(kwargs)
    try:
        result = jarvis_main._transition(jarvis_main.ListenState.IDLE)
    finally:
        broadcaster.emit = original_emit

    assert result is jarvis_main.ListenState.IDLE
    assert events == [{"state": "idle"}], f"IDLE 전환은 'idle' 이벤트를 emit해야 함, got {events!r}"


def test_transition_to_conversing_emits_listening() -> None:
    events = []
    original_emit = broadcaster.emit
    broadcaster.emit = lambda **kwargs: events.append(kwargs)
    try:
        result = jarvis_main._transition(jarvis_main.ListenState.CONVERSING)
    finally:
        broadcaster.emit = original_emit

    assert result is jarvis_main.ListenState.CONVERSING
    assert events == [{"state": "listening"}], (
        f"CONVERSING 전환은 'listening' 이벤트를 emit해야 함, got {events!r}"
    )


def main() -> None:
    tests = [
        test_transition_to_idle_emits_idle,
        test_transition_to_conversing_emits_listening,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print("\nListenState 전환 배선 검증 통과")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m tests.test_listen_state`
Expected: `AttributeError: module 'main' has no attribute 'ListenState'`

- [ ] **Step 3: `ListenState` + `_transition()` 추가, `_run_voice_loop()` 배선 교체**

`main.py` 상단 import 블록에 `from enum import Enum, auto` 추가 (`import argparse`
다음 줄):

```python
import argparse
from enum import Enum, auto
import logging
```

`_EXIT_WORD` 등 모듈 상수 정의 다음, `_is_deactivate_command()` 앞에 추가:

```python
class ListenState(Enum):
    """main.py가 실제로 관찰 가능한 음성 루프 상태만 다룬다.

    WhisperFlow 원형의 BOOT_WAIT(모델 로딩)/SPEECH(VAD 발화 경계)는
    각각 wakeword.py/stt.py 내부에 갇혀 있어 main.py 레벨에서 구분할 수
    없다 — 이 두 파일을 건드리는 건 이번 리팩토링 범위 밖(설계 문서 참고).
    """
    IDLE = auto()        # 웨이크워드/박수 트리거 대기 중
    CONVERSING = auto()  # 깨어난 뒤 명령을 듣고 처리하는 중, 재웨이크워드 불필요


def _transition(state: ListenState) -> ListenState:
    """상태를 기록하고 대응하는 broadcaster 이벤트를 emit한 뒤 그대로 반환한다."""
    broadcaster.emit(state="idle" if state is ListenState.IDLE else "listening")
    return state
```

`_run_voice_loop()`을 교체한다 (기존 `active: bool` 로직을 `ListenState`로 치환,
루프 상단의 별도 `broadcaster.emit(state="listening")` 호출은 `_transition()`
안으로 흡수해 제거):

```python
def _run_voice_loop(router: Router, dispatcher: Dispatcher, context: ConversationContext) -> None:
    # 모델 로딩이 무거워 음성 모드를 실제로 쓸 때만 import한다.
    from voice import stt, tts, wakeword

    print(
        '자비스가 준비됐습니다. "자비스" 또는 박수 2번으로 음성인식을 켜고, '
        '"자비스 오프"/"자비스 종료"로 끌 수 있습니다. (Ctrl+C로 프로그램 종료)'
    )
    state = _transition(ListenState.IDLE)

    try:
        while True:
            if state is ListenState.IDLE:
                trigger = wakeword.wait_for_activation()
                logger.info(f"음성인식 활성화 (트리거: {trigger})")
                state = ListenState.CONVERSING

            # 이 시점에서 state는 항상 CONVERSING이다 — 매 반복 stt.listen() 전에
            # "listening"을 emit해야 하는 기존 동작(반복마다 무조건 emit)을
            # 그대로 유지하기 위해 매번 호출한다. 방금 IDLE→CONVERSING으로
            # 전환됐든, 이미 CONVERSING이던 반복이든 동일하게 emit된다.
            state = _transition(state)
            text = stt.listen()

            if not text:
                continue

            if _is_deactivate_command(text):
                tts.speak("음성인식을 종료합니다.")
                state = _transition(ListenState.IDLE)
                continue

            if text == _EXIT_WORD:
                tts.speak("자비스를 종료합니다.")
                broadcaster.emit(state="idle")
                break

            if _is_clear_history_command(text):
                _clear_history(context)
                tts.speak("대화 기록을 지웠습니다.")
                continue

            event = normalize_input(text, channel="voice")
            skill = router.route(event.text)
            result = dispatcher.dispatch(skill, event.text, context, channel=event.channel)

            _speak_with_clap_interrupt(result.speech)
            if context.get("sleep_requested"):
                context.set("sleep_requested", False)
                state = _transition(ListenState.IDLE)
                continue
    except KeyboardInterrupt:
        print("\n자비스를 종료합니다.")
        broadcaster.emit(state="idle")
```

(종료 두 분기 — `_EXIT_WORD`와 `KeyboardInterrupt` — 는 루프를 끝내고 프로그램이
바로 종료되므로 `ListenState`로 갱신할 다음 반복이 없다. `_transition()`이 아니라
기존처럼 `broadcaster.emit(state="idle")`을 직접 호출해 "더 이상 상태를 추적할
필요 없는 최종 이벤트"라는 의도를 유지한다.)

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m tests.test_listen_state`
Expected: 2개 테스트 모두 `[OK]`, 마지막 줄 `ListenState 전환 배선 검증 통과`

- [ ] **Step 5: 회귀 확인 (import 안전성)**

Run:
```powershell
python -c "import sys, main; loaded = [m for m in sys.modules if 'faster_whisper' in m or 'silero_vad' in m]; assert loaded == [], loaded; print('OK: main.py import은 STT 스택을 즉시 로딩하지 않음')"
```
Expected: `OK: main.py import은 STT 스택을 즉시 로딩하지 않음`
(`enum` 표준 라이브러리만 추가했으므로 지연 로딩 불변식이 깨질 이유가 없지만,
4-A에서 실제로 이 불변식이 깨진 적이 있어 매 main.py 변경마다 확인한다.)

- [ ] **Step 6: 커밋**

```bash
git add main.py tests/test_listen_state.py
git commit -m "feat: 음성 루프 active bool을 ListenState Enum으로 교체 (4-C)"
```

---

## 수동 검증 (실 하드웨어)

자동 테스트는 `_transition()`의 emit 배선만 검증한다. 실제 루프 동작(웨이크워드→
명령→응답→재대기)이 리팩토링 전과 동일한지 아래로 확인한다:

1. `python main.py`로 기동 → "자비스"로 깨우기 → 아무 질문 → 응답 후 재웨이크워드
   없이 바로 다음 질문이 되는지 확인 (`CONVERSING` 유지 확인).
2. "자비스 오프"로 비활성화 → "자비스" 없이는 반응 없다가, 다시 "자비스"로
   깨우면 정상 동작하는지 확인 (`IDLE` 복귀 확인).
3. 잠자기 요청(`sleep_requested`를 쓰는 스킬이 있다면) 후에도 동일하게 `IDLE`로
   돌아가는지 확인.

## 영향받는 파일 요약

| 파일 | 변경 내용 |
|------|-----------|
| `main.py` | `ListenState` Enum + `_transition()` 추가, `_run_voice_loop()` 배선 교체 |
| `tests/test_listen_state.py` | 신규 — `_transition()` 배선 테스트 |
