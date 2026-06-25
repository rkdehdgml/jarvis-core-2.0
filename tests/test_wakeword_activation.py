"""wakeword.wait_for_activation()의 분기 배선(클랩 우선 검사 → 웨이크워드 추론) 검증.

실제 마이크/openWakeWord 모델 없이 sounddevice와 모델 로더를 스텁으로 바꿔,
"박수 2번이 먼저 오면 클랩으로, 아니면 웨이크워드 추론으로 넘어간다"는 배선만
검증한다. ClapDetector 자체의 판정 로직은 test_clap_detector.py에서 이미 검증했다.

실행: python -m tests.test_wakeword_activation (프로젝트 루트에서)
"""
import threading

import numpy as np

import voice.wakeword as wakeword

_SAMPLE_RATE = 16000
_FRAME_SAMPLES = 1280


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


class _NeverWakewordModel:
    """openWakeWord Model 대체. 항상 임계값 미달로 답해 웨이크워드가 안 잡히게 한다."""

    def predict(self, _pcm16):
        return {wakeword._WAKEWORD_NAME: 0.0}

    def reset(self) -> None:
        pass


class _AlwaysWakewordModel:
    """매 프레임 임계값을 넘긴다고 답하는 스텁(웨이크워드 경로 검증용)."""

    def predict(self, _pcm16):
        return {wakeword._WAKEWORD_NAME: 1.0}

    def reset(self) -> None:
        pass


def _silence(seconds: float) -> list[np.ndarray]:
    frame_count = max(1, round(seconds * _SAMPLE_RATE / _FRAME_SAMPLES))
    return [np.zeros(_FRAME_SAMPLES, dtype=np.float32) for _ in range(frame_count)]


def _spike(peak: float = 0.9) -> np.ndarray:
    frame = np.zeros(_FRAME_SAMPLES, dtype=np.float32)
    frame[_FRAME_SAMPLES // 2] = peak
    return frame


def _run_activation(frames: list[np.ndarray], model, timeout: float = 5.0) -> str:
    """frames를 모두 흘려보낸 뒤 wait_for_activation()의 결과를 반환한다.

    실제 함수는 frame_queue가 비면 block하므로, frames 구성이 잘못되면(클랩도
    웨이크워드도 안 잡히면) 영원히 멈출 수 있다 — 그 경우 곧바로 실패시키기
    위해 별도 스레드 + 타임아웃으로 감싼다.
    """
    original = {
        "_get_input_device": wakeword._get_input_device,
        "query_devices": wakeword.sd.query_devices,
        "InputStream": wakeword.sd.InputStream,
        "_get_model": wakeword._get_model,
    }
    wakeword._get_input_device = lambda: 0
    wakeword.sd.query_devices = lambda _device: {"default_samplerate": float(_SAMPLE_RATE)}
    wakeword.sd.InputStream = lambda **kwargs: _FakeStream(frames, **kwargs)
    wakeword._get_model = lambda: model

    result: dict = {}

    def _target() -> None:
        result["value"] = wakeword.wait_for_activation()

    thread = threading.Thread(target=_target, daemon=True)
    try:
        thread.start()
        thread.join(timeout)
    finally:
        wakeword._get_input_device = original["_get_input_device"]
        wakeword.sd.query_devices = original["query_devices"]
        wakeword.sd.InputStream = original["InputStream"]
        wakeword._get_model = original["_get_model"]

    if thread.is_alive():
        raise AssertionError("wait_for_activation()가 타임아웃 내에 반환하지 않음(행 의심)")
    return result["value"]


def test_double_clap_returns_clap_without_touching_model() -> None:
    frames = [*_silence(0.3), _spike(), *_silence(0.5), _spike(), *_silence(0.3)]
    trigger = _run_activation(frames, model=_NeverWakewordModel())
    assert trigger == "clap", "박수 2번이면 웨이크워드 모델과 무관하게 'clap'을 반환해야 함"


def test_wakeword_path_still_works_when_no_clap() -> None:
    frames = [*_silence(0.3)]
    trigger = _run_activation(frames, model=_AlwaysWakewordModel())
    assert trigger == "wakeword", "박수가 없으면 기존처럼 웨이크워드 추론 경로로 깨어나야 함"


def main() -> None:
    tests = [
        test_double_clap_returns_clap_without_touching_model,
        test_wakeword_path_still_works_when_no_clap,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print("\nwakeword.wait_for_activation 배선 검증 통과")


if __name__ == "__main__":
    main()
