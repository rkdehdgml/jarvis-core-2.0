"""skill_screen_agent.py streaming 상태 emit 순서 검증 (plain assert 스크립트).

HybridScreenEngine을 실제로 기동하지 않고(UIA/스크린샷 불필요) 모듈에 바인딩된
클래스만 가짜로 교체해, "streaming" emit이 engine.run() 호출보다 먼저 일어나는지
확인한다.

실행: python -m tests.test_skill_screen_agent_streaming  (프로젝트 루트에서)
"""
import skills.skill_screen_agent as mod
from core.status_events import broadcaster


def main() -> None:
    observed: dict = {}

    class _FakeEngine:
        def __init__(self, on_chunk=None) -> None:
            self.on_chunk = on_chunk

        def run(self, task: str) -> str:
            observed["state"] = broadcaster.get_current().state
            return "화면 제어 완료"

    original_engine = mod.HybridScreenEngine
    mod.HybridScreenEngine = _FakeEngine
    try:
        skill = mod.ScreenAgentSkill()
        result = skill.execute("화면 제어로 메모장에 안녕 입력해줘", {})
    finally:
        mod.HybridScreenEngine = original_engine

    assert observed.get("state") == "streaming", f"engine.run() 호출 시점 상태: {observed.get('state')}"
    assert result.success
    assert result.speech == "화면 제어 완료"

    print("\ntest_skill_screen_agent_streaming 검증 통과")


if __name__ == "__main__":
    main()
