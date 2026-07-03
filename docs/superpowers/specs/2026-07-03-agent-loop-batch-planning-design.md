# 화면/웹 제어 공통 하네스 + 배치 플래닝 설계

> 사용자가 화면 인식·제어의 정확성/속도 개선을 요청. 조사 결과 CLI 자체를 가볍게 만드는
> 방법은 문서화되어 있지 않음(세션 유지 스트리밍 미지원, `--resume`도 매번 새 프로세스 기동,
> `--bare`는 존재하나 효과 불명)이 확인되어, "호출을 가볍게" 대신 "호출 횟수를 줄이기"를
> 핵심 레버로 채택. 작성일: 2026-07-03.

## 배경

`core/hybrid_screen.py`(네이티브 UIA+Vision)와 `core/web_collector.py`(Playwright DOM)는
동일한 관찰→판단→실행 폐쇄 루프 패턴을 각자 구현하고 있다. 두 엔진 모두 매 스텝마다
`ClaudeCliEngine.decide()`를 호출해 "행동 1개"만 판단받는데, 이 호출 자체가 스텝당 평균
17초 이상(대부분 CLI 서브프로세스 기동+모델 호출)을 차지한다.

Claude Code CLI 공식 문서를 조사한 결과:
- 프로세스를 유지한 채 여러 턴을 스트리밍으로 주고받는 공식 지원 모드는 없다.
- `--resume`은 시스템 프롬프트 재전송만 건너뛸 뿐, 매번 새 프로세스를 기동한다.
- `--bare`가 존재하지만 실제 절감 효과는 문서화되어 있지 않다.
- Claude Agent SDK도 CLI와 동일한 지연 프로파일을 가진다(SDK는 CLI의 래퍼일 뿐).

즉 이 프로젝트의 제약("Claude Code CLI만 사용, 직접 API 호출 금지") 안에서는 **호출 1건을
가볍게 만들 방법이 없고**, 유일하게 유효한 레버는 **호출 횟수 자체를 줄이는 것**이다.

## 범위

- **포함**: 두 엔진이 공유할 수 있는 관찰-판단-실행 하네스(`core/agent_loop.py`) 신설.
  `core/web_collector.py`를 이 하네스 위로 이전하면서 "배치 플래닝"(한 번의 판단으로
  짧은 행동 묶음을 계획하고, 확신 가능한 구간에서는 Claude를 다시 부르지 않고 로컬 검증만
  거쳐 연속 실행)을 적용.
- **제외 (이번 설계에서 다루지 않음)**: `core/hybrid_screen.py`의 실제 리팩터링과 배치
  적용. 네이티브는 스크린샷 기반이라 상태 변화 예측이 DOM보다 불안정해 배치의 위험이 더
  크다고 판단, 이번 스코프에서는 하네스 설계만 네이티브를 염두에 두고(향후 이전 가능하도록)
  대비하되 실제 마이그레이션은 별도 후속 계획으로 미룬다.
- 정확성 개선은 "배치 실행 시 로컬 검증 체크포인트"(요소가 실제로 아직 존재하는지 확인)
  하나로 한정한다 — 사용자가 명시한 대로 아직 실제 운용에서 반복 관측된 정확성 실패 유형이
  없어(추측 단계), 그 이상의 정확성 엔지니어링(동적 로딩 대기, 다단계 흐름 감지 등)은
  실제 실패가 관측된 뒤 별도로 다룬다.

## 아키텍처

```
core/agent_loop.py   (신규, 공유 하네스)
  ├── Element              # idx/label/kind 최소 필드를 가진 공통 요소 표현
  ├── Observer 프로토콜      # collect() -> (elements, image_path: str | None)
  ├── Executor 프로토콜      # execute(action, elements) -> outcome: str
  │                         # verify(action, elements) -> bool  (배치 로컬 검증)
  └── AgentLoop.run(task)   # 스텝 루프, 히스토리, session_id 재사용(--resume),
                            # _MAX_STEPS, 배치 플래닝(옵션)을 모두 포함

core/web_collector.py   (수정)
  └── WebCollectorEngine   # WebObserver(Playwright DOM 수집) + WebExecutor(click/type/
                           # navigate/scroll/extract, 안전 키워드 차단, verify()=
                           # data-jarvis-idx 존재 확인) 구현. 루프 자체는 AgentLoop에 위임.
                           # _finish()/_wants_file_save()/_summarize_records()(저장·요약
                           # 로직)는 웹 전용 관심사이므로 그대로 이 클래스에 남는다.

core/hybrid_screen.py   (이번 설계에서는 변경 없음 — 후속 계획에서 같은 하네스로 이전 예정,
                         이전 시에도 batch_enabled=False로 지금과 동일한 단일행동 동작 유지)
```

## 배치 플래닝

- `decide()`에 전달하는 프롬프트가 "행동 1개"가 아니라 **행동 배열(1~4개, `_MAX_BATCH = 4`)**
  을 요청하도록 바뀐다. Claude는 확신되는 구간(예: 검색창 클릭→입력→엔터)에서는 여러 개를,
  애매하거나 분기 가능성이 있으면 배열 길이 1을 반환하도록 프롬프트로 유도한다(강제 아님 —
  프롬프트 지시일 뿐이므로 하네스가 계획 검증으로 안전망을 담당).
- 배치 내 각 행동을 실행하기 **직전**, `Executor.verify(action, elements)`로 로컬 검증만
  수행한다 (Claude 재호출 없음). 배치의 **첫 번째 행동도 예외 없이** 검증한다 — 관찰
  시점과 실행 시점 사이에 페이지가 바뀌는 드문 경우까지 동일하게 방어하기 위함이며, 비용이
  거의 없는 로컬 체크라 예외를 둘 이유가 없다.
  - web: `[data-jarvis-idx="N"]` 셀렉터로 대상 요소가 여전히 존재하는지 확인.
  - 검증 실패 시 → 남은 계획을 전부 폐기하고, 그 스텝까지의 outcome만 history에 기록한 뒤
    다음 루프 반복에서 새로 관찰하고 Claude를 다시 호출한다.
- Claude가 `max_batch`(4)를 초과하는 배열을 반환하면 앞의 4개만 사용하고 나머지는 버린다
  (자르는 지점 이후는 애초에 존재하지 않았던 것처럼 취급 — 다음 스텝에서 새로 계획됨).
- `navigate` 행동은 페이지 구조를 통째로 바꾸므로, 배치 도중 `navigate`가 실행되면 그 행동만
  수행하고 **배치를 무조건 중단**한다 (남은 계획 폐기, 새 관찰로 복귀).
- 안전 키워드 차단(`_IRREVERSIBLE_ACTION_KEYWORDS`)은 배치 내 각 행동마다 개별적으로 그대로
  적용된다 — 배치라는 이유로 우회되지 않는다.
- `extract`(상태를 바꾸지 않는 읽기 행동)는 배치에 자유롭게 포함 가능하며 verify 대상이
  아니다. `click`/`type`만 verify 대상.
- `_MAX_STEPS`는 지금처럼 **"Claude 호출(계획 라운드) 횟수"** 기준으로 유지한다 — 배치 안의
  개별 행동은 별도 스텝으로 세지 않는다. 실제 지연 시간을 좌우하는 것이 호출 횟수이기
  때문이다.

## 컴포넌트 상세

```python
# core/agent_loop.py

@dataclass
class Element:
    idx: int
    label: str   # 프롬프트에 보여줄 표시 텍스트 (web: text, native: name)
    kind: str    # 프롬프트에 보여줄 종류 (web: role/tag, native: control_type 한글 라벨)

class Observer(Protocol):
    def collect(self) -> tuple[list[Element], str | None]: ...

class Executor(Protocol):
    def execute(self, action: dict, elements: list[Element]) -> str: ...
    def verify(self, action: dict, elements: list[Element]) -> bool: ...

class AgentLoop:
    def __init__(
        self,
        observer: Observer,
        executor: Executor,
        prompt_builder: Callable[[str, list[Element], list[str], str | None], str],
        batch_enabled: bool = False,
        max_batch: int = 4,
        max_steps: int = 15,
        on_chunk: Callable[[str], None] | None = None,
    ) -> None: ...

    def run(self, task: str) -> str: ...
```

- `web_collector.py`의 `WebCollectorEngine`은 `_collect_elements`/`_execute_action`을
  `WebObserver`/`WebExecutor`로 얇게 감싸 `AgentLoop`에 전달하고, 루프 본체(`for step in
  range(...)`)는 삭제한다. `run()`은 `AgentLoop(...).run(task)`를 호출한 뒤 결과를
  `_finish()`로 넘기는 얇은 메서드가 된다.
- 프롬프트 빌더(`_build_decision_prompt`)는 행동 배열을 요청하는 문구와 예시로 갱신된다
  (기존 "정확히 하나의 JSON 객체" → "1~4개의 행동으로 이루어진 JSON 배열, 확신이 없으면
  배열 길이 1").

## 에러 처리

- 개별 행동 실행 중 예외는 지금처럼 `Executor.execute()` 내부 try/except에서 잡아 outcome
  문자열로 변환한다 — 하네스로 예외가 전파되지 않아 한 스텝 실패가 전체 루프를 죽이지
  않는다는 기존 불변조건을 그대로 유지한다.
- 배치 검증 실패(`verify() -> False`)는 예외가 아니라 정상적인 제어 흐름 신호다 — 배치를
  조용히 중단하고 다음 관찰로 넘어간다.
- `_parse_action`(JSON 파싱)은 이제 배열을 파싱해야 하므로, 최상위가 리스트가 아니면
  (예: 여전히 단일 객체를 반환한 경우) `[obj]`로 감싸 하위 호환 처리한다 — 프롬프트를
  완벽히 따르지 않는 응답에 대한 방어.

## 테스트

- `tests/test_agent_loop.py` (신규, plain assert) — 가짜 Observer/Executor로 `AgentLoop`의
  로직만 검증: 배치 캡(4개 초과 요청 시 잘리는지), `navigate` 시 배치 중단, `verify()
  -> False` 시 남은 계획 폐기, `_MAX_STEPS` 도달 시 종료 메시지. 실제 Playwright/Claude
  CLI 없이 실행 가능.
- 기존 `tests/test_skill_web_collector_streaming.py`는 `WebCollectorEngine`의 공개
  인터페이스(스트리밍 콜백, 라우팅)가 바뀌지 않으므로 그대로 유지되어야 한다 — 리팩터링이
  내부 구조만 바꾸고 공개 동작을 바꾸지 않았음을 검증하는 회귀 테스트 역할.
- 실제 사이트 대상 통합 테스트(배치가 실제로 스텝 수/소요 시간을 줄이는지)는 이번 설계
  범위에서 자동화하지 않는다 — 구현 완료 후 사용자가 실제 사이트로 직접 확인한다.

## 후속 계획 (이번 스코프 밖)

- `core/hybrid_screen.py`를 `AgentLoop` 위로 이전 (`batch_enabled=False`로 지금과 동일한
  단일행동 동작 유지). UIA `_walk_uia` 결과를 `Element`로 매핑하는 `ScreenObserver`,
  `click_element`/`type_into_element`/`_press_key`/`_scroll`을 감싸는 `ScreenExecutor`
  구현이 필요.
- 네이티브에도 배치를 적용할지 여부는 이번 이전 작업 이후 실제 안정성을 관찰하고 별도로
  결정한다.
