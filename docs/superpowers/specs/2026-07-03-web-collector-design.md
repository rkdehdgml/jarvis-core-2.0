# Playwright 기반 웹 수집·검색 확인 스킬 설계

> 사용자가 화면 제어 개선안(하이브리드 아키텍처 - 의도 추출/시각적 실행 분리)을 검토 요청한 것을
> 계기로, "임의 사이트를 탐색하며 데이터를 검색·수집·필터링·확인하는" 읽기 중심 자동화를
> Playwright로 새로 추가하기로 결정. 작성일: 2026-07-03.

## 배경

현재 웹 관련 자동화는 두 계층으로 나뉘어 있다.

1. **`skills/skill_browser.py`** — LLM 호출 없이 정규식으로 알려진 사이트 바로가기·검색 URL을
   조합해 기본 브라우저로 연다. 빠르지만 URL 조합 이상의 상호작용(필터, 로그인, 페이지네이션)은
   못 한다.
2. **`skills/skill_agent.py`** → `ClaudeCliEngine.run_task()`(`core/engines/claude_cli_engine.py`) —
   클로드 코드 CLI 내장 `WebSearch`/`WebFetch`/`Write` 툴로 조사·수집·파일 저장을 수행한다.
   `WebFetch`는 **정적 HTML만** 가져오므로 자바스크립트 렌더링 사이트(네이버 부동산 매물 목록,
   로그인 후 노출되는 콘텐츠, 무한스크롤/페이지네이션 목록)는 다루지 못한다.
3. 이런 사이트는 지금 `core/hybrid_screen.py`의 `HybridScreenEngine`(UIA + 스크린샷 Vision
   관찰-판단-실행 루프)으로 처리되고 있는데, 매 스텝 스크린샷을 찍어 클로드에게 Read 툴로
   보여주고 판단을 받는 구조라 느리고(스텝마다 CLI 서브프로세스+Vision 왕복), 최대 스텝
   수(`_MAX_STEPS=15`)에 막혀 목록형 데이터 수집에는 근본적으로 부적합하다.

이 틈(JS 렌더링·로그인·필터가 필요한 사이트에서의 읽기 중심 데이터 수집)을 Playwright로
메운다.

## 범위

- **포함**: 임의 사이트 탐색, 검색창 입력, 필터/드롭다운 조작, 페이지네이션·무한스크롤을 통한
  목록 순회, 목록/표 데이터를 구조화된 레코드로 추출, xlsx 저장.
- **제외 (이번 스킬에서 다루지 않음)**: 결제, 삭제, 메시지 전송, 폼 제출처럼 되돌리기 어려운
  "쓰기" 액션. 필요해지면 별도 설계·별도 확인 절차와 함께 추후 확장한다.
- 기존 `skill_browser.py`(URL 바로가기)와 `skill_agent.py`(정적 리서치)는 그대로 유지 —
  이번 스킬은 "실제 브라우저 렌더링·상호작용이 필요한 읽기 작업"만 새로 커버한다.

## 아키텍처

`core/hybrid_screen.py`의 관찰→판단→실행 폐쇄 루프 패턴을 웹에 그대로 적용하되, 스크린샷·UIA
대신 Playwright의 DOM을 쓴다 — 이미지가 없으므로 클로드 호출이 텍스트 전용이 되어 스텝당
속도·비용이 크게 개선된다.

- **`core/web_collector.py`** (신규, `core/hybrid_screen.py`와 동일 레벨) — `WebCollectorEngine`
  클래스. Playwright로 Chromium을 **headed 모드**(눈에 보이게)로 띄우고 루프를 돈다.
- **`skills/skill_web_collector.py`** (신규) — 트리거 매칭 후
  `WebCollectorEngine.run(task)` 호출. `skill_agent.py`/`skill_screen_agent.py`와 동일하게
  얇은 어댑터 역할만 한다.

`core/`의 기존 파일은 수정하지 않는다 (라우터 스코어링 조정을 위해 `skill_agent.py`의 트리거
리스트에 대한 코멘트만 추가할 수 있음 — 아래 라우터 절 참조).

## 데이터 흐름 (매 스텝)

1. `_collect_elements(page)` — Playwright로 현재 페이지에서 상호작용 가능하거나 정보성인
   요소(링크·버튼·입력창·드롭다운·리스트 항목·제목·가격 등 텍스트 노드)를 DOM에서 걸어
   내려가며 수집한다. `hybrid_screen.py`의 `UIAElement`/`_walk_uia`와 동일하게 각 요소에
   **idx 번호**를 매겨 텍스트 목록(JSON)으로 직렬화한다. 요소 상한(`_MAX_ELEMENTS`)을 둔다.
2. 이 텍스트 목록 + 지금까지의 행동 기록(history)을 `ClaudeCliEngine.decide()`에 순수 텍스트
   프롬프트로 전달한다 (이미지 없음 → Read 툴 왕복도 없음).
3. 클로드는 아래 중 정확히 하나의 JSON 행동만 리턴한다:
   - `{"action": "navigate", "url": "..."}`
   - `{"action": "click", "idx": N}`
   - `{"action": "type", "idx": N, "text": "..."}`
   - `{"action": "extract", "idx": [N, ...]}` — 지정 요소들을 구조화 레코드 1건으로 누적
   - `{"action": "scroll", "direction": "up|down"}`
   - `{"action": "wait", "seconds": 1~3}`
   - `{"action": "done", "message": "..."}`
   - `{"action": "fail", "message": "..."}`
4. `WebCollectorEngine`이 Playwright API로 실제 실행하고, 결과를 history에 기록한 뒤 다음
   스텝으로 넘어간다 (`_MAX_STEPS` 상한으로 무한 루프 방지 — `hybrid_screen.py`와 동일 값
   재사용).

## 범위 가드레일 (읽기 전용 강제)

`hybrid_screen.py`의 `_DANGEROUS_ELEMENT_KEYWORDS` 패턴을 그대로 차용한다.
`_IRREVERSIBLE_ACTION_KEYWORDS = ["구매", "결제", "신청하기", "삭제", "전송", "제출", "탈퇴", "취소"]`
등 되돌리기 어려운 액션으로 보이는 이름의 요소는 `click`/`type` 대상이어도 코드 레벨에서
무조건 거부한다 (클로드의 판단만으로는 막을 수 없다는 것이 `hybrid_screen.py` 주석에 이미
사고 사례로 명시돼 있음 — 동일 원칙 적용).

## 결과 저장

`extract`로 누적된 레코드 리스트를 `done` 시점에 `openpyxl`로 xlsx 저장한다
(`requirements.txt`에 이미 있는 의존성 재사용, `agent_tools/file_tool`의 xlsx 저장 관례와
동일한 방식). 저장 경로는 `data/collected/`(신규 디렉터리) 아래 태스크 기반 파일명으로 생성.
반환 `speech`는 "N건 수집해서 OO.xlsx로 저장했습니다" 형태의 한국어 요약.

## 라우터 통합 (트리거 충돌 방지)

`skill_agent.py`가 이미 `_STRONG_TRIGGERS = ["조사해줘", "조사해서", "수집해줘", "수집해서",
"에이전트로"]`를 0.9로 매칭하므로 겹친다. `skill_screen_agent.py`의 2단 스코어링
(`_STRONG`/`_OPEN`/`_ACTION`) 패턴을 따라 구분한다.

- **강한 트리거** (0.95): "브라우저로 수집", "브라우저에서 검색", "사이트에서 직접 수집" 등
  명시적으로 실제 브라우저 상호작용을 요구하는 문구.
- **사이트+액션 조합** (0.93, `skill_agent`의 0.9보다 우선): 알려진 인터랙티브 사이트
  키워드(부동산·쇼핑몰·중고거래 등 도메인 성격 키워드, 확장 가능한 리스트) + 수집/필터/검색
  액션 동사가 함께 있는 경우.
- 그 외 일반 리서치("OO 트렌드 조사해줘")는 지금처럼 `skill_agent`가 처리하도록 이 스킬은
  0.0을 반환한다.

`skill_screen_agent.py`도 "네이버 부동산 켜서 ... 수집해줘"류 example을 갖고 있어 스코어가
겹칠 수 있다 — 웹 브라우저 대상 수집 작업은 새 스킬이 우선하도록 스코어를 조정하고,
`skill_screen_agent.py`의 examples 주석에서 이제 처리 범위가 아님을 명시한다 (데스크톱 앱
제어는 계속 `screen_agent` 담당).

## 로그인 세션

Playwright의 `storage_state`를 `data/web_collector_state.json`에 저장해 재사용한다.
파일이 없으면 headed 브라우저가 뜬 상태로 사용자가 수동 로그인할 시간을 주고(타임아웃 내
사용자 입력 대기), 로그인 완료 후 상태를 저장한다. 이 흐름의 구체적 UX(대기 시간, 안내
메시지)는 구현 계획 단계에서 확정한다.

## 의존성

- `requirements.txt`에 `playwright>=1.42` 추가.
- 최초 1회 `playwright install chromium` 별도 설치 필요 — README/CLAUDE.md에 setup 절차로
  문서화.

## 에러 처리

`hybrid_screen.py`와 동일하게 각 행동 실행은 개별 try/except로 감싸 실패해도 루프 전체가
죽지 않게 하고, 실패 사유를 history에 남겨 다음 판단에 반영한다. 페이지 로드 타임아웃,
셀렉터 미발견 등은 "실행 실패: ..." 형태로 outcome을 만들어 다음 스텝 프롬프트에 포함한다.
Playwright/브라우저 자체가 기동 실패하면(브라우저 미설치 등) 스킬 실행 전체가 한국어 에러
메시지로 즉시 종료한다.

## 테스트

- **단위/플레인 테스트** (`tests/test_skill_web_collector_streaming.py`) —
  `tests/test_skill_screen_agent_streaming.py`와 동일한 방식으로 `WebCollectorEngine`을
  가짜로 교체해 스트리밍 상태·라우팅을 검증. 실제 Playwright/브라우저 기동 없이 실행 가능.
- **라우터 스코어링 테스트** — `skill_web_collector`/`skill_agent`/`skill_screen_agent`
  간 트리거 문장별 점수 우선순위 검증 (plain assert).
- **실제 통합 테스트**는 이번 설계 범위에서 자동화하지 않는다 — 구현 완료 후 사용자가 실제
  사이트(예: 네이버 부동산, 쿠팡 등)로 직접 수동 테스트한다.

## 미결 사항 (구현 계획 단계에서 구체화)

- 로그인 대기 UX의 정확한 타임아웃/안내 문구.
- "인터랙티브 사이트 키워드" 리스트의 초기 구성 (부동산/쇼핑몰/중고거래 등 카테고리 예시만
  정해져 있고 전체 목록은 미정).
- DOM 요소 수집 시 어떤 태그/role을 "정보성 텍스트"로 포함할지 세부 휴리스틱
  (가격/제목/날짜 등 흔한 패턴).
