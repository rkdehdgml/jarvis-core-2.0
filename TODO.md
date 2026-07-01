# jarvis-core 2.0 — 남은 작업 목록

> 노트북/PC 작업 전환용 메모. 완료 시 삭제 예정.  
> 마지막 업데이트: 2026-07-01

---

## 완료된 작업 ✅

### 1단계: Claude CLI 단일 엔진 교체
- [x] `core/engines/groq_engine.py` 삭제
- [x] `core/engines/ollama_engine.py` 삭제
- [x] `core/groq_usage.py` 삭제
- [x] `core/engines/claude_cli_engine.py` 신규 생성
  - `ask()` / `generate()` — 안전 모드 (WebSearch·WebFetch만 허용)
  - `run_task()` — 풀파워 모드 (computer_use 포함 전체 툴)
  - `describe()` — UI 엔진 패널용
- [x] `skills/skill_ai_chat.py` 교체 (ClaudeCliEngine 단일)
- [x] `skills/skill_agent.py` 교체 (run_task() 위임)
- [x] `skills/skill_screen_agent.py` 교체 (HybridScreenEngine 사용)
- [x] `skills/skill_howto.py` / `skill_joke.py` / `skill_weather.py` / `skill_web_search.py` — GroqEngine → ClaudeCliEngine
- [x] `requirements.txt` — groq 제거, uiautomation 추가
- [x] `tests/test_agent_e2e.py` / `test_skill_agent.py` 삭제

### 전략 A: UIA + Vision 하이브리드 화면 제어
- [x] `core/hybrid_screen.py` 신규 생성
  - UIA 요소 트리 수집 (`_collect_uia`)
  - SoM 번호 오버레이 이미지 생성 (`_capture_annotated`)
  - Claude 통합 레이어 (`_ask_claude`)
- [x] `skills/skill_computer_use.py` 신규 생성
- [x] `hooks/jarvis_tool_hook.py` / `jarvis_hook.py` / `jarvis_send.py` 신규 생성
- [x] `.claude/settings.json` 훅 등록

---

## 남은 작업

---

### 🔴 우선순위 1 — 버그 수정 (동작 안 함)

#### 1-A. `hybrid_screen.py` 이미지 전달 방식 수정
**문제**: `_capture_annotated()`가 생성한 base64 이미지를 `_ask_claude()`에서 프롬프트 텍스트에 직접 임베드하고 있는데,  
Claude Code CLI의 `-p` 플래그는 텍스트만 받으므로 이미지를 인식하지 못함.

**해결 방향 (둘 중 하나 선택):**

- **옵션 A (권장)**: 스크린샷을 temp 파일로 저장 → 프롬프트에 파일 경로 포함
  ```python
  # 현재 (동작 안 함)
  prompt = f"...base64 이미지: {annotated_b64}..."
  
  # 수정 후
  import tempfile
  path = tempfile.mktemp(suffix=".png")
  annotated_img.save(path)
  prompt = f"...스크린샷 파일: {path} (Read 툴로 열어볼 수 있음)..."
  ```
  > Claude Code CLI는 computer_use 툴로 자체 스크린샷을 찍을 수 있으므로  
  > 파일 경로만 알려줘도 직접 열어볼 수 있음.

- **옵션 B**: 스크린샷 직접 전달 포기 → UIA JSON만 전달하고 Claude computer_use가 자체 스크린샷 촬영
  ```python
  # _capture_annotated() 전체 제거
  # _ask_claude()에서 UIA JSON만 전달
  # Claude가 필요하면 computer_use로 스스로 스크린샷 찍음
  ```

**수정할 파일**: `core/hybrid_screen.py` → `_capture_annotated()`, `_ask_claude()`

---

#### 1-B. `.claude/settings.json` gitignore 제외 확인
**문제**: `.gitignore`에 `.claude/`가 등록되어 있어 훅 설정 파일이 저장소에 포함 안 됨.

**해결**: 두 가지 선택지
- `.gitignore`에서 `.claude/settings.json`만 예외 처리: `!.claude/settings.json`
- 또는 수동으로 `git add -f .claude/settings.json && git commit && git push`

**수정할 파일**: `.gitignore`

---

### 🟠 우선순위 2 — 실 동작 테스트

#### 2-A. uiautomation 패키지 설치 및 테스트
```powershell
pip install uiautomation>=2.0.18
```
**테스트 시나리오:**
1. 메모장 열기 → "화면 제어로 메모장에 '안녕' 입력해줘" 실행
2. 크롬 열기 → "화면 제어로 크롬 주소창에 naver.com 입력해줘" 실행
3. "지금 화면 봐줘" 실행 → UIA 요소 목록 + 설명 확인

**확인 포인트:**
- UIA 요소가 60개 이하로 정상 수집되는지
- Windows 앱(메모장, 탐색기)에서 정확한 좌표가 나오는지
- 크롬 브라우저에서 UIA 수집이 부분 지원되는지 (웹 콘텐츠는 Vision 폴백)

---

#### 2-B. Claude Code CLI 연결 테스트
```powershell
# .venv 활성화 후
python -c "from core.engines.claude_cli_engine import ClaudeCliEngine; e = ClaudeCliEngine(); print(e.describe())"
```
**예상 출력**: `{'provider': 'Claude Code', 'model': 'Claude Code CLI', 'connected': True, 'usagePercent': 0.0}`

```powershell
# 간단한 ask() 테스트
python -c "from core.engines.claude_cli_engine import ClaudeCliEngine; print(ClaudeCliEngine().ask('안녕'))"
```

---

#### 2-C. 훅 동작 테스트
```powershell
# UI 서버 먼저 실행
python main.py --text

# 별도 터미널에서 훅 수동 테스트
echo '{"result": "테스트 응답"}' | python hooks/jarvis_hook.py
echo '{"tool_name": "WebSearch", "tool_input": {"query": "날씨"}}' | python hooks/jarvis_tool_hook.py
```
웹 대시보드(`http://localhost:8765`)에서 메시지 수신 확인.

---

### 🟡 우선순위 3 — UI 스트리밍 개선

#### 3-A. `core/status_events.py` — `"streaming"` 상태 추가
```python
# 현재
State = Literal["idle", "listening", "processing", "responded", "navigation_request"]

# 수정 후
State = Literal["idle", "listening", "processing", "streaming", "responded", "navigation_request"]
```
`streaming` 상태: Claude가 run_task()로 실행 중이고 청크가 들어오는 중.

**수정할 파일**: `core/status_events.py`

---

#### 3-B. `ui/server.py` — 훅 WebSocket 이벤트 수신 처리
현재 훅(`jarvis_send.py`)이 `ws://127.0.0.1:8765/ws`로 보내는 `tool_action` 타입 메시지를  
서버가 받아서 모든 클라이언트에 브로드캐스트하도록 추가.

```python
# ui/server.py WS 엔드포인트에 추가
if data.get("type") == "tool_action":
    # Claude Code 훅에서 온 툴 동작 알림
    await broadcast({"type": "tool_action", "value": data["value"]})
```

**수정할 파일**: `ui/server.py`

---

#### 3-C. 프론트엔드 — Claude 실행 중 실시간 진행 표시
`ui/web/hooks/useJarvisStatus.ts`에서 `tool_action` 이벤트 수신 후  
"화면 제어: click", "웹 검색 중: 날씨" 등을 UI에 실시간 표시.

**수정할 파일**: `ui/web/hooks/useJarvisStatus.ts`, 관련 컴포넌트

---

### 🟢 우선순위 4 — 기능 추가

#### 4-A. TTS 인터럽트 (WhisperFlow 방식)
박수 두 번 감지 시 현재 재생 중인 TTS를 즉시 중단.  
`ClapDetector`는 이미 존재 (`voice/clap_detector.py`).

```python
# voice/tts.py에 추가
import pygame
def stop():
    if pygame.mixer.get_init():
        pygame.mixer.music.stop()

# voice/wakeword.py 또는 main.py에서
# ClapDetector가 감지하면 tts.stop() 호출
```

**수정할 파일**: `voice/tts.py`, `main.py`

---

#### 4-B. `claude --resume` 세션 유지
장시간 화면 제어 작업에서 이전 Claude 세션을 이어가는 기능.

```python
# claude_cli_engine.py에 session_id 관리 추가
proc = subprocess.Popen([
    "claude", "-p", prompt,
    "--resume", self._session_id,  # 이전 세션 ID
    "--dangerously-skip-permissions",
    "--output-format", "stream-json",
])
# result 이벤트에서 session_id 추출해 저장
```

**수정할 파일**: `core/engines/claude_cli_engine.py`

---

#### 4-C. `skill_screen_agent.py` 트리거 확장
현재 트리거가 "화면 제어", "직접 제어" 등 명시적 키워드에만 반응.  
더 자연스러운 발화 패턴 추가.

```python
# 추가 트리거 예시
"열어서 ~ 해줘"   → 앱 열고 작업
"들어가서 ~ 해줘" → 웹사이트 접속 후 작업
"클릭해줘"        → 현재 화면의 특정 요소 클릭
"입력해줘"        → 현재 포커스 창에 텍스트 입력
```

**수정할 파일**: `skills/skill_screen_agent.py`

---

#### 4-D. 화면 제어 결과를 음성으로 단계별 보고
`run_task(on_chunk=tts.speak)` 시 Claude의 스트리밍 텍스트가 그대로 TTS 출력됨.  
현재는 청크 단위(단어/문장 조각)라 어색함.  
문장 단위로 버퍼링 후 TTS 호출하도록 개선.

```python
# claude_cli_engine.py run_task() 내 on_chunk 처리
buffer = ""
for chunk in streaming:
    buffer += chunk
    if any(buffer.endswith(p) for p in (".", "!", "?", "\n")):
        if on_chunk:
            on_chunk(buffer.strip())
        buffer = ""
```

**수정할 파일**: `core/engines/claude_cli_engine.py`

---

### ⚪ 우선순위 5 — 선택 작업

#### 5-A. `core/hybrid_screen.py` UIA 깊이 튜닝
현재 `_walk_uia()` 최대 깊이 8, 최대 요소 60개.  
실제 테스트 후 값 조정 (복잡한 앱은 더 필요할 수 있음).

#### 5-B. 화면 제어 전용 테스트 스크립트 작성
```python
# tests/test_hybrid_screen.py
from core.hybrid_screen import HybridScreenEngine
engine = HybridScreenEngine()
elements = engine._collect_uia()
print(f"수집된 요소 수: {len(elements)}")
for el in elements[:10]:
    print(el.to_dict())
```

#### 5-C. `data/groq_usage.json` 파일 역할 변경
Groq 제거로 내용이 무의미해짐.  
`data/claude_usage.json`으로 교체하거나 기존 `data/usage.json`으로 통합.

---

## 작업 순서 권장

```
1-A 버그 수정 (hybrid_screen.py 이미지 전달)
    ↓
2-A uiautomation 설치 + 테스트
2-B Claude CLI 연결 테스트
    ↓
2-C 훅 동작 확인
    ↓
3-A status_events.py streaming 상태 추가
3-B ui/server.py 훅 이벤트 처리
    ↓
4-D TTS 청크 버퍼링 개선
4-A TTS 인터럽트
    ↓
3-C 프론트엔드 실시간 진행 표시
    ↓
4-B 세션 유지 (--resume)
4-C 트리거 확장
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

# 3. 패키지
pip install -r requirements.txt

# 4. Claude Code CLI
npm install -g @anthropic-ai/claude-code
claude login

# 5. .env 복사 (Kakao, NewsAPI, 버스 API 키 등)
copy .env.example .env
# 각 키 입력

# 6. 훅 설정 (gitignore 제외 상태라 수동 생성)
# .claude/settings.json 파일을 아래 내용으로 직접 생성
# {
#   "hooks": {
#     "PostToolUse": [{"matcher":".*","hooks":[{"type":"command","command":"python hooks/jarvis_tool_hook.py"}]}],
#     "Stop": [{"hooks":[{"type":"command","command":"python hooks/jarvis_hook.py"}]}]
#   }
# }

# 7. 동작 확인
python main.py --text
```
