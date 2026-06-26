"""skill_pdf_reader 검증.

실행: python -m tests.test_skill_pdf_reader  (프로젝트 루트에서)

주의: edge-tts mp3 합성은 실제로 실행되므로 네트워크가 필요하다.
미디어 플레이어를 띄우는 재생 단계(run_command)만 mock으로 패치한다.
"""
import tempfile
from pathlib import Path
from unittest.mock import patch

from reportlab.pdfgen import canvas

from skills.skill_pdf_reader import PdfReaderSkill

_PDF_TEXT = "Hello Jarvis Test PDF 안녕하세요"


def _make_test_pdf(path: Path) -> None:
    c = canvas.Canvas(str(path))
    c.drawString(100, 750, _PDF_TEXT)
    c.save()


def test_can_handle() -> None:
    skill = PdfReaderSkill()
    assert skill.can_handle("", "보고서.pdf 읽어줘") >= 0.4
    assert skill.can_handle("", "오늘 날씨 어때") == 0.0
    print("[can_handle] 통과")


def test_execute_success() -> None:
    skill = PdfReaderSkill()
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "테스트문서.pdf"
        _make_test_pdf(pdf_path)

        text = f"{pdf_path} 읽어줘"
        with patch("skills.skill_pdf_reader.run_command") as mock_run:
            result = skill.execute(text, {})

        assert result.success, f"실패: {result.speech}"
        assert result.data["text_length"] > 0

        mp3 = Path(result.data["mp3_path"])
        assert mp3.is_file(), f"mp3 파일 없음: {mp3}"
        size = mp3.stat().st_size
        assert size > 0, "mp3 크기가 0"

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args.args[0] == "BROWSER_OPEN_URL"
        assert call_args.kwargs["url"] == str(mp3)

        print(f"[execute 성공] mp3={mp3} size={size}bytes text_length={result.data['text_length']}")


def test_execute_missing_file() -> None:
    skill = PdfReaderSkill()
    with patch("skills.skill_pdf_reader.run_command"):
        result = skill.execute("없는파일123.pdf 읽어줘", {})
    assert result.success is False
    print("[없는 파일] 통과:", result.speech)


def main() -> None:
    test_can_handle()
    test_execute_success()
    test_execute_missing_file()
    print("\nskill_pdf_reader 검증 통과")


if __name__ == "__main__":
    main()
