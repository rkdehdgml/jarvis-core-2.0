"""skills/skill_pdf_reader.py — PDF 텍스트를 추출해 음성(mp3)으로 읽어주는 스킬.

설계 의도: 보통 스킬은 SkillResult.speech에 텍스트만 담고 호출자(main.py 음성 루프)가
TTS로 읽어준다. 하지만 PDF 전체처럼 긴 텍스트를 통째로 읽어주려면 일반 파이프라인이
부적합하므로, 이 스킬이 직접 edge-tts로 mp3를 합성해 별도 파일로 저장하고 그 mp3를
기본 미디어 플레이어로 "열어서"(explorer.exe) 재생시킨다. speech에는 짧은 확인 문구만 담는다.

레이어 분리 원칙상 voice/를 import하지 않고 edge_tts를 직접 사용한다.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path

import edge_tts

from commands.windows_bridge import run_command
from core.skill_base import Skill, SkillResult

logger = logging.getLogger(__name__)

_VOICE = "ko-KR-SunHiNeural"
_MAX_TEXT_LEN = 2000
_PDF_PATTERN = re.compile(r"\S+\.pdf", re.IGNORECASE)
_TRIGGERS = ["PDF 읽어줘", "피디에프 읽어줘", "PDF 읽어"]
_DRIVE_LETTER = re.compile(r"^[a-zA-Z]:[\\/]")


class PdfReaderSkill(Skill):
    """PDF 파일의 텍스트를 추출해서 음성으로 읽어준다."""

    name = "pdf_reader"
    description = "PDF 파일의 텍스트를 추출해서 음성으로 읽어준다"
    triggers = _TRIGGERS
    examples = [
        "보고서.pdf 읽어줘",
        "다운로드 폴더에 있는 계약서.pdf 읽어줘",
        "PDF 읽어줘 C:\\Users\\me\\Desktop\\문서.pdf",
    ]

    def can_handle(self, intent: str, text: str) -> float:
        lowered = text.lower()
        if any(t.lower() in lowered for t in _TRIGGERS):
            return 0.85
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        match = _PDF_PATTERN.search(text)
        if match is None:
            return SkillResult(speech="읽을 PDF 파일명을 말씀해주세요.", success=False)

        raw = match.group(0)
        pdf_path = self._resolve_path(raw)
        if pdf_path is None:
            return SkillResult(speech=f"'{raw}' 파일을 찾을 수 없습니다.", success=False)

        extracted = self._extract_text(pdf_path)
        if extracted is None:
            return SkillResult(speech="PDF를 읽는 중 오류가 발생했습니다.", success=False)
        if not extracted.strip():
            return SkillResult(speech="이 PDF에서 텍스트를 추출할 수 없습니다.", success=False)

        speak_text = extracted[:_MAX_TEXT_LEN]

        mp3_path = self._synthesize(speak_text)
        if mp3_path is None:
            return SkillResult(speech="음성 합성 중 오류가 발생했습니다.", success=False)

        run_command("BROWSER_OPEN_URL", url=str(mp3_path))

        return SkillResult(
            speech="PDF 내용을 읽어드리겠습니다.",
            success=True,
            data={
                "pdf_path": str(pdf_path),
                "mp3_path": str(mp3_path),
                "text_length": len(speak_text),
            },
        )

    def _resolve_path(self, raw: str) -> Path | None:
        """추출된 PDF 문자열을 실제 파일 경로로 해석한다(없으면 None)."""
        if _DRIVE_LETTER.match(raw):
            p = Path(raw)
            return p if p.is_file() else None

        filename = Path(raw).name
        root = Path(__file__).parent.parent
        candidates = [
            Path.home() / "Downloads" / filename,
            root / filename,
            root / "data" / filename,
        ]
        for c in candidates:
            if c.is_file():
                return c
        return None

    def _extract_text(self, pdf_path: Path) -> str | None:
        """pypdf로 텍스트를 추출한다. 파싱 실패 시 None을 반환(예외를 던지지 않음)."""
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(pdf_path))
            parts = [page.extract_text() or "" for page in reader.pages]
            return "\n".join(parts)
        except Exception:
            logger.exception("PDF 텍스트 추출 실패: %s", pdf_path)
            return None

    def _synthesize(self, text: str) -> Path | None:
        """edge-tts로 mp3를 합성해 data/pdf_audio/ 아래에 저장한다(실패 시 None)."""
        out_dir = Path(__file__).parent.parent / "data" / "pdf_audio"
        out_dir.mkdir(parents=True, exist_ok=True)
        mp3_path = out_dir / f"pdf_{int(time.time())}.mp3"

        try:
            asyncio.run(self._save_async(text, mp3_path))
        except Exception:
            logger.exception("edge-tts 합성 실패")
            return None

        if not mp3_path.is_file() or mp3_path.stat().st_size == 0:
            return None
        return mp3_path

    async def _save_async(self, text: str, mp3_path: Path) -> None:
        communicate = edge_tts.Communicate(text, _VOICE)
        await communicate.save(str(mp3_path))
