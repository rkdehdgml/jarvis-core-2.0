"""skill_speedtest 검증.

can_handle()은 순수 점수 계산. execute()는 실제 네트워크 측정을 수행하므로 몇 초 걸릴 수
있다 — 측정값이 0보다 큰 합리적 범위인지 확인한다. 네트워크가 없는 환경에서는 success=False로
우아하게 끝나는 것까지 허용한다(예외는 절대 밖으로 나오면 안 된다).

실행: python -m tests.test_skill_speedtest  (프로젝트 루트에서)
"""
from skills.skill_speedtest import SpeedtestSkill


def test_can_handle() -> None:
    s = SpeedtestSkill()
    assert s.can_handle("", "인터넷 속도 측정해줘") >= 0.4
    assert s.can_handle("", "오늘 날씨 어때") == 0.0


def test_execute() -> None:
    s = SpeedtestSkill()
    result = s.execute("인터넷 속도 측정해줘", {})
    print("[speedtest]", result.success, "|", result.speech)
    if result.success:
        assert result.data["download_mbps"] > 0, "측정값이 0 이하"
    else:
        assert result.speech == "인터넷 속도 측정에 실패했습니다."


def main() -> None:
    test_can_handle()
    test_execute()
    print("test_skill_speedtest 통과")


if __name__ == "__main__":
    main()
