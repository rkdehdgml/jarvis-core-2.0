"""skill_whatsapp 단위 테스트.

실행: python -m tests.test_skill_whatsapp  (프로젝트 루트에서)

절대 원칙: 실제 WhatsApp 발송/브라우저/GUI 조작을 하지 않는다.
pywhatkit.sendwhatmsg_instantly 는 항상 unittest.mock.patch 로 가로챈다.
"""
import json
import types
from pathlib import Path
from unittest.mock import patch

import skills.skill_whatsapp as sw
from skills.skill_whatsapp import WhatsAppSkill

_CONTACTS_PATH = Path(sw.__file__).parent.parent / "data" / "contacts.json"


def _ensure_patchable_pywhatkit() -> None:
    """pywhatkit 미설치 환경에서도 patch 가능하도록 더미 모듈을 끼운다."""
    if sw.pywhatkit is None:
        sw.pywhatkit = types.SimpleNamespace(
            sendwhatmsg_instantly=lambda *a, **kw: None
        )


def test_can_handle() -> None:
    skill = WhatsAppSkill()
    assert skill.can_handle("", "엄마한테 왓츠앱 보내줘 저녁 늦어요") >= 0.4
    assert skill.can_handle("", "010-1234-5678로 WhatsApp 보내줘 안녕") >= 0.4
    assert skill.can_handle("", "오늘 날씨 어때") == 0.0
    print("[test_can_handle] 통과")


def test_send_by_phone() -> None:
    _ensure_patchable_pywhatkit()
    skill = WhatsAppSkill()

    with patch.object(sw.pywhatkit, "sendwhatmsg_instantly") as mock_send:
        result = skill.execute("010-1234-5678로 왓츠앱 보내줘 안녕", {})

    assert mock_send.called, "sendwhatmsg_instantly 가 호출되지 않음"
    called_phone = mock_send.call_args.args[0]
    assert called_phone == "+821012345678", f"국가번호 변환 실패: {called_phone}"
    called_message = mock_send.call_args.args[1]
    assert "안녕" in called_message, f"메시지 추출 실패: {called_message!r}"
    assert result.success is True
    assert result.data["phone"] == "+821012345678"
    print("[test_send_by_phone] 통과")


def test_send_by_contact_name() -> None:
    _ensure_patchable_pywhatkit()
    skill = WhatsAppSkill()

    # data/contacts.json 백업 후 테스트 연락처 주입, 끝나면 복원.
    backup = None
    if _CONTACTS_PATH.exists():
        backup = _CONTACTS_PATH.read_text(encoding="utf-8")
    _CONTACTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    contacts = json.loads(backup) if backup else {}
    contacts["테스트유저123"] = {"phone": "010-9876-5432", "email": None}
    _CONTACTS_PATH.write_text(
        json.dumps(contacts, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    try:
        with patch.object(sw.pywhatkit, "sendwhatmsg_instantly") as mock_send:
            result = skill.execute("테스트유저123한테 왓츠앱 보내줘 안녕", {})

        assert mock_send.called, "sendwhatmsg_instantly 가 호출되지 않음"
        called_phone = mock_send.call_args.args[0]
        assert called_phone == "+821098765432", f"연락처 번호 변환 실패: {called_phone}"
        assert result.success is True
    finally:
        if backup is not None:
            _CONTACTS_PATH.write_text(backup, encoding="utf-8")
        else:
            _CONTACTS_PATH.unlink(missing_ok=True)
    print("[test_send_by_contact_name] 통과")


def test_no_recipient() -> None:
    _ensure_patchable_pywhatkit()
    skill = WhatsAppSkill()

    with patch.object(sw.pywhatkit, "sendwhatmsg_instantly") as mock_send:
        result = skill.execute("왓츠앱 보내줘 안녕하세요", {})

    assert not mock_send.called, "수신자가 없는데 발송이 시도됨"
    assert result.success is False
    print("[test_no_recipient] 통과")


def main() -> None:
    test_can_handle()
    test_send_by_phone()
    test_send_by_contact_name()
    test_no_recipient()
    print("\nskill_whatsapp 검증 통과")


if __name__ == "__main__":
    main()
