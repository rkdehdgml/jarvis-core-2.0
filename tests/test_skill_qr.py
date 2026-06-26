"""skill_qr 검증: 라우팅 점수와 실제 QR 이미지 파일 생성을 확인한다.

실행: python -m tests.test_skill_qr  (프로젝트 루트에서)
"""
from pathlib import Path

from skills.skill_qr import QrSkill


def main() -> None:
    skill = QrSkill()

    # can_handle: 트리거 있으면 0.4 이상, 무관 문장은 0.0
    assert skill.can_handle("", "QR코드 만들어줘") >= 0.4, "트리거 문장 점수 미달"
    assert skill.can_handle("", "오늘 날씨 어때") == 0.0, "무관 문장은 0.0이어야 함"

    # execute: payload 있는 정상 케이스 → 실제 파일 생성
    result = skill.execute("https://example.com QR코드 만들어줘", {})
    assert result.success, "정상 입력인데 success=False"
    path = Path(result.data["path"])
    assert path.exists(), f"생성된 파일이 존재하지 않음: {path}"
    assert path.stat().st_size > 0, "생성된 파일 크기가 0"
    assert result.data["payload"] == "https://example.com", (
        f"payload 추출 오류: {result.data['payload']!r}"
    )

    # execute: 트리거만 있고 내용 없음 → success=False
    empty = skill.execute("QR코드 만들어줘", {})
    assert not empty.success, "내용 없는데 success=True"

    print("[can_handle]", skill.can_handle("", "QR코드 만들어줘"))
    print("[execute]", result.speech)
    print("[empty]", empty.speech)
    print("\nskill_qr 검증 통과")


if __name__ == "__main__":
    main()
