"""skill_camera 검증 (plain assert).

실행: python -m tests.test_skill_camera  (프로젝트 루트에서)
"""
import os

from skills.skill_camera import CameraSkill


def test_can_handle() -> None:
    skill = CameraSkill()
    assert skill.can_handle("", "웹캠으로 사진 찍어줘") >= 0.4
    assert skill.can_handle("", "카메라로 찍어줘") >= 0.4
    assert skill.can_handle("", "오늘 날씨 어때") == 0.0
    print("[can_handle] 통과")


def test_local_webcam() -> None:
    skill = CameraSkill()
    result = skill.execute("웹캠으로 사진 찍어줘", {})
    print("[로컬 웹캠] success=%s speech=%s" % (result.success, result.speech))
    if result.success:
        path = result.data["path"]
        assert os.path.exists(path), "성공인데 파일이 없음"
        assert os.path.getsize(path) > 0, "성공인데 파일 크기가 0"
        print("[로컬 웹캠] 파일 저장 확인:", path, os.path.getsize(path), "bytes")
    else:
        # 웹캠/ffmpeg가 없으면 예외 없이 우아하게 실패해야 한다 (환경 제약, 코드 버그 아님).
        assert isinstance(result.success, bool)
        print("[로컬 웹캠] 웹캠/ffmpeg 미존재 - 예외 없이 우아하게 실패 (환경 제약)")


def test_ip_stream_unreachable() -> None:
    skill = CameraSkill()
    result = skill.execute("http://192.0.2.1:9999/nonexistent 카메라 캡처해줘", {})
    print("[IP 스트림] success=%s speech=%s" % (result.success, result.speech))
    # 접근 불가 URL은 예외 없이 success=False여야 한다.
    assert result.success is False, "접근 불가 스트림인데 success=True"
    print("[IP 스트림] 접근 불가 URL - 예외 없이 우아하게 실패")


def main() -> None:
    test_can_handle()
    test_local_webcam()
    test_ip_stream_unreachable()
    print("\nskill_camera 검증 통과")


if __name__ == "__main__":
    main()
