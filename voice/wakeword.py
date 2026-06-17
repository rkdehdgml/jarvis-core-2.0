"""핫워드 감지 — openWakeWord로 "자비스" 호출을 상시 대기한다.

참고: 한국어 "자비스" 발음에 특화된 모델은 별도 데이터 수집/학습이
필요해 이번 구현 범위 밖이다. 대신 openWakeWord가 기본 제공하는
영어 사전학습 모델 "hey_jarvis"("Hey Jarvis")를 웨이크 프레이즈로 쓴다.
나중에 커스텀 한국어 모델을 학습하면 _WAKEWORD_NAME만 교체하면 된다.
"""
import logging
import queue

import numpy as np
import sounddevice as sd
from openwakeword.model import Model
from openwakeword.utils import download_models

from voice.stt import _get_input_device, _resample

logger = logging.getLogger(__name__)

_WAKEWORD_NAME = "hey_jarvis"
_SAMPLE_RATE = 16000
_FRAME_SAMPLES = 1280  # openWakeWord 권장 청크 크기 (80ms @ 16kHz)
_THRESHOLD = 0.5

_model: Model | None = None


def _get_model() -> Model:
    global _model
    if _model is None:
        logger.info("openWakeWord 모델 로딩 중...")
        download_models([_WAKEWORD_NAME])
        _model = Model(wakeword_models=[_WAKEWORD_NAME], inference_framework="onnx")
    return _model


def wait_for_wakeword() -> None:
    """웨이크워드가 감지될 때까지 블로킹한다. 감지되면 즉시 반환한다."""
    device = _get_input_device()
    if device is None:
        raise RuntimeError("사용 가능한 오디오 입력 장치가 없습니다.")

    model = _get_model()
    native_rate = sd.query_devices(device)["default_samplerate"]
    capture_blocksize = round(_FRAME_SAMPLES * native_rate / _SAMPLE_RATE)

    frame_queue: queue.Queue[np.ndarray] = queue.Queue()

    def _callback(indata, _frames, _time_info, _status) -> None:
        frame_queue.put(indata[:, 0].copy())

    with sd.InputStream(
        device=device,
        samplerate=native_rate,
        channels=1,
        dtype="float32",
        blocksize=capture_blocksize,
        callback=_callback,
    ):
        while True:
            raw_frame = frame_queue.get()
            frame = _resample(raw_frame, native_rate, _SAMPLE_RATE)
            pcm16 = np.clip(frame * 32767, -32768, 32767).astype(np.int16)

            prediction = model.predict(pcm16)
            if prediction.get(_WAKEWORD_NAME, 0.0) >= _THRESHOLD:
                model.reset()
                return
