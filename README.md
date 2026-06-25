# jarvis-core

Windows 네이티브 개인 AI 비서. Claude Code CLI 단일 엔진.

## 요구 사항

- Python 3.11 이상
- Claude Code CLI 설치 및 로그인 완료

## 가상환경 설정 (Windows PowerShell)

```powershell
# 1. 가상환경 생성
python -m venv .venv

# 2. 가상환경 활성화
.\.venv\Scripts\Activate.ps1

# 실행 정책 오류 시 먼저 실행:
# Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# 3. 의존성 설치
pip install -r requirements.txt

# 4. 실행 (STEP 6 이후)
python main.py

# 텍스트 모드로 실행 (음성 없이)
python main.py --text

# 5. 가상환경 비활성화
deactivate
```

## 웹 대시보드 실행

음성/텍스트 루프(`main.py`)와는 별개의 독립 프로세스입니다. 두 프로세스는 상태를 공유하지 않습니다.

```powershell
uvicorn ui.server:app --host 127.0.0.1 --port 8765
```

### 프론트엔드 (ui/web)

```powershell
cd ui\web
npm install
npm run dev         # Vite 개발 서버, http://localhost:5173
npm run build        # tsc -b && vite build
npm run typecheck    # tsc --noEmit
```

## 테스트 실행

pytest는 사용하지 않습니다. `tests/` 아래 assert 기반 스크립트를 모듈로 직접 실행합니다.

```powershell
python -m tests.test_skills_step5
```

## 프로젝트 구조

```
jarvis-core/
├── main.py                  # 진입점
├── config/                  # 전역 설정, 자비스 성격 프롬프트
├── core/                    # ⚠️ 본체 — 거의 수정하지 않음
├── voice/                   # 음성 입출력 (STT, TTS, 핫워드)
├── ui/                      # 웹 UI (FastAPI + React)
├── skills/                  # ⭐ 기능 추가 시 여기에 파일만 넣기
└── data/                    # 스킬 데이터 저장소
```

## 새 기능 추가

`skills/` 폴더에 `skill_<이름>.py` 파일을 추가하면 자동으로 등록됩니다.
본체 코드(`core/`) 수정은 필요 없습니다.

## 음성 모드 참고

- 웨이크워드는 현재 openWakeWord의 사전학습 모델 "hey_jarvis"(영어 "Hey Jarvis")를 사용합니다.
  한국어 "자비스" 전용 모델은 별도 학습이 필요해 아직 지원하지 않습니다.
- 마이크가 인식되지 않거나 무응답이면 Windows 설정 > 시스템 > 소리 > 입력에서
  마이크 장치가 "사용" 상태인지 먼저 확인하세요(녹음 탭에서 비활성화/숨김 상태인 경우가 흔합니다).
