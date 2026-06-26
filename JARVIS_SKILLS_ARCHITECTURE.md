# JARVIS_SKILLS_ARCHITECTURE.md

> 이 문서는 **설계 문서**다. 코드는 인터페이스 시그니처/스텁 수준까지만 포함하며, 실제 로직 구현은
> 다음 단계의 구현자 에이전트가 맡는다. `JARVIS_PLUGIN_DESIGN.md`가 코어 파이프라인(라우터/디스패처/
> 레지스트리)의 설계 근거를 다루는 문서라면, 이 문서는 그 위에 신규 기능 6개 카테고리를 얹기 위한
> 확장 설계를 다룬다.

## 0. 전제와 범위

- **전제(주어진 컨텍스트 그대로 채택)**: `main.py`(또는 그 후속 엔트리포인트)가 **WSL2(Ubuntu)** 안에서
  Python으로 실행되고, Claude Code CLI도 같은 WSL 세션 안에 설치되어 subprocess로 호출된다. OS 종속
  기능(볼륨/전원/스크린샷/녹화 등)은 WSL에서 직접 실행할 수 없으므로 **Windows 네이티브로 위임**한다.
- **이 전제는 현재 저장소의 실제 런타임과 다르다.** 현재 `CLAUDE.md`/`JARVIS_PLUGIN_DESIGN.md`는
  "jarvis-core는 Windows-native 어시스턴트"라고 명시하고, `skill_volume.py`는 `pycaw`로 Windows COM을
  **직접** 호출한다(WSL Python에서는 동작 불가). 이 불일치는 임의로 한쪽으로 정리하지 않고
  [8. 결정 필요](#8-결정-필요) #1, #2에 질문으로 남긴다. 이 문서의 나머지 부분은 "주어진 컨텍스트(WSL2
  + Windows 위임)"를 전제로 신규 기능만 설계한다.
- **범위 밖**: 기존 4개 스킬(`skill_volume`, `skill_window`, `skill_app_launch`, `skill_app_control`)의
  재작성. 이미 동작하는 코드이므로 이번 설계에서 건드리지 않는다 — 단, WSL 전제와의 충돌은 결정 필요
  항목으로 남긴다.
- **core/는 수정하지 않는다.** `core/skill_base.py`, `core/registry.py` 등 기존 계약은 그대로 두고,
  이 문서에서 추가하는 모든 메타데이터/규약은 "ABC가 강제하지 않는 서브클래스 차원의 관례"로 얹는다.

---

## 1. 디렉터리 구조

```
jarvis-core/
├── .env                            # (gitignore) 모든 API 키 — 신규 키는 §6 참고
├── .env.example
├── core/                           # 절대 수정 없음
│   ├── skill_base.py               #   Skill ABC, SkillResult — 그대로
│   ├── registry.py                 #   skills/ glob 스캔 — 그대로
│   ├── router.py / dispatcher.py   #   그대로
│   ├── context.py                  #   그대로
│   ├── engines/                    #   그대로 (claude_code.py, groq_engine.py)
│   └── ...
├── commands/                       # ★ 신규 — OS 위임 + dict 기반 명령 매핑 전용 레이어
│   ├── __init__.py
│   ├── registry.py                 #   COMMAND_MAP 단일 dict(CommandSpec) + register()
│   ├── windows_bridge.py           #   WSL→Windows 호출의 유일한 통로 (run_command, run_powershell 등)
│   └── specs/                      #   카테고리별 CommandSpec 정의 (registry.py가 이걸 모아 등록)
│       ├── power_specs.py          #     전원(종료/재시작/절전)
│       ├── capture_specs.py        #     스크린샷/화면녹화/음성녹음/웹캠 캡처
│       ├── browser_specs.py        #     URL/유튜브재생/SNS/쇼핑/구글앱 열기
│       └── system_specs.py         #     CPU/RAM/디스크 조회
├── skills/                         # 기존 패턴 그대로 — skill_*.py만 추가하면 auto-discovery 대상
│   │                               #   (기존 8개: ai_chat, app_control, app_launch, clipboard,
│   │                               #              system_info, volume, weather, web_search, window)
│   ├── skill_power.py              # 신규 — 카테고리 1
│   ├── skill_screenshot.py         # 신규 — 카테고리 1
│   ├── skill_screen_record.py      # 신규 — 카테고리 1
│   ├── skill_voice_record.py       # 신규 — 카테고리 1
│   ├── skill_datetime.py           # 신규 — 카테고리 2
│   ├── skill_ip_info.py            # 신규 — 카테고리 2
│   ├── skill_speedtest.py          # 신규 — 카테고리 2
│   ├── skill_system_status.py      # 신규 — 카테고리 2 (CPU/RAM/디스크, Windows 위임 — §8 #2 참고)
│   ├── skill_location.py           # 신규 — 카테고리 2
│   ├── skill_youtube.py            # 신규 — 카테고리 3
│   ├── skill_browser.py            # 신규 — 카테고리 3 (검색/URL/구글앱/SNS/쇼핑 열기)
│   ├── skill_wikipedia.py          # 신규 — 카테고리 3
│   ├── skill_news.py               # 신규 — 카테고리 3
│   ├── skill_howto.py              # 신규 — 카테고리 3 ("~하는 방법", AI 폴백 경유)
│   ├── skill_email.py              # 신규 — 카테고리 4
│   ├── skill_whatsapp.py           # 신규 — 카테고리 4 (§8 #5 참고)
│   ├── skill_pdf_reader.py         # 신규 — 카테고리 5
│   ├── skill_qr.py                 # 신규 — 카테고리 5
│   ├── skill_contacts.py           # 신규 — 카테고리 5
│   ├── skill_camera.py             # 신규 — 카테고리 5
│   ├── skill_joke.py               # 신규 — 카테고리 5
│   ├── skill_schedule.py           # 신규 — 카테고리 5
│   ├── skill_timer.py              # 신규 — 카테고리 5
│   └── skill_sleep_mode.py         # 신규 — 카테고리 5 (§8 #8 참고)
├── data/
│   ├── contacts.json               # 신규 — skill_contacts 로컬 저장
│   ├── schedule.json                # 신규 — skill_schedule 로컬 저장
│   └── qr/                          # 신규 — 생성된 QR 이미지 출력 폴더
├── voice/, ui/                      # 변경 없음
└── tests/
    └── test_commands_registry.py    # 신규 — COMMAND_MAP 무결성(중복 키, 필수 필드) 검사
```

### 카테고리 → 모듈 매핑

| 카테고리 | skill 파일 | `commands/specs/*` 사용 여부 |
|---|---|---|
| 1. 시스템 제어 | `skill_power`, `skill_screenshot`, `skill_screen_record`, `skill_voice_record` | `power_specs`, `capture_specs` |
| 2. 정보 제공 | `skill_datetime`, `skill_ip_info`, `skill_speedtest`, `skill_system_status`, `skill_location` | `system_specs` (system_status만) |
| 3. 웹/미디어 | `skill_youtube`, `skill_browser`, `skill_wikipedia`, `skill_news`, `skill_howto` | `browser_specs` (youtube 재생, browser만) |
| 4. 커뮤니케이션 | `skill_email`, `skill_whatsapp` | 없음 — `skill_whatsapp`은 Windows 보조 프로세스(§8 #5) |
| 5. 유틸리티 | `skill_pdf_reader`, `skill_qr`, `skill_contacts`, `skill_camera`, `skill_joke`, `skill_schedule`, `skill_timer`, `skill_sleep_mode` | `capture_specs` (camera만) |

`commands/`를 쓰지 않는 스킬(날짜/IP/위키피디아/뉴스/이메일/QR/연락처/농담/일정 등)은 전부 **WSL
네이티브에서 그대로 실행 가능** — 순수 Python 로직 또는 외부 REST API 호출이라 OS 위임이 필요 없다.

---

## 2. Skill 인터페이스 계약

`core/skill_base.py`의 `Skill` ABC(`name`/`description`/`triggers`/`examples`/`can_handle()`/`execute()`)는
**그대로 유지**한다. 아래 필드는 ABC가 강제하지 않는, 이 설계에서 새로 도입하는 **서브클래스 관례**다 —
Python은 추가 클래스 속성을 자유롭게 허용하므로 `core/`를 건드리지 않고도 적용할 수 있다.

```python
# skills/skill_<name>.py 공통 관례 (core/skill_base.py는 수정하지 않음)

class Skill(ABC):  # 기존 계약, 참고용 재게시
    name: str
    description: str
    triggers: list[str]
    examples: list[str]

    # --- 이 설계가 추가하는 선택적 관례 ---
    command_ids: tuple[str, ...] = ()
    """이 스킬이 Windows로 위임하는 commands.registry.COMMAND_MAP 키 목록.
    비어 있으면 OS 위임이 필요 없는 순수 WSL 로직(예: skill_joke)이라는 뜻.
    문서화 용도 + tests/test_commands_registry.py 가 "스킬이 참조하는 모든
    command_id가 COMMAND_MAP에 실재하는지" 검증할 때 쓴다."""
```

OS 위임이 필요한 스킬의 표준 형태(예: `skill_power.py` 스텁):

```python
from core.skill_base import Skill, SkillResult
from commands.windows_bridge import run_command

# "자연어 명령 → command_id" 매핑. 이 스킬이 다루는 하위 명령이 여러 개일 때
# if/elif 체인 대신 dict로 분기한다 (§3의 COMMAND_MAP과는 별개의, 스킬 로컬 dict).
_PHRASE_TO_COMMAND: dict[str, str] = {
    "종료": "POWER_SHUTDOWN",
    "꺼줘": "POWER_SHUTDOWN",
    "재시작": "POWER_RESTART",
    "재부팅": "POWER_RESTART",
    "절전": "POWER_SLEEP",
}

class PowerSkill(Skill):
    name = "power"
    description = "컴퓨터를 종료/재시작/절전 모드로 전환한다"
    triggers = ["종료", "재시작", "절전", "재부팅"]
    examples = ["컴퓨터 종료해줘", "재시작해줘", "절전모드로 바꿔줘"]
    command_ids = ("POWER_SHUTDOWN", "POWER_RESTART", "POWER_SLEEP")

    def can_handle(self, intent: str, text: str) -> float: ...
        # 기존 app_control.py와 동일한 패턴: 모호하면 낮은 점수, 명확하면 0.9

    def _resolve_command_id(self, text: str) -> str | None: ...
        # _PHRASE_TO_COMMAND 순회, 가장 먼저 매칭되는 키워드의 command_id 반환

    def execute(self, text: str, context: dict) -> SkillResult:
        command_id = self._resolve_command_id(text)
        if command_id is None:
            return SkillResult(speech="어떤 동작인지 알 수 없습니다.", success=False)
        result = run_command(command_id)   # commands/windows_bridge.py 진입점, 예외를 던지지 않음
        return SkillResult(speech=..., success=result.ok, data={"command_id": command_id})
```

이 패턴이 모든 OS-위임 스킬(`skill_screenshot`, `skill_screen_record`, `skill_voice_record`,
`skill_system_status`, `skill_browser`, `skill_youtube`(재생), `skill_camera`)에 동일하게 적용된다.

---

## 3. 명령어 라우팅 dict 스펙 (`commands/registry.py`)

2단계 dict 구조로 "확장 시 한 곳만 건드린다"를 만족시킨다.

1. **1단계 (스킬 로컬)**: 위 `_PHRASE_TO_COMMAND` — 자연어 트리거 키워드 → `command_id`. 스킬 파일에
   귀속되므로 `skills-only` 확장 원칙과 충돌하지 않는다.
2. **2단계 (중앙 집중)**: `commands/registry.py`의 `COMMAND_MAP` — `command_id` → "어떻게 위임할지"
   (`CommandSpec`). **기존 카테고리에 새 명령을 추가할 때는 해당 `commands/specs/<category>_specs.py`
   파일 한 곳만 건드린다.** 새 카테고리를 통째로 추가할 때만 `registry.py`에 `register()` 호출 한 줄이
   추가된다.

```python
# commands/registry.py (스텁)
from dataclasses import dataclass
from typing import Callable, Literal

Runner = Literal["windows_bridge"]  # 현재는 위임 전용. WSL native 스킬은 이 레이어를 거치지 않는다.
BridgeKind = Literal["exe", "powershell", "ffmpeg"]

@dataclass(frozen=True)
class CommandSpec:
    command_id: str
    description: str
    bridge: BridgeKind
    binary: str | None = None                          # bridge="exe"일 때 호출할 실행 파일
    script: str | None = None                          # bridge="powershell"일 때 인라인 스크립트(또는 .ps1 경로)
    build_args: Callable[[dict], list[str]] | None = None  # kwargs → 인자 리스트
    timeout: int = 15

COMMAND_MAP: dict[str, CommandSpec] = {}

def register(specs: dict[str, CommandSpec]) -> None:
    """commands/specs/*.py 가 자신의 CommandSpec들을 COMMAND_MAP에 등록하는 단일 진입점.
    중복 command_id가 들어오면 조용히 덮어쓰지 않고 ValueError로 즉시 실패시킨다."""
    for command_id, spec in specs.items():
        if command_id in COMMAND_MAP:
            raise ValueError(f"중복 command_id: {command_id}")
        COMMAND_MAP[command_id] = spec

# 파일 하단에서 각 카테고리 spec을 등록 (여기만 보면 전체 명령 목록의 "목차"가 됨)
from commands.specs import power_specs, capture_specs, browser_specs, system_specs
register(power_specs.SPECS)
register(capture_specs.SPECS)
register(browser_specs.SPECS)
register(system_specs.SPECS)
```

```python
# commands/specs/power_specs.py (스텁) — 카테고리 1개 추가 시 건드릴 "한 곳"
from commands.registry import CommandSpec

SPECS: dict[str, CommandSpec] = {
    "POWER_SHUTDOWN": CommandSpec(
        command_id="POWER_SHUTDOWN", description="시스템 종료",
        bridge="exe", binary="shutdown.exe", build_args=lambda kw: ["/s", "/t", "0"],
    ),
    "POWER_RESTART": CommandSpec(
        command_id="POWER_RESTART", description="시스템 재시작",
        bridge="exe", binary="shutdown.exe", build_args=lambda kw: ["/r", "/t", "0"],
    ),
    "POWER_SLEEP": CommandSpec(
        command_id="POWER_SLEEP", description="절전 모드 진입",
        bridge="exe", binary="rundll32.exe",
        build_args=lambda kw: ["powrprof.dll,SetSuspendState", "0,1,0"],
    ),
}
```

`commands/windows_bridge.py`는 기존 `ClaudeCodeEngine`/`GroqEngine`의 "절대 예외를 던지지 않는다" 원칙을
그대로 따른다 — OS 위임은 실패 모드가 더 많기 때문(바이너리 없음, 권한 없음, WSL↔Windows 경로 문제 등).

```python
# commands/windows_bridge.py (스텁)
from dataclasses import dataclass
from commands.registry import COMMAND_MAP

@dataclass(frozen=True)
class CommandResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int

def run_command(command_id: str, **kwargs) -> CommandResult:
    """COMMAND_MAP[command_id]를 찾아 bridge 종류에 맞는 내부 함수로 위임한다.
    command_id가 없거나 실행 자체가 실패해도 예외를 던지지 않고 ok=False로 반환한다."""

def _run_exe(binary: str, args: list[str], timeout: int) -> CommandResult: ...
def _run_powershell(script: str, timeout: int) -> CommandResult: ...
def _run_ffmpeg(args: list[str], timeout: int) -> CommandResult: ...
```

---

## 4. OS 종속 기능의 위임 전략

| 기능 | 실행 위치 | 추천 방식 | 호출 형태 | 사유 / 대안 |
|---|---|---|---|---|
| 볼륨 조절·음소거 | Windows 위임 | **nircmd.exe** | `nircmd.exe setsysvolume <0-65535>` / `mutesysvolume 1` | Windows에 볼륨 제어용 표준 CLI가 없음(Core Audio API는 COM). nircmd가 가장 가벼움. 대안: PowerShell Gallery `AudioDeviceCmdlets`(서명된 모듈, 설치 필요) — 서명 신뢰도는 높지만 모듈 설치 단계가 추가됨. **결정 필요 #4** |
| 전원: 종료/재시작 | Windows 위임 | **shutdown.exe** | `/s /t 0`, `/r /t 0` | OS 내장, 추가 설치 불필요 |
| 전원: 절전 | Windows 위임 | **rundll32.exe + powrprof.dll** | `powrprof.dll,SetSuspendState 0,1,0` | shutdown.exe는 절전을 지원하지 않음. OS 내장 |
| 앱 실행 | Windows 위임 | **powershell.exe Start-Process** | `Start-Process notepad` | 기존 `skill_app_launch.py`는 WSL에서 직접 실행 불가 — 위임 시 동일 패턴 적용(§8 #1) |
| 앱 종료 | Windows 위임 | **taskkill.exe** | `/IM notepad.exe /F` | OS 내장, 단순. 기존 `skill_app_control.py`(psutil 직접 종료)와 동등 기능 |
| 스크린샷 | Windows 위임 | **PowerShell + .NET (`System.Drawing`)** | 인라인 스크립트 1개 | OS 내장만으로 충분, 추가 바이너리 불필요. 대안: `nircmd savescreenshot` |
| 화면녹화 + 음성 | Windows 위임 | **ffmpeg (`gdigrab` + `dshow`)** | `ffmpeg -f gdigrab -i desktop -f dshow -i audio="마이크" out.mp4` | 성숙하고 무료. yt-dlp도 내부적으로 ffmpeg에 의존하므로 의존성을 재사용. 대안: OBS CLI(더 무거움, 사전 설정 필요) |
| 음성만 녹음 | Windows 위임 | **ffmpeg (`dshow` 오디오만)** | `ffmpeg -f dshow -i audio="마이크" out.wav` | 화면녹화와 동일 의존성 재사용 |
| 웹캠 캡처(로컬 디바이스) | Windows 위임 | **ffmpeg (`dshow` 비디오)** | `ffmpeg -f dshow -i video="카메라" -frames:v 1 out.png` | 카메라 디바이스는 WSL 패스스루가 거의 불가능 |
| 모바일 카메라(IP 스트림) | **WSL native** | `opencv-python` 또는 `requests`로 스트림 URL 수신 | — | 네트워크 스트림이라 로컬 디바이스 접근이 필요 없음 — 위임 불필요 |
| CPU/RAM/디스크 | Windows 위임 | **PowerShell `Get-CimInstance`** | `Win32_Processor`, `Win32_OperatingSystem`, `Win32_LogicalDisk` | WSL2의 psutil은 WSL VM 자체 리소스를 보고하므로 호스트 값과 다름(§8 #2). CIM/WMI는 OS 내장 |
| 인터넷 속도 | WSL native (1차) | `speedtest` 파이썬 패키지 | — | 구현 단순. WSL2 NAT로 인해 체감과 오차 가능 — **결정 필요 #6** |
| 브라우저 검색 / URL / 구글앱 / SNS / 쇼핑 열기 | Windows 위임 | **PowerShell `Start-Process <url>`** | 기본 브라우저·프로토콜 핸들러로 위임 | 브라우저 종류를 신경 쓸 필요 없음, OS 내장 |
| 유튜브 다운로드 | WSL native | **yt-dlp** | — | 파일시스템 작업이라 위임 불필요 (pytube는 deprecated) |
| 유튜브 "재생"(GUI로 열기) | Windows 위임 | **PowerShell `Start-Process <url>`** | browser_specs와 동일 경로 재사용 | 재생은 화면 출력이 필요한 GUI 동작 |
| PDF 음성 재생(합성된 mp3) | Windows 위임 | **PowerShell `Start-Process <mp3경로>`** | 기본 연결 프로그램으로 재생 | `Media.SoundPlayer`는 wav만 지원 — mp3 변환 없이 가장 단순한 경로 |
| WhatsApp 발신 | Windows 위임(보조 프로세스) | **Windows에 설치된 `python.exe` + `pywhatkit`** | WSL → `powershell.exe -Command "python C:\...\whatsapp_sender.py ..."` | pywhatkit이 내부적으로 `pyautogui` GUI 자동화를 쓰므로 단순 바이너리 호출이 아니라 별도 Python 실행 환경이 필요함 — **결정 필요 #5** |
| 타이머 알림 | WSL native (TTS) | 기존 음성 출력 파이프라인 재사용 | — | 토스트 알림까지는 불필요하다고 판단(옵션 — §8 #9) |

---

## 5. 의존성 목록

### WSL(Linux) 측 신규 Python 패키지

| 패키지 | 용도 | 비고 |
|---|---|---|
| `yt-dlp>=2024.1` | 유튜브 다운로드 | `pytube` deprecated 대체 |
| `pypdf>=4.0` | PDF 텍스트 추출 | `PyPDF2` deprecated 대체 |
| `qrcode[pil]>=7.4` | QR 이미지 생성 | |
| `pyjokes>=0.6.0` | 프로그래밍 농담 | |
| `speedtest>=1.0` (`speedtest-cli` 후속 유지보수 패키지명 확인 필요) | 인터넷 속도 측정 | **결정 필요 #6** |
| `requests` | 뉴스/IP/위치/위키 REST 호출 | 이미 `requirements.txt`에 있음, 재사용 |
| `python-dotenv` | `.env` 로딩 | 이미 있음, 재사용 |

### Windows 측 (pip이 아닌 바이너리/도구)

| 도구 | 용도 | 설치 방식 가정 |
|---|---|---|
| `ffmpeg.exe` | 화면녹화/음성녹음/웹캠 캡처 | winget/choco로 사전 설치, PATH 등록 — **결정 필요 #7** |
| `nircmd.exe` | 볼륨 제어 | 사전 다운로드 + PATH 등록 — **결정 필요 #4** |
| `shutdown.exe` / `rundll32.exe` / `taskkill.exe` / `powershell.exe` | 전원/앱 제어 | OS 내장, 추가 설치 없음 |
| Windows용 `python.exe` + `pywhatkit` | WhatsApp 발신 | 별도 설치 — **결정 필요 #5** |

### Deprecated → 대체 매핑

| 기존/흔한 선택 | 상태 | 대체 | 비고 |
|---|---|---|---|
| `pytube` | 유지보수 단절 | `yt-dlp` | 지침에 이미 명시 |
| `PyPDF2` | deprecated | `pypdf` | 지침에 이미 명시 |
| `duckduckgo_search` | deprecated | `ddgs` | 이미 적용됨(`core/search_engine.py`) |
| `speedtest-cli`(파이썬, 2020년 이후 업데이트 희소) | 유지보수 느림 | Ookla 공식 `speedtest` CLI(Windows 위임) 또는 활성 유지보수 패키지 확인 | **결정 필요 #6** |
| `wikipedia`(파이썬, abandonware 추정) | 유지보수 느림 | `wikipedia-api` 또는 MediaWiki REST API 직접 호출 | **결정 필요 #10** |

---

## 6. `.env` 키 명세

| 키 | 용도 | 필수/선택 |
|---|---|---|
| `GROQ_API_KEY` | (기존) AI 폴백 엔진 | 기존 |
| `BRAVE_SEARCH_API_KEY` | (기존) 웹검색 폴백 | 기존, 선택 |
| `NEWSAPI_KEY` | 최신 뉴스(NewsAPI.org) 조회 | 신규, 뉴스 기능 사용 시 필수 |
| `GMAIL_ADDRESS` | Gmail SMTP 발신 계정 | 신규, 이메일 기능 시 필수 |
| `GMAIL_APP_PASSWORD` | Gmail 앱 비밀번호(2단계 인증 기반 — 계정 비밀번호 아님) | 신규, 이메일 기능 시 필수 |
| `WHATSAPP_DEFAULT_COUNTRY_CODE` | pywhatkit 발신 시 기본 국가코드(예: `+82`) | 신규, 선택 |
| `GOOGLE_CALENDAR_CREDENTIALS_PATH` | (선택) Google Calendar OAuth 클라이언트 파일 경로 — 일정을 로컬 JSON 대신 캘린더로 연동할 때만 | 신규, 선택 — **결정 필요 #9** |

> 참고: 날씨(Open-Meteo)·IP 기반 위치(`ip-api.com` 등)는 무료·무키 한도 내에서 충분해 별도 키가
> 필요 없다고 가정했다. 호출량이 한도를 넘으면 추가 키가 필요할 수 있다.

> **`ANTHROPIC_API_KEY` 관련**: 주어진 컨텍스트는 "subprocess 환경에 절대 주입하지 않는다"고 명시했지만,
> 현재 `core/engines/claude_code.py`의 `_ENV_WHITELIST`에는 이미 포함되어 있다. `core/`를 수정하지
> 않는다는 원칙과 충돌하므로 새 키를 추가하지 않고 **결정 필요 #3**으로 남긴다.

---

## 7. 구현 배치 계획

의존성 낮은 것부터, 위험한 것(전원 제어)과 무거운 설치 요구사항(WhatsApp)은 뒤로 배치했다.

| 배치 | 내용 | 완료 기준 |
|---|---|---|
| **1. 기반 레이어** | `commands/registry.py`, `windows_bridge.py` 골격 + 빈 `COMMAND_MAP` | `python -c "from commands.registry import COMMAND_MAP"` 임포트 성공, `tests/test_commands_registry.py`가 빈 dict에 대해 통과 |
| **2. 순수 WSL 정보/유틸 스킬** | `skill_datetime`, `skill_joke`, `skill_qr`, `skill_contacts`, `skill_schedule`(로컬 JSON) | 각 스킬을 단독 실행해 한국어 응답 텍스트가 정상 출력되는지 assert (기존 `tests/test_skills_step5` 패턴) |
| **3. 외부 무료 API 스킬** | `skill_ip_info`, `skill_location`, `skill_wikipedia`, `skill_news`, `skill_howto` | `.env`에 `NEWSAPI_KEY` 설정 후 각 스킬 실제 네트워크 호출 1회씩 수동 실행, 응답 확인 |
| **4. Windows 위임 브릿지 검증** | `windows_bridge.py`의 `_run_powershell`/`_run_exe` 실제 구현 + `skill_power`(절전/재시작부터) | WSL에서 `powershell.exe -Command "echo test"`가 stdout을 정상 반환하는지 확인 → 사용자 승인 하에 `POWER_RESTART` 1회 수동 트리거해 실제 재시작되는지 확인 |
| **5. 미디어 캡처** | `skill_screenshot`, `skill_screen_record`, `skill_voice_record`, `skill_camera` | 각 실행 후 결과 파일(png/mp4/wav)이 0바이트가 아닌지 확인, 화면녹화는 5초 분량을 직접 재생해 화면+음성이 잡혔는지 눈으로 확인 |
| **6. 브라우저/유튜브/시스템상태** | `skill_browser`, `skill_youtube`, `skill_system_status`, `skill_speedtest` | 브라우저가 실제로 열리는지, yt-dlp 다운로드 파일 생성 확인, `system_status` 값을 Windows 작업 관리자와 대조해 WSL 내부 값이 아님을 확인 |
| **7. 커뮤니케이션 + PDF** | `skill_email`, `skill_whatsapp`(Windows 보조 프로세스), `skill_pdf_reader`(+TTS 재생) | 본인 메일로 테스트 발송 성공, 본인 번호로 WhatsApp 테스트 메시지 1회 발송 확인, PDF 한 페이지가 TTS로 들리는지 확인 |
| **8. 타이머/슬립모드 + 통합 검증** | `skill_timer`, `skill_sleep_mode` + `COMMAND_MAP` 전체 무결성 재검증 | "5분 후 깨워줘" 발화 후 실제 알림 발생 확인, "슬립모드" 발화 후 "wake up" 전까지 무응답 확인, `COMMAND_MAP` 중복 키 없음 검증 |

---

## 8. 결정 필요

아래는 코드/대화만으로 결론 낼 수 없어 사용자 확인이 필요한 지점이다.

1. **실행 환경 불일치**: 현재 4개 스킬(`skill_volume`, `skill_app_launch`, `skill_app_control`,
   `skill_window`)은 Windows 네이티브 프로세스 안에서 `pycaw`/`pygetwindow`로 OS를 **직접** 제어한다.
   주어진 전제(메인 프로세스가 WSL2에서 실행)대로면 이 4개는 더 이상 동작하지 않는다(WSL Python은
   Windows COM에 접근 불가). 이 4개를 `commands/windows_bridge` 위임 방식으로 다시 설계할지, 아니면
   메인 프로세스를 계속 Windows 네이티브로 유지하고 이번 신규 기능만 "향후 WSL 전환 대비 옵션
   설계"로 둘지?
2. **같은 이유로 시스템 정보**: 기존 `skill_system_info.py`(psutil 기반)도 WSL 안에서 돌면 WSL 가상머신
   자체의 CPU/RAM을 보고한다(Windows 호스트 값 아님). 신규 `skill_system_status.py`(Windows 위임판)와
   기존 것을 둘 다 유지할지, 기존 것을 위임 방식으로 교체할지?
3. **`ANTHROPIC_API_KEY` 화이트리스트 충돌**: `core/engines/claude_code.py`의 `_ENV_WHITELIST`에 이미
   포함되어 있어 "subprocess 환경에 절대 주입하지 않는다"는 원칙과 충돌한다. 새 기능에만 이 원칙을
   적용하고 기존 `claude_code.py`는 그대로 둘지, 아니면 `core/` 수정이 필요한 별도 작업으로 분리할지?
4. **nircmd 설치 가정 가능 여부**: 볼륨 위임에 추천한 `nircmd.exe`는 서명되지 않은 서드파티 바이너리라
   SmartScreen/안티바이러스 경고가 뜰 수 있다. 사전 설치를 가정해도 될지, 서명된 PowerShell 모듈
   `AudioDeviceCmdlets`(설치 단계 추가)로 대체할지?
5. **WhatsApp 발신의 무거운 설치 요구사항**: `pywhatkit`은 GUI 자동화(`pyautogui`)가 필수라 WSL에서
   실행할 수 없다. Windows 쪽에 별도 Python 환경 + `pywhatkit`을 설치해 그쪽에서 실행하는 구조를
   가정해도 될지?
6. **인터넷 속도 측정 정확도**: WSL2 NAT 네트워킹 특성상 측정값이 Windows 호스트 체감과 다를 수 있다.
   WSL native(구현 간단, 정확도 낮을 가능성)로 시작할지, 처음부터 Windows 위임(Ookla 공식 CLI, 정확도
   높음, 설치 부담 추가)으로 갈지?
7. **ffmpeg 사전 설치 가정**: 화면녹화/음성녹음/웹캠 캡처가 모두 ffmpeg(Windows 빌드)를 전제한다.
   PATH에 설치되어 있다고 가정해도 될지, 설치 확인/안내 로직까지 설계 범위에 포함해야 할지?
8. **슬립 모드의 구현 위치**: "wake up까지 유지"는 `SkillResult.follow_up` 한 턴짜리 플래그로 표현되지
   않는, "리스닝 자체를 한동안 억제"하는 동작이다. 스킬의 `context.data` 상태만으로 충분한지, 아니면
   `main.py`(이건 `core/`가 아니므로 수정 가능하다고 해석했는데 맞는지?)의 음성 루프 쪽 로직 변경이
   필요한지?
9. **뉴스/일정의 외부 의존도**: NewsAPI 무료 티어는 하루 100회 호출 제한이 있다. 이 한도로 충분한지,
   일정 기능을 로컬 JSON으로만 둘지 Google Calendar API 연동까지 포함할지?
10. **wikipedia 패키지의 유지보수 상태**: "deprecated 라이브러리 금지" 원칙에 따라, 업데이트가 뜸한
    `wikipedia` 패키지 대신 MediaWiki REST API를 `requests`로 직접 호출하는 방식으로 대체할지?
