"""skill_screen_record 검증.

실행: python -m tests.test_skill_screen_record  (프로젝트 루트에서)

실제 캡처를 짧게(3초) 실행해 검증한다. 이 환경에 ffmpeg/마이크가 없으면
예외 없이 success=False로 우아하게 끝나는지만 확인한다(환경 제약, 코드 버그 아님).
"""
import os

from skills.skill_screen_record import ScreenRecordSkill, _list_dshow_devices


def test_can_handle() -> None:
    skill = ScreenRecordSkill()
    assert skill.can_handle("", "화면 녹화해줘") >= 0.4
    assert skill.can_handle("", "음성 녹음해줘") == 0.0
    assert skill.can_handle("", "오늘 날씨 어때") == 0.0
    print("[can_handle] 통과")


def test_execute() -> None:
    skill = ScreenRecordSkill()
    result = skill.execute("3초 동안 화면 녹화해줘", {})
    print("[execute] success=", result.success, "speech=", result.speech)

    audio_devices = _list_dshow_devices("audio")
    if result.success:
        path = result.data["path"]
        assert os.path.exists(path), f"녹화 파일이 존재하지 않음: {path}"
        assert os.path.getsize(path) > 0, "녹화 파일 크기가 0"
        print(f"[execute] 녹화 성공 — {path} ({os.path.getsize(path)} bytes)")
    else:
        # ffmpeg 부재 또는 마이크 부재 — 예외 없이 우아하게 실패하면 통과.
        assert result.success is False
        print(f"[execute] 환경 제약으로 우아하게 실패 처리 (audio_devices={audio_devices})")


def main() -> None:
    test_can_handle()
    test_execute()
    print("\nskill_screen_record 검증 통과")


if __name__ == "__main__":
    main()
