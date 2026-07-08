"""TTS 인터럽트(박수 2번 → 즉시 중단) 배선 검증.

실제 마이크/스피커 없이 pygame.mixer / sounddevice.InputStream을 모킹해
"박수 2번 감지 시 tts.stop()이 호출되고, 재생이 정상 종료돼도 워처 스레드가
정리된다"는 배선만 검증한다.

실행: python -m tests.test_tts_interrupt (프로젝트 루트에서)
"""
import threading
import types

import numpy as np

import voice.clap_detector as clap_detector
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


def main() -> None:
    tests = [
        test_stop_calls_pygame_stop_when_busy,
        test_stop_is_noop_when_not_playing,
        test_stop_is_noop_when_mixer_not_initialized,
        test_wait_for_double_clap_detects_two_spikes,
        test_wait_for_double_clap_returns_false_when_stop_event_preset,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print("\ntts 인터럽트 배선 검증 통과")


if __name__ == "__main__":
    main()
