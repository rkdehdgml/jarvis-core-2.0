"""Gmail SMTP로 이메일을 보내는 스킬.

표준 라이브러리(smtplib, email)만 사용한다 — 신규 패키지 설치 불필요.
발신 계정/앱 비밀번호는 .env의 GMAIL_ADDRESS / GMAIL_APP_PASSWORD에서 읽되,
groq_engine.py의 GROQ_API_KEY lazy-check 패턴처럼 execute() 안에서 os.getenv()로
읽는다(모듈 로드 시점에 읽으면 키 없는 환경에서 SkillRegistry 로딩이 깨질 수 있다).

실제 발송은 _send_email() 한 곳으로 격리해 두었다 — 테스트는 이 메서드를
unittest.mock.patch로 패치해서 실제 SMTP 연결이 일어나지 않게 한다.
"""
import json
import logging
import os
import re
import smtplib
from email.mime.text import MIMEText
from pathlib import Path

from core.skill_base import Skill, SkillResult

logger = logging.getLogger(__name__)

_CONTACTS_PATH = Path(__file__).parent.parent / "data" / "contacts.json"

_TRIGGERS = ["이메일 보내줘", "메일 보내줘", "이메일로 보내줘"]

_EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

_DEFAULT_SUBJECT = "자비스에서 보낸 메일"

# 본문 추출 시 걷어낼 트리거/조사 (긴 것부터).
_FILLER_WORDS = [
    "이메일로 보내줘",
    "이메일 보내줘",
    "메일 보내줘",
    "이메일을",
    "이메일",
    "메일을",
    "메일",
    "한테",
    "에게",
    "께",
]

# 제목/본문 구분자.
_SUBJECT_MARKERS = ["제목은", "제목:", "제목 "]
_BODY_MARKERS = ["내용은", "본문은", "내용:", "본문:"]


class EmailSkill(Skill):
    """텍스트(또는 연락처)에서 수신자/제목/본문을 뽑아 Gmail로 메일을 보낸다."""

    name = "email"
    description = "Gmail로 이메일을 보낸다"
    triggers = _TRIGGERS
    examples = [
        "test@example.com 한테 이메일 보내줘 안녕하세요",
        "엄마한테 메일 보내줘",
        "철수한테 제목은 회의 내용은 3시에 시작 메일 보내줘",
    ]

    def can_handle(self, intent: str, text: str) -> float:
        if any(trigger in text for trigger in _TRIGGERS):
            return 0.85
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        gmail_address = os.getenv("GMAIL_ADDRESS")
        gmail_app_password = os.getenv("GMAIL_APP_PASSWORD")
        if not gmail_address or not gmail_app_password:
            return SkillResult(
                speech="이메일 기능을 사용하려면 .env 파일에 GMAIL_ADDRESS와 "
                "GMAIL_APP_PASSWORD를 설정해주세요.",
                success=False,
            )

        to = self._extract_recipient(text)
        if not to:
            return SkillResult(
                speech="받을 사람의 이메일 주소를 말씀해주세요.",
                success=False,
            )

        subject, body = self._extract_subject_body(text, to)

        sent = self._send_email(to, subject, body)
        if sent:
            return SkillResult(
                speech=f"{to}로 이메일을 보냈습니다.",
                success=True,
                data={"to": to, "subject": subject},
            )
        return SkillResult(
            speech="이메일 발송에 실패했습니다.",
            success=False,
            data={"to": to},
        )

    # --- 추출 ---

    def _extract_recipient(self, text: str) -> str:
        """텍스트에 이메일 주소가 있으면 그걸, 없으면 연락처의 email 필드를 본다."""
        match = _EMAIL_PATTERN.search(text)
        if match:
            return match.group()

        # 보너스 경로: 연락처에 email이 채워진 이름이 텍스트에 있으면 사용.
        # (현재 skill_contacts는 email을 채우지 않아 거의 항상 null이라 안전망 수준.)
        contacts = self._load_contacts()
        for name, info in contacts.items():
            if name in text and info.get("email"):
                return info["email"]
        return ""

    def _extract_subject_body(self, text: str, to: str) -> tuple[str, str]:
        """'제목은'/'내용은' 마커가 있으면 그에 맞춰, 없으면 기본 제목 + 정리한 본문."""
        subject_idx, subject_marker = self._find_marker(text, _SUBJECT_MARKERS)
        body_idx, body_marker = self._find_marker(text, _BODY_MARKERS)

        if subject_idx != -1:
            subject_start = subject_idx + len(subject_marker)
            if body_idx != -1 and body_idx > subject_idx:
                subject = text[subject_start:body_idx].strip()
                body = text[body_idx + len(body_marker):]
            else:
                subject = text[subject_start:].strip()
                body = ""
            body = self._clean_body(body, to)
            return subject or _DEFAULT_SUBJECT, body

        if body_idx != -1:
            body = self._clean_body(text[body_idx + len(body_marker):], to)
            return _DEFAULT_SUBJECT, body

        # 마커가 없으면 트리거/수신자/조사를 걷어낸 나머지를 본문으로.
        return _DEFAULT_SUBJECT, self._clean_body(text, to)

    def _find_marker(self, text: str, markers: list[str]) -> tuple[int, str]:
        for marker in markers:
            idx = text.find(marker)
            if idx != -1:
                return idx, marker
        return -1, ""

    def _clean_body(self, text: str, to: str) -> str:
        body = text.replace(to, " ")
        for word in _FILLER_WORDS:
            body = body.replace(word, " ")
        return re.sub(r"\s+", " ", body).strip()

    # --- 발송 (테스트에서 patch 대상) ---

    def _send_email(self, to: str, subject: str, body: str) -> bool:
        """Gmail SMTP로 메일을 보낸다. 성공하면 True, 어떤 실패든 False(예외 안 던짐)."""
        gmail_address = os.getenv("GMAIL_ADDRESS")
        gmail_app_password = os.getenv("GMAIL_APP_PASSWORD")
        try:
            message = MIMEText(body, _charset="utf-8")
            message["Subject"] = subject
            message["From"] = gmail_address
            message["To"] = to

            with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
                server.starttls()
                server.login(gmail_address, gmail_app_password)
                server.send_message(message)
            return True
        except smtplib.SMTPException as e:
            logger.error(f"SMTP 오류로 이메일 발송 실패: {e}")
            return False
        except Exception as e:
            logger.error(f"이메일 발송 중 오류: {e}")
            return False

    # --- 헬퍼 ---

    def _load_contacts(self) -> dict:
        try:
            return json.loads(_CONTACTS_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
