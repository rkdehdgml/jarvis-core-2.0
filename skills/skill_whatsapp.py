import json
import os
import re
from pathlib import Path

from core.skill_base import Skill, SkillResult

try:
    import pywhatkit
except ImportError:  # pyautogui 등 GUI 의존성이 없는 환경에서도 레지스트리 로딩이 깨지지 않게
    pywhatkit = None

_CONTACTS_PATH = Path(__file__).parent.parent / "data" / "contacts.json"

_TRIGGERS = ["왓츠앱 보내줘", "왓츠앱으로 보내줘", "whatsapp 보내줘"]

# 텍스트에서 직접 추출할 전화번호(국내 휴대폰) 패턴.
_PHONE_PATTERN = re.compile(r"01[016789]-?\d{3,4}-?\d{4}")

# 수신자/트리거에서 메시지를 분리할 때 걷어낼 조각들(긴 것부터).
_FILLER_WORDS = [
    "왓츠앱으로 보내줘",
    "왓츠앱 보내줘",
    "whatsapp 보내줘",
    "왓츠앱으로",
    "왓츠앱",
    "whatsapp",
    "보내줘",
    "에게",
    "한테",
    "로",
    "으로",
]

_DEFAULT_COUNTRY_CODE = "+82"


class WhatsAppSkill(Skill):
    """WhatsApp으로 메시지를 보낸다."""

    name = "whatsapp"
    description = "WhatsApp으로 메시지를 보낸다"
    triggers = _TRIGGERS
    examples = [
        "엄마한테 왓츠앱 보내줘 저녁 늦어요",
        "010-1234-5678로 왓츠앱 보내줘 안녕",
        "철수한테 왓츠앱으로 보내줘 회의 끝났어",
    ]

    def can_handle(self, intent: str, text: str) -> float:
        lowered = text.lower()
        if any(trigger.lower() in lowered for trigger in _TRIGGERS):
            return 0.85
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        if pywhatkit is None:
            return SkillResult(
                speech="WhatsApp 기능을 사용할 수 없습니다 (pywhatkit 미설치).",
                success=False,
            )

        recipient_label, raw_phone = self._resolve_recipient(text)
        if raw_phone is None:
            return SkillResult(
                speech="받을 사람의 전화번호를 말씀해주세요.",
                success=False,
            )

        phone = self._to_international(raw_phone)
        message = self._extract_message(text, recipient_label, raw_phone)

        try:
            pywhatkit.sendwhatmsg_instantly(
                phone, message, wait_time=15, tab_close=True, close_time=3
            )
        except Exception:  # pyautogui/GUI 예외 포함 — 절대 밖으로 던지지 않는다.
            return SkillResult(
                speech="WhatsApp 메시지 발송에 실패했습니다.",
                success=False,
            )

        return SkillResult(
            speech=f"{recipient_label}에게 WhatsApp 메시지를 보냈습니다.",
            success=True,
            data={"phone": phone},
        )

    # --- 헬퍼 ---

    def _resolve_recipient(self, text: str):
        """(표시용 라벨, 원본 전화번호 문자열) 반환. 못 찾으면 (None, None)."""
        phone_match = _PHONE_PATTERN.search(text)
        if phone_match:
            phone = phone_match.group()
            return phone, phone

        contacts = self._load_contacts()
        for name, info in contacts.items():
            if name in text and info.get("phone"):
                return name, info["phone"]

        return None, None

    def _to_international(self, raw_phone: str) -> str:
        """+로 시작하지 않으면 국가번호를 붙이고 하이픈/선행 0을 제거한다."""
        if raw_phone.strip().startswith("+"):
            return re.sub(r"[^\d+]", "", raw_phone)

        country_code = os.getenv("WHATSAPP_DEFAULT_COUNTRY_CODE") or _DEFAULT_COUNTRY_CODE
        digits = re.sub(r"\D", "", raw_phone)
        digits = digits.lstrip("0")
        return f"{country_code}{digits}"

    def _extract_message(self, text: str, recipient_label: str, raw_phone: str) -> str:
        """트리거/수신자(이름 또는 번호)/조사를 제거한 나머지를 메시지로 본다."""
        message = text
        message = message.replace(raw_phone, " ")
        if recipient_label and recipient_label != raw_phone:
            message = message.replace(recipient_label, " ")
        for word in _FILLER_WORDS:
            message = message.replace(word, " ")
        return " ".join(message.split())

    def _load_contacts(self) -> dict:
        try:
            return json.loads(_CONTACTS_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
