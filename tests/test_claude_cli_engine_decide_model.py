"""ClaudeCliEngine.decide()가 --model haiku 플래그를 붙이는지 검증 (plain assert 스크립트).

실행: python -m tests.test_claude_cli_engine_decide_model  (프로젝트 루트에서)
"""
import subprocess

from core.engines import claude_cli_engine
from core.engines.claude_cli_engine import ClaudeCliEngine


def main() -> None:
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(
            cmd, 0, stdout='{"result": "행동 결정 결과"}', stderr=""
        )

    original_run = subprocess.run
    subprocess.run = fake_run
    try:
        engine = ClaudeCliEngine()
        result, session_id = engine.decide("화면을 보고 다음 행동을 결정해라")
    finally:
        subprocess.run = original_run

    cmd = captured["cmd"]
    assert "--model" in cmd, f"--model 플래그가 없음: {cmd}"
    model_idx = cmd.index("--model")
    assert cmd[model_idx + 1] == claude_cli_engine._DECIDE_MODEL, (
        f"decide()는 _DECIDE_MODEL({claude_cli_engine._DECIDE_MODEL})을 써야 함: {cmd}"
    )
    assert "--allowedTools" in cmd
    tools_idx = cmd.index("--allowedTools")
    assert cmd[tools_idx + 1] == "Read", f"decide()는 Read 툴만 허용해야 함: {cmd}"
    assert result == "행동 결정 결과"
    assert session_id is None, f"응답에 session_id가 없으면 None이어야 함: {session_id}"

    # ask()/generate()는 모델을 지정하지 않아 --model이 붙지 않아야 한다
    # (기본 모델 유지 - 사용자 대화 품질 우선).
    captured.clear()
    subprocess.run = fake_run
    try:
        engine.ask("안녕")
    finally:
        subprocess.run = original_run
    assert "--model" not in captured["cmd"], f"ask()는 --model을 붙이면 안 됨: {captured['cmd']}"

    print("\ntest_claude_cli_engine_decide_model 검증 통과")


if __name__ == "__main__":
    main()
