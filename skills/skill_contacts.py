import json
import re
from pathlib import Path

from core.skill_base import Skill, SkillResult

_CONTACTS_PATH = Path(__file__).parent.parent / "data" / "contacts.json"

# 강한 트리거 — 단독으로도 임계값(0.4)을 넘긴다.
_STRONG_KEYWORD = "연락처"

# 약한 트리거 — "버스 번호 몇번이야"처럼 무관한 문장에 흔히 끼므로 단독으론 낮게 두고,
# 아래 행동 동사가 같이 나올 때만 점수를 보탠다(skill_web_search.py의 2단계 점수 패턴).
_WEAK_KEYWORD = "번호"
# "몇번"은 "버스 번호 몇번이야"처럼 무관한 문장에 흔히 끼므로 행동 동사로 치지 않는다
# (이게 약한 트리거를 둔 이유 자체다 — 연락처 의도가 분명할 때만 "연락처" 강트리거로 잡힌다).
_ACTION_WORDS = ["저장", "추가", "등록", "알려줘", "뭐야", "목록"]

_PHONE_PATTERN = re.compile(r"01[016789]-?\d{3,4}-?\d{4}")
_HANGUL_TOKEN = re.compile(r"[가-힣][가-힣\w]*")

# 이름 추출 시 걷어낼 트리거/조사/동사 (긴 것부터 제거해야 안전).
_FILLER_WORDS = [
    "연락처에",
    "연락처",
    "번호는",
    "번호",
    "추가해줘",
    "저장해줘",
    "등록해줘",
    "추가",
    "저장",
    "등록",
    "알려줘",
    "뭐야",
    "몇번",
    "에게",
    "한테",
    "에",
    "의",
    "는",
    "은",
    "이",
    "가",
]


class ContactsSkill(Skill):
    """연락처(이름과 전화번호)를 로컬 JSON에 저장하고 조회한다."""

    name = "contacts"
    description = "연락처(이름과 전화번호)를 로컬에 저장하고 조회한다"
    triggers = [_STRONG_KEYWORD]
    examples = [
        "연락처에 엄마 010-1234-5678 추가해줘",
        "엄마 번호 알려줘",
        "연락처 목록 보여줘",
    ]

    def can_handle(self, intent: str, text: str) -> float:
        if _STRONG_KEYWORD in text:
            return 0.85
        if _WEAK_KEYWORD in text:
            if any(w in text for w in _ACTION_WORDS):
                return 0.8
            return 0.3
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        phone_match = _PHONE_PATTERN.search(text)
        if phone_match:
            return self._add(text, phone_match.group())
        if "목록" in text or "전체" in text:
            return self._list()
        return self._lookup(text)

    # --- 의도별 처리 ---

    def _add(self, text: str, phone: str) -> SkillResult:
        remaining = text.replace(phone, " ")
        name = self._extract_name(remaining)
        if not name:
            return SkillResult(
                speech="이름을 못 찾았습니다, 다시 말씀해주세요.",
                success=False,
            )

        phone = self._normalize_phone(phone)
        contacts = self._load()
        contacts[name] = {"phone": phone, "email": None}
        self._save(contacts)

        return SkillResult(
            speech=f"{name} 연락처를 저장했습니다.",
            success=True,
            data={"name": name, "phone": phone},
        )

    def _list(self) -> SkillResult:
        contacts = self._load()
        if not contacts:
            return SkillResult(speech="저장된 연락처가 없습니다.", success=True, data={"count": 0})

        lines = [f"{name}: {info['phone']}" for name, info in contacts.items()]
        speech = "저장된 연락처입니다. " + ", ".join(lines)
        return SkillResult(speech=speech, success=True, data={"count": len(contacts)})

    def _lookup(self, text: str) -> SkillResult:
        name = self._extract_name(text)
        if not name:
            return SkillResult(
                speech="이름을 못 찾았습니다, 다시 말씀해주세요.",
                success=False,
            )

        contacts = self._load()
        info = contacts.get(name)
        if info is None:
            return SkillResult(
                speech=f"{name} 연락처를 찾을 수 없습니다.",
                success=False,
                data={"name": name},
            )

        return SkillResult(
            speech=f"{name} 번호는 {info['phone']}입니다.",
            success=True,
            data={"name": name, "phone": info["phone"]},
        )

    # --- 헬퍼 ---

    def _extract_name(self, text: str) -> str:
        """트리거/조사/동사를 걷어낸 뒤 남는 첫 한글 토큰을 이름으로 본다."""
        query = text
        for word in _FILLER_WORDS:
            query = query.replace(word, " ")
        token = _HANGUL_TOKEN.search(query)
        return token.group() if token else ""

    def _normalize_phone(self, phone: str) -> str:
        """하이픈 없는 번호를 010-XXXX-XXXX 형태로 통일한다."""
        digits = re.sub(r"\D", "", phone)
        if len(digits) == 11:
            return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
        if len(digits) == 10:
            return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
        return phone

    def _load(self) -> dict:
        try:
            return json.loads(_CONTACTS_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save(self, contacts: dict) -> None:
        _CONTACTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CONTACTS_PATH.write_text(
            json.dumps(contacts, ensure_ascii=False, indent=2), encoding="utf-8"
        )
