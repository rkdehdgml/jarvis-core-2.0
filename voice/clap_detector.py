"""박수 2번 감지 — 진폭 스파이크 2회를 짧은 시간 안에 포착하는 단순 임계값 검출기.

openWakeWord처럼 학습된 모델이 아니라 "클랩은 매우 짧고 강한 브로드밴드 임펄스"라는
특성만 이용한 휴리스틱이다. wakeword.wait_for_activation()이 웨이크워드와 OR 조건으로
같은 오디오 스트림에 흘려보내 쓰므로, 오탐/누락이 있어도 "자비스" 호출로 보완된다.
임계값(_PEAK_THRESHOLD 등)은 마이크/환경마다 다를 수 있는 휴리스틱이라 실제 사용
환경에서 오탐(시끄러운 환경)·누락(약한 박수)이 보이면 조정이 필요하다.
"""
import queue
import threading

import numpy as np
import sounddevice as sd

from voice.stt import _get_input_device

_PEAK_THRESHOLD = 0.35  # 클랩 한 번으로 보는 피크 진폭(절댓값, float32 -1~1 기준)
_REFRACTORY_SECONDS = 0.25  # 같은 클랩의 잔향을 다음 클랩으로 잘못 세지 않기 위한 최소 간격
_MAX_GAP_SECONDS = 1.2  # 두 클랩이 "박수 2번"으로 인정되는 최대 간격


class ClapDetector:
    """오디오 프레임을 순서대로 process()에 넣으면 박수 2번을 감지한다.

    내부적으로 경과 시간을 프레임 길이로 누적하므로, 실시간 오디오 콜백뿐 아니라
    합성된 프레임 시퀀스로도 동일하게 동작한다(테스트 용이).
    """

    def __init__(
        self,
        peak_threshold: float = _PEAK_THRESHOLD,
        refractory_seconds: float = _REFRACTORY_SECONDS,
        max_gap_seconds: float = _MAX_GAP_SECONDS,
    ) -> None:
        self._peak_threshold = peak_threshold
        self._refractory_seconds = refractory_seconds
        self._max_gap_seconds = max_gap_seconds
        self._elapsed_seconds = 0.0
        self._last_onset: float | None = None
        self._first_onset: float | None = None

    def reset(self) -> None:
        """대기 중인 "첫 박수" 상태를 지운다."""
        self._first_onset = None
        self._last_onset = None

    def process(self, frame: np.ndarray, sample_rate: float) -> bool:
        """frame을 처리한다. 이 frame으로 박수 2번이 막 완성됐으면 True를 반환한다."""
        now = self._elapsed_seconds
        self._elapsed_seconds += len(frame) / sample_rate

        if len(frame) == 0:
            return False

        peak = float(np.max(np.abs(frame)))
        is_onset = peak >= self._peak_threshold and (
            self._last_onset is None or now - self._last_onset >= self._refractory_seconds
        )
        if not is_onset:
            return False

        self._last_onset = now

        if self._first_onset is None:
            self._first_onset = now
            return False

        gap = now - self._first_onset
        if gap <= self._max_gap_seconds:
            self.reset()
            return True

        # 첫 박수가 너무 오래 전이면, 이번 온셋을 새 첫 박수로 다시 잡는다.
        self._first_onset = now
        return False


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
