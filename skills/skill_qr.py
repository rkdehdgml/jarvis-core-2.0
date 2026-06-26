import re
from datetime import datetime
from pathlib import Path

from core.skill_base import Skill, SkillResult

_QR_DIR = Path(__file__).parent.parent / "data" / "qr"

_TRIGGERS = ["QR코드", "qr코드", "큐알코드", "큐알", "QR"]

# payload에서 걷어낼 동사/조사/지시어. 트리거(_TRIGGERS)도 함께 제거된다.
_FILLER_WORDS = [
    "만들어줘",
    "만들어",
    "생성해줘",
    "생성해",
    "생성",
    "코드로",
    "로 만들어줘",
    "이 주소를",
    "이 주소",
    "주소를",
    "자비스야",
    "자비스",
]

_PUNCTUATION = re.compile(r"[?!,~]")


class QrSkill(Skill):
    """텍스트나 URL을 QR 코드 PNG 이미지로 생성해 로컬에 저장한다."""

    name = "qr"
    description = "텍스트나 URL을 QR 코드 이미지로 생성한다"
    triggers = ["QR", "큐알", "큐알코드", "qr코드", "QR코드"]
    examples = [
        "이 주소를 QR코드로 만들어줘 https://example.com",
        "큐알코드 생성해줘",
        "QR 만들어줘 자비스 공식 홈페이지",
    ]

    def can_handle(self, intent: str, text: str) -> float:
        upper = text.upper()
        if any(t.upper() in upper for t in self.triggers):
            return 0.85
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        payload = self._extract_payload(text)
        if not payload:
            return SkillResult(
                speech="QR 코드로 만들 내용을 함께 말씀해주세요.",
                success=False,
            )

        try:
            import qrcode
        except ImportError:
            return SkillResult(
                speech="QR 코드 기능을 사용할 수 없습니다 (qrcode 미설치).",
                success=False,
            )

        _QR_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"qr_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        path = _QR_DIR / filename

        img = qrcode.make(payload)
        img.save(path)

        return SkillResult(
            speech=f"QR 코드를 생성했습니다. 저장 위치: {path}",
            success=True,
            data={"path": str(path), "payload": payload},
        )

    def _extract_payload(self, text: str) -> str:
        """발화에서 트리거·동사·조사를 걷어내고 인코딩할 내용만 남긴다.

        URL은 보존해야 하므로 마침표(.)는 구두점 제거 대상에서 제외한다.
        """
        query = text
        for word in _TRIGGERS:
            query = re.sub(re.escape(word), "", query, flags=re.IGNORECASE)
        for word in _FILLER_WORDS:
            query = query.replace(word, "")
        query = _PUNCTUATION.sub("", query)
        return " ".join(query.split())
