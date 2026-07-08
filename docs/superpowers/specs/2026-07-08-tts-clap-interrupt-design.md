# 4-A. TTS 인터럽트(박수 2번 → 즉시 중단) 설계

> TODO.md 우선순위 4 항목 중 4-A 구현을 위한 설계 문서. 작성일: 2026-07-08.
> WhisperFlow에는 없는 기능(Mac 특성상 불필요)이지만, 자비스가 긴 응답을 읽는 동안
> 사용자가 끼어들 방법이 없다는 실사용 불편을 해소하기 위해 이식한다.

## 배경

`voice/tts.py`의 `speak()`는 `pygame.mixer.music.play()` 후 `get_busy()`가 `False`가
될 때까지 블로킹한다. 재생 도중 사용자가 끼어들 방법이 전혀 없어 — 긴 응답을 끝까지
들어야 다음 명령을 낼 수 있다. `voice/clap_detector.py`의 `ClapDetector`는 이미 존재하지만
현재는 `voice/wakeword.py`의 `wait_for_activation()` 안에서만(웨이크워드와 OR 조건으로)
쓰이고 있고, TTS 재생 중에는 마이크를 듣고 있지 않다.

## 범위

`_run_voice_loop()`(음성 모드)에서 TTS 재생 중 박수 2번으로 즉시 중단하고, 중단 직후
바로 다음 명령을 듣는다(재웨이크워드 불필요). `_run_text_loop()`(`--text` 모드)는 TTS를
쓰지 않으므로 영향 없음.

## 컴포넌트 책임

### `voice/tts.py` — `stop()` 신규

```python
def stop() -> None:
    """재생 중인 TTS를 즉시 중단한다. 다른 스레드에서 호출해도 안전
    (pygame.mixer.music 제어 함수는 스레드 세이프)."""
    try:
        if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
            pygame.mixer.music.stop()
    except Exception:
        pass
```

`speak()`/`_play()`는 수정하지 않는다 — `_play()`의 `while pygame.mixer.music.get_busy():
pygame.time.wait(50)` 루프는 다른 스레드에서 `stop()`이 호출되면 다음 50ms 폴링에서
자연스럽게 `False`를 관측하고 빠져나온다.

### `voice/clap_detector.py` — `wait_for_double_clap()` 신규

```python
def wait_for_double_clap(stop_event: threading.Event) -> bool:
    """마이크에서 박수 2번이 감지될 때까지 블로킹한다.

    stop_event가 set되면(TTS가 정상 종료돼 더 들을 필요가 없어지면) 프레임을
    더 기다리지 않고 즉시 False를 반환한다.

    Returns:
        박수 2번이 감지돼 반환하면 True, stop_event로 인해 중단되면 False.
    """
```

`wakeword.wait_for_activation()`과 같은 패턴(자체 `sd.InputStream` 오픈 → 콜백이 프레임을
큐에 적재 → 순서대로 `ClapDetector.process()`에 전달)을 따르되, 두 가지가 다르다:

- 웨이크워드 모델 추론이 없으므로 리샘플링 불필요 — 네이티브 샘플레이트 프레임을
  그대로 `ClapDetector`에 전달.
- 큐에서 프레임을 꺼낼 때 `queue.get(timeout=0.1)`로 짧게 폴링하며, 매 폴링마다
  `stop_event.is_set()`을 확인한다. 프레임이 없어 타임아웃돼도 그냥 다음 반복으로
  넘어간다(빈 프레임 처리 없이 `continue`).

`wakeword.py`는 이 함수를 사용하도록 리팩토링하지 않는다 — 웨이크워드 모델과 클랩을
하나의 스트림에서 함께 검사하는 기존 구조가 이미 동작 중이고, 이번 설계 범위와
무관한 리팩토링이므로 손대지 않는다(YAGNI).

### `main.py` — `_speak_with_clap_interrupt()` 신규

```python
def _speak_with_clap_interrupt(text: str) -> None:
    from voice import tts
    from voice.clap_detector import wait_for_double_clap
    import threading

    stop_event = threading.Event()

    def _watch() -> None:
        if wait_for_double_clap(stop_event):
            tts.stop()

    watcher = threading.Thread(target=_watch, daemon=True)
    watcher.start()
    try:
        tts.speak(text)
    finally:
        stop_event.set()
        watcher.join()
```

`_run_voice_loop()`의 `tts.speak(result.speech)` 호출 한 곳만 이 헬퍼로 교체한다.
`finally`로 `stop_event.set()` + `join()`을 보장해, `speak()`가 정상 종료하든
중단되든 관계없이 워처 스레드(와 그 안의 마이크 스트림)를 다음 `stt.listen()`이
새 스트림을 열기 전에 반드시 정리한다 — 두 입력 스트림이 겹치는 것을 방지.

## 제어 흐름

인터럽트 발생 후 상태는 별도 분기 없이 자연스럽게 처리된다: `_run_voice_loop()`의
`while` 루프는 `_speak_with_clap_interrupt()`가 반환하면(중단이든 정상 종료든) 바로
다음 반복에서 `stt.listen()`을 호출하므로, "중단 후 바로 다음 명령 대기"가 기존 루프
구조만으로 충족된다. `active` 플래그나 `broadcaster` 상태를 별도로 만지지 않는다.

## 오탐(false positive) 대응

`ClapDetector`의 기존 임계값(`_PEAK_THRESHOLD` 등)을 그대로 사용한다 — 이미 "매우 짧고
강한 브로드밴드 임펄스"만 잡도록 튜닝돼 있어 일반 TTS 음성으로는 잘 안 걸린다.
TTS 출력(스피커)과 클랩 감지 입력(마이크)은 별도 장치이므로 WDM-KS 배타 모드 충돌도
없다 — 이 시점에 열려 있는 입력 스트림은 워처 스레드의 것 하나뿐(웨이크워드 스트림은
이미 닫혔고, `stt.listen()`은 아직 시작 전). 실사용 중 오탐/누락이 보이면 이후
5-B(파라미터 튜닝) 작업에서 다룬다 — 이번 설계 범위 밖.

## 테스트 방침

`tests/test_wakeword_activation.py`와 동일한 기법 사용 — `sd.InputStream`을 합성
프레임을 흘리는 페이크로 교체해 실 마이크 없이 배선만 검증.

- `wait_for_double_clap()`: ① 박수 2번에 해당하는 프레임 시퀀스를 흘리면 `True` 반환.
  ② 프레임 없이 `stop_event`를 먼저 set하면 프레임 대기 없이 짧게(폴링 간격 내) `False`
  반환 — 타임아웃 가드로 무한 대기 여부 검증.
- `_speak_with_clap_interrupt()`: `voice.tts.speak`/`voice.tts.stop`과
  `voice.clap_detector.wait_for_double_clap`을 모킹해 "`wait_for_double_clap`이 `True`를
  반환하면 `tts.stop()`이 호출된다"는 배선과 "`speak()`가 예외 없이 끝나면 `stop_event`가
  set되고 워처 스레드가 join된다"는 정리 로직만 검증(실제 오디오 재생 없이).

## 영향받는 파일 요약

| 파일 | 변경 내용 |
|------|-----------|
| `voice/tts.py` | `stop()` 신규 |
| `voice/clap_detector.py` | `wait_for_double_clap()` 신규 |
| `main.py` | `_speak_with_clap_interrupt()` 신규, `_run_voice_loop()`에서 `tts.speak()` 대신 사용 |
| `tests/test_tts_interrupt.py` | 신규 — 위 두 함수 배선 테스트 |
