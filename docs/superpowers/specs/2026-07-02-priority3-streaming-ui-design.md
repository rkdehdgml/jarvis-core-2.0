# 우선순위 3 — 스트리밍·UI 개선 설계

> TODO.md 우선순위 3 (3-A~3-D) 구현을 위한 설계 문서. 작성일: 2026-07-02.

## 배경

`ClaudeCliEngine.run_task()`와 `HybridScreenEngine`은 장시간(최대 600초) 멀티스텝 작업을
수행하는데, 현재 UI/음성 쪽에 다음 세 가지 문제가 있다.

1. `run_task()`의 `on_chunk` 콜백이 stream-json의 텍스트 블록 단위로 호출돼, TTS로 읽을 때
   문장이 부자연스럽게 끊긴다.
2. 장시간 작업 중에도 상태는 `"processing"`(Dispatcher가 실행 직전 1회 emit) 그대로 고정돼,
   실제로 몇 분간 무엇이 진행 중인지 UI에서 알 수 없다.
3. Claude Code 훅(`jarvis_send.py`)이 `/ws`에 `tool_action`/`output` 메시지를 보내지만,
   서버(`ui/server.py`)가 이를 수신만 하고 버려서 브라우저에 전달되지 않는다.

## 범위

TODO.md 우선순위 3의 3-A~3-D 전체. 3-A는 `skill_agent.py`(웹 조사 에이전트)에만 영향—
`skill_screen_agent.py`가 쓰는 `HybridScreenEngine.on_chunk`는 이미 스텝 단위(완결 문장)로
호출되므로(`core/hybrid_screen.py:184-186`) 버퍼링 대상에서 제외한다.

## 3-A. TTS 문장 버퍼링

**파일**: `core/engines/claude_cli_engine.py` (`run_task()`)

stream-json 루프에서 `on_chunk(chunk)`를 즉시 호출하는 대신 버퍼에 누적하고, 버퍼가
문장 종결 문자(`.`, `!`, `?`, `。`, `\n`)로 끝날 때만 `on_chunk(sentence)`를 호출한다.
루프 종료 후 잔여 버퍼가 있으면 마지막으로 한 번 더 flush한다.

```python
_SENTENCE_END = (".", "!", "?", "。", "\n")
buf = ""
...
if event_type == "assistant":
    for block in ...:
        chunk = block["text"]
        collected.append(chunk)
        buf += chunk
        if on_chunk and buf.rstrip().endswith(_SENTENCE_END):
            sentence = buf.strip()
            if sentence:
                on_chunk(sentence)
            buf = ""
...
finally:
    if on_chunk and buf.strip():
        on_chunk(buf.strip())
```

`collected`(최종 반환값 조립용)는 그대로 유지 — 버퍼링은 `on_chunk` 호출 타이밍에만 영향.

## 3-B. `"streaming"` 상태 추가

**파일**: `core/status_events.py`, `skills/skill_agent.py`, `skills/skill_screen_agent.py`

`core/status_events.py`의 `State` Literal에 `"streaming"` 추가:

```python
State = Literal["idle", "listening", "processing", "streaming", "responded", "navigation_request"]
```

`core/dispatcher.py`(core, 동결 대상)는 건드리지 않는다. 대신 장시간 작업을 시작하는
두 스킬이 자기 `execute()` 안에서 엔진 호출 직전에 직접 emit한다:

```python
# skill_agent.py execute() — self._engine.run_task() 호출 직전
from core.status_events import broadcaster
broadcaster.emit(state="streaming")
result = self._engine.run_task(text, on_chunk=tts_callback)
```

```python
# skill_screen_agent.py execute() — engine.run() 호출 직전
from core.status_events import broadcaster
broadcaster.emit(state="streaming")
result = engine.run(task=text)
```

Dispatcher가 실행 직전 찍어둔 `"processing"`을 작업 시작 시점에 `"streaming"`으로 덮어쓰고,
작업 완료 후에는 Dispatcher의 기존 `"responded"` emit이 그대로 마무리한다.

## 3-C. 훅 WebSocket 브로드캐스트

**파일**: `ui/server.py` (`ws_endpoint`)

훅(`hooks/jarvis_send.py`)은 `/ws`에 단발성으로 접속해
`{"type": "tool_action"|"output", "value": "..."}`를 보내고 바로 끊는다. 현재
`ws_endpoint`의 수신 루프는 `await websocket.receive_text()`만 하고 반환값을 버린다.

수신한 텍스트를 JSON 파싱해 `type`이 `tool_action`/`output`이면 전체 연결된 클라이언트에
그대로 브로드캐스트하는 로직을 추가한다 (파싱 실패나 다른 타입은 무시):

```python
try:
    while True:
        raw = await websocket.receive_text()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if data.get("type") in ("tool_action", "output"):
            dead = []
            for ws in _clients:
                try:
                    await ws.send_json(data)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                _clients.discard(ws)
except WebSocketDisconnect:
    pass
finally:
    _clients.discard(websocket)
```

브로드캐스트 대상에 보낸 쪽(훅 연결) 자신도 포함되지만, 훅은 메시지 전송 직후 곧바로
연결을 끊으므로 무해하다. 기존 `_broadcast()`(StatusEvent 전용, `_event_to_dict` 포맷)와는
페이로드 shape가 다르므로 재사용하지 않고 별도 처리한다.

## 3-D. 프론트엔드 실시간 진행 표시

**파일**: `ui/web/hooks/useJarvisStatus.ts`

`ConversationTurn`에 선택 필드 추가:

```typescript
export interface ConversationTurn {
  role: "user" | "jarvis";
  text: string;
  timestamp: number;
  transient?: boolean;   // tool_action 진행 표시용 임시 말풍선
}
```

WebSocket 메시지 핸들러에서 `state` 필드가 있으면 기존 `WsPushPayload`로, `type` 필드가
있으면 훅 메시지로 분기:

```typescript
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === "tool_action" || data.type === "output") {
    handleHookMessage(data);
  } else {
    handlePush(data);
  }
};
```

`handleHookMessage` 동작:
- `type === "tool_action"`: `conversationLog`의 마지막 항목이 `transient === true`면 그
  항목의 `text`/`timestamp`만 교체, 아니면 `{ role: "jarvis", text: value, timestamp, transient: true }`를
  새로 추가. 즉 "지금 하는 일" 1개만 항상 최신 상태로 유지하고 액션마다 쌓이지 않는다.
- `type === "output"`: 마지막 항목이 `transient === true`면 제거만 하고 텍스트는 채우지
  않는다. 곧이어 오는 정식 `responded` 이벤트(`state` 필드 payload)가 실제 최종 답변을 붙인다.

`handlePush`에서 `isNewEvent && payload.state === "responded"`로 실제 턴을 추가하는 지점
직전에도, 로그에 남아있는 `transient` 항목을 먼저 제거한다 (훅이 UI 서버 미기동 등으로
`output`을 못 보낸 경우에 대한 안전장치).

## 테스트 방침

기존 프로젝트에 `pytest` 없음 — `tests/`의 assert 기반 스크립트 컨벤션을 따른다.

- 3-A: `run_task()`의 stream-json 파싱 루프에 대해 가짜 stdout(문장이 여러 청크로
  쪼개진 JSON 라인들)을 주입해 `on_chunk`가 문장 단위로만 호출되는지 검증하는 단위
  테스트를 `tests/`에 추가할 수 있는지 검토 (subprocess.Popen을 직접 모킹해야 해서
  난이도가 있으면 수동 검증으로 대체하고 계획에 명시).
- 3-B: `broadcaster.emit(state="streaming")`이 예외 없이 동작하는지, `State` Literal
  타입 체크(정적)로 충분.
- 3-C: `ui/server.py` 기동 후 `jarvis_send.py`를 수동 트리거해 다른 WS 클라이언트가
  실제로 페이로드를 받는지 수동 검증 (기존 2-C 테스트 방식과 동일).
- 3-D: `npm run typecheck` + 브라우저에서 수동으로 화면 제어/에이전트 태스크 실행해
  임시 말풍선 생성·교체·제거 확인.

## 영향받는 파일 요약

| 파일 | 변경 내용 |
|------|-----------|
| `core/engines/claude_cli_engine.py` | `run_task()` 문장 버퍼링 (3-A) |
| `core/status_events.py` | `State`에 `"streaming"` 추가 (3-B) |
| `skills/skill_agent.py` | `run_task()` 호출 전 `streaming` emit (3-B) |
| `skills/skill_screen_agent.py` | `engine.run()` 호출 전 `streaming` emit (3-B) |
| `ui/server.py` | `ws_endpoint` 훅 메시지 수신·브로드캐스트 (3-C) |
| `ui/web/hooks/useJarvisStatus.ts` | `transient` 말풍선 로직, 훅 메시지 분기 (3-D) |
