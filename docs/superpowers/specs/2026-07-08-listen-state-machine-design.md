# 4-C. Always-Listen 상태 머신 리팩토링 설계

> TODO.md 우선순위 4 항목 중 4-C 구현을 위한 설계 문서. 작성일: 2026-07-08.
> 사용자 지시로 확인 질문 없이 판단해 진행.

## 범위 결정

TODO.md 원래 설계는 WhisperFlow의 `BOOT_WAIT→IDLE→SPEECH→CONV_WAIT` 4단계를
그대로 옮기는 안이었다. 그러나 `main.py`가 실제로 관찰할 수 있는 전환은 2개뿐이다:

- **BOOT_WAIT vs IDLE**: `wakeword.wait_for_activation()`이 모델을 지연 로딩하므로
  "부팅 중"과 "대기 중"이 `main.py` 입장에서 구분되지 않는다(둘 다 같은 함수 호출
  안에서 벌어짐). 구분하려면 `wakeword.py`에 로딩 완료 콜백을 새로 만들어야 하는데,
  이는 이번 TODO 항목("main.py 루프 재설계")의 범위를 넘는 손질이다.
- **SPEECH**: `stt.listen()` 내부의 VAD 발화 경계 감지는 `main.py`에 노출되지 않는다.
  진짜 상태로 만들려면 `voice/stt.py`를 뜯어 콜백을 추가해야 한다.

따라서 이번 리팩토링은 **`main.py`에서 실제로 관찰 가능한 2개 상태**만
`ListenState` Enum으로 명시화한다. 이는 순수 코드 가독성 리팩토링이다 —
동작(사용자가 보는 결과)은 바뀌지 않는다. `voice/stt.py`, `voice/wakeword.py`는
건드리지 않는다.

## 상태 정의

```python
class ListenState(Enum):
    IDLE       = auto()  # 웨이크워드/박수 트리거 대기 중 (기존 active=False)
    CONVERSING = auto()  # 깨어난 뒤 명령을 듣고 처리하는 중, 재웨이크워드 불필요 (기존 active=True)
```

전환:
- 시작: `IDLE`
- `IDLE` → `CONVERSING`: `wakeword.wait_for_activation()`이 반환
- `CONVERSING` → `IDLE`: 비활성화 명령(`"자비스오프"`) 또는 `sleep_requested`
- `CONVERSING` → `CONVERSING`: 일반 명령 처리 후 다음 `stt.listen()` 반복
- 종료(`_EXIT_WORD` 또는 `KeyboardInterrupt`)는 상태와 무관하게 루프 자체를 끝냄

## 현재 코드의 문제와 개선

현재 `_run_voice_loop()`은 `active: bool` 플래그와 함께 `broadcaster.emit(state="idle")`
호출이 3곳(비활성화, 종료, sleep_requested)에 흩어져 있고, 각 분기가 "무슨 상태로
가는지"를 주석 없이 `active = False`로만 표현한다. `_transition(new_state)` 헬퍼
하나로 "Enum 갱신 + 해당 broadcaster 이벤트 emit"을 묶어, 상태 전환 지점을 한
곳으로 모은다:

```python
def _transition(state: ListenState) -> ListenState:
    broadcaster.emit(state="idle" if state is ListenState.IDLE else "listening")
    return state
```

`CONVERSING`으로 전환될 때 emit하는 `"listening"`은 기존 코드에서 루프 맨 위
`broadcaster.emit(state="listening")` 호출과 동일한 시점·의미이므로 중복 emit이
아니라 대체다.

## 테스트 방침

상태 전환 자체는 순수 로직(`_transition()`이 어떤 `state` 문자열을 emit하는지)만
검증한다 — `broadcaster.emit`을 모킹해 `_transition(ListenState.IDLE)`이
`"idle"`을, `_transition(ListenState.CONVERSING)`이 `"listening"`을 emit하는지
확인. 루프 전체(`_run_voice_loop`)는 실제 마이크/모델이 필요해 기존과 동일하게
자동 테스트 대상 밖 — 수동 검증(기존 동작과 동일하게 웨이크워드→명령→응답→
재대기 흐름이 유지되는지)으로 남긴다.

## 영향받는 파일 요약

| 파일 | 변경 내용 |
|------|-----------|
| `main.py` | `ListenState` Enum + `_transition()` 추가, `_run_voice_loop()`의 `active` bool을 Enum으로 교체 |
| `tests/test_listen_state.py` | 신규 — `_transition()` 배선 테스트 |
