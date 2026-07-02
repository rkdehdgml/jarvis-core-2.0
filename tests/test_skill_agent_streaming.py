"""skill_agent.py streaming 상태 emit 순서 검증 (plain assert 스크립트).

run_task()를 실제로 호출하지 않고(Claude CLI 프로세스 미기동) 엔진의
run_task 메서드만 스텁으로 교체해, "streaming" emit이 호출 시점보다
먼저 일어나는지만 확인한다.

실행: python -m tests.test_skill_agent_streaming  (프로젝트 루트에서)
"""
from core.status_events import broadcaster
from skills.skill_agent import AgentSkill


def main() -> None:
    skill = AgentSkill()
    observed: dict = {}

    def fake_run_task(task: str, on_chunk=None) -> str:
        observed["state"] = broadcaster.get_current().state
        return "조사 결과 요약"

    skill._engine.run_task = fake_run_task  # type: ignore[method-assign]

    result = skill.execute("삼성전자 최신 뉴스 조사해줘", {})

    assert observed.get("state") == "streaming", f"run_task 호출 시점 상태: {observed.get('state')}"
    assert result.success
    assert result.speech == "조사 결과 요약"

    print("\ntest_skill_agent_streaming 검증 통과")


if __name__ == "__main__":
    main()
