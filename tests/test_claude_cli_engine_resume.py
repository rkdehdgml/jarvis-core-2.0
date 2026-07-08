"""ClaudeCliEngine.run_task()의 --resume 세션 재사용(4-D) 검증 (plain assert 스크립트).

실제 Claude CLI 프로세스 없이 subprocess.Popen을 페이크로 교체해 명령 구성과
session_id 저장/재사용 배선만 검증한다.

실행: python -m tests.test_claude_cli_engine_resume (프로젝트 루트에서)
"""
import json
import subprocess

from core.engines.claude_cli_engine import ClaudeCliEngine


class _FakeProc:
    """subprocess.Popen 대체. stream-json 라인들을 stdout으로 흘려보낸다."""

    def __init__(self, lines: list[str], returncode: int = 0) -> None:
        self.stdout = iter(lines)
        self.stderr = iter([])
        self.returncode = returncode

    def wait(self, timeout: float | None = None) -> None:
        pass

    def kill(self) -> None:
        pass


def _result_line(text: str, session_id: str | None = None) -> str:
    obj = {"type": "result", "result": text}
    if session_id:
        obj["session_id"] = session_id
    return json.dumps(obj)


def test_run_task_stores_and_reuses_session_id() -> None:
    captured_cmds: list[list[str]] = []

    def fake_popen(cmd, **kwargs):
        captured_cmds.append(cmd)
        if len(captured_cmds) == 1:
            return _FakeProc([_result_line("첫 응답", session_id="sess-1")])
        return _FakeProc([_result_line("이어진 응답")])

    original_popen = subprocess.Popen
    subprocess.Popen = fake_popen
    try:
        engine = ClaudeCliEngine()
        first = engine.run_task("첫 태스크")
        second = engine.run_task("이어지는 태스크", resume=True)
    finally:
        subprocess.Popen = original_popen

    assert first == "첫 응답"
    assert second == "이어진 응답"
    assert "--resume" not in captured_cmds[0], (
        f"첫 호출엔 저장된 세션이 없어 --resume이 없어야 함: {captured_cmds[0]}"
    )
    assert "--resume" in captured_cmds[1], (
        f"두 번째 호출은 resume=True이므로 --resume이 있어야 함: {captured_cmds[1]}"
    )
    resume_idx = captured_cmds[1].index("--resume")
    assert captured_cmds[1][resume_idx + 1] == "sess-1", (
        f"1차 호출의 session_id를 그대로 재사용해야 함: {captured_cmds[1]}"
    )


def test_run_task_default_does_not_resume() -> None:
    captured_cmds: list[list[str]] = []

    def fake_popen(cmd, **kwargs):
        captured_cmds.append(cmd)
        return _FakeProc([_result_line("응답", session_id="sess-2")])

    original_popen = subprocess.Popen
    subprocess.Popen = fake_popen
    try:
        engine = ClaudeCliEngine()
        engine.run_task("태스크1")
        engine.run_task("태스크2")  # resume 생략 → 기본 False
    finally:
        subprocess.Popen = original_popen

    assert "--resume" not in captured_cmds[1], (
        f"resume 생략(기본 False)이면 저장된 세션이 있어도 --resume이 붙으면 안 됨: {captured_cmds[1]}"
    )


def test_run_task_resume_true_without_prior_session_is_noop() -> None:
    captured_cmds: list[list[str]] = []

    def fake_popen(cmd, **kwargs):
        captured_cmds.append(cmd)
        return _FakeProc([_result_line("응답")])  # session_id 없는 결과

    original_popen = subprocess.Popen
    subprocess.Popen = fake_popen
    try:
        engine = ClaudeCliEngine()
        result = engine.run_task("첫 태스크", resume=True)
    finally:
        subprocess.Popen = original_popen

    assert result == "응답"
    assert "--resume" not in captured_cmds[0], (
        f"저장된 세션이 없으면 resume=True여도 --resume 없이 새 세션으로 시작해야 함: {captured_cmds[0]}"
    )


def main() -> None:
    tests = [
        test_run_task_stores_and_reuses_session_id,
        test_run_task_default_does_not_resume,
        test_run_task_resume_true_without_prior_session_is_noop,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print("\nrun_task() resume 배선 검증 통과")


if __name__ == "__main__":
    main()
