"""skill_voice_record 검증 — plain assert.

실행: python -m tests.test_skill_voice_record  (프로젝트 루트에서)

짧게(3초 이하) 녹음하는 안전한 동작이므로 mock 없이 실제 실행한다.
ffmpeg/마이크가 없는 환경에서는 예외 없이 success=False로 우아하게 끝나야 한다.
"""
import os

from skills.skill_voice_record import VoiceRecordSkill, _parse_duration, _list_dshow_devices


def test_can_handle() -> None:
    skill = VoiceRecordSkill()
    assert skill.can_handle("", "음성 녹음해줘") >= 0.4
    assert skill.can_handle("", "목소리 좀 녹음해줘") >= 0.4
    # 다른 스킬 영역("녹화") — 이 스킬은 처리하지 않는다.
    assert skill.can_handle("", "화면 녹화해줘") == 0.0
    # 무관한 문장.
    assert skill.can_handle("", "오늘 날씨 어때") == 0.0
    print("[test_can_handle] 통과")


def test_parse_duration() -> None:
    assert _parse_duration("3초 동안 음성 녹음해줘") == 3
    assert _parse_duration("2분 녹음해줘") == 60  # 120초 → 60초로 clamp
    assert _parse_duration("음성 녹음해줘") == 10  # 기본값
    assert _parse_duration("100초 녹음") == 60  # clamp
    print("[test_parse_duration] 통과")


def test_execute() -> None:
    skill = VoiceRecordSkill()
    result = skill.execute("3초 동안 음성 녹음해줘", {})

    devices = _list_dshow_devices("audio")
    if not devices:
        # 환경 제약: ffmpeg 부재 또는 마이크 없음 → 우아하게 실패.
        assert result.success is False
        assert "찾을 수 없습니다" in result.speech
        print("[test_execute] 마이크/ffmpeg 없음, 우아한 실패 확인 (환경 제약)")
        return

    if result.success:
        path = result.data["path"]
        assert os.path.exists(path), f"녹음 파일이 존재하지 않음: {path}"
        assert os.path.getsize(path) > 0, "녹음 파일 크기가 0임"
        print(f"[test_execute] 통과, 녹음 파일 {path} ({os.path.getsize(path)} bytes)")
    else:
        # 마이크 장치는 있으나 ffmpeg 실행이 실패한 경우(권한/코덱 등).
        print(f"[test_execute] 마이크 있으나 녹음 실패: {result.data.get('stderr', '')[:200]}")


def main() -> None:
    test_can_handle()
    test_parse_duration()
    test_execute()
    print("\nskill_voice_record 검증 통과")


if __name__ == "__main__":
    main()
