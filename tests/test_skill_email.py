"""skill_email 검증.

절대 원칙: 이 테스트는 실제로 이메일을 발송하지 않는다.
_send_email(그 안의 smtplib.SMTP 호출 포함)을 항상 unittest.mock.patch로 막은 채
실행하며, 패치되지 않은 경로(키 없음 안내)는 _send_email에 도달하기 전에 끝난다.

실행: python -m tests.test_skill_email  (프로젝트 루트에서)
"""
import os
from unittest.mock import patch

from dotenv import load_dotenv

from skills.skill_email import EmailSkill

load_dotenv()


def test_can_handle() -> None:
    skill = EmailSkill()
    assert skill.can_handle("", "test@example.com 한테 이메일 보내줘 안녕") >= 0.4
    assert skill.can_handle("", "엄마한테 메일 보내줘") >= 0.4
    assert skill.can_handle("", "오늘 날씨 어때") == 0.0
    print("[can_handle] 통과")


def test_send_with_credentials() -> None:
    skill = EmailSkill()
    has_creds = bool(os.getenv("GMAIL_ADDRESS")) and bool(os.getenv("GMAIL_APP_PASSWORD"))
    print(f"[.env] GMAIL_ADDRESS/GMAIL_APP_PASSWORD 존재: {has_creds}")

    if has_creds:
        # 실제 SMTP를 막은 채로만 발송 경로를 검증한다.
        with patch.object(EmailSkill, "_send_email", return_value=True) as mock_send:
            result = skill.execute(
                "test@example.com 한테 이메일 보내줘 테스트 메일입니다", {}
            )
        assert mock_send.called, "_send_email이 호출되어야 함"
        called_to = mock_send.call_args.args[0]
        assert called_to == "test@example.com", f"수신자 불일치: {called_to}"
        assert result.success is True
        assert "test@example.com" in result.speech
        print("[발송 경로(키 있음)] 통과 - 실제 SMTP는 patch로 차단됨")
    else:
        # 키가 없으면 _send_email에 도달하기 전에 안내 문구로 끝나야 한다.
        result = skill.execute(
            "test@example.com 한테 이메일 보내줘 테스트 메일입니다", {}
        )
        assert result.success is False
        assert ".env" in result.speech and "GMAIL_ADDRESS" in result.speech
        print("[키 없음 안내] 통과 - _send_email 미도달")


def test_no_recipient() -> None:
    skill = EmailSkill()
    # 키가 있든 없든 _send_email에 닿지 않아야 하므로 항상 patch로 안전망을 친다.
    with patch.object(EmailSkill, "_send_email", return_value=True) as mock_send:
        with patch.dict(
            os.environ,
            {"GMAIL_ADDRESS": "me@gmail.com", "GMAIL_APP_PASSWORD": "x"},
        ):
            result = skill.execute("그냥 이메일 보내줘 안녕하세요", {})
    assert result.success is False
    assert "이메일 주소" in result.speech
    assert not mock_send.called, "수신자 없으면 _send_email이 호출되면 안 됨"
    print("[수신자 없음] 통과")


def test_subject_body_parsing() -> None:
    skill = EmailSkill()
    text = "abc@test.com 한테 제목은 회의 내용은 3시에 시작 메일 보내줘"
    with patch.object(EmailSkill, "_send_email", return_value=True) as mock_send:
        with patch.dict(
            os.environ,
            {"GMAIL_ADDRESS": "me@gmail.com", "GMAIL_APP_PASSWORD": "x"},
        ):
            result = skill.execute(text, {})

    assert mock_send.called
    to, subject, body = mock_send.call_args.args
    assert to == "abc@test.com", f"수신자: {to}"
    assert subject == "회의", f"제목: {subject!r}"
    assert "3시에 시작" in body, f"본문: {body!r}"
    assert result.success is True
    print(f"[제목/본문 파싱] 통과 - to={to}, subject={subject!r}, body={body!r}")


def test_default_subject() -> None:
    skill = EmailSkill()
    text = "abc@test.com 한테 이메일 보내줘 안녕하세요 반갑습니다"
    with patch.object(EmailSkill, "_send_email", return_value=True) as mock_send:
        with patch.dict(
            os.environ,
            {"GMAIL_ADDRESS": "me@gmail.com", "GMAIL_APP_PASSWORD": "x"},
        ):
            skill.execute(text, {})

    to, subject, body = mock_send.call_args.args
    assert subject == "자비스에서 보낸 메일", f"기본 제목: {subject!r}"
    assert "안녕하세요" in body and "abc@test.com" not in body
    print(f"[기본 제목] 통과 - subject={subject!r}, body={body!r}")


def main() -> None:
    test_can_handle()
    test_send_with_credentials()
    test_no_recipient()
    test_subject_body_parsing()
    test_default_subject()
    print("\nskill_email 검증 통과 (실제 SMTP 발송 0회)")


if __name__ == "__main__":
    main()
