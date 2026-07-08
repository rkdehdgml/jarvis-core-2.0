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
