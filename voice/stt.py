"""음성 인식(Speech-to-Text) — silero-vad로 발화 구간만 잘라 faster-whisper(base)로 변환한다."""
import logging
import queue

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from scipy.signal import resample
from silero_vad import VADIterator, load_silero_vad

logger = logging.getLogger(__name__)

_TARGET_SAMPLE_RATE = 16000  # silero-vad/whisper가 요구하는 샘플레이트
_VAD_FRAME_SAMPLES = 512  # silero-vad가 16kHz 기준으로 요구하는 청크 크기
_WAIT_TIMEOUT_SECONDS = 8  # 발화가 시작되길 기다리는 한도
_MAX_RECORD_SECONDS = 15  # 한 발화의 최대 녹음 길이(안전장치)

_whisper_model: WhisperModel | None = None
_vad_model = None
_input_device: int | None = -2  # -2 = 아직 탐색 안 함, None = 사용 가능한 장치 없음


def _get_whisper() -> WhisperModel:
    global _whisper_model
    if _whisper_model is None:
        logger.info("faster-whisper(base) 모델 로딩 중...")
        _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
    return _whisper_model


def _get_vad():
    global _vad_model
    if _vad_model is None:
        logger.info("silero-vad 모델 로딩 중...")
        _vad_model = load_silero_vad()
    return _vad_model


def _get_input_device() -> int | None:
    """입력 가능한 오디오 장치 중 마이크로 추정되는 장치를 찾는다.

    Windows에서 한국어 Realtek 드라이버는 장치 이름의 한글 부분이
    PortAudio를 거치며 깨지지만(예: "□□□ (Realtek HD Audio Mic input)"),
    영문 접미사는 보존되므로 "mic" 문자열로 식별한다. 시스템 기본
    입력 장치(-1)는 "스테레오 믹스" 등 마이크가 아닌 장치를 가리키는
    경우가 있어 신뢰하지 않는다.
    """
    global _input_device
    if _input_device != -2:
        return _input_device

    devices = sd.query_devices()
    candidates = [i for i, d in enumerate(devices) if d["max_input_channels"] > 0]
    mic = next((i for i in candidates if "mic" in devices[i]["name"].lower()), None)

    if mic is not None:
        _input_device = mic
    elif candidates:
        logger.warning("마이크로 추정되는 입력 장치를 찾지 못해 첫 입력 장치를 사용합니다.")
        _input_device = candidates[0]
    else:
        logger.error("사용 가능한 오디오 입력 장치가 없습니다.")
        _input_device = None

    return _input_device


def _resample(audio: np.ndarray, src_rate: float, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate:
        return audio
    target_len = max(1, round(len(audio) * dst_rate / src_rate))
    return resample(audio, target_len).astype(np.float32)


def listen() -> str:
    """마이크에서 한 번의 발화를 녹음해 한국어 텍스트로 변환한다.

    발화가 시작되기 전 _WAIT_TIMEOUT_SECONDS 동안 침묵만 이어지면 빈
    문자열을 반환한다(타임아웃). 발화가 시작되면 VAD가 무음 종료를
    판단할 때까지 녹음한 뒤 텍스트로 변환한다.

    WDM-KS 백엔드는 장치 고유 샘플레이트(보통 44.1kHz)만 허용하고
    blocking read도 지원하지 않으므로, 콜백 스트림으로 네이티브
    레이트에서 캡처한 뒤 silero-vad/whisper가 요구하는 16kHz로
    직접 리샘플링한다.
    """
    device = _get_input_device()
    if device is None:
        return ""

    native_rate = sd.query_devices(device)["default_samplerate"]
    capture_blocksize = round(_VAD_FRAME_SAMPLES * native_rate / _TARGET_SAMPLE_RATE)

    vad_iterator = VADIterator(
        _get_vad(), sampling_rate=_TARGET_SAMPLE_RATE, min_silence_duration_ms=600
    )

    raw_chunks: list[np.ndarray] = []
    speaking = False
    waited_frames = 0
    max_wait_frames = int(_WAIT_TIMEOUT_SECONDS * _TARGET_SAMPLE_RATE / _VAD_FRAME_SAMPLES)
    max_record_frames = int(_MAX_RECORD_SECONDS * _TARGET_SAMPLE_RATE / _VAD_FRAME_SAMPLES)

    frame_queue: queue.Queue[np.ndarray] = queue.Queue()

    def _callback(indata, _frames, _time_info, _status) -> None:
        frame_queue.put(indata[:, 0].copy())

    try:
        with sd.InputStream(
            device=device,
            samplerate=native_rate,
            channels=1,
            dtype="float32",
            blocksize=capture_blocksize,
            callback=_callback,
        ):
            for _ in range(max_record_frames + max_wait_frames):
                raw_frame = frame_queue.get(timeout=2.0)
                vad_frame = _resample(raw_frame, native_rate, _TARGET_SAMPLE_RATE)
                event = vad_iterator(vad_frame)

                if not speaking:
                    if event and "start" in event:
                        speaking = True
                        raw_chunks.append(raw_frame)
                    else:
                        waited_frames += 1
                        if waited_frames >= max_wait_frames:
                            return ""
                    continue

                raw_chunks.append(raw_frame)
                if (event and "end" in event) or len(raw_chunks) >= max_record_frames:
                    break
    except queue.Empty:
        logger.error("마이크 입력이 끊겼습니다.")
        return ""
    except Exception as e:
        logger.error(f"마이크 입력 오류: {e}")
        return ""
    finally:
        vad_iterator.reset_states()

    if not raw_chunks:
        return ""

    audio = _resample(np.concatenate(raw_chunks), native_rate, _TARGET_SAMPLE_RATE)
    segments, _info = _get_whisper().transcribe(audio, language="ko")
    return "".join(segment.text for segment in segments).strip()
