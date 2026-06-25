"""박수 2번 감지 — 진폭 스파이크 2회를 짧은 시간 안에 포착하는 단순 임계값 검출기.

openWakeWord처럼 학습된 모델이 아니라 "클랩은 매우 짧고 강한 브로드밴드 임펄스"라는
특성만 이용한 휴리스틱이다. wakeword.wait_for_activation()이 웨이크워드와 OR 조건으로
같은 오디오 스트림에 흘려보내 쓰므로, 오탐/누락이 있어도 "자비스" 호출로 보완된다.
임계값(_PEAK_THRESHOLD 등)은 마이크/환경마다 다를 수 있는 휴리스틱이라 실제 사용
환경에서 오탐(시끄러운 환경)·누락(약한 박수)이 보이면 조정이 필요하다.
"""
import numpy as np

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
