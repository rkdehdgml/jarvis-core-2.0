# MANUAL_CHECKLIST.md

자동 테스트로 검증할 수 없는(또는 검증해서는 안 되는) 위험·비가역 작업 목록.
각 항목은 실제 동작 전 사용자가 직접 수동으로 1회 확인해야 한다.

## 묶음 D — 전원 제어 (skill_power)

- [ ] "컴퓨터 종료해줘" 발화 → 실제로 시스템이 종료되는지 확인 (POWER_SHUTDOWN, `shutdown.exe /s /t 0`)
- [ ] "재시작해줘" 발화 → 실제로 재시작되는지 확인 (POWER_RESTART, `shutdown.exe /r /t 0`)
- [ ] "절전모드로 바꿔줘" 발화 → 실제로 절전 모드로 들어가는지 확인 (POWER_SLEEP, `rundll32.exe powrprof.dll,SetSuspendState 0,1,0`)
- [ ] 위 3개 명령 모두 작업 저장/문서 닫기 등 사전 준비 후 테스트할 것 (특히 종료/재시작은 미저장 작업 손실 위험)

## 묶음 G — 이메일 / WhatsApp 발송 (skill_email, skill_whatsapp)

- [ ] `.env`에 `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`(Gmail 앱 비밀번호 — 계정 비밀번호 아님) 설정
- [ ] Gmail 2단계 인증 활성화 후 "앱 비밀번호" 발급해 `GMAIL_APP_PASSWORD`에 입력
- [ ] 이메일 실발송 확인: "본인이메일@gmail.com 한테 이메일 보내줘 자비스 테스트입니다" 발화 → 수신함 도착 확인
- [ ] 이메일 제목/본문 분리 확인: "본인이메일@gmail.com 한테 제목은 회의 내용은 3시 시작 메일 보내줘" → 제목="회의", 본문="3시 시작" 확인
- [ ] `.env`에 `WHATSAPP_DEFAULT_COUNTRY_CODE`(선택, 기본 `+82`) 필요 시 설정
- [ ] WhatsApp Web에 미리 로그인(최초 1회 QR 스캔)해서 세션이 유지되어 있는지 확인 — 미로그인 시 발송 실패
- [ ] WhatsApp 실발송 확인: 본인 번호로 "010-XXXX-XXXX로 왓츠앱 보내줘 테스트" 발화 → 브라우저에서 WhatsApp Web이 열리고 메시지가 자동 전송/탭이 자동 닫히는지 확인
- [ ] WhatsApp 발송은 `pyautogui`로 실제 마우스/키보드를 제어하므로, 전송 중에는 마우스·키보드를 건드리지 말 것
