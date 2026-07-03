"""skill_web_collector.py streaming 상태 emit + 라우팅 스코어링 검증 (plain assert 스크립트).

실행: python -m tests.test_skill_web_collector  (프로젝트 루트에서)
"""
import skills.skill_web_collector as mod
from skills.skill_agent import AgentSkill
from core.status_events import broadcaster


def test_streaming_state_before_run() -> None:
    observed: dict = {}

    class _FakeEngine:
        def __init__(self, on_chunk=None) -> None:
            self.on_chunk = on_chunk

        def run(self, task: str) -> str:
            observed["state"] = broadcaster.get_current().state
            return "수집 완료"

    original_engine = mod.WebCollectorEngine
    mod.WebCollectorEngine = _FakeEngine
    try:
        skill = mod.WebCollectorSkill()
        result = skill.execute("네이버 부동산에서 대전 아파트 수집해줘", {})
    finally:
        mod.WebCollectorEngine = original_engine

    assert observed.get("state") == "streaming", f"engine.run() 호출 시점 상태: {observed.get('state')}"
    assert result.success
    assert result.speech == "수집 완료"

    print("test_streaming_state_before_run 통과")


def test_routing_priority_over_agent_skill() -> None:
    text = "네이버 부동산에서 대전 아파트 수집해줘"
    collector_score = mod.WebCollectorSkill().can_handle("", text)
    agent_score = AgentSkill().can_handle("", text)

    assert collector_score == 0.93, f"web_collector 점수 불일치: {collector_score}"
    assert agent_score == 0.9, f"agent 점수 불일치: {agent_score}"
    assert collector_score > agent_score, "사이트+수집 문장에서 web_collector가 agent를 이겨야 함"

    print("test_routing_priority_over_agent_skill 통과")


def test_routing_falls_back_for_generic_research() -> None:
    text = "인공지능 트렌드 조사해줘"
    collector_score = mod.WebCollectorSkill().can_handle("", text)
    agent_score = AgentSkill().can_handle("", text)

    assert collector_score == 0.0, f"일반 리서치 문장에 web_collector가 반응함: {collector_score}"
    assert agent_score == 0.9, f"agent 점수 회귀: {agent_score}"

    print("test_routing_falls_back_for_generic_research 통과")


def test_strong_trigger_scores_highest() -> None:
    text = "브라우저로 수집해서 알려줘"
    score = mod.WebCollectorSkill().can_handle("", text)
    assert score == 0.95, f"강한 트리거 점수 불일치: {score}"

    print("test_strong_trigger_scores_highest 통과")


def main() -> None:
    test_streaming_state_before_run()
    test_routing_priority_over_agent_skill()
    test_routing_falls_back_for_generic_research()
    test_strong_trigger_scores_highest()
    print("\ntest_skill_web_collector 검증 통과")


if __name__ == "__main__":
    main()
