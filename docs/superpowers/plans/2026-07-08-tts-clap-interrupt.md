# 4-A TTS 인터럽트(박수 2번 중단) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 음성 모드에서 자비스가 TTS로 응답을 읽는 동안 박수 2번을 감지하면 즉시 재생을 중단하고, 별도 재웨이크워드 없이 바로 다음 명령을 듣게 한다.

**Architecture:** `voice/tts.py`에 스레드 세이프한 `stop()`을 추가하고, `voice/clap_detector.py`에 자체 마이크 스트림으로 박수 2번만 감지하는 블로킹 함수 `wait_for_double_clap(stop_event)`를 추가한다. `main.py`가 이 둘을 워커 스레드로 묶어 `tts.speak()`와 병렬로 돌리는 `_speak_with_clap_interrupt()`를 두고, `_run_voice_loop()`의 기존 `tts.speak()` 호출 한 곳만 교체한다. 기존 `while` 루프 구조가 이미 "응답 후 바로 다음 명령 대기"이므로 인터럽트 후 상태 처리를 위한 추가 분기는 필요 없다.

**Tech Stack:** Python 3.10+, `pygame`(이미 의존성), `sounddevice`(이미 의존성), `threading`/`queue`(표준 라이브러리). 테스트는 `pytest` 없이 `tests/`의 assert 기반 스크립트 컨벤션(`python -m tests.<module>`)을 따르고, `tests/test_wakeword_activation.py`의 페이크 스트림/모킹 패턴을 재사용한다.

## Global Constraints

- `voice/tts.py`의 기존 `speak()`/`_play()`는 수정하지 않는다 — `stop()`만 추가.
- `voice/wakeword.py`는 리팩토링하지 않는다 — 웨이크워드+클랩을 한 스트림에서 함께 보는 기존 구조를 그대로 둔다.
- `_run_text_loop()`(`--text` 모드)는 TTS를 쓰지 않으므로 변경하지 않는다.
- 실제 오디오 하드웨어 없이 테스트 가능해야 한다 — `sd.InputStream`/`pygame.mixer`를 모킹한다.
- 인터럽트 후 별도 상태 머신 분기를 만들지 않는다 (스펙 결정 사항).
- `voice.clap_detector`는 `voice.stt`(무거운 `faster_whisper`/`silero_vad` 스택)를
  import하므로, `main.py`에서 `voice.tts`/`voice.clap_detector`를 참조하는 코드는
  기존 `_run_voice_loop()`와 동일하게 함수 본문 안에서 지연 import한다 — 모듈
  최상단 import 금지.

---

### Task 1: `voice/tts.py` — `stop()`

**Files:**
- Modify: `voice/tts.py`
- Test: `tests/test_tts_interrupt.py` (신규 — Task 2/3도 이 파일에 이어서 씀)

**Interfaces:**
- Produces: `voice.tts.stop() -> None`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_tts_interrupt.py`를 새로 만들고 `stop()` 테스트부터 작성한다 (아직
`voice.tts.stop`이 없어 `AttributeError`로 실패해야 정상):

```python
"""TTS 인터럽트(박수 2번 → 즉시 중단) 배선 검증.

실제 마이크/스피커 없이 pygame.mixer / sounddevice.InputStream을 모킹해
"박수 2번 감지 시 tts.stop()이 호출되고, 재생이 정상 종료돼도 워처 스레드가
정리된다"는 배선만 검증한다.

실행: python -m tests.test_tts_interrupt (프로젝트 루트에서)
"""
import threading
import types

import numpy as np

import voice.tts as tts


class _FakeMusic:
    def __init__(self, busy: bool) -> None:
        self._busy = busy
        self.stop_calls = 0

    def get_busy(self) -> bool:
        return self._busy

    def stop(self) -> None:
        self.stop_calls += 1
        self._busy = False


def test_stop_calls_pygame_stop_when_busy() -> None:
    fake_music = _FakeMusic(busy=True)
    fake_mixer = types.SimpleNamespace(get_init=lambda: True, music=fake_music)
    original_mixer = tts.pygame.mixer
    tts.pygame.mixer = fake_mixer
    try:
        tts.stop()
    finally:
        tts.pygame.mixer = original_mixer
    assert fake_music.stop_calls == 1, "재생 중이면 pygame.mixer.music.stop()을 호출해야 함"


def test_stop_is_noop_when_not_playing() -> None:
    fake_music = _FakeMusic(busy=False)
    fake_mixer = types.SimpleNamespace(get_init=lambda: True, music=fake_music)
    original_mixer = tts.pygame.mixer
    tts.pygame.mixer = fake_mixer
    try:
        tts.stop()
    finally:
        tts.pygame.mixer = original_mixer
    assert fake_music.stop_calls == 0, "재생 중이 아니면 stop()을 호출하지 않아야 함"


def test_stop_is_noop_when_mixer_not_initialized() -> None:
    fake_mixer = types.SimpleNamespace(get_init=lambda: False, music=_FakeMusic(busy=True))
    original_mixer = tts.pygame.mixer
    tts.pygame.mixer = fake_mixer
    try:
        tts.stop()  # 예외 없이 조용히 반환돼야 함
    finally:
        tts.pygame.mixer = original_mixer


def main() -> None:
    tests = [
        test_stop_calls_pygame_stop_when_busy,
        test_stop_is_noop_when_not_playing,
        test_stop_is_noop_when_mixer_not_initialized,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print("\ntts 인터럽트 배선 검증 통과")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m tests.test_tts_interrupt`
Expected: `AttributeError: module 'voice.tts' has no attribute 'stop'`

- [ ] **Step 3: `stop()` 구현**

`voice/tts.py`의 `speak()` 함수 바로 다음에 추가:

```python
def stop() -> None:
    """재생 중인 TTS를 즉시 중단한다.

    다른 스레드(클랩 감지 워처)에서 호출되는 것을 전제로 한다 — pygame.mixer.music의
    재생 제어 함수는 스레드 세이프하다. speak()의 재생 루프(_play())는 이 호출 이후
    다음 폴링에서 get_busy()가 False가 된 것을 보고 자연스럽게 빠져나온다.
    """
    try:
        if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
            pygame.mixer.music.stop()
    except Exception:
        pass
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m tests.test_tts_interrupt`
Expected: 3개 테스트 모두 `[OK]`, 마지막 줄 `tts 인터럽트 배선 검증 통과`

- [ ] **Step 5: 커밋**

```bash
git add voice/tts.py tests/test_tts_interrupt.py
git commit -m "feat: voice.tts.stop() 추가 - TTS 재생 즉시 중단"
```

---

### Task 2: `voice/clap_detector.py` — `wait_for_double_clap()`

**Files:**
- Modify: `voice/clap_detector.py`
- Test: `tests/test_tts_interrupt.py` (Task 1 파일에 이어서 추가)

**Interfaces:**
- Consumes: `voice.clap_detector.ClapDetector` (기존, 변경 없음)
- Produces: `voice.clap_detector.wait_for_double_clap(stop_event: threading.Event) -> bool`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_tts_interrupt.py`에 아래 클래스/테스트를 추가한다
(`tests/test_wakeword_activation.py`의 `_FakeStream` 패턴을 그대로 재사용):

```python
import queue as _queue  # 파일 상단 import 블록에 추가

import voice.clap_detector as clap_detector


class _FakeStream:
    """sd.InputStream 대체. with 블록에 들어가는 즉시 합성 프레임을 콜백에 흘려보낸다."""

    def __init__(self, frames, **kwargs):
        self._frames = frames
        self._callback = kwargs["callback"]

    def __enter__(self):
        for frame in self._frames:
            self._callback(frame.reshape(-1, 1), len(frame), None, None)
        return self

    def __exit__(self, *exc_info) -> bool:
        return False


_SAMPLE_RATE = 16000
_FRAME_SAMPLES = 1280


def _silence(seconds: float):
    frame_count = max(1, round(seconds * _SAMPLE_RATE / _FRAME_SAMPLES))
    return [np.zeros(_FRAME_SAMPLES, dtype=np.float32) for _ in range(frame_count)]


def _spike(peak: float = 0.9):
    frame = np.zeros(_FRAME_SAMPLES, dtype=np.float32)
    frame[_FRAME_SAMPLES // 2] = peak
    return frame


def _run_wait_for_double_clap(frames, stop_event, timeout: float = 5.0) -> bool:
    """frames를 모두 흘려보낸 뒤 wait_for_double_clap()의 결과를 반환한다.

    프레임이 다 소진되고 clap도 stop_event도 안 걸리면 실제 함수는 계속
    폴링하며 대기하므로, 무한 대기를 곧바로 실패시키기 위해 별도 스레드 +
    타임아웃으로 감싼다.
    """
    original = {
        "_get_input_device": clap_detector._get_input_device,
        "query_devices": clap_detector.sd.query_devices,
        "InputStream": clap_detector.sd.InputStream,
    }
    clap_detector._get_input_device = lambda: 0
    clap_detector.sd.query_devices = lambda _device: {"default_samplerate": float(_SAMPLE_RATE)}
    clap_detector.sd.InputStream = lambda **kwargs: _FakeStream(frames, **kwargs)

    result: dict = {}

    def _target() -> None:
        result["value"] = clap_detector.wait_for_double_clap(stop_event)

    thread = threading.Thread(target=_target, daemon=True)
    try:
        thread.start()
        thread.join(timeout)
    finally:
        clap_detector._get_input_device = original["_get_input_device"]
        clap_detector.sd.query_devices = original["query_devices"]
        clap_detector.sd.InputStream = original["InputStream"]

    if thread.is_alive():
        stop_event.set()
        thread.join(1.0)
        raise AssertionError("wait_for_double_clap()가 타임아웃 내에 반환하지 않음(행 의심)")
    return result["value"]


def test_wait_for_double_clap_detects_two_spikes() -> None:
    frames = [*_silence(0.3), _spike(), *_silence(0.5), _spike(), *_silence(0.3)]
    stop_event = threading.Event()
    detected = _run_wait_for_double_clap(frames, stop_event)
    assert detected is True, "박수 2번 프레임이면 True를 반환해야 함"


def test_wait_for_double_clap_returns_false_when_stop_event_preset() -> None:
    stop_event = threading.Event()
    stop_event.set()
    detected = _run_wait_for_double_clap([*_silence(0.1)], stop_event)
    assert detected is False, "stop_event가 이미 set이면 프레임과 무관하게 False를 반환해야 함"
```

`main()`의 `tests` 리스트에 두 테스트를 추가하고, 파일 상단 import에 `threading`,
`numpy as np`를 추가한다(Task 1에서 아직 없다면).

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m tests.test_tts_interrupt`
Expected: `AttributeError: module 'voice.clap_detector' has no attribute 'wait_for_double_clap'`
(또는 `_get_input_device`가 없다는 에러 — 아직 `clap_detector.py`가 `voice.stt`를 import하지 않으므로)

- [ ] **Step 3: `wait_for_double_clap()` 구현**

`voice/clap_detector.py` 상단 import에 추가:

```python
import queue
import threading

import numpy as np
import sounddevice as sd

from voice.stt import _get_input_device
```

파일 끝(`ClapDetector` 클래스 다음)에 추가:

```python
def wait_for_double_clap(stop_event: threading.Event) -> bool:
    """마이크에서 박수 2번이 감지될 때까지 블로킹한다.

    wakeword.wait_for_activation()과 달리 웨이크워드 모델 추론이 없어
    리샘플링이 필요 없다 — 네이티브 샘플레이트 프레임을 그대로 ClapDetector에
    넘긴다. stop_event가 set되면(TTS가 정상 종료돼 더 들을 필요가 없어지면)
    프레임을 더 기다리지 않고 즉시 False를 반환한다.

    Returns:
        박수 2번이 감지돼 반환하면 True, stop_event로 인해 중단되면 False.
    """
    device = _get_input_device()
    if device is None:
        return False

    detector = ClapDetector()
    native_rate = sd.query_devices(device)["default_samplerate"]
    blocksize = round(0.08 * native_rate)  # 80ms 상당의 네이티브 레이트 프레임

    frame_queue: queue.Queue[np.ndarray] = queue.Queue()

    def _callback(indata, _frames, _time_info, _status) -> None:
        frame_queue.put(indata[:, 0].copy())

    with sd.InputStream(
        device=device,
        samplerate=native_rate,
        channels=1,
        dtype="float32",
        blocksize=blocksize,
        callback=_callback,
    ):
        while not stop_event.is_set():
            try:
                frame = frame_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if detector.process(frame, native_rate):
                return True

    return False
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m tests.test_tts_interrupt`
Expected: 5개 테스트 모두 `[OK]`

- [ ] **Step 5: 커밋**

```bash
git add voice/clap_detector.py tests/test_tts_interrupt.py
git commit -m "feat: clap_detector.wait_for_double_clap() 추가 - TTS 중 박수 감지"
```

---

### Task 3: `main.py` — `_speak_with_clap_interrupt()` 배선

**Files:**
- Modify: `main.py`
- Test: `tests/test_tts_interrupt.py` (Task 1/2 파일에 이어서 추가)

**Interfaces:**
- Consumes: `voice.tts.speak(text: str) -> None`, `voice.tts.stop() -> None`,
  `voice.clap_detector.wait_for_double_clap(stop_event: threading.Event) -> bool`
  (Task 1, 2에서 생산)
- Produces: `main._speak_with_clap_interrupt(text: str) -> None`

**중요 — 지연 import 유지**: `voice/clap_detector.py`는 (Task 2에서) `voice.stt`를
import한다. `voice/stt.py`는 `faster_whisper`/`silero_vad` 등 무거운 패키지를 모듈
최상단에서 import한다 — 이것이 정확히 `main.py`가 `from voice import stt, tts,
wakeword`를 `_run_voice_loop()` 함수 **안에서** 지연 import하는 이유다(파일 docstring:
"모델 로딩이 무거워 음성 모드를 실제로 쓸 때만 import한다"). 따라서
`voice.clap_detector`(→ `voice.stt`)를 `main.py` **모듈 최상단**에서 import하면
`--text` 모드를 포함한 모든 실행에서 매번 무거운 STT 스택을 로딩하게 돼 기존
지연 로딩 설계를 깨뜨린다. `_speak_with_clap_interrupt()`도 `_run_voice_loop()`와
같은 방식으로, 함수 본문 안에서 지연 import해야 한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_tts_interrupt.py`에 추가 (파일 상단 import에 `import main`,
`import voice.tts as tts_module`, `import voice.clap_detector as clap_detector_module`
추가 — `main.py`가 지연 import를 쓰므로 `main` 모듈 자체엔 `tts`/`wait_for_double_clap`
속성이 없고, 실제 함수가 참조하는 원본 모듈(`voice.tts`, `voice.clap_detector`)의
속성을 직접 몽키패치해야 지연 import로 가져간 이름도 패치된 버전을 보게 된다):

```python
import main as jarvis_main
import voice.clap_detector as clap_detector_module
import voice.tts as tts_module


def test_speak_with_clap_interrupt_stops_tts_on_clap() -> None:
    """wait_for_double_clap이 True를 반환하면 tts.stop()이 호출돼야 한다."""
    calls = []
    original_speak = tts_module.speak
    original_stop = tts_module.stop
    original_wait = clap_detector_module.wait_for_double_clap

    def fake_speak(text: str) -> None:
        calls.append(("speak", text))

    def fake_stop() -> None:
        calls.append(("stop",))

    def fake_wait(stop_event: threading.Event) -> bool:
        return True  # 즉시 "박수 감지됨"으로 응답

    tts_module.speak = fake_speak
    tts_module.stop = fake_stop
    clap_detector_module.wait_for_double_clap = fake_wait
    try:
        jarvis_main._speak_with_clap_interrupt("테스트 문장")
    finally:
        tts_module.speak = original_speak
        tts_module.stop = original_stop
        clap_detector_module.wait_for_double_clap = original_wait

    assert ("speak", "테스트 문장") in calls, "speak()가 호출돼야 함"
    assert ("stop",) in calls, "wait_for_double_clap이 True면 stop()이 호출돼야 함"


def test_speak_with_clap_interrupt_joins_watcher_thread() -> None:
    """speak()가 정상 종료되면 워처 스레드가 join되어(살아있지 않아야) 한다."""
    original_speak = tts_module.speak
    original_wait = clap_detector_module.wait_for_double_clap

    def fake_speak(_text: str) -> None:
        pass

    def fake_wait(stop_event: threading.Event) -> bool:
        stop_event.wait(2.0)  # 메인이 stop_event.set()할 때까지 대기하는 실제 워처처럼 동작
        return False

    tts_module.speak = fake_speak
    clap_detector_module.wait_for_double_clap = fake_wait
    try:
        jarvis_main._speak_with_clap_interrupt("다른 문장")
    finally:
        tts_module.speak = original_speak
        clap_detector_module.wait_for_double_clap = original_wait

    active_names = [t.name for t in threading.enumerate()]
    assert "_speak_with_clap_interrupt-watcher" not in active_names, (
        "speak() 종료 후 워처 스레드가 정리되지 않고 남아있음"
    )
```

`main()`의 `tests` 리스트에 두 테스트를 추가한다.

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m tests.test_tts_interrupt`
Expected: `AttributeError: module 'main' has no attribute '_speak_with_clap_interrupt'`

- [ ] **Step 3: `_speak_with_clap_interrupt()` 구현**

`main.py`에 top-level import는 추가하지 않는다. `_run_voice_loop()` 함수 바로 앞에
추가 (내부에서 `voice.tts`/`voice.clap_detector`를 `_run_voice_loop()`와 동일하게
지연 import):

```python
def _speak_with_clap_interrupt(text: str) -> None:
    """TTS 재생 중 박수 2번을 감지하면 즉시 중단한다.

    speak()가 정상 종료하든 중단되든, finally에서 stop_event를 set하고
    워처 스레드를 join해 마이크 스트림을 반드시 정리한다 — 다음 stt.listen()이
    새 입력 스트림을 열기 전에 겹치지 않도록 하기 위함.

    voice.tts/voice.clap_detector는 voice.stt(무거운 STT 스택)를 끌어오므로
    _run_voice_loop()와 마찬가지로 여기서 지연 import한다.
    """
    from voice import tts
    from voice.clap_detector import wait_for_double_clap

    stop_event = threading.Event()

    def _watch() -> None:
        if wait_for_double_clap(stop_event):
            tts.stop()

    watcher = threading.Thread(
        target=_watch, name="_speak_with_clap_interrupt-watcher", daemon=True
    )
    watcher.start()
    try:
        tts.speak(text)
    finally:
        stop_event.set()
        watcher.join()
```

`_run_voice_loop()` 안의 `tts.speak(result.speech)` 호출(현재 main.py:155)을
`_speak_with_clap_interrupt(result.speech)`로 교체한다. 이 함수 안의 다른
`tts.speak(...)` 호출(비활성화/종료/기록삭제 안내 등, 짧은 고정 문구들)은 그대로
`tts.speak(...)`를 유지한다 — 인터럽트 대상은 스킬 응답을 읽는 긴 발화만이다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m tests.test_tts_interrupt`
Expected: 7개 테스트 모두 `[OK]`, 마지막 줄 `tts 인터럽트 배선 검증 통과`

- [ ] **Step 5: 회귀 확인**

Run: `python -m tests.test_wakeword_activation` (기존 클랩/웨이크워드 배선에
영향 없는지 확인 — `wakeword.py`를 건드리지 않았으므로 그대로 통과해야 함)
Expected: 기존과 동일하게 통과

- [ ] **Step 6: 커밋**

```bash
git add main.py tests/test_tts_interrupt.py
git commit -m "feat: 음성 루프에 TTS 인터럽트(박수 2번 중단) 연결 (4-A)"
```

---

## 수동 검증 (실 하드웨어)

자동 테스트는 전부 모킹 기반이라 실제 마이크/스피커 동작은 별도로 확인이 필요하다
(5-B 파라미터 튜닝과 같은 결이므로 이 계획의 정식 Task로는 넣지 않고, 완료 후
수동으로 1회 확인):

1. `python main.py` (음성 모드)로 기동, "자비스"로 깨운 뒤 긴 응답이 나올 만한
   질문(예: "오늘 날씨 자세히 알려줘")을 던진다.
2. TTS가 읽는 도중 박수를 빠르게 두 번 친다 — 즉시 재생이 멎고, 곧바로 다음
   질문을 (재웨이크워드 없이) 받아들이는지 확인한다.
3. 박수를 치지 않은 경우 기존처럼 끝까지 읽고 다음 명령을 받는지(회귀 없는지)
   확인한다.

## 영향받는 파일 요약

| 파일 | 변경 내용 |
|------|-----------|
| `voice/tts.py` | `stop()` 신규 (Task 1) |
| `voice/clap_detector.py` | `wait_for_double_clap()` 신규 (Task 2) |
| `main.py` | `_speak_with_clap_interrupt()` 신규 + `_run_voice_loop()` 배선 (Task 3) |
| `tests/test_tts_interrupt.py` | 신규 — Task 1/2/3 배선 테스트 전체 |
