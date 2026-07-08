# jarvis-core 2.0 — 전체 작업 목록

> 노트북/PC 작업 전환용 메모. 완료 시 삭제 예정.  
> 마지막 업데이트: 2026-07-08 (우선순위 3 완료, 4-A·4-B 완료)

---

## WhisperFlow 벤치마킹 기능 전체 목록

WhisperFlow에서 가져오기로 한 기능과 jarvis-core 2.0에 새로 추가·수정할 전체 항목.

| # | 기능 | WhisperFlow 원본 방식 | jarvis-core 2.0 구현 방식 | 상태 |
|---|------|----------------------|--------------------------|------|
| 1 | Claude CLI 단일 엔진 | claude 터미널에 STT 텍스트 직접 주입 | `claude -p` + `--dangerously-skip-permissions` | ✅ 완료 |
| 2 | 화면 인식·제어 | computer_use Vision 단독 | UIA 트리 + Vision 하이브리드 (전략 A) | ✅ 완료 |
| 3 | Claude Code 훅 | `jarvis_hook.sh` PostToolUse | `hooks/*.py` PostToolUse·Stop | ✅ 완료 |
| 4 | 버그: 이미지 전달 | — | base64 → 파일 경로 방식 수정 | ✅ 완료 |
| 5 | 가상 키보드 출력 | pbcopy + AppleScript → Claude 터미널 붙여넣기 | pyperclip + pyautogui Ctrl+V → 포커스 앱 입력 | ✅ 완료 |
| 6 | Always-Listen 상태 머신 | BOOT_WAIT→IDLE→SPEECH→CONV_WAIT | main.py 루프 재설계 | ❌ 미구현 |
| 7 | TTS 인터럽트 | 없음 (Mac 특성) | 박수 2번 → pygame.mixer 즉시 중단 | ✅ 완료 |
| 8 | 스트리밍 TTS | STT→Claude 실시간 스트림 | run_task() 문장 버퍼링 → 즉시 TTS | ✅ 완료 |
| 9 | 실행 중 CLI 세션 주입 | STT를 열린 터미널에 직접 타이핑 | claude --resume 세션 재연결 | ❌ 미구현 |
| 10 | 오디오 레벨 시각화 | 마이크 레벨 파형 UI 표시 | 웹 대시보드 AudioWave 컴포넌트 | ❌ 미구현 |
| 11 | UI 실시간 진행 표시 | Claude 응답 스트리밍 실시간 출력 | streaming 상태 + tool_action 이벤트 | ✅ 완료 |
| 12 | skill_virtual_keyboard | 없음 | "이 내용 입력해줘" → 포커스 앱 타이핑 스킬 | ✅ 완료 |
| 13 | 실 동작 테스트 | — | uiautomation·Claude CLI·훅 연결 검증 | ❌ 미완료 |
| 14 | UIA 깊이·요소수 튜닝 | — | 실 앱 테스트 후 _MAX_ELEMENTS 조정 | ❌ 미완료 |
| 15 | claude --resume 세션 유지 | 없음 (단발 -p) | 장시간 작업 세션 연속성 | ❌ 미구현 |
| 16 | 트리거 자연어 확장 | — | "열어서~", "들어가서~" 패턴 추가 | ❌ 미구현 |
| 17 | groq_usage.json 정리 | — | 삭제 또는 claude_usage.json으로 교체 | ❌ 미완료 |

---

## 완료된 작업 ✅

### 1단계: Claude CLI 단일 엔진 교체
- [x] `core/engines/groq_engine.py` 삭제
- [x] `core/engines/ollama_engine.py` 삭제
- [x] `core/groq_usage.py` 삭제
- [x] `core/engines/claude_cli_engine.py` 신규
  - `ask()` / `generate()` — 안전 모드 (WebSearch·WebFetch만 허용)
  - `run_task()` — 풀파워 모드 (computer_use 포함 전체 툴, stream-json)
  - `describe()` — UI 엔진 패널용
- [x] `skills/skill_ai_chat.py` 교체 (ClaudeCliEngine 단일)
- [x] `skills/skill_agent.py` 교체 (run_task() 위임)
- [x] `skills/skill_screen_agent.py` 교체 (HybridScreenEngine 사용)
- [x] `skills/skill_howto|joke|weather|web_search.py` — GroqEngine → ClaudeCliEngine
- [x] `requirements.txt` — groq 제거, uiautomation 추가
- [x] `tests/test_agent_e2e.py` / `test_skill_agent.py` 삭제

### 전략 A: UIA + Vision 하이브리드 화면 제어
- [x] `core/hybrid_screen.py` 신규
  - UIA 요소 트리 수집 (`_collect_uia`)
  - SoM 번호 오버레이 PNG 임시 파일 저장 (`_capture_annotated`)
  - Claude 통합 레이어 — UIA JSON + 파일 경로 전달 (`_ask_claude`)
  - `_cleanup()` — 작업 완료 후 임시 파일 삭제
- [x] `skills/skill_computer_use.py` 신규 (화면 분석 전용)
- [x] `hooks/jarvis_tool_hook.py` / `jarvis_hook.py` / `jarvis_send.py` 신규
- [x] `.claude/settings.json` 훅 등록 + `.gitignore` 예외 처리

### 우선순위 1: 버그 수정 (2026-07-01 완료)
- [x] `hybrid_screen.py` — base64 임베드 → 파일 경로 방식으로 수정
- [x] `.gitignore` — `.claude/settings.json` 예외 추가, 저장소 포함

### 우선순위 2: 실 동작 테스트 (2026-07-01 완료)
- [x] 2-A UIA 요소 수집 확인 — 메모장(5개)·크롬(39개, 부분 지원) 모두 60개 이하로 정상 수집,
      `hybrid_screen.py`의 `_collect_uia()`/`_capture_annotated()`로 스크린샷·SoM 오버레이 임시 파일
      생성 및 `_cleanup()` 삭제까지 확인. 진행 중 `comtypes 1.4.6`이 Python 3.13에서
      `NameError: _compointer_base`로 깨지는 것을 발견 — `1.4.16`으로 업그레이드하고
      `requirements.txt` 최소 버전 상향으로 반영.
- [x] 2-B Claude CLI 연결 테스트 — `ClaudeCliEngine().describe()`
      (`{'provider': 'Claude Code', 'connected': True, ...}`) 및 `.ask('안녕, 자비스야')`
      실응답("안녕하세요. 자비스입니다. 무엇을 도와드릴까요?") 확인.
- [x] 2-C 훅 동작 테스트 — `uvicorn ui.server:app` 기동 후 `jarvis_hook.py`/`jarvis_tool_hook.py`를
      수동 트리거해 WebSocket 연결·전송이 예외 없이 종료(exit 0)됨을 확인. 단, 대시보드
      클라이언트는 훅이 보낸 `tool_action`/`output` 페이로드를 **받지 못함** —
      `ui/server.py`의 `/ws`가 클라이언트→서버 수신 메시지를 아직 브로드캐스트하지 않기 때문
      (우선순위 3-C에서 구현 예정, 회귀 아님).

### 회귀 전수 테스트 (2026-07-02, 이 PC 새 환경에서 재검증)
40개 스킬 전체 로딩, 기존 `tests/` 32개 스크립트, `ClaudeCliEngine.describe/ask/run_task()`,
`hybrid_screen.py` UIA 수집·스크린샷·정리, 훅 2종, `main.py --text` 엔드투엔드까지 전부
재실행. 발견·수정한 버그 3건:
- **`main.py` 크래시** — `_run_text_loop()`의 `print(result.speech)`가 콘솔 코드페이지(cp949)로
  인코딩 불가한 문자(위키백과 요약에 섞여 나오는 IPA 발음 기호 등)를 만나면
  `UnicodeEncodeError`로 프로그램 전체가 죽음. `main()` 시작부에
  `sys.stdout/stderr.reconfigure(errors="replace")` 추가로 수정 — 크래시 대신 `?`로 대체.
- **`main.py` stdin 인코딩 미설정** — stdin이 파이프로 리다이렉트되는 경우(자동화 스크립트 등)
  Python이 로케일 코드페이지(cp949)로 UTF-8 입력을 잘못 디코드해 한글이 깨지고,
  `"종료"` 같은 정확 일치 명령이 실패해 AI 폴백으로 새고 결국 stdin EOF로 크래시까지 이어짐.
  `sys.stdin.reconfigure(encoding="utf-8", errors="replace")` 추가로 수정 (실제 콘솔 인터랙티브
  입력은 Windows 콘솔 API를 타므로 영향 없음, 리다이렉트된 입력에서만 적용됨).
- **`uiautomation` 패키지 미설치** — `requirements.txt`엔 있었지만 이 PC의 `.venv`엔 실제로
  설치돼 있지 않아 UIA 수집이 항상 빈 리스트로 폴백 중이었음 (기존 2-A 검증은 다른 PC에서
  했던 것으로 추정). `pip install uiautomation>=2.0.18`로 재설치 후 크롬 창에서 25~52개 요소
  정상 수집 확인.

`tests/test_skill_wikipedia.py`도 동일한 cp949 인코딩 문제로 테스트 자체가 죽던 것을
`sys.stdout.reconfigure(errors="replace")` 추가로 함께 수정.

---

## 남은 작업

---

### 🟠 우선순위 2 — 실 동작 테스트 (구현 전 필수 검증) — ✅ 완료 (위 참고)

#### 2-A. 패키지 설치 및 UIA 동작 확인
```powershell
pip install uiautomation>=2.0.18
```

```python
# 빠른 UIA 수집 확인 스크립트 (터미널에서 직접 실행)
# 메모장을 먼저 열어두고 실행
import uiautomation as auto
root = auto.GetForegroundControl()
print(root.Name, root.ControlTypeName)
for c in root.GetChildren():
    print(" ", c.Name, c.ControlTypeName, c.BoundingRectangle)
```

**테스트 시나리오:**
1. 메모장 오픈 → `python main.py --text` → "화면 제어로 메모장에 안녕 입력해줘"
2. 크롬 오픈 → "화면 제어로 크롬 주소창에 naver.com 입력해줘"
3. "지금 화면 봐줘" → UIA 요소 목록 + 설명 출력 확인

**확인 포인트:**
- UIA 요소 60개 이하 정상 수집 여부
- Windows 네이티브 앱 (메모장, 탐색기) 정확 좌표 여부
- 크롬에서 UIA 부분 지원 / 웹 콘텐츠 Vision 폴백 동작 여부
- 임시 파일(`jarvis_screen_*.png`, `jarvis_som_*.png`) 생성 및 cleanup 여부

---

#### 2-B. Claude Code CLI 연결 테스트
```powershell
# describe() 확인
python -c "from core.engines.claude_cli_engine import ClaudeCliEngine; print(ClaudeCliEngine().describe())"
# 예상: {'provider': 'Claude Code', 'model': 'Claude Code CLI', 'connected': True, 'usagePercent': 0.0}

# ask() 단순 응답 확인
python -c "from core.engines.claude_cli_engine import ClaudeCliEngine; print(ClaudeCliEngine().ask('안녕, 자비스야'))"
```

---

#### 2-C. 훅 동작 테스트
```powershell
# 터미널 1: 자비스 실행
python main.py --text

# 터미널 2: 훅 수동 트리거
echo '{"result": "테스트 응답입니다"}' | python hooks/jarvis_hook.py
echo '{"tool_name": "WebSearch", "tool_input": {"query": "날씨"}, "tool_response": {}}' | python hooks/jarvis_tool_hook.py
```
→ `http://localhost:8765` 대시보드에서 메시지 수신 확인

---

### 🟡 우선순위 3 — 스트리밍·UI 개선 — ✅ 완료 (위 참고)

#### 3-A. `core/engines/claude_cli_engine.py` — TTS 문장 버퍼링
현재 `on_chunk` 콜백이 단어/문장 조각 단위로 호출돼 TTS가 어색하게 끊김.  
마침표·느낌표·줄바꿈 기준으로 버퍼링 후 문장 완성 시에만 TTS 호출.

```python
# run_task() 내 스트리밍 루프 수정
_SENTENCE_END = (".", "!", "?", "。", "\n")

buf = ""
for raw_line in proc.stdout:
    # ... JSON 파싱 후 chunk 추출 ...
    buf += chunk
    if on_chunk and any(buf.rstrip().endswith(p) for p in _SENTENCE_END):
        sentence = buf.strip()
        if sentence:
            on_chunk(sentence)
        buf = ""
# 루프 종료 후 잔여 버퍼 처리
if on_chunk and buf.strip():
    on_chunk(buf.strip())
```

**수정할 파일**: `core/engines/claude_cli_engine.py` (`run_task()`)

---

#### 3-B. `core/status_events.py` — `"streaming"` 상태 추가
```python
# 현재
State = Literal["idle", "listening", "processing", "responded", "navigation_request"]

# 수정 후
State = Literal["idle", "listening", "processing", "streaming", "responded", "navigation_request"]
```
- `processing`: 라우팅·디스패치 중 (짧은 구간)
- `streaming`: Claude run_task() 실행 중, 청크가 들어오는 중 (긴 구간)

`Dispatcher.dispatch()` 또는 `skill_screen_agent.execute()` 에서 streaming emit 추가.

**수정할 파일**: `core/status_events.py`, `core/dispatcher.py` 또는 해당 스킬

---

#### 3-C. `ui/server.py` — 훅 WebSocket 이벤트 수신·브로드캐스트
현재 WS 엔드포인트는 클라이언트(브라우저)→서버 방향만 처리.  
훅(`jarvis_send.py`)이 `tool_action` / `output` 타입으로 보내는 메시지를  
받아서 전체 클라이언트에 브로드캐스트하도록 추가.

```python
# ui/server.py WebSocket 핸들러 내 수신 처리 추가
async def websocket_endpoint(ws: WebSocket):
    ...
    async for raw in ws.iter_text():
        data = json.loads(raw)
        if data.get("type") in ("tool_action", "output"):
            # 훅에서 온 Claude 진행 상황 → 전체 클라이언트 브로드캐스트
            await _broadcast_all(data)
```

**수정할 파일**: `ui/server.py`

---

#### 3-D. 프론트엔드 — Claude 실행 중 실시간 진행 표시
`useJarvisStatus.ts`에서 `tool_action` 이벤트 수신 후  
"웹 검색 중: 날씨", "화면 제어: click" 등을 채팅 UI에 인라인으로 표시.

```typescript
// useJarvisStatus.ts 추가
case "tool_action":
  setToolAction(data.value);   // 진행 표시줄 or 인라인 배지
  break;
```

**수정할 파일**: `ui/web/hooks/useJarvisStatus.ts`, `ui/web/components/JarvisMinimal.tsx` 또는 `JarvisFull.tsx`

---

### 🔵 우선순위 4 — WhisperFlow 핵심 기능 이식

#### 4-A. TTS 인터럽트 — 박수 2번 → TTS 즉시 중단 — ✅ 완료 (2026-07-08)
설계: `docs/superpowers/specs/2026-07-08-tts-clap-interrupt-design.md`
계획: `docs/superpowers/plans/2026-07-08-tts-clap-interrupt.md`

`voice/tts.py`에 `stop()`, `voice/clap_detector.py`에 자체 마이크 스트림으로
박수 2번만 감지하는 `wait_for_double_clap(stop_event)`를 추가하고, `main.py`에
`_speak_with_clap_interrupt()`를 두어 `_run_voice_loop()`의 스킬 응답 TTS 호출을
교체했다. `voice.clap_detector`가 `voice.stt`(무거운 STT 스택)를 import하므로
`main.py`에서는 반드시 함수 본문 안에서 지연 import해야 한다는 점을 계획 자체
리뷰 단계에서 발견해 수정 — 안 그러면 `--text` 모드까지 매번 STT 스택을 로딩하게
돼 기존 지연 로딩 설계가 깨졌을 것. 자동 테스트(`tests/test_tts_interrupt.py`,
7개)는 전부 모킹 기반이라 실 하드웨어(마이크로 스피커 소리가 오탐되는지 등)
검증은 별도 수동 확인이 필요 — 계획 문서의 "수동 검증" 절 참고.

---

#### 4-B. 가상 키보드 출력 — ✅ 완료 (2026-07-08)
설계: `docs/superpowers/specs/2026-07-08-virtual-keyboard-design.md`
계획: `docs/superpowers/plans/2026-07-08-virtual-keyboard.md`

WhisperFlow 원래 설계의 "Claude CLI 터미널에 직접 주입"(`inject_to_claude_terminal`)은
jarvis-core가 `claude -p` 서브프로세스 1회 호출 방식이라 인터랙티브 터미널 세션
자체가 없어 이 아키텍처와 맞지 않는다고 판단해 제외했다 — 범용 "포커스된 창에
타이핑" 기능만 구현. 별도 `voice/virtual_keyboard.py` 모듈 대신 `skill_window.py`/
`skill_clipboard.py` 관례를 따라 `skills/skill_virtual_keyboard.py` 하나에 로직을
담았다(`voice/`는 오디오 I/O 전용 경계). 타이핑할 텍스트는 ①"~라고 입력해줘"
패턴 ②노이즈 단어 제거 후 남는 텍스트 ③직전 자비스 응답(`context["history"]`)
순으로 결정한다. 계획 자체 리뷰 중 "라고 입력해"를 고정 문자열로 매칭하면
"라고 입력하고 엔터 쳐줘"처럼 조사가 다른 자연스러운 문장을 놓치는 버그를
발견해 "라고" 단독 매칭으로 수정. 자동 테스트(`tests/test_skill_virtual_keyboard.py`,
11개)는 전부 모킹 기반이라 실제 클립보드/키 입력 동작은 계획 문서의 "수동 검증"
절에 따라 별도 확인 필요.

---

#### 4-C. Always-Listen 상태 머신 개선
WhisperFlow 방식: `BOOT_WAIT → IDLE → SPEECH → CONV_WAIT` 4단계.  
현재 `main.py`는 단순 while 루프 + active 플래그. 상태 전환이 명시적이지 않음.

```python
# main.py 상태 머신 리팩토링
from enum import Enum, auto

class ListenState(Enum):
    BOOT_WAIT  = auto()  # 시작 대기 (wakeword 또는 clap 감지 전)
    IDLE       = auto()  # 웨이크워드 감지 후 명령 대기
    SPEECH     = auto()  # STT 수신 중
    CONV_WAIT  = auto()  # Claude 응답 중 (follow_up 대기)

# 각 상태에서 broadcaster.emit()으로 UI에 현재 상태 전달
# BOOT_WAIT → idle, IDLE → listening, SPEECH → processing, CONV_WAIT → streaming
```

**수정할 파일**: `main.py`

---

#### 4-D. 실행 중인 Claude CLI 세션 재연결 (`--resume`)
단발 `-p` 호출 대신 이전 세션을 이어가는 방식.  
장시간 화면 제어 작업에서 컨텍스트 유지에 유리.

```python
# core/engines/claude_cli_engine.py 에 session_id 관리 추가
class ClaudeCliEngine:
    def __init__(self, ...):
        self._session_id: str | None = None   # 마지막 세션 ID 저장

    def run_task(self, task, on_chunk=None, resume=False):
        cmd = ["claude", "-p", prompt, "--dangerously-skip-permissions",
               "--output-format", "stream-json"]
        if resume and self._session_id:
            cmd += ["--resume", self._session_id]
        ...
        # result 이벤트에서 session_id 추출
        elif event_type == "result":
            self._session_id = obj.get("session_id")  # 다음 호출에서 재사용
```

**수정할 파일**: `core/engines/claude_cli_engine.py`

---

#### 4-E. 실시간 오디오 레벨 시각화
WhisperFlow UI처럼 마이크 입력 레벨을 실시간 파형으로 표시.

**흐름**:
```
voice/stt.py 오디오 콜백 → 레벨 계산(RMS) → broadcaster.emit(state="listening", extra={"level": rms})
→ ui/server.py WS 브로드캐스트
→ ui/web AudioWave.tsx 컴포넌트 실시간 렌더링
```

**신규 파일**: `ui/web/components/AudioWave.tsx`

```typescript
// 간단한 막대 파형 컴포넌트
const AudioWave = ({ level }: { level: number }) => (
  <div className="audio-wave">
    {Array.from({ length: 12 }).map((_, i) => (
      <span key={i} style={{ height: `${Math.random() * level * 100}%` }} />
    ))}
  </div>
);
```

**수정할 파일**: `voice/stt.py` (레벨 emit 추가), `core/status_events.py` (extra 필드 활용), `ui/server.py`, `ui/web/`

---

### ⚪ 우선순위 5 — 마무리·정리

#### 5-A. `skill_screen_agent.py` 트리거 자연어 확장
```python
# 현재 (명시적 키워드만)
_STRONG = ["화면 제어", "화면 에이전트", "직접 제어", ...]

# 추가할 패턴
"열어서 ~ 해줘"    → 앱 열고 작업 수행
"들어가서 ~ 해줘"  → 웹사이트 접속 후 작업
"클릭해줘"         → 현재 화면의 특정 버튼 클릭
"입력해줘"         → 현재 포커스 창에 텍스트 입력
"스크롤해줘"       → 화면 스크롤
"닫아줘"           → 현재 창 닫기
```

#### 5-B. `core/hybrid_screen.py` UIA 파라미터 튜닝
실 앱 테스트 후 아래 값 조정:
```python
_MAX_ELEMENTS   = 60   # 복잡한 앱은 80~100으로 증가 검토
_OVERLAY_RADIUS = 12   # 고해상도 화면은 16으로 증가 검토
# _walk_uia depth 8 → 앱에 따라 10~12 필요할 수 있음
```

#### 5-C. `data/groq_usage.json` 정리
Groq 제거로 파일 내용이 무의미.
```powershell
# 파일 초기화 후 커밋
echo '{}' > data/groq_usage.json
# 또는 .gitignore에 추가하고 삭제
```

#### 5-D. 화면 제어 전용 테스트 스크립트
```python
# tests/test_hybrid_screen.py
from core.hybrid_screen import HybridScreenEngine
engine = HybridScreenEngine()

# UIA 수집 테스트
elements = engine._collect_uia()
print(f"UIA 요소 수: {len(elements)}")
for el in elements[:5]:
    print(f"  [{el.idx}] {el.control_type} '{el.name}' @ {el.center}")

# 스크린샷 저장 테스트
orig, ann = engine._capture_annotated(elements)
print(f"원본: {orig}")
print(f"SoM: {ann}")
```

---

## 권장 작업 순서

```
[즉시] 우선순위 2 — 실 동작 테스트
  2-A  pip install uiautomation → UIA 수집 확인
  2-B  Claude CLI ask() 응답 확인
  2-C  훅 WebSocket 수신 확인
       ↓
[단기] 우선순위 3 — 스트리밍·UI 개선
  3-A  claude_cli_engine.py TTS 문장 버퍼링
  3-B  status_events.py streaming 상태 추가
  3-C  ui/server.py 훅 이벤트 수신·브로드캐스트
  3-D  프론트엔드 실시간 진행 표시
       ↓
[중기] 우선순위 4 — WhisperFlow 기능 이식
  4-A  TTS 인터럽트 (박수 2번 → pygame stop) — ✅ 완료
  4-B  가상 키보드 출력 (virtual_keyboard.py + skill) — ✅ 완료
  4-C  Always-Listen 상태 머신 리팩토링
  4-D  claude --resume 세션 유지
  4-E  오디오 레벨 시각화 (AudioWave.tsx)
       ↓
[마무리] 우선순위 5 — 정리
  5-A  트리거 자연어 확장
  5-B  UIA 파라미터 튜닝
  5-C  groq_usage.json 정리
  5-D  테스트 스크립트 작성
```

---

## 환경 세팅 체크리스트 (새 환경 시작 전)

```powershell
# 1. 저장소 클론
git clone https://github.com/rkdehdgml/jarvis-core-2.0.git
cd jarvis-core-2.0

# 2. 가상환경
python -m venv .venv
.\.venv\Scripts\Activate.ps1
# 실행 정책 오류 시: Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# 3. 패키지 설치
pip install -r requirements.txt
# uiautomation은 별도 설치 필요할 수 있음
pip install uiautomation>=2.0.18

# 4. Claude Code CLI 설치 및 로그인 (최초 1회)
npm install -g @anthropic-ai/claude-code
claude login

# 5. 환경변수 설정
copy .env.example .env
# KAKAO_REST_API_KEY, KAKAO_JS_API_KEY, NEWSAPI_KEY, DAEJEON_BUS_API_KEY 등 입력

# 6. .claude/settings.json 확인 (이제 저장소에 포함됨)
# 없으면 수동 생성:
# {
#   "hooks": {
#     "PostToolUse": [{"matcher":".*","hooks":[{"type":"command","command":"python hooks/jarvis_tool_hook.py"}]}],
#     "Stop": [{"hooks":[{"type":"command","command":"python hooks/jarvis_hook.py"}]}]
#   }
# }

# 7. 동작 확인 (텍스트 모드로 빠르게 검증)
python main.py --text

# 8. Claude CLI 연결 확인
python -c "from core.engines.claude_cli_engine import ClaudeCliEngine; print(ClaudeCliEngine().describe())"
```

---

## 파일별 변경 영향도 요약

| 파일 | 작업 | 우선순위 |
|------|------|---------|
| `core/engines/claude_cli_engine.py` | TTS 버퍼링(3-A), --resume(4-D) | 3, 4 |
| `core/status_events.py` | streaming 상태 추가(3-B) | 3 |
| `core/hybrid_screen.py` | UIA 파라미터 튜닝(5-B) | 5 |
| `ui/server.py` | 훅 이벤트 수신·브로드캐스트(3-C) | 3 |
| `ui/web/hooks/useJarvisStatus.ts` | tool_action 처리(3-D) | 3 |
| `ui/web/components/AudioWave.tsx` | 신규 — 오디오 파형(4-E) | 4 |
| `voice/tts.py` | stop() 추가(4-A) — ✅ 완료 | 4 |
| `voice/clap_detector.py` | wait_for_double_clap() 추가(4-A) — ✅ 완료 | 4 |
| `voice/stt.py` | 레벨 emit 추가(4-E) | 4 |
| `main.py` | TTS 인터럽트 배선(4-A) — ✅ 완료, 상태 머신(4-C) — 미착수 | 4 |
| `skills/skill_virtual_keyboard.py` | 신규 — 가상 키보드 스킬(4-B) — ✅ 완료 | 4 |
| `skills/skill_screen_agent.py` | 트리거 확장(5-A) | 5 |
| `data/groq_usage.json` | 정리(5-C) | 5 |
