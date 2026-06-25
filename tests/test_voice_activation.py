"""상시 음성인식 해제 문구(_is_deactivate_command) 검증.

핵심 회귀 시나리오: "자비스 크롬 종료해줘"처럼 "자비스"와 "종료" 사이에 다른 말이
끼면 해제 명령이 아니라 skill_app_control(앱 종료)로 라우팅돼야 한다.

실행: python -m tests.test_voice_activation (프로젝트 루트에서)
"""
from main import _is_deactivate_command


def test_jarvis_off_detected() -> None:
    assert _is_deactivate_command("자비스 오프")
    assert _is_deactivate_command("자비스오프")


def test_jarvis_exit_detected() -> None:
    assert _is_deactivate_command("자비스 종료")
    assert _is_deactivate_command("자비스종료")


def test_trailing_words_allowed() -> None:
    assert _is_deactivate_command("자비스 종료해줘")
    assert _is_deactivate_command("자비스 오프 해줘")


def test_bare_exit_word_is_not_deactivate_command() -> None:
    # 프로그램 전체 종료("종료" 단독)는 main.py의 _EXIT_WORD 분기가 별도로 처리한다.
    assert not _is_deactivate_command("종료")


def test_app_control_command_not_misdetected() -> None:
    # "자비스"와 "종료" 사이에 앱 이름이 끼면 해제 명령으로 잘못 잡으면 안 됨
    # (skill_app_control의 "크롬 종료해줘"가 정상 라우팅돼야 함).
    assert not _is_deactivate_command("자비스 크롬 종료해줘")
    assert not _is_deactivate_command("크롬 종료해줘")


def main() -> None:
    tests = [
        test_jarvis_off_detected,
        test_jarvis_exit_detected,
        test_trailing_words_allowed,
        test_bare_exit_word_is_not_deactivate_command,
        test_app_control_command_not_misdetected,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print("\n_is_deactivate_command 검증 통과")


if __name__ == "__main__":
    main()
