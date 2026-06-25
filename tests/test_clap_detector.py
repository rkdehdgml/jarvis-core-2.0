"""ClapDetector(박수 2번 검출) 검증: 실제 마이크 없이 합성 프레임으로 로직만 테스트한다.

실행: python -m tests.test_clap_detector (프로젝트 루트에서)
"""
import numpy as np

from voice.clap_detector import ClapDetector

_SAMPLE_RATE = 16000
_FRAME_SAMPLES = 1280  # 80ms @ 16kHz, wakeword.py와 동일한 청크 크기


def _silence(seconds: float) -> list[np.ndarray]:
    frame_count = max(1, round(seconds * _SAMPLE_RATE / _FRAME_SAMPLES))
    return [np.zeros(_FRAME_SAMPLES, dtype=np.float32) for _ in range(frame_count)]


def _spike(peak: float = 0.9) -> np.ndarray:
    frame = np.zeros(_FRAME_SAMPLES, dtype=np.float32)
    frame[_FRAME_SAMPLES // 2] = peak
    return frame


def _feed(detector: ClapDetector, frames: list[np.ndarray]) -> bool:
    """frames를 순서대로 흘려보내고, 그 중 하나라도 True를 반환하면 True."""
    return any(detector.process(frame, _SAMPLE_RATE) for frame in frames)


def test_two_claps_within_window_detected() -> None:
    detector = ClapDetector()
    frames = [*_silence(0.3), _spike(), *_silence(0.5), _spike(), *_silence(0.3)]
    assert _feed(detector, frames), "정상적인 박수 2번은 감지돼야 함"


def test_single_clap_not_detected() -> None:
    detector = ClapDetector()
    frames = [*_silence(0.3), _spike(), *_silence(2.0)]
    assert not _feed(detector, frames), "박수 1번만으로는 감지되면 안 됨"


def test_claps_too_far_apart_not_detected() -> None:
    detector = ClapDetector(max_gap_seconds=1.2)
    frames = [*_silence(0.3), _spike(), *_silence(2.0), _spike(), *_silence(0.3)]
    assert not _feed(detector, frames), "간격이 너무 길면 박수 2번으로 인정하면 안 됨"


def test_ringing_tail_does_not_count_as_second_clap() -> None:
    # 첫 박수 직후 잔향(refractory 이내의 추가 피크)은 두 번째 박수로 세면 안 되고,
    # 그 뒤에 진짜 두 번째 박수가 오면 정상적으로 감지돼야 한다.
    detector = ClapDetector(refractory_seconds=0.25)
    frames = [
        *_silence(0.3),
        _spike(),
        _spike(),  # 같은 박수의 잔향(80ms 뒤, refractory 이내)
        *_silence(0.5),
        _spike(),  # 진짜 두 번째 박수
        *_silence(0.3),
    ]
    assert _feed(detector, frames), "잔향을 걸러내고도 진짜 두 번째 박수는 감지돼야 함"


def test_quiet_speech_does_not_trigger() -> None:
    detector = ClapDetector()
    rng = np.random.default_rng(0)
    frames = [(rng.uniform(-0.1, 0.1, _FRAME_SAMPLES)).astype(np.float32) for _ in range(50)]
    assert not _feed(detector, frames), "조용한 잡음/말소리는 박수로 오인하면 안 됨"


def test_detector_resets_after_detection() -> None:
    detector = ClapDetector()
    frames = [*_silence(0.3), _spike(), *_silence(0.5), _spike(), *_silence(0.3)]
    assert _feed(detector, frames)
    # 감지 후에는 내부 상태가 리셋되어, 그 다음 박수 한 번만으로는 다시 감지되면 안 됨
    assert not detector.process(_spike(), _SAMPLE_RATE)


def main() -> None:
    tests = [
        test_two_claps_within_window_detected,
        test_single_clap_not_detected,
        test_claps_too_far_apart_not_detected,
        test_ringing_tail_does_not_count_as_second_clap,
        test_quiet_speech_does_not_trigger,
        test_detector_resets_after_detection,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print("\nClapDetector 검증 통과")


if __name__ == "__main__":
    main()
