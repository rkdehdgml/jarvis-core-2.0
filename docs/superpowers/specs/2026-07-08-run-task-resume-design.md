# 4-D. claude --resume 세션 유지 설계

> TODO.md 우선순위 4 항목 중 4-D 구현을 위한 설계 문서. 작성일: 2026-07-08.
> 사용자 지시로 확인 질문 없이 판단해 진행.

## 배경

`ClaudeCliEngine.decide()`는 이미 `session_id` 파라미터를 받아 `--resume`을
붙이고, 응답에서 다음 `session_id`를 뽑아 호출자(`hybrid_screen.py`,
`web_collector.py`)에게 돌려주는 패턴이 검증되어 있다(`_run_safe()`의
`session_id`/`_parse_json_result()` 참고). `run_task()`("풀파워 모드",
computer_use·Bash·Edit·Write 전체 툴 해제)는 이 패턴이 없어 매 호출마다
새 세션으로 시작한다 — CLAUDE.md/시스템 프롬프트를 매번 새로 로드해 느리다.

## 범위 결정

TODO.md 원래 설계 스케치의 **수정할 파일은 `core/engines/claude_cli_engine.py`
하나뿐**이다. 현재 `run_task()`의 유일한 호출자인 `skills/skill_agent.py`는
"팔로우업(이어서 하는 질문)" 감지 로직이 전혀 없다 — 언제 이전 세션을
재사용해야 하는지 판단하는 트리거 휴리스틱을 새로 만드는 건 그 자체로 별도
설계 결정(오탐 시 서로 무관한 조사 작업이 뒤섞일 위험)이라 이번 항목 범위를
넘는다고 판단했다. 따라서 이번 4-D는 **엔진에 재사용 가능한 능력만
추가**하고, `skill_agent.py`를 수정해 자동으로 켜지는 일은 하지 않는다
(향후 팔로우업 감지가 필요해지면 그때 별도 항목으로 다룬다).

## 설계

`ClaudeCliEngine.__init__`에 `self._task_session_id: str | None = None` 추가
(`decide()`가 쓰는 세션과는 별개 — `decide()`는 호출자가 session_id를 직접
주고받는 무상태 설계라 엔진 자신은 아무 것도 기억하지 않는다. `run_task()`는
엔진 인스턴스가 프로세스 생애주기 동안 재사용되므로(`AgentSkill.__init__`에서
한 번만 생성) 엔진이 마지막 세션을 스스로 기억하는 편이 자연스럽다).

`run_task(self, task: str, on_chunk=None, resume: bool = False) -> str`:
- `resume=True`이고 `self._task_session_id`가 있으면 명령에 `--resume
  <session_id>` 추가 (`decide()`와 동일한 조건문 패턴).
- 스트리밍 루프의 `event_type == "result"` 분기에서 기존 `cost` 기록에 더해
  `session_id = obj.get("session_id")`를 뽑아 `self._task_session_id`에
  저장(`_parse_json_result()`와 동일한 타입 체크 — 문자열이 아니면 `None`).
  다음 호출이 `resume=True`로 오면 이 값을 재사용한다.
- `resume=False`(기본값)이면 항상 새 세션으로 시작 — 기존 동작과 100% 동일,
  하위 호환.

## 테스트 방침

`pytest` 없음 — `tests/test_claude_cli_engine_decide_model.py`(subprocess.run
모킹) 패턴을 `run_task()`(subprocess.Popen 사용)에 맞게 변형한다. Popen을
대체하는 페이크 클래스로 `stdout`(stream-json 라인 이터러블), `stderr`(빈
이터러블), `wait()`, `returncode`, `kill()`을 최소 구현해 실제 프로세스 없이
검증한다.

- 1차 `run_task()` 호출(결과에 `session_id: "sess-1"` 포함) 후 `resume=True`로
  2차 호출 시 명령에 `--resume sess-1`이 포함되는지 확인.
- `resume=False`(또는 생략)면 이전 세션이 있어도 `--resume`이 붙지 않는지 확인.
- 첫 호출처럼 저장된 세션이 없는 상태에서 `resume=True`를 줘도 `--resume`이
  붙지 않는지(예외 없이 새 세션으로 폴백) 확인.

## 영향받는 파일 요약

| 파일 | 변경 내용 |
|------|-----------|
| `core/engines/claude_cli_engine.py` | `run_task()`에 `resume` 파라미터 + `self._task_session_id` 저장/재사용 |
| `tests/test_claude_cli_engine_resume.py` | 신규 — `run_task()` resume 배선 테스트 |
