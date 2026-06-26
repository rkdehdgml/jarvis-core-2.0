"""skill_contacts 검증: can_handle 점수 + add/lookup/list 동작.

실행: python -m tests.test_skill_contacts  (프로젝트 루트에서)

실제 data/contacts.json을 더럽히지 않으려고, 테스트 시작 시 원본을 백업하고
끝나면 무조건 복원한다(파일이 없었으면 테스트가 만든 파일을 삭제).
"""
from pathlib import Path

from skills.skill_contacts import ContactsSkill, _CONTACTS_PATH

_TEST_NAME = "테스트유저123"


def _backup() -> bytes | None:
    if _CONTACTS_PATH.exists():
        return _CONTACTS_PATH.read_bytes()
    return None


def _restore(original: bytes | None) -> None:
    if original is None:
        if _CONTACTS_PATH.exists():
            _CONTACTS_PATH.unlink()
    else:
        _CONTACTS_PATH.write_bytes(original)


def _run(skill: ContactsSkill) -> None:
    # --- can_handle 점수 ---
    assert skill.can_handle("", "연락처에 누구 추가해줘") >= 0.4
    assert skill.can_handle("", "버스 번호 몇번이야") <= 0.3
    assert skill.can_handle("", "오늘 점심 뭐 먹지") == 0.0
    print("[can_handle] 점수 검증 통과")

    # --- 추가 ---
    add = skill.execute(f"연락처에 {_TEST_NAME} 010-9999-8888 추가해줘", {})
    assert add.success, f"추가 실패: {add.speech}"
    assert add.data.get("name") == _TEST_NAME
    print("[add]", add.speech)

    # --- 조회 ---
    lookup = skill.execute(f"{_TEST_NAME} 번호 알려줘", {})
    assert lookup.success, f"조회 실패: {lookup.speech}"
    assert "010-9999-8888" in lookup.speech, f"번호 누락: {lookup.speech}"
    print("[lookup]", lookup.speech)

    # --- 목록 ---
    listing = skill.execute("연락처 목록 보여줘", {})
    assert listing.success, f"목록 실패: {listing.speech}"
    assert _TEST_NAME in listing.speech, f"목록에 항목 누락: {listing.speech}"
    print("[list]", listing.speech)


def main() -> None:
    original = _backup()
    skill = ContactsSkill()
    try:
        _run(skill)
    finally:
        _restore(original)

    print("\nskill_contacts 검증 통과")


if __name__ == "__main__":
    main()
