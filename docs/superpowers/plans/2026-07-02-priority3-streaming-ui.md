# 우선순위 3 — 스트리밍·UI 개선 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `run_task()`의 TTS 청크를 문장 단위로 버퍼링하고, 장시간 작업 중 `"streaming"` 상태를
방송하며, Claude Code 훅의 진행 상황 메시지를 웹 대시보드에 실시간 임시 말풍선으로 보여준다.

**Architecture:** 백엔드 3곳(`core/engines/claude_cli_engine.py`, `core/status_events.py` +
두 스킬, `ui/server.py`)과 프론트엔드 1곳(`useJarvisStatus.ts`)을 독립적으로 수정한다.
`core/dispatcher.py`는 건드리지 않고, 장시간 작업을 시작하는 스킬(`skill_agent.py`,
`skill_screen_agent.py`)이 자기 `execute()` 안에서 직접 `"streaming"`을 emit한다.

**Tech Stack:** Python 3.13 / FastAPI / Starlette TestClient (테스트용, httpx 백엔드) /
TypeScript + React 18 + Vite.

## Global Constraints

- `core/dispatcher.py`는 수정하지 않는다 (프로젝트의 "core는 동결" 원칙, 스펙 3-B).
- 문장 종결 문자는 `.`, `!`, `?`, `。`, `\n` 5종 고정 (스펙 3-A).
- 훅 메시지 타입은 `tool_action`, `output` 2종 고정 (스펙 3-C/3-D).
- 이 프로젝트에는 `pytest`가 없다. 모든 Python 테스트는 plain assert 스크립트로 작성하고
  `python -m tests.<module>` (프로젝트 루트에서)로 실행한다. `main()` 함수 + 마지막에
  `print("\n<모듈명> 검증 통과")` 컨벤션을 따른다 (`tests/test_skill_datetime.py` 참고).
- 프론트엔드(`ui/web`)에는 JS 테스트 러너가 없다. 검증은 `npm run typecheck` (0 에러) +
  수동 브라우저 확인으로 한다.
- 각 Task는 완료 후 그 Task에서 변경한 파일만 골라 커밋한다 (다른 Task의 변경분을 섞지 않음).

---

### Task 1: TTS 문장 버퍼링 (`_SentenceBuffer`)

**Files:**
- Modify: `core/engines/claude_cli_engine.py:39` (새 클래스 삽입), `core/engines/claude_cli_engine.py:165-203` (`run_task()` 내부 배선)
- Test: `tests/test_claude_cli_engine_buffer.py`

**Interfaces:**
- Produces: `core.engines.claude_cli_engine._SentenceBuffer` — `__init__(self, on_chunk: Callable[[str], None] | None) -> None`, `.feed(chunk: str) -> None`, `.flush() -> None`. 이후 Task에서는 이 클래스를 직접 사용하지 않지만, `run_task()`의 스트리밍 동작이 이 클래스에 위임된다는 사실만 알면 됨.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_claude_cli_engine_buffer.py` 신규 생성:

```python
"""ClaudeCliEngine._SentenceBuffer 문장 버퍼링 검증 (plain assert 스크립트).

실행: python -m tests.test_claude_cli_engine_buffer  (프로젝트 루트에서)
"""
from core.engines.claude_cli_engine import _SentenceBuffer


def main() -> None:
    received: list[str] = []
    buf = _SentenceBuffer(received.append)

    # 문장이 여러 청크로 쪼개져 들어와도 종결부호를 만나기 전까지는 호출되지 않는다.
    buf.feed("안녕")
    buf.feed("하세요")
    assert received == [], f"종결부호 전에는 호출되면 안 됨: {received}"

    buf.feed(".")
    assert received == ["안녕하세요."], f"문장 종결 시 1회 호출돼야 함: {received}"

    # 다음 문장 조각들도 동일하게 동작
    buf.feed(" 반갑")
    buf.feed("습니다!")
    assert received == ["안녕하세요.", "반갑습니다!"], received

    # 잔여 버퍼는 flush()로만 방출된다
    buf.feed("마무리 중")
    assert received == ["안녕하세요.", "반갑습니다!"], "flush 전에는 방출되면 안 됨"
    buf.flush()
    assert received == ["안녕하세요.", "반갑습니다!", "마무리 중"], received

    # flush 이후 버퍼는 비어 있어 다시 flush해도 추가 호출이 없다
    buf.flush()
    assert received == ["안녕하세요.", "반갑습니다!", "마무리 중"], "빈 버퍼 flush는 무동작이어야 함"

    # on_chunk가 None이면 아무 것도 호출하지 않고 조용히 무시
    silent_buf = _SentenceBuffer(None)
    silent_buf.feed("아무 일도 안 일어남.")
    silent_buf.flush()  # 예외 없이 통과하면 성공

    print("\ntest_claude_cli_engine_buffer 검증 통과")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m tests.test_claude_cli_engine_buffer`
Expected: `ImportError: cannot import name '_SentenceBuffer' from 'core.engines.claude_cli_engine'`

- [ ] **Step 3: `_SentenceBuffer` 구현**

`core/engines/claude_cli_engine.py:39` (`_SAFE_TOOLS = ["WebSearch", "WebFetch"]` 바로 다음)에 삽입:

```python
_SAFE_TOOLS = ["WebSearch", "WebFetch"]


class _SentenceBuffer:
    """텍스트 청크를 모았다가 문장 종결부호를 만나면 on_chunk로 흘려보낸다.

    stream-json의 assistant 텍스트 블록이 문장 중간에서 쪼개져 오면 TTS가
    어색하게 끊기는 문제를 막기 위함 — 종결부호를 볼 때까지 누적한다.
    """

    _SENTENCE_END = (".", "!", "?", "。", "\n")

    def __init__(self, on_chunk: "Callable[[str], None] | None") -> None:
        self._on_chunk = on_chunk
        self._buf = ""

    def feed(self, chunk: str) -> None:
        self._buf += chunk
        if self._on_chunk and self._buf.rstrip().endswith(self._SENTENCE_END):
            sentence = self._buf.strip()
            if sentence:
                self._on_chunk(sentence)
            self._buf = ""

    def flush(self) -> None:
        if self._on_chunk and self._buf.strip():
            self._on_chunk(self._buf.strip())
        self._buf = ""
```

(`Callable`은 파일 상단에 이미 `from typing import Callable`로 import돼 있으므로 문자열
타입힌트 없이 `Callable[[str], None] | None`로 써도 되지만, 위와 동일하게 동작한다 —
따옴표 없이 작성해도 무방함.)

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `python -m tests.test_claude_cli_engine_buffer`
Expected: `test_claude_cli_engine_buffer 검증 통과` 출력, exit code 0

- [ ] **Step 5: `run_task()`에 배선**

`core/engines/claude_cli_engine.py`의 `run_task()` 내부, 현재 이 부분:

```python
        collected: list[str] = []
        try:
            assert proc.stdout
            for raw_line in proc.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event_type = obj.get("type", "")

                if event_type == "assistant":
                    for block in obj.get("message", {}).get("content", []):
                        if isinstance(block, dict) and block.get("type") == "text":
                            chunk = block["text"]
                            collected.append(chunk)
                            if on_chunk and chunk.strip():
                                on_chunk(chunk)

                elif event_type == "result":
                    cost = obj.get("total_cost_usd")
                    if isinstance(cost, (int, float)):
                        usage.record_cost(cost)
                    final = str(obj.get("result", "")).strip()
                    if final:
                        return final

        except Exception as e:
            logger.error(f"stream-json 파싱 오류: {e}")
        finally:
            try:
                proc.wait(timeout=_TASK_TIMEOUT)
            except subprocess.TimeoutExpired:
                logger.error("run_task 타임아웃 — 프로세스 강제 종료")
                proc.kill()
            stderr_thread.join(timeout=2)
```

다음으로 교체:

```python
        collected: list[str] = []
        sentence_buffer = _SentenceBuffer(on_chunk)
        try:
            assert proc.stdout
            for raw_line in proc.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event_type = obj.get("type", "")

                if event_type == "assistant":
                    for block in obj.get("message", {}).get("content", []):
                        if isinstance(block, dict) and block.get("type") == "text":
                            chunk = block["text"]
                            collected.append(chunk)
                            sentence_buffer.feed(chunk)

                elif event_type == "result":
                    cost = obj.get("total_cost_usd")
                    if isinstance(cost, (int, float)):
                        usage.record_cost(cost)
                    final = str(obj.get("result", "")).strip()
                    if final:
                        return final

        except Exception as e:
            logger.error(f"stream-json 파싱 오류: {e}")
        finally:
            try:
                proc.wait(timeout=_TASK_TIMEOUT)
            except subprocess.TimeoutExpired:
                logger.error("run_task 타임아웃 — 프로세스 강제 종료")
                proc.kill()
            stderr_thread.join(timeout=2)
            sentence_buffer.flush()
```

(`return final`로 함수가 조기 반환되는 정상 종료 경로에서도 `finally` 블록은 항상
실행되므로 `sentence_buffer.flush()`가 호출된다 — 다만 그 시점엔 이미 함수 반환값이
확정된 뒤이므로 flush로 나온 마지막 문장은 `on_chunk`에는 전달되지만 반환값 `final`에는
영향을 주지 않는다. 이는 기존 동작과 동일하다: `collected`는 반환값 조립에 쓰이지 않고
`final`만 쓰인다.)

- [ ] **Step 6: 회귀 확인**

Run: `python -m tests.test_claude_cli_engine_buffer`
Expected: 여전히 `test_claude_cli_engine_buffer 검증 통과`

Run: `python -c "from core.engines.claude_cli_engine import ClaudeCliEngine; print(ClaudeCliEngine().describe())"`
Expected: `{'provider': 'Claude Code', 'model': 'Claude Code CLI', 'connected': True, ...}` (기존 2-B 검증과 동일 — import/구문 오류가 없음을 빠르게 확인)

- [ ] **Step 7: 커밋**

```bash
git add core/engines/claude_cli_engine.py tests/test_claude_cli_engine_buffer.py
git commit -m "feat: run_task() TTS 청크를 문장 단위로 버퍼링 (3-A)"
```

---

### Task 2: `"streaming"` 상태 추가

**Files:**
- Modify: `core/status_events.py:8`
- Test: `tests/test_status_events_streaming.py`

**Interfaces:**
- Consumes: 없음 (독립).
- Produces: `core.status_events.State`가 `"streaming"`을 허용 리터럴로 포함. Task 3/4는
  `broadcaster.emit(state="streaming")`을 호출하며 이 값에 의존한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_status_events_streaming.py` 신규 생성:

```python
"""status_events.py streaming 상태 추가 검증 (plain assert 스크립트).

실행: python -m tests.test_status_events_streaming  (프로젝트 루트에서)
"""
from core.status_events import StatusBroadcaster


def main() -> None:
    broadcaster = StatusBroadcaster()
    received = []
    broadcaster.subscribe(received.append)

    broadcaster.emit(state="streaming")

    assert len(received) == 1, received
    assert received[0].state == "streaming", received[0].state
    assert broadcaster.get_current().state == "streaming"

    print("\ntest_status_events_streaming 검증 통과")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 테스트 실행**

Run: `python -m tests.test_status_events_streaming`
Expected: `State` Literal에 없는 값이라도 파이썬은 런타임에 `Literal`을 강제하지 않으므로
이 테스트는 변경 전에도 **통과한다** (타입 체커만 잡아낸다). 그래도 정적 타입 안전성을
위해 다음 Step을 진행한다.

- [ ] **Step 3: `State` Literal에 `"streaming"` 추가**

`core/status_events.py:8`:

```python
State = Literal["idle", "listening", "processing", "responded", "navigation_request"]
```

다음으로 교체:

```python
State = Literal["idle", "listening", "processing", "streaming", "responded", "navigation_request"]
```

- [ ] **Step 4: 테스트 재실행 (여전히 통과해야 함)**

Run: `python -m tests.test_status_events_streaming`
Expected: `test_status_events_streaming 검증 통과`

- [ ] **Step 5: 커밋**

```bash
git add core/status_events.py tests/test_status_events_streaming.py
git commit -m "feat: status_events State에 streaming 상태 추가 (3-B)"
```

---

### Task 3: `skill_agent.py` — `run_task()` 호출 전 streaming emit

**Files:**
- Modify: `skills/skill_agent.py:13-18` (import), `skills/skill_agent.py:47-56` (`execute()`)
- Test: `tests/test_skill_agent_streaming.py`

**Interfaces:**
- Consumes: `core.status_events.broadcaster` (Task 2에서 `"streaming"`이 유효 상태가 됨), `core.status_events.broadcaster.get_current() -> StatusEvent`(`.state: str`).
- Produces: 없음 (최종 소비 지점).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_skill_agent_streaming.py` 신규 생성:

```python
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
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m tests.test_skill_agent_streaming`
Expected: `AssertionError: run_task 호출 시점 상태: processing` (Dispatcher가 찍는 기본값이 아니라, 아직 아무도 emit하지 않아 `StatusBroadcaster` 기본 초기 상태 `"idle"`이 나올 수도 있음 — 어느 쪽이든 `"streaming"`이 아니므로 AssertionError 발생)

- [ ] **Step 3: `skill_agent.py`에 streaming emit 추가**

`skills/skill_agent.py:13-18`:

```python
import logging

from core.engines.claude_cli_engine import ClaudeCliEngine
from core.skill_base import Skill, SkillResult

logger = logging.getLogger(__name__)
```

다음으로 교체:

```python
import logging

from core.engines.claude_cli_engine import ClaudeCliEngine
from core.skill_base import Skill, SkillResult
from core.status_events import broadcaster

logger = logging.getLogger(__name__)
```

`skills/skill_agent.py:47-56` (`execute()` 전체):

```python
    def execute(self, text: str, context: dict) -> SkillResult:
        tts_callback = None
        try:
            from voice import tts as _tts
            tts_callback = _tts.speak
        except Exception:
            pass

        result = self._engine.run_task(text, on_chunk=tts_callback)
        return SkillResult(speech=result, success=True, data={"task": text})
```

다음으로 교체:

```python
    def execute(self, text: str, context: dict) -> SkillResult:
        tts_callback = None
        try:
            from voice import tts as _tts
            tts_callback = _tts.speak
        except Exception:
            pass

        broadcaster.emit(state="streaming")
        result = self._engine.run_task(text, on_chunk=tts_callback)
        return SkillResult(speech=result, success=True, data={"task": text})
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `python -m tests.test_skill_agent_streaming`
Expected: `test_skill_agent_streaming 검증 통과`

- [ ] **Step 5: 커밋**

```bash
git add skills/skill_agent.py tests/test_skill_agent_streaming.py
git commit -m "feat: skill_agent run_task 호출 전 streaming 상태 emit (3-B)"
```

---

### Task 4: `skill_screen_agent.py` — `engine.run()` 호출 전 streaming emit

**Files:**
- Modify: `skills/skill_screen_agent.py:15-19` (import), `skills/skill_screen_agent.py:54-64` (`execute()`)
- Test: `tests/test_skill_screen_agent_streaming.py`

**Interfaces:**
- Consumes: `core.status_events.broadcaster` (Task 2).
- Produces: 없음 (최종 소비 지점).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_skill_screen_agent_streaming.py` 신규 생성:

```python
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
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m tests.test_skill_screen_agent_streaming`
Expected: `AssertionError: engine.run() 호출 시점 상태: ...` (`"streaming"`이 아닌 값)

- [ ] **Step 3: `skill_screen_agent.py`에 streaming emit 추가**

`skills/skill_screen_agent.py:15-19`:

```python
import logging

from core.hybrid_screen import HybridScreenEngine
from core.skill_base import Skill, SkillResult

logger = logging.getLogger(__name__)
```

다음으로 교체:

```python
import logging

from core.hybrid_screen import HybridScreenEngine
from core.skill_base import Skill, SkillResult
from core.status_events import broadcaster

logger = logging.getLogger(__name__)
```

`skills/skill_screen_agent.py:54-64` (`execute()` 전체):

```python
    def execute(self, text: str, context: dict) -> SkillResult:
        tts_callback = None
        try:
            from voice import tts as _tts
            tts_callback = _tts.speak
        except Exception:
            pass

        engine = HybridScreenEngine(on_chunk=tts_callback)
        result = engine.run(task=text)
        return SkillResult(speech=result, success=True, data={"task": text})
```

다음으로 교체:

```python
    def execute(self, text: str, context: dict) -> SkillResult:
        tts_callback = None
        try:
            from voice import tts as _tts
            tts_callback = _tts.speak
        except Exception:
            pass

        broadcaster.emit(state="streaming")
        engine = HybridScreenEngine(on_chunk=tts_callback)
        result = engine.run(task=text)
        return SkillResult(speech=result, success=True, data={"task": text})
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `python -m tests.test_skill_screen_agent_streaming`
Expected: `test_skill_screen_agent_streaming 검증 통과`

- [ ] **Step 5: 커밋**

```bash
git add skills/skill_screen_agent.py tests/test_skill_screen_agent_streaming.py
git commit -m "feat: skill_screen_agent engine.run 호출 전 streaming 상태 emit (3-B)"
```

---

### Task 5: `ui/server.py` — 훅 WebSocket 메시지 브로드캐스트

**Files:**
- Modify: `ui/server.py:12` (import), `ui/server.py:109-119` (신규 `_broadcast_raw` 추가 위치), `ui/server.py:176-191` (`ws_endpoint`)
- Test: `tests/test_ui_hook_broadcast.py`

**Interfaces:**
- Consumes: 없음 (독립).
- Produces: `/ws` 엔드포인트가 `{"type": "tool_action"|"output", "value": str}` 형태의 수신
  메시지를 다른 모든 연결된 클라이언트에 동일한 shape로 그대로 재전송함. Task 6(프론트엔드)이
  이 shape(`type`/`value` 키)를 그대로 소비한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_ui_hook_broadcast.py` 신규 생성:

```python
"""ui/server.py 훅 메시지 WebSocket 브로드캐스트 검증 (plain assert 스크립트).

FastAPI TestClient로 실제 uvicorn 기동 없이 두 WebSocket 클라이언트를 연결해,
한쪽이 보낸 tool_action 메시지를 다른 쪽이 그대로 수신하는지 확인한다.

실행: python -m tests.test_ui_hook_broadcast  (프로젝트 루트에서)
"""
from fastapi.testclient import TestClient

from ui.server import app


def main() -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as browser_ws, \
             client.websocket_connect("/ws") as hook_ws:
            # 연결 직후 각자 현재 상태 스냅샷을 한 번씩 받는다 (기존 동작).
            browser_ws.receive_json()
            hook_ws.receive_json()

            hook_ws.send_text('{"type": "tool_action", "value": "웹 검색 중: 날씨"}')

            received = browser_ws.receive_json()
            assert received["type"] == "tool_action", received
            assert received["value"] == "웹 검색 중: 날씨", received

            # 알 수 없는 타입은 무시되어 아무 것도 도착하지 않아야 한다 —
            # output 타입으로 한 번 더 보내 정상 케이스만 확인.
            hook_ws.send_text('{"type": "output", "value": "작업 완료"}')
            received2 = browser_ws.receive_json()
            assert received2["type"] == "output", received2
            assert received2["value"] == "작업 완료", received2

    print("\ntest_ui_hook_broadcast 검증 통과")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m tests.test_ui_hook_broadcast`
Expected: 두 번째 `browser_ws.receive_json()`(첫 번째 tool_action 대기) 호출에서 타임아웃/예외
발생 — 현재 `ws_endpoint`는 받은 메시지를 버리기만 하고 아무것도 재전송하지 않기 때문.

- [ ] **Step 3: `import json` 추가**

`ui/server.py:12`:

```python
import asyncio
import logging
import os
```

다음으로 교체:

```python
import asyncio
import json
import logging
import os
```

- [ ] **Step 4: `_broadcast_raw` 헬퍼와 훅 메시지 처리 추가**

`ui/server.py`의 기존 `async def _broadcast(event: StatusEvent) -> None:` 함수(109-119번째 줄) 바로 뒤에 삽입:

```python
_HOOK_MESSAGE_TYPES = ("tool_action", "output")


async def _broadcast_raw(payload: dict) -> None:
    """훅(jarvis_send.py)이 보낸 원본 페이로드를 모든 클라이언트에 그대로 중계한다."""
    dead: list[WebSocket] = []
    for ws in _clients:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _clients.discard(ws)
```

`ui/server.py:176-191`의 `ws_endpoint` 전체:

```python
@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    _clients.add(websocket)

    # 연결 즉시 현재 상태를 한 번 보낸다.
    await websocket.send_json(_event_to_dict(broadcaster.get_current()))

    try:
        while True:
            # 클라이언트는 보통 메시지를 보내지 않지만, 연결 유지를 위해 수신 대기.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(websocket)
```

다음으로 교체:

```python
@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    _clients.add(websocket)

    # 연결 즉시 현재 상태를 한 번 보낸다.
    await websocket.send_json(_event_to_dict(broadcaster.get_current()))

    try:
        while True:
            # 브라우저 클라이언트는 보통 메시지를 보내지 않지만, 훅(jarvis_send.py)은
            # {"type": "tool_action"|"output", "value": ...}를 보내고 바로 끊는다 —
            # 수신 즉시 파싱해 다른 클라이언트에 브로드캐스트한다.
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("type") in _HOOK_MESSAGE_TYPES:
                await _broadcast_raw(data)
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(websocket)
```

- [ ] **Step 5: 테스트 실행 → 통과 확인**

Run: `python -m tests.test_ui_hook_broadcast`
Expected: `test_ui_hook_broadcast 검증 통과`

- [ ] **Step 6: 기존 훅 수동 검증 재확인 (회귀 없음 확인)**

Run (터미널 1): `uvicorn ui.server:app --host 127.0.0.1 --port 8765`
Run (터미널 2):
```powershell
echo '{"result": "테스트 응답입니다"}' | python hooks/jarvis_hook.py
echo '{"tool_name": "WebSearch", "tool_input": {"query": "날씨"}, "tool_response": {}}' | python hooks/jarvis_tool_hook.py
```
Expected: 두 명령 모두 예외 없이 종료 (exit 0) — 기존 2-C 검증과 동일 절차, 회귀 없음 확인용.

- [ ] **Step 7: 커밋**

```bash
git add ui/server.py tests/test_ui_hook_broadcast.py
git commit -m "feat: ws_endpoint 훅 메시지(tool_action/output) 브로드캐스트 (3-C)"
```

---

### Task 6: `useJarvisStatus.ts` — 프론트엔드 실시간 진행 표시(임시 말풍선)

**Files:**
- Modify: `ui/web/hooks/useJarvisStatus.ts:5-9` (`ConversationTurn`), `ui/web/hooks/useJarvisStatus.ts:94-103` (인터페이스 영역에 `HookMessagePayload` 추가), `ui/web/hooks/useJarvisStatus.ts:147-323` (`handlePush` 내 responded 처리부 + `handleHookMessage` 신규), `ui/web/hooks/useJarvisStatus.ts:325-346` (`connect`)

**Interfaces:**
- Consumes: Task 5가 만든 `/ws` 브로드캐스트 payload shape `{"type": "tool_action"|"output", "value": string}`.
- Produces: `ConversationTurn.transient?: boolean` — `JarvisMinimal.tsx`/`JarvisFull.tsx`가 향후 이 필드로 임시 말풍선을 다르게 스타일링할 수 있음(이번 Task에서는 컴포넌트 스타일링은 범위 밖, 데이터만 흘려보냄).

- [ ] **Step 1: `ConversationTurn`에 `transient` 필드 추가**

`ui/web/hooks/useJarvisStatus.ts:5-9`:

```typescript
export interface ConversationTurn {
  role: "user" | "jarvis";
  text: string;
  timestamp: number;
}
```

다음으로 교체:

```typescript
export interface ConversationTurn {
  role: "user" | "jarvis";
  text: string;
  timestamp: number;
  transient?: boolean;   // tool_action 진행 표시용 임시 말풍선
}
```

- [ ] **Step 2: `HookMessagePayload` 인터페이스 추가**

`ui/web/hooks/useJarvisStatus.ts:94-103`(`interface WsPushPayload { ... }` 블록) 바로 뒤에 삽입:

```typescript
interface HookMessagePayload {
  type: "tool_action" | "output";
  value: string;
}
```

- [ ] **Step 3: `handlePush`의 responded 처리부를 transient 제거 로직으로 교체**

`ui/web/hooks/useJarvisStatus.ts:161-166`:

```typescript
      if (isNewEvent && payload.state === "responded" && payload.lastResponse) {
        next.conversationLog = [
          ...prev.conversationLog,
          { role: "jarvis", text: payload.lastResponse, timestamp: payload.timestamp },
        ];
      }
```

다음으로 교체:

```typescript
      if (isNewEvent && payload.state === "responded") {
        const lastTurn = prev.conversationLog[prev.conversationLog.length - 1];
        const withoutTransient = lastTurn?.transient
          ? prev.conversationLog.slice(0, -1)
          : prev.conversationLog;
        next.conversationLog = payload.lastResponse
          ? [...withoutTransient, { role: "jarvis", text: payload.lastResponse, timestamp: payload.timestamp }]
          : withoutTransient;
      }
```

- [ ] **Step 4: `handleHookMessage` 콜백 추가**

`ui/web/hooks/useJarvisStatus.ts`에서 `handlePush` 콜백 정의(현재 147번째 줄 `const handlePush = useCallback(...)`)가 끝나는 지점, 즉 `}, []);`(323번째 줄) 바로 뒤에 삽입:

```typescript

  const handleHookMessage = useCallback((msg: HookMessagePayload) => {
    setStatus((prev) => {
      const lastTurn = prev.conversationLog[prev.conversationLog.length - 1];
      const isLastTransient = lastTurn?.transient === true;

      if (msg.type === "tool_action") {
        const updatedTurn: ConversationTurn = {
          role: "jarvis",
          text: msg.value,
          timestamp: Date.now(),
          transient: true,
        };
        const conversationLog = isLastTransient
          ? [...prev.conversationLog.slice(0, -1), updatedTurn]
          : [...prev.conversationLog, updatedTurn];
        return { ...prev, conversationLog };
      }

      // type === "output": 임시 말풍선 제거만 한다 — 실제 텍스트는 곧 오는
      // "responded" 상태 이벤트가 채운다.
      if (isLastTransient) {
        return { ...prev, conversationLog: prev.conversationLog.slice(0, -1) };
      }
      return prev;
    });
  }, []);
```

- [ ] **Step 5: `ws.onmessage`에서 훅 메시지와 상태 이벤트 분기**

`ui/web/hooks/useJarvisStatus.ts:329-336`:

```typescript
    ws.onmessage = (event: MessageEvent<string>) => {
      try {
        const payload = JSON.parse(event.data) as WsPushPayload;
        handlePush(payload);
      } catch {
        // 파싱 실패한 페이로드는 무시
      }
    };
```

다음으로 교체:

```typescript
    ws.onmessage = (event: MessageEvent<string>) => {
      try {
        const payload = JSON.parse(event.data) as WsPushPayload | HookMessagePayload;
        if ("type" in payload) {
          handleHookMessage(payload);
        } else {
          handlePush(payload);
        }
      } catch {
        // 파싱 실패한 페이로드는 무시
      }
    };
```

`ui/web/hooks/useJarvisStatus.ts:346`의 `connect` 의존성 배열도 갱신:

```typescript
  }, [handlePush]);
```

다음으로 교체:

```typescript
  }, [handlePush, handleHookMessage]);
```

- [ ] **Step 6: 타입체크**

Run: `cd ui/web && npm run typecheck`
Expected: 에러 0개로 종료

- [ ] **Step 7: 수동 브라우저 검증**

터미널 1: `uvicorn ui.server:app --host 127.0.0.1 --port 8765`
터미널 2: `cd ui/web && npm run dev` → `http://localhost:5173` 접속
터미널 3: `python main.py --text` → `"화면 제어로 메모장에 안녕 입력해줘"` 같은 화면 제어
요청을 입력해 실제 훅이 발화하는 조건을 만든다.

확인 포인트:
- 작업 진행 중 채팅 로그 맨 아래에 임시 말풍선이 나타나고, 새 tool_action이 올 때마다
  **새로 쌓이지 않고** 텍스트만 갱신되는지
- 작업 완료 후 임시 말풍선이 사라지고 최종 응답 말풍선으로 자연스럽게 교체되는지
- 페이지를 새로고침해도(=WS 재연결) 깨지지 않는지

- [ ] **Step 8: 커밋**

```bash
git add ui/web/hooks/useJarvisStatus.ts
git commit -m "feat: 채팅 로그에 tool_action 임시 말풍선 실시간 표시 (3-D)"
```

---

## 전체 검증 (모든 Task 완료 후)

- [ ] Run: `python -m tests.test_claude_cli_engine_buffer`
- [ ] Run: `python -m tests.test_status_events_streaming`
- [ ] Run: `python -m tests.test_skill_agent_streaming`
- [ ] Run: `python -m tests.test_skill_screen_agent_streaming`
- [ ] Run: `python -m tests.test_ui_hook_broadcast`
- [ ] Run: `cd ui/web && npm run typecheck`
- [ ] TODO.md 우선순위 3 표(3-A~3-D)를 "✅ 완료"로 갱신하고 커밋
