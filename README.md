# jarvis-core 2.0

Windows 네이티브 한국어 개인 AI 비서. 음성("Hey Jarvis" 또는 박수 두 번) 또는 웹 대시보드 텍스트로 조작합니다.

**AI 엔진**: Claude Code CLI (`--dangerously-skip-permissions`) — 단일 엔진, Groq/Ollama 완전 제거  
**화면 제어**: UIA 요소 트리 + Claude Vision 하이브리드 (전략 A) — 픽셀 추정 없는 정밀 제어  
**스킬**: 41개 (자동 등록 — `skills/skill_*.py` 파일만 추가하면 됨)

---

## 1.x → 2.0 주요 변경

| 항목 | 1.x | 2.0 |
|------|-----|-----|
| AI 엔진 | Groq (`llama-3.3-70b`) + Ollama 폴백 | Claude Code CLI 단일 엔진 |
| 화면 인식 | OCR(winocr) 텍스트만 | UIA 요소 트리 + Claude Vision 이미지 |
| 화면 제어 | 좌표 추정 클릭 | UIA 정확 좌표 + Vision 맥락 이해 |
| 에이전트 | Groq native tool-calling 루프 | Claude Code 내장 툴 위임 |
| Claude 훅 | 없음 | PostToolUse·Stop 훅 → JARVIS UI 시각화 |
| 삭제 파일 | — | groq_engine.py, ollama_engine.py, groq_usage.py |

---

## 요구 사항

- Python 3.11 이상 (Windows)
- **Claude Code CLI** — `npm install -g @anthropic-ai/claude-code` 후 `claude login`
- **Anthropic API 키** — Claude Code CLI 로그인 시 자동 설정 (별도 .env 불필요)
- ffmpeg — 화면 녹화·음성 녹음·카메라 사용 시 PATH에 등록 필요
- nircmd — 볼륨 제어 사용 시 PATH에 등록 필요

---

## 설치 및 실행

```powershell
# 1. 가상환경 생성 및 활성화
python -m venv .venv
.\.venv\Scripts\Activate.ps1
# (실행 정책 오류 시: Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser)

# 2. 의존성 설치
pip install -r requirements.txt

# 3. Claude Code CLI 설치 및 로그인 (최초 1회)
npm install -g @anthropic-ai/claude-code
claude login

# 4. 환경변수 설정 (선택 스킬용)
copy .env.example .env
# GROQ_API_KEY 불필요 — Claude Code CLI 사용

# 5. 실행 — 음성 + 웹 대시보드 동시 실행 (기본)
python main.py

# 5'. 실행 — 텍스트 + 웹 대시보드 (마이크 없이)
python main.py --text

# 5''. 실행 — 웹 대시보드 없이 음성만
python main.py --no-web
```

> `python main.py` 하나로 **음성 루프와 웹 대시보드(포트 8765)가 동시에 실행**됩니다.

### 웹 대시보드 프론트엔드

```powershell
cd ui\web
npm install
npm run dev        # Vite 개발 서버: http://localhost:5173
npm run build      # 프로덕션 빌드
npm run typecheck  # 타입 검사
```

빌드 후에는 `http://localhost:8765` 로 바로 접속 가능합니다.

---

## 환경변수 (.env)

| 변수 | 필수 | 설명 |
|------|------|------|
| `ANTHROPIC_API_KEY` | Claude Code CLI 로그인으로 대체 | claude login 시 자동 처리 |
| `KAKAO_REST_API_KEY` | 선택 | 카카오맵 경로 안내·POI 검색 (developers.kakao.com) |
| `KAKAO_JS_API_KEY` | 선택 | 카카오맵 웹 지도 표시용 JavaScript 앱 키 |
| `KAKAO_DEFAULT_LAT` | 선택 | 기본 출발지 위도 (예: `36.3504`) |
| `KAKAO_DEFAULT_LNG` | 선택 | 기본 출발지 경도 (예: `127.3845`) |
| `DAEJEON_BUS_API_KEY` | 선택 | 대전광역시 버스 정보 스킬 (data.go.kr) |
| `NEWSAPI_KEY` | 선택 | 뉴스 스킬 (NewsAPI.org 무료 티어) |
| `BRAVE_SEARCH_API_KEY` | 선택 | 웹 검색을 Brave로 전환 (없으면 DuckDuckGo) |
| `GMAIL_ADDRESS` | 선택 | 이메일 스킬용 Gmail 주소 |
| `GMAIL_APP_PASSWORD` | 선택 | Gmail 앱 비밀번호 (2단계 인증 필요) |
| `WHATSAPP_DEFAULT_COUNTRY_CODE` | 선택 | WhatsApp 기본 국가코드 (기본값: `+82`) |

---

## 기능 목록

### AI 대화 & 에이전트

| 스킬 | 예시 발화 | 비고 |
|------|-----------|------|
| AI 대화 | "파이썬 리스트와 튜플 차이 알려줘" | Claude Code CLI, 다른 스킬이 처리 못하면 자동 폴백 |
| 웹 검색 | "환율 검색해줘", "요즘 주가 찾아줘" | DuckDuckGo 기본, Brave Search 선택 |
| 위키백과 | "아인슈타인 알려줘", "블랙홀 위키백과" | MediaWiki REST API |
| 방법 안내 | "파이썬 설치 방법", "엑셀 단축키 알려줘" | Claude 기반 단계별 설명 |
| **에이전트** | "AI 트렌드 조사해줘", "삼성전자 뉴스 찾아서 저장해줘" | Claude Code 내장 툴(WebSearch·Write) 자동 실행 |

### 화면 인식 & 제어 (2.0 신규)

| 스킬 | 예시 발화 | 비고 |
|------|-----------|------|
| **화면 제어** | "화면 제어로 네이버 열어서 날씨 검색해줘" | UIA + Vision 하이브리드, 정밀 좌표 클릭 |
| **화면 제어** | "직접 제어해서 엑셀 열고 데이터 입력해줘" | Windows 앱·웹 모두 대응 |
| **화면 분석** | "지금 화면 봐줘", "화면에 뭐가 있는지 설명해줘" | UIA 요소 목록 + Vision으로 내용 설명 |
| **화면 분석** | "지금 뭐가 열려 있어?" | 스크린샷 + 번호 오버레이 후 Claude 분석 |

### 날씨 & 정보

| 스킬 | 예시 발화 | 비고 |
|------|-----------|------|
| 날씨 | "서울 날씨", "내일 대전 기온", "강수확률" | Open-Meteo (무료, 키 불필요) |
| 뉴스 | "오늘 뉴스", "최신 기술 뉴스" | NewsAPI 필요 |
| 날짜·시간 | "지금 몇 시야", "오늘 날짜" | 시스템 시간 기준 |
| IP 정보 | "내 IP 알려줘", "IP 주소" | 공인 IP + 위치 정보 |
| 인터넷 속도 | "속도 측정", "인터넷 빠른지 확인해줘" | Cloudflare 엔드포인트 |

### 카카오맵 경로 안내 & POI 검색

`KAKAO_REST_API_KEY` + `KAKAO_JS_API_KEY` 필요 (developers.kakao.com 앱 등록 후 발급)

웹 대시보드에서 드래그 가능한 플로팅 지도 창으로 표시됩니다.

**경로 안내**

| 발화 | 동작 |
|------|------|
| "서울역까지 경로 알려줘" | 현재 위치 → 서울역 최적 경로, 지도·거리·시간·통행료 표시 |
| "대전IC에서 서울까지 최단 시간 경로" | 출발지 명시 지원 |
| "강남역으로 무료도로 우선으로 안내해줘" | 경로 유형: 추천·최단시간·최단거리·무료도로 |

**경로 주변 POI 검색**

| 발화 | 동작 |
|------|------|
| "경로에 주유소 표시해줘" | 경로 500m 이내 마커 표시 |
| "경로 주변 전체 표시해줘" | 8개 카테고리 동시 검색 |

### 대전광역시 버스 정보

`DAEJEON_BUS_API_KEY` 필요 (data.go.kr 발급)

| 발화 | 동작 |
|------|------|
| "샘머리아파트정류장 버스 정보 알려줘" | 도착 예정 버스 목록 |
| "② 추적해줘" / "102번 추적해줘" | 버스 도착까지 반복 추적, 이동 시 알림 |
| "버스 추적 중단" | 진행 중인 추적 중지 |

### PC 제어

| 스킬 | 예시 발화 | 비고 |
|------|-----------|------|
| 앱 실행 | "크롬 열어", "메모장 실행" | ShellExecute |
| 앱 종료 | "크롬 꺼줘", "메모장 종료" | pygetwindow |
| 볼륨 | "볼륨 올려줘", "소리 50으로", "음소거" | pycaw (Windows 전용) |
| 창 제어 | "창 최소화", "최대화해줘" | pygetwindow |
| 클립보드 | "클립보드 뭐야" | pyperclip |
| 시스템 정보 | "CPU 몇 퍼센트야", "메모리 확인" | psutil |
| 전원 관리 | "컴퓨터 종료", "재시작해줘" | ⚠️ 즉시 실행 |
| 슬립 모드 | "슬립 모드", "자비스 잠깐 꺼줘" | 음성인식만 일시 중단 |

### 미디어 캡처 (ffmpeg 필요)

| 스킬 | 예시 발화 | 저장 위치 |
|------|-----------|-----------|
| 스크린샷 | "스크린샷 찍어줘" | `data/captures/` |
| 화면 녹화 | "화면 녹화해줘", "30초 녹화" | `data/captures/` |
| 음성 녹음 | "녹음해줘", "30초 녹음" | `data/captures/` |
| 카메라 촬영 | "사진 찍어줘" | `data/captures/` |

### 생산성 & 유틸리티

| 스킬 | 예시 발화 | 비고 |
|------|-----------|------|
| 달력 | "달력 띄워줘", "6월 달력" | 한국 공휴일·대체공휴일·음력 연휴 |
| 타이머 | "3분 타이머", "30초 후 알려줘" | 백그라운드 실행 |
| 일정 관리 | "내일 오후 3시 회의 등록해줘" | 로컬 JSON |
| 이메일 발송 | "홍길동한테 메일 보내줘" | Gmail SMTP ⚠️ 실제 발송 |
| PDF 읽기 | "보고서.pdf 읽어줘" | pypdf |
| QR 코드 | "QR 코드 만들어줘" | `data/qr/` 저장 |
| 농담 | "농담 해줘" | pyjokes |

---

## 화면 제어 상세 (2.0 핵심 기능)

### 하이브리드 인식 구조 (전략 A)

```
화면 제어 요청
      │
      ├─① UIA 레이어 (pyuiautomation)
      │    현재 포커스 앱의 UI 요소 트리 수집
      │    버튼·입력창·체크박스 등 최대 60개
      │    이름·종류·정확한 좌표·enabled 상태
      │    (실패 시 Vision 단독 모드로 자동 전환)
      │
      ├─② Vision 레이어 (pyautogui + Pillow)
      │    스크린샷 캡처
      │    UIA 요소 위치에 빨간 원 + 번호 오버레이 (Set-of-Mark)
      │    원본 이미지 + 번호 주석 이미지 생성
      │
      └─③ Claude 통합 레이어
           UIA JSON + 번호 오버레이 이미지 동시 전달
           Claude: "3번(검색창)에 '날씨' 입력 → 검색 버튼 클릭"
           실행: UIA 정확 좌표로 클릭 (픽셀 추정 오차 없음)
           웹/이미지 영역: Vision 좌표로 자동 폴백
```

### 트리거 패턴

| 패턴 | 예시 |
|------|------|
| `화면 제어로 ~` | "화면 제어로 네이버 부동산 켜서 대전 서구 아파트 수집해줘" |
| `직접 제어해서 ~` | "직접 제어해서 크롬으로 유튜브 자비스 검색해줘" |
| `화면 에이전트로 ~` | "화면 에이전트로 엑셀 열고 데이터 입력해줘" |
| `[앱] 켜서/열어서 + [저장 동작]` | "네이버 켜서 뉴스 수집해줘" |
| `지금 화면 봐줘` | 화면 분석 전용 (제어 없이 설명만) |

---

## Claude Code 훅 (hooks/)

Claude Code CLI 실행 중 실시간으로 JARVIS 웹 대시보드에 진행 상황을 표시합니다.

| 파일 | 훅 종류 | 동작 |
|------|---------|------|
| `hooks/jarvis_tool_hook.py` | PostToolUse | 툴 사용 시 UI에 "화면 제어: click" 등 표시 |
| `hooks/jarvis_hook.py` | Stop | Claude 최종 응답을 UI WebSocket으로 전송 |
| `hooks/jarvis_send.py` | (공통) | `ws://127.0.0.1:8765/ws` 전송 유틸 |

훅 등록 설정: `.claude/settings.json` (`.gitignore` 제외 시 수동 추가 필요)

```json
{
  "hooks": {
    "PostToolUse": [{"matcher": ".*", "hooks": [{"type": "command",
        "command": "python hooks/jarvis_tool_hook.py"}]}],
    "Stop": [{"hooks": [{"type": "command",
        "command": "python hooks/jarvis_hook.py"}]}]
  }
}
```

---

## 에이전트 상세 (2.0)

"AI 트렌드 조사해줘" 같은 복합 태스크를 Claude Code CLI가 내장 툴로 자동 수행합니다.

### 트리거 조건

| 패턴 | 예시 |
|------|------|
| `~조사해줘 / ~수집해줘` | "최신 AI 논문 수집해줘" |
| `찾아서/검색해서 + 저장 키워드` | "삼성전자 뉴스 찾아서 파일로 저장해줘" |
| `에이전트로 ~` | "에이전트로 처리해줘" |

### Claude Code 내장 툴 활용

| 도구 | 동작 |
|------|------|
| `WebSearch` | 웹 검색 |
| `WebFetch` | URL 페이지 내용 읽기 |
| `Write` | 파일 저장 (txt, json, xlsx 등) |
| `Bash` | 쉘 명령 실행 |
| `computer_use` | 화면 캡처·마우스·키보드 제어 |

---

## 음성 모드

| 동작 | 방법 |
|------|------|
| 활성화 | "Hey Jarvis" (웨이크워드) 또는 박수 두 번 |
| 비활성화 | "자비스 오프" 또는 "자비스 종료" |
| 슬립 | "슬립 모드" → 웨이크워드 대기로 복귀 |
| 프로그램 종료 | "종료" |

- **STT**: faster-whisper (`base` 모델, 한국어)
- **TTS**: edge-tts (`ko-KR-SunHiNeural`)
- **웨이크워드**: openWakeWord `hey_jarvis` (영어 발음)

> 한국어 "자비스" 전용 웨이크워드 모델은 현재 없습니다. 학습 후 `voice/wakeword.py`의 `_WAKEWORD_NAME`만 바꾸면 교체됩니다.

---

## 프로젝트 구조

```
jarvis-core2.0/
├── main.py                         # 진입점 (음성+웹 동시 실행)
├── config/
│   ├── settings.yaml               # 설정 참조
│   └── persona.md                  # 자비스 성격·응답 지침 (AI 시스템 프롬프트)
├── core/                           # ⚠️ 핵심 엔진 — 수정 금지
│   ├── engines/
│   │   ├── claude_cli_engine.py    # 2.0 통합 엔진 — ask()/generate() + run_task()
│   │   └── claude_code.py          # 레거시 (미사용)
│   ├── hybrid_screen.py            # ★ UIA + Vision 하이브리드 화면 인식·제어
│   ├── registry.py                 # 스킬 자동 등록
│   ├── router.py                   # 라우팅 (can_handle 최고 점수 ≥ 0.4)
│   ├── dispatcher.py               # 스킬 실행 + 예외 격리
│   ├── context.py                  # 대화 맥락 (최근 20턴)
│   ├── skill_base.py               # Skill ABC, SkillResult 정의
│   ├── kakao_map_client.py         # 카카오 Directions·Local API
│   ├── bus_client.py               # 대전 버스 도착정보 API
│   ├── buspos_client.py            # 대전 버스 실시간 위치 API
│   └── busstop_client.py           # 대전 버스정류소 검색 + 캐시
├── hooks/                          # ★ Claude Code CLI 훅 (2.0 신규)
│   ├── jarvis_tool_hook.py         # PostToolUse — 툴 동작 UI 시각화
│   ├── jarvis_hook.py              # Stop — 최종 응답 UI 전송
│   └── jarvis_send.py              # WebSocket 전송 유틸
├── commands/                       # Windows OS 위임 카탈로그
│   ├── registry.py
│   ├── windows_bridge.py
│   └── specs/
├── voice/                          # 음성 입출력 (Windows 전용)
│   ├── stt.py                      # faster-whisper STT
│   ├── tts.py                      # edge-tts TTS
│   ├── wakeword.py                 # openWakeWord + ClapDetector
│   └── clap_detector.py            # 박수 감지
├── ui/
│   ├── server.py                   # FastAPI (REST + WebSocket)
│   └── web/                        # React 18 + TypeScript + Vite
├── skills/                         # ⭐ 기능 파일 (41개, 여기에만 추가)
│   ├── skill_screen_agent.py       # ★ 화면 제어 (HybridScreenEngine)
│   ├── skill_computer_use.py       # ★ 화면 분석 (HybridScreenEngine)
│   ├── skill_agent.py              # 멀티스텝 에이전트 (Claude Code CLI)
│   ├── skill_ai_chat.py            # AI 대화 폴백 (ClaudeCliEngine)
│   ├── skill_navigation.py         # 카카오맵 경로 안내
│   ├── skill_poi_search.py         # POI 검색
│   ├── skill_bus_tracker.py        # 대전 버스 추적
│   ├── skill_web_search.py         # 웹 검색
│   ├── skill_weather.py            # 날씨
│   ├── skill_news.py               # 뉴스
│   └── ...                         # 기타 33개 스킬
├── tests/                          # assert 기반 단위 테스트
├── data/                           # 런타임 데이터
│   ├── contacts.json
│   ├── schedule.json
│   ├── bus_config.json
│   └── usage.json                  # Claude Code 일일 비용 추적
├── .env.example
├── requirements.txt
└── CLAUDE.md                       # Claude Code 전용 개발 지침
```

---

## 새 기능 추가

`skills/` 폴더에 `skill_<이름>.py` 파일 하나만 추가하면 자동 등록됩니다. `core/` 수정 불필요.

```python
from core.skill_base import Skill, SkillResult

class MySkill(Skill):
    name = "my_skill"
    description = "한 줄 설명"
    triggers = ["키워드"]
    examples = ["예시 발화"]

    def can_handle(self, intent: str, text: str) -> float:
        return 0.9 if "키워드" in text else 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        return SkillResult(speech="응답 텍스트", success=True)
```

라우터 임계값 **0.4** — `can_handle`이 0.4 미만이면 AI 대화 폴백으로 넘어갑니다.

---

## 테스트 실행

```powershell
# 개별 스킬 테스트 (pytest 없음 — assert 기반 스크립트)
python -m tests.test_skill_calendar
python -m tests.test_skill_timer
python -m tests.test_skill_browser
python -m tests.test_clap_detector
```

---

## 주의사항

- **전원 종료·재시작**: 미저장 작업이 모두 손실됩니다. 실행 전 저장 여부를 반드시 확인하세요.
- **화면 제어 (`--dangerously-skip-permissions`)**: Claude가 마우스·키보드를 직접 제어합니다. 실행 전 화면 상태를 확인하세요.
- **이메일·WhatsApp 발송**: 실제로 전송됩니다. 수신자를 확인하세요.
- **화면 녹화·녹음·카메라**: ffmpeg이 PATH에 없으면 비활성화됩니다.
- **Gmail 앱 비밀번호**: 구글 계정 비밀번호가 아닌 "앱 비밀번호"를 사용하세요.
- **버스 스킬**: `DAEJEON_BUS_API_KEY` 없어도 다른 기능에는 영향 없습니다.
- **uiautomation 패키지**: 없으면 화면 제어가 Vision 단독 모드로 자동 전환됩니다.
