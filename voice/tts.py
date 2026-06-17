"""음성 합성(Text-to-Speech) — edge-tts로 합성하고 pygame으로 재생한다."""
import asyncio
import logging
import tempfile
from pathlib import Path

import edge_tts
import pygame

logger = logging.getLogger(__name__)

_VOICE = "ko-KR-SunHiNeural"


def speak(text: str) -> None:
    """텍스트를 한국어 음성으로 합성해 재생한다.

    합성/재생 실패는 사용자 경험을 끊지 않기 위해 예외를 던지지 않고
    로그만 남긴다(메인 루프는 텍스트 자체로도 결과를 표시하므로 안전).
    """
    if not text:
        return
    try:
        asyncio.run(_speak_async(text))
    except Exception as e:
        logger.error(f"TTS 재생 오류: {e}")


async def _speak_async(text: str) -> None:
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        path = Path(f.name)

    try:
        communicate = edge_tts.Communicate(text, _VOICE)
        await communicate.save(str(path))
        _play(path)
    finally:
        path.unlink(missing_ok=True)


def _play(path: Path) -> None:
    if not pygame.mixer.get_init():
        pygame.mixer.init()

    pygame.mixer.music.load(str(path))
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        pygame.time.wait(50)
    pygame.mixer.music.unload()
