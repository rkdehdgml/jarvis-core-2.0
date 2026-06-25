"""활성화 트리거 감지 — openWakeWord로 "자비스" 호출 또는 박수 2번을 상시 대기한다.

참고: 한국어 "자비스" 발음에 특화된 모델은 별도 데이터 수집/학습이
필요해 이번 구현 범위 밖이다. 대신 openWakeWord가 기본 제공하는
영어 사전학습 모델 "hey_jarvis"("Hey Jarvis")를 웨이크 프레이즈로 쓴다.
나중에 커스텀 한국어 모델을 학습하면 _WAKEWORD_NAME만 교체하면 된다.

박수 2번은 ClapDetector(voice/clap_detector.py)가 같은 오디오 스트림에서
독립적으로 검사하며, 웨이크워드와 OR 조건으로 둘 중 먼저 감지되는 쪽이 이긴다.
"""
import logging
import queue

import numpy as np
import sounddevice as sd
from openwakeword.model import Model
from openwakeword.utils import download_models

from voice.clap_detector import ClapDetector
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


def wait_for_activation() -> str:
    """웨이크워드("자비스") 또는 박수 2번 중 먼저 감지되는 쪽을 기다려 블로킹한다.

    Returns:
        "wakeword" 또는 "clap" — 어느 트리거로 깨어났는지.
    """
    device = _get_input_device()
    if device is None:
        raise RuntimeError("사용 가능한 오디오 입력 장치가 없습니다.")

    model = _get_model()
    clap = ClapDetector()
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

            # 클랩 검출은 원본(리샘플 전) 프레임의 피크 진폭만 보면 되므로
            # 웨이크워드 추론보다 먼저, 더 가볍게 검사한다.
            if clap.process(raw_frame, native_rate):
                return "clap"

            frame = _resample(raw_frame, native_rate, _SAMPLE_RATE)
            pcm16 = np.clip(frame * 32767, -32768, 32767).astype(np.int16)

            prediction = model.predict(pcm16)
            if prediction.get(_WAKEWORD_NAME, 0.0) >= _THRESHOLD:
                model.reset()
                return "wakeword"
