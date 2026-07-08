# 4-D claude --resume 세션 유지 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `ClaudeCliEngine.run_task()`에 `resume: bool` 파라미터를 추가해, 엔진이 마지막 `run_task()` 호출의 `session_id`를 기억했다가 다음 호출에서 `--resume`으로 이어 쓸 수 있게 한다.

**Architecture:** `ClaudeCliEngine.__init__`에 `self._task_session_id: str | None = None`을 추가하고, `run_task()`의 stream-json `result` 이벤트 처리부에서 `session_id`를 뽑아 저장한다(`decide()`가 쓰는 `_parse_json_result()`와 동일한 타입 체크 패턴). `resume=True`이고 저장된 세션이 있으면 명령에 `--resume <id>`를 추가한다. `skill_agent.py`는 이번 계획에서 건드리지 않는다(설계 문서 참고 — 팔로우업 감지 휴리스틱은 별도 결정).

**Tech Stack:** Python 3.10+, 표준 라이브러리(`subprocess.Popen`). 테스트는 `pytest` 없이 `tests/`의 assert 기반 스크립트 컨벤션(`python -m tests.<module>`)을 따르고, `tests/test_claude_cli_engine_decide_model.py`(subprocess 모킹) 패턴을 `Popen`용으로 변형한다.

## Global Constraints

- `skills/skill_agent.py`는 수정하지 않는다 — `resume` 파라미터는 엔진 능력으로만 추가한다 (스펙 결정 사항).
- `resume` 기본값은 `False` — 기존 호출자(전부 `resume` 생략)는 동작이 100% 그대로 유지되어야 한다.
- `decide()`가 쓰는 세션 상태와 `run_task()`가 쓰는 세션 상태는 분리한다 — `decide()`는 무상태(호출자가 session_id를 직접 주고받음), `run_task()`만 `self._task_session_id`로 엔진 스스로 기억한다.

---

### Task 1: `run_task()` resume 파라미터 + 세션 저장/재사용

**Files:**
- Modify: `core/engines/claude_cli_engine.py`
- Test: `tests/test_claude_cli_engine_resume.py` (신규)

**Interfaces:**
- Produces: `ClaudeCliEngine.run_task(task: str, on_chunk: Callable[[str], None] | None = None, resume: bool = False) -> str` (기존 시그니처에 `resume` 추가), `ClaudeCliEngine._task_session_id: str | None` (인스턴스 속성)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_claude_cli_engine_resume.py`를 새로 만든다 (아직 `resume` 파라미터가
없어 `TypeError`로 실패해야 정상):

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m tests.test_claude_cli_engine_resume`
Expected: `TypeError: ClaudeCliEngine.run_task() got an unexpected keyword argument 'resume'`

- [ ] **Step 3: `resume` 파라미터 + 세션 저장/재사용 구현**

`core/engines/claude_cli_engine.py`의 `__init__`을 수정 (`core/engines/claude_cli_engine.py:77-79`):

```python
    def __init__(self, timeout: int = _DEFAULT_TIMEOUT) -> None:
        self._timeout = timeout
        self._persona = self._load_persona()
        self._task_session_id: str | None = None  # run_task()의 마지막 세션 (decide()와 별개)
```

`run_task()`의 시그니처와 명령 구성부를 수정 (`core/engines/claude_cli_engine.py:168-201`):

```python
    def run_task(
        self,
        task: str,
        on_chunk: Callable[[str], None] | None = None,
        resume: bool = False,
    ) -> str:
        """--dangerously-skip-permissions으로 모든 툴을 해제하고 태스크를 실행한다.

        computer_use, Bash, Edit, Write 등 Claude Code 전체 툴이 활성화된다.
        화면 캡처 → Claude Vision 인식 → 마우스/키보드 제어가 자동으로 이루어진다.

        Args:
            task: 실행할 태스크 설명 (자연어).
            on_chunk: 스트리밍 텍스트 청크를 실시간으로 받을 콜백.
                      진행 상황을 TTS로 알리거나 UI에 표시할 때 사용.
            resume: True이고 이전 run_task() 호출이 남긴 세션이 있으면
                    --resume으로 이어간다. CLAUDE.md/시스템 프롬프트를 매번
                    새로 로드하지 않아 후속 호출이 빨라진다. 저장된 세션이
                    없으면(첫 호출 등) 조용히 새 세션으로 시작한다.

        Returns:
            최종 응답 텍스트. 스트리밍 완료 후 result 이벤트에서 추출.
        """
        prompt = self._build_prompt(task)
        cmd = [
            "claude", "-p", prompt,
            "--dangerously-skip-permissions",
            "--output-format", "stream-json",
            "--verbose",  # CLI가 --output-format=stream-json에 필수로 요구
        ]
        if resume and self._task_session_id:
            cmd += ["--resume", self._task_session_id]
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=self._build_env(),
            )
        except FileNotFoundError:
            return "Claude Code CLI를 찾을 수 없습니다. 설치 여부와 PATH를 확인해주세요."
        except Exception as e:
            logger.error(f"Claude CLI Popen 오류: {e}")
            return f"Claude CLI 실행 오류: {e}"
```

(`try` 블록 위쪽만 교체 — 아래 stderr 드레인 스레드부터 함수 끝까지는 그대로
둔다. 단, `elif event_type == "result":` 분기 하나만 아래처럼 수정한다,
`core/engines/claude_cli_engine.py:243-249`):

```python
                elif event_type == "result":
                    cost = obj.get("total_cost_usd")
                    if isinstance(cost, (int, float)):
                        usage.record_cost(cost)
                    session_id = obj.get("session_id")
                    self._task_session_id = session_id if isinstance(session_id, str) else None
                    final = str(obj.get("result", "")).strip()
                    if final:
                        return final
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m tests.test_claude_cli_engine_resume`
Expected: 3개 테스트 모두 `[OK]`, 마지막 줄 `run_task() resume 배선 검증 통과`

- [ ] **Step 5: 회귀 확인**

Run: `python -m tests.test_claude_cli_engine_buffer` 와
`python -m tests.test_claude_cli_engine_decide_model` (기존 `_SentenceBuffer`,
`decide()`/`ask()` 배선에 영향 없는지 확인 — `__init__`에 속성 하나 추가한
것 외엔 그 경로들을 건드리지 않았으므로 그대로 통과해야 함)
Expected: 기존과 동일하게 통과

- [ ] **Step 6: 커밋**

```bash
git add core/engines/claude_cli_engine.py tests/test_claude_cli_engine_resume.py
git commit -m "feat: run_task()에 --resume 세션 재사용 능력 추가 (4-D)"
```

---

## 영향받는 파일 요약

| 파일 | 변경 내용 |
|------|-----------|
| `core/engines/claude_cli_engine.py` | `run_task()`에 `resume` 파라미터 + `self._task_session_id` 저장/재사용 |
| `tests/test_claude_cli_engine_resume.py` | 신규 — `run_task()` resume 배선 테스트 |
