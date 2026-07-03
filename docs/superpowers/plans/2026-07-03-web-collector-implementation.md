# Playwright 웹 수집 스킬 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** JS 렌더링·로그인이 필요한 사이트에서 검색·수집·필터링·확인을 수행하는 읽기 전용 Playwright
자동화 스킬(`skill_web_collector`)을 추가한다.

**Architecture:** `core/hybrid_screen.py`의 관찰→판단→실행 폐쇄 루프 패턴을 웹에 적용한 신규
`core/web_collector.py`(`WebCollectorEngine`) + 얇은 어댑터 `skills/skill_web_collector.py`.
매 스텝 Playwright가 현재 페이지의 DOM 요소를 텍스트 목록으로 뽑아 `ClaudeCliEngine.decide()`
(텍스트 전용, Vision 없음)에 넘기면, 클로드는 행동 1개(JSON)만 판단하고 실제 실행은
`WebCollectorEngine`이 담당한다.

**Tech Stack:** Playwright(Python, sync API) + Chromium(headed 기본), 기존 `ClaudeCliEngine`
(`core/engines/claude_cli_engine.py`), 기존 `openpyxl` 저장 유틸(`skills/agent_tools/file_tool.py`).

## Global Constraints

- 설계 문서: `docs/superpowers/specs/2026-07-03-web-collector-design.md` (승인 완료).
- 범위는 **읽기 전용**(검색/수집/필터링/확인)만 — 결제·삭제·전송·제출 등 되돌릴 수 없는
  액션은 코드 레벨에서 강제 차단한다 (모델 판단만으로 막지 않는다).
- `core/`의 기존 파일(`hybrid_screen.py`, `router.py`, `dispatcher.py` 등)은 **수정하지
  않는다** — 새 파일만 추가한다. 유일한 예외는 문서 파일(`requirements.txt`, `CLAUDE.md`).
- 테스트는 pytest가 아니라 plain assert 스크립트 (`python -m tests.<module>`로 실행,
  `tests/test_skill_screen_agent_streaming.py`와 동일한 스타일).
- Playwright 테스트는 `headless=True`로 실행해 창이 뜨지 않게 한다 — 실제 스킬 실행 시의
  기본값(`headless=False`, 눈에 보이게)과는 별개.
- Claude 판단 호출은 실제 `claude` CLI를 부르지 않고 **가짜 엔진으로 대체**해 테스트한다
  (외부 유료 API 호출은 항상 페이크, Playwright 자체는 실제 브라우저로 검증 — 프로젝트
  기존 테스트 관례와 동일).
- **설계 문서와의 차이**: 설계 문서는 결과 저장 위치로 `data/collected/`를 제안했지만, 이미
  검증된 `skills/agent_tools/file_tool.py`의 `save_xlsx()`가 정확히 필요한 기능(rows/headers →
  xlsx)을 제공하므로 이를 그대로 재사용한다 (DRY) — 저장 위치는 그 유틸의 기존 관례대로
  `~/Desktop`이 된다. `skill_agent.py`가 만드는 파일과 같은 위치에 모이므로 사용자 입장에서도
  일관적이다.

---

### Task 1: Playwright 의존성 설치 + DOM 요소 수집 (`_collect_elements`)

**Files:**
- Modify: `requirements.txt` (파일 끝에 추가)
- Modify: `CLAUDE.md:18-44` (Commands 섹션에 Playwright 설치 안내 추가)
- Create: `core/web_collector.py`
- Test: `tests/test_web_collector_engine.py`

**Interfaces:**
- Produces: `core.web_collector.WebElement` (dataclass: `idx: int, tag: str, type: str, role: str,
  text: str`, 메서드 `to_dict() -> dict`), `core.web_collector.WebCollectorEngine`
  (`__init__(self, on_chunk: Callable[[str], None] | None = None, headless: bool = False)`,
  메서드 `_collect_elements(self, page) -> list[WebElement]`).

- [ ] **Step 1: Playwright 설치**

```bash
pip install playwright
playwright install chromium
```

- [ ] **Step 2: `requirements.txt`에 의존성 추가**

`requirements.txt` 파일 끝(64번째 줄, `uiautomation>=2.0.18 ...` 다음)에 아래 내용을 추가한다:

```
# 웹 수집 에이전트 (core/web_collector.py + skills/skill_web_collector.py)
# 전략: Playwright DOM 스냅샷(텍스트) + Claude 판단 — 스크린샷/Vision 없이 관찰-판단-실행
playwright>=1.42        # 실제 브라우저(Chromium) 제어 — 최초 1회 `playwright install chromium` 별도 필요
```

- [ ] **Step 3: `CLAUDE.md` Commands 섹션에 설치 안내 추가**

`CLAUDE.md`의 `## Commands` 코드블록 안, `pip install -r requirements.txt` 다음 줄에 추가:

```diff
 # Setup
 python -m venv .venv
 .\.venv\Scripts\Activate.ps1
 pip install -r requirements.txt
+playwright install chromium   # skill_web_collector 최초 1회 필요 (브라우저 바이너리 설치)
```

- [ ] **Step 4: 실패하는 테스트 작성**

`tests/test_web_collector_engine.py` 새로 작성:

```python
"""core/web_collector.py 단위 테스트 (plain assert 스크립트).

실행: python -m tests.test_web_collector_engine  (프로젝트 루트에서)
Playwright + Chromium이 설치되어 있어야 한다 (playwright install chromium).
"""
from core.web_collector import WebCollectorEngine


def test_collect_elements() -> None:
    from playwright.sync_api import sync_playwright

    html = """
    <html><body>
      <h1>테스트 상품 목록</h1>
      <input type="search" placeholder="검색어" />
      <button>검색</button>
      <li class="title">노트북 A</li>
    </body></html>
    """

    engine = WebCollectorEngine(headless=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.set_content(html)
            elements = engine._collect_elements(page)

            tags = {el.tag for el in elements}
            assert "h1" in tags, f"h1이 수집되지 않음: {tags}"
            assert "input" in tags, f"input이 수집되지 않음: {tags}"
            assert "button" in tags, f"button이 수집되지 않음: {tags}"
            assert "li" in tags, f"li가 수집되지 않음: {tags}"

            heading = next(el for el in elements if el.tag == "h1")
            assert heading.text == "테스트 상품 목록", f"h1 텍스트 불일치: {heading.text}"

            search_input = next(el for el in elements if el.tag == "input")
            assert search_input.text == "검색어", f"input placeholder 미수집: {search_input.text}"

            marked = page.evaluate(
                f'document.querySelector(\'[data-jarvis-idx="{heading.idx}"]\')?.tagName'
            )
            assert marked == "H1", f"data-jarvis-idx가 DOM에 반영 안 됨: {marked}"
        finally:
            browser.close()

    print("test_collect_elements 통과")


def main() -> None:
    test_collect_elements()
    print("\ntest_web_collector_engine (Task 1) 검증 통과")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 테스트 실행 → 실패 확인**

Run: `python -m tests.test_web_collector_engine`
Expected: `ModuleNotFoundError: No module named 'core.web_collector'`

- [ ] **Step 6: `core/web_collector.py` 최소 구현**

```python
"""Playwright DOM 스냅샷 + Claude 판단 기반 웹 수집 에이전트.

core/hybrid_screen.py의 관찰-판단-실행 폐쇄 루프 패턴을 웹에 적용한다.
UIA+스크린샷 대신 Playwright의 DOM을 텍스트로 뽑아 클로드에 넘기므로, 이미지가 없어
스텝당 클로드 호출이 텍스트 전용이 된다 (Read 툴 왕복 불필요 — hybrid_screen.py보다 가볍다).

이 엔진은 읽기 전용(검색/수집/필터링/확인)만 수행한다 — 구매/결제/삭제/전송/제출 등
되돌릴 수 없는 액션은 요소 텍스트에 그런 키워드가 보이면 코드 레벨에서 강제 차단한다.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

_MAX_STEPS = 15          # hybrid_screen.py와 동일 값 재사용 — 무한 루프 방지
_MAX_WAIT_SECONDS = 3.0  # hybrid_screen.py와 동일 값 재사용
_MAX_ELEMENTS = 80       # 프롬프트 과부하 방지

_ACTION_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

_STORAGE_STATE_PATH = Path(__file__).parent.parent / "data" / "web_collector_state.json"

# 클릭/입력 대상 요소 텍스트에 이 키워드가 포함되면 무조건 거부한다 — 이 엔진은
# 읽기 전용(검색/수집/필터링)만 다루고, 되돌릴 수 없는 액션은 모델 판단만으로
# 막을 수 없어(hybrid_screen.py의 잠금화면 클릭 사고 사례 참고) 코드 레벨에서 차단한다.
_IRREVERSIBLE_ACTION_KEYWORDS = [
    "구매", "결제", "신청하기", "삭제", "전송", "제출", "탈퇴", "취소",
]

_COLLECT_JS = """
() => {
  const SEL = 'a, button, input, select, textarea, [role="button"], [role="link"], ' +
              '[role="checkbox"], h1, h2, h3, li, td, th, [class*="price"], [class*="title"]';
  const nodes = Array.from(document.querySelectorAll(SEL));
  const out = [];
  let idx = 0;
  for (const el of nodes) {
    if (out.length >= 80) break;
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) continue;
    const style = window.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') continue;
    idx += 1;
    el.setAttribute('data-jarvis-idx', String(idx));
    const text = (el.innerText || el.value || el.placeholder ||
                  el.getAttribute('aria-label') || '').trim().slice(0, 80);
    out.push({
      idx: idx,
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute('type') || '',
      role: el.getAttribute('role') || '',
      text: text,
    });
  }
  return out;
}
"""


@dataclass
class WebElement:
    """Playwright DOM에서 추출한 단일 요소."""
    idx: int
    tag: str
    type: str
    role: str
    text: str

    def to_dict(self) -> dict:
        return {
            "번호": self.idx,
            "태그": self.tag,
            "종류": self.role or self.type or self.tag,
            "텍스트": self.text,
        }


class WebCollectorEngine:
    """Playwright + Claude 하이브리드로 웹사이트를 탐색하며 데이터를 수집하는 엔진."""

    def __init__(
        self,
        on_chunk: Callable[[str], None] | None = None,
        headless: bool = False,
    ) -> None:
        self._on_chunk = on_chunk
        self._headless = headless
        # Claude Code CLI 엔진 - lazy import로 순환 참조 방지
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            from core.engines.claude_cli_engine import ClaudeCliEngine
            self._engine = ClaudeCliEngine(timeout=600)
        return self._engine

    # -- DOM 수집 레이어 -----------------------------------------------------

    def _collect_elements(self, page) -> list[WebElement]:
        """현재 페이지에서 상호작용 가능·정보성 요소를 idx 번호와 함께 수집한다.

        각 요소에 data-jarvis-idx 속성을 실제로 심어두므로, 이후
        `[data-jarvis-idx="N"]` 셀렉터로 같은 요소를 다시 찾아 클릭/입력할 수 있다.
        """
        try:
            raw = page.evaluate(_COLLECT_JS)
        except Exception as e:
            logger.warning(f"요소 수집 실패: {e}")
            return []
        return [WebElement(**item) for item in raw]
```

- [ ] **Step 7: 테스트 실행 → 통과 확인**

Run: `python -m tests.test_web_collector_engine`
Expected: `test_collect_elements 통과` 및 `test_web_collector_engine (Task 1) 검증 통과` 출력, exit code 0

- [ ] **Step 8: 커밋**

```bash
git add requirements.txt CLAUDE.md core/web_collector.py tests/test_web_collector_engine.py
git commit -m "feat: Playwright 웹 수집 엔진 - DOM 요소 수집 레이어 추가"
```

---

### Task 2: 행동 실행 (`_execute_action`) — navigate/click/type/extract/scroll/wait + 가드레일

**Files:**
- Modify: `core/web_collector.py`
- Test: `tests/test_web_collector_engine.py` (Task 1 파일에 이어서 추가)

**Interfaces:**
- Consumes: Task 1의 `WebElement`, `_IRREVERSIBLE_ACTION_KEYWORDS`.
- Produces: `WebCollectorEngine._execute_action(self, action: dict, elements: list[WebElement],
  page, records: list[dict]) -> str`, `WebCollectorEngine._find_element(elements, idx) ->
  WebElement | None` (staticmethod), 모듈 함수 `_find_irreversible_keyword(text: str) -> str |
  None`, `_clamp_wait_seconds(value) -> float`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_web_collector_engine.py`에 아래 함수들을 `test_collect_elements` 다음, `main()`
이전에 추가한다:

```python
def test_execute_click_and_type() -> None:
    from playwright.sync_api import sync_playwright

    html = """
    <html><body>
      <input type="search" placeholder="검색어" />
      <button onclick="window.__clicked = true">검색</button>
    </body></html>
    """

    engine = WebCollectorEngine(headless=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.set_content(html)
            elements = engine._collect_elements(page)
            records: list = []

            input_el = next(el for el in elements if el.tag == "input")
            outcome = engine._execute_action(
                {"action": "type", "idx": input_el.idx, "text": "노트북"}, elements, page, records
            )
            assert "입력" in outcome, f"입력 outcome 형식 불일치: {outcome}"
            value = page.evaluate(f'document.querySelector(\'[data-jarvis-idx="{input_el.idx}"]\').value')
            assert value == "노트북", f"입력값이 반영 안 됨: {value}"

            button_el = next(el for el in elements if el.tag == "button")
            outcome = engine._execute_action(
                {"action": "click", "idx": button_el.idx}, elements, page, records
            )
            assert "클릭" in outcome, f"클릭 outcome 형식 불일치: {outcome}"
            clicked = page.evaluate("window.__clicked")
            assert clicked is True, "버튼 클릭이 실제로 실행되지 않음"
        finally:
            browser.close()

    print("test_execute_click_and_type 통과")


def test_execute_click_blocks_irreversible_action() -> None:
    from playwright.sync_api import sync_playwright

    html = '<html><body><button onclick="window.__clicked = true">구매하기</button></body></html>'

    engine = WebCollectorEngine(headless=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.set_content(html)
            elements = engine._collect_elements(page)
            button_el = elements[0]

            outcome = engine._execute_action(
                {"action": "click", "idx": button_el.idx}, elements, page, []
            )
            assert "거부" in outcome, f"위험 액션이 차단되지 않음: {outcome}"
            clicked = page.evaluate("window.__clicked")
            assert clicked is None, "차단됐어야 할 클릭이 실제로 실행됨"
        finally:
            browser.close()

    print("test_execute_click_blocks_irreversible_action 통과")


def test_execute_extract_appends_record() -> None:
    from playwright.sync_api import sync_playwright

    html = """
    <html><body>
      <li class="title">노트북 A</li>
      <li class="price">100000</li>
    </body></html>
    """

    engine = WebCollectorEngine(headless=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.set_content(html)
            elements = engine._collect_elements(page)
            title_el = next(el for el in elements if el.text == "노트북 A")
            price_el = next(el for el in elements if el.text == "100000")
            records: list = []

            outcome = engine._execute_action(
                {"action": "extract", "record": {"제목": title_el.idx, "가격": price_el.idx}},
                elements, page, records,
            )
            assert "추출" in outcome, f"추출 outcome 형식 불일치: {outcome}"
            assert records == [{"제목": "노트북 A", "가격": "100000"}], f"레코드 불일치: {records}"
        finally:
            browser.close()

    print("test_execute_extract_appends_record 통과")


def test_clamp_wait_seconds() -> None:
    from core.web_collector import _clamp_wait_seconds

    assert _clamp_wait_seconds(10) == 3.0, "상한(3.0)으로 clamp 안 됨"
    assert _clamp_wait_seconds(0.05) == 0.2, "하한(0.2)으로 clamp 안 됨"
    assert _clamp_wait_seconds(1.5) == 1.5, "범위 안 값이 그대로 유지 안 됨"

    print("test_clamp_wait_seconds 통과")
```

`main()`을 아래처럼 갱신한다:

```python
def main() -> None:
    test_collect_elements()
    test_execute_click_and_type()
    test_execute_click_blocks_irreversible_action()
    test_execute_extract_appends_record()
    test_clamp_wait_seconds()
    print("\ntest_web_collector_engine (Task 1-2) 검증 통과")
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m tests.test_web_collector_engine`
Expected: `AttributeError: 'WebCollectorEngine' object has no attribute '_execute_action'`

- [ ] **Step 3: `_execute_action` 등 구현**

`core/web_collector.py`의 `WebCollectorEngine` 클래스 안, `_collect_elements` 메서드 다음에
추가:

```python
    # -- 행동 실행 (Claude가 아니라 이 코드가 직접 수행) --------------------

    def _execute_action(
        self,
        action: dict,
        elements: list[WebElement],
        page,
        records: list[dict],
    ) -> str:
        kind = action.get("action")
        try:
            if kind == "navigate":
                url = str(action.get("url", "")).strip()
                if not url:
                    return "이동 실패: url 값 없음"
                if not url.startswith("http"):
                    url = "https://" + url
                page.goto(url, timeout=15000, wait_until="domcontentloaded")
                return f"이동: {url}"

            if kind == "click":
                idx = int(action.get("idx", -1))
                el = self._find_element(elements, idx)
                if el is None:
                    return f"클릭 실패: 존재하지 않는 요소 번호 {idx}"
                danger = _find_irreversible_keyword(el.text)
                if danger:
                    return (f"클릭 거부: '{el.text}'은(는) 되돌릴 수 없는 동작('{danger}')으로 "
                             f"판단되어 실행하지 않았습니다.")
                page.locator(f'[data-jarvis-idx="{idx}"]').first.click(timeout=5000)
                return f"클릭: [{idx}] {el.text or el.tag}"

            if kind == "type":
                idx = int(action.get("idx", -1))
                text = str(action.get("text", ""))
                el = self._find_element(elements, idx)
                if el is None:
                    return f"입력 실패: 존재하지 않는 요소 번호 {idx}"
                danger = _find_irreversible_keyword(el.text)
                if danger:
                    return (f"입력 거부: '{el.text}'은(는) 되돌릴 수 없는 동작('{danger}')으로 "
                             f"판단되어 실행하지 않았습니다.")
                page.locator(f'[data-jarvis-idx="{idx}"]').first.fill(text, timeout=5000)
                return f"입력: [{idx}] {el.text or el.tag} <- '{text}'"

            if kind == "extract":
                record_spec = action.get("record")
                if not isinstance(record_spec, dict) or not record_spec:
                    return "추출 실패: record 값 없음"
                record: dict[str, str] = {}
                for field, idx_val in record_spec.items():
                    el = self._find_element(elements, int(idx_val))
                    record[str(field)] = el.text if el else ""
                records.append(record)
                return f"추출: {record}"

            if kind == "scroll":
                direction = str(action.get("direction", "down"))
                delta = -800 if direction == "up" else 800
                page.mouse.wheel(0, delta)
                return f"스크롤: {direction}"

            if kind == "wait":
                seconds = _clamp_wait_seconds(action.get("seconds", 1))
                time.sleep(seconds)
                return f"대기: {seconds}초"

            if kind in ("done", "fail"):
                return str(action.get("message", ""))

            return f"알 수 없는 행동: {kind}"
        except Exception as e:
            logger.error(f"행동 실행 오류({kind}): {e}")
            return f"행동 실행 오류({kind}): {e}"

    @staticmethod
    def _find_element(elements: list[WebElement], idx: int) -> WebElement | None:
        return next((el for el in elements if el.idx == idx), None)
```

파일 맨 아래(모듈 레벨, 클래스 밖)에 헬퍼 함수를 추가한다:

```python
def _find_irreversible_keyword(text: str) -> str | None:
    return next((kw for kw in _IRREVERSIBLE_ACTION_KEYWORDS if kw in text), None)


def _clamp_wait_seconds(value) -> float:
    return min(max(float(value), 0.2), _MAX_WAIT_SECONDS)
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `python -m tests.test_web_collector_engine`
Expected: 5개 테스트 모두 통과, `test_web_collector_engine (Task 1-2) 검증 통과` 출력, exit code 0

- [ ] **Step 5: 커밋**

```bash
git add core/web_collector.py tests/test_web_collector_engine.py
git commit -m "feat: 웹 수집 엔진 - 행동 실행(click/type/extract/scroll/wait) + 되돌릴 수 없는 액션 차단"
```

---

### Task 3: 판단 프롬프트 빌더 + 행동 JSON 파서

**Files:**
- Modify: `core/web_collector.py`
- Test: `tests/test_web_collector_engine.py`

**Interfaces:**
- Produces: 모듈 함수 `_build_decision_prompt(task: str, elements: list[WebElement],
  history: list[str], url: str) -> str`, `_elements_section(elements: list[WebElement]) -> str`,
  `_parse_action(raw: str) -> dict`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_web_collector_engine.py`에 추가 (Task 2 테스트들 다음, `main()` 이전):

```python
def test_build_decision_prompt_includes_task_and_elements() -> None:
    from core.web_collector import WebElement, _build_decision_prompt

    elements = [WebElement(idx=1, tag="input", type="search", role="", text="검색어")]
    prompt = _build_decision_prompt(
        task="노트북 검색해줘",
        elements=elements,
        history=["1) 이동: https://example.com"],
        url="https://example.com",
    )

    assert "노트북 검색해줘" in prompt, "목표가 프롬프트에 없음"
    assert "https://example.com" in prompt, "URL이 프롬프트에 없음"
    assert "1) 이동" in prompt, "history가 프롬프트에 없음"
    assert '"번호": 1' in prompt, "요소 목록이 프롬프트에 없음"

    print("test_build_decision_prompt_includes_task_and_elements 통과")


def test_parse_action_extracts_json_from_markdown_fence() -> None:
    from core.web_collector import _parse_action

    raw = '```json\n{"action": "click", "idx": 3}\n```'
    action = _parse_action(raw)
    assert action == {"action": "click", "idx": 3}, f"파싱 결과 불일치: {action}"

    print("test_parse_action_extracts_json_from_markdown_fence 통과")


def test_parse_action_raises_on_missing_action_field() -> None:
    from core.web_collector import _parse_action

    try:
        _parse_action('{"idx": 3}')
        assert False, "action 필드가 없는데도 예외가 발생하지 않음"
    except ValueError:
        pass

    print("test_parse_action_raises_on_missing_action_field 통과")
```

`main()`에 세 줄 추가:

```python
    test_build_decision_prompt_includes_task_and_elements()
    test_parse_action_extracts_json_from_markdown_fence()
    test_parse_action_raises_on_missing_action_field()
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m tests.test_web_collector_engine`
Expected: `ImportError: cannot import name '_build_decision_prompt' from 'core.web_collector'`

- [ ] **Step 3: 구현**

`core/web_collector.py` 파일 맨 아래(Task 2에서 추가한 `_find_irreversible_keyword`,
`_clamp_wait_seconds` 다음)에 추가:

```python
def _elements_section(elements: list[WebElement]) -> str:
    if not elements:
        return "## 현재 페이지 요소 없음"
    data = json.dumps([el.to_dict() for el in elements], ensure_ascii=False, indent=2)
    return (
        "## 현재 페이지 요소 목록\n"
        "클릭·입력·추출 대상은 반드시 이 목록의 '번호'(idx)로 지정하라.\n\n"
        f"```json\n{data}\n```"
    )


def _build_decision_prompt(
    task: str,
    elements: list[WebElement],
    history: list[str],
    url: str,
) -> str:
    """한 스텝의 "행동 1개"만 JSON으로 결정하게 하는 프롬프트.

    이미지가 없는 텍스트 전용 프롬프트다 — hybrid_screen.py와 달리 Read 툴로 스크린샷을
    열어볼 필요가 없어 클로드 응답이 빠르다.
    """
    history_section = "\n".join(history) if history else "(아직 없음)"
    return (
        "너는 자비스(JARVIS)야. 브라우저로 웹사이트를 탐색하며 목표 달성을 위한 "
        '"행동 딱 1개"만 JSON으로 결정하는 에이전트다.\n'
        "실제 클릭·입력·스크롤·페이지 이동은 네가 하지 않는다 — 네가 고른 행동을 시스템이 "
        "대신 실행하고, 그 결과가 반영된 페이지를 다음 턴에 다시 보여준다.\n"
        "이 에이전트는 정보를 검색·수집·확인하는 읽기 전용 작업만 한다 — 구매/결제/신청/"
        "삭제/전송/제출처럼 되돌릴 수 없는 액션은 시스템이 강제로 차단한다.\n\n"
        f"## 최종 목표\n{task}\n\n"
        f"## 현재 페이지 URL\n{url or '(아직 페이지 없음)'}\n\n"
        f"## 지금까지 실행한 행동과 결과\n{history_section}\n\n"
        f"{_elements_section(elements)}\n\n"
        "## 응답 형식\n"
        "다른 설명 없이 아래 중 정확히 하나의 JSON 객체만 출력하라:\n"
        '- {"action": "navigate", "url": "<이동할 전체 URL>"}\n'
        '- {"action": "click", "idx": <요소 번호>}\n'
        '- {"action": "type", "idx": <요소 번호>, "text": "<입력할 텍스트>"}\n'
        '- {"action": "extract", "record": {"<필드명>": <요소 번호>, ...}}\n'
        '- {"action": "scroll", "direction": "up|down"}\n'
        '- {"action": "wait", "seconds": <1~3 사이 숫자>}\n'
        '- {"action": "done", "message": "<수집 결과 요약 - 사용자에게 들려줄 한국어 문장>"}\n'
        '- {"action": "fail", "message": "<더 진행할 수 없는 이유, 한국어>"}\n\n'
        "목표에 필요한 사이트가 아직 안 열려 있으면 navigate로 먼저 이동하라. "
        "데이터를 발견하면 extract로 그 자리에서 바로 기록하라 — 나중에 한꺼번에 하려 "
        "하지 마라. 같은 레코드를 두 번 extract하지 마라. "
        "목표한 만큼 수집했거나 더 수집할 데이터가 없으면 반드시 done을 선택하라."
    )


def _parse_action(raw: str) -> dict:
    """클로드의 판단 응답에서 행동 JSON 객체 하나를 추출한다.

    마크다운 코드펜스(```json ... ```)로 감싸거나 앞뒤에 설명을 붙이는 경우가
    흔해 첫 번째 {...} 블록만 관대하게 추출한다 (hybrid_screen.py의 _parse_action과 동일 패턴).
    """
    text = re.sub(r"```(?:json)?", "", raw).strip()
    match = _ACTION_JSON_RE.search(text)
    if not match:
        raise ValueError(f"JSON 행동을 찾을 수 없음: {raw[:200]}")
    obj = json.loads(match.group(0))
    if not isinstance(obj, dict) or "action" not in obj:
        raise ValueError(f"'action' 필드가 없는 응답: {raw[:200]}")
    return obj
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `python -m tests.test_web_collector_engine`
Expected: 8개 테스트 모두 통과, exit code 0

- [ ] **Step 5: 커밋**

```bash
git add core/web_collector.py tests/test_web_collector_engine.py
git commit -m "feat: 웹 수집 엔진 - 판단 프롬프트 빌더 + 행동 JSON 파서"
```

---

### Task 4: 로그인 세션 저장/로드 (`storage_state`)

**Files:**
- Modify: `core/web_collector.py`
- Test: `tests/test_web_collector_engine.py`

**Interfaces:**
- Produces: `WebCollectorEngine._load_storage_state(self) -> dict | None`,
  `WebCollectorEngine._save_storage_state(self, context) -> None`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_web_collector_engine.py`에 추가:

```python
def test_storage_state_roundtrip() -> None:
    import tempfile
    from pathlib import Path
    import core.web_collector as mod

    original_path = mod._STORAGE_STATE_PATH
    with tempfile.TemporaryDirectory() as tmp:
        mod._STORAGE_STATE_PATH = Path(tmp) / "state.json"
        try:
            engine = WebCollectorEngine(headless=True)

            assert engine._load_storage_state() is None, "파일 없을 때는 None을 반환해야 함"

            class _FakeContext:
                def storage_state(self):
                    return {"cookies": [{"name": "sid", "value": "abc"}]}

            engine._save_storage_state(_FakeContext())
            assert mod._STORAGE_STATE_PATH.exists(), "저장 파일이 생성되지 않음"

            loaded = engine._load_storage_state()
            assert loaded == {"cookies": [{"name": "sid", "value": "abc"}]}, f"로드 값 불일치: {loaded}"
        finally:
            mod._STORAGE_STATE_PATH = original_path

    print("test_storage_state_roundtrip 통과")
```

`main()`에 `test_storage_state_roundtrip()` 호출을 추가한다.

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m tests.test_web_collector_engine`
Expected: `AttributeError: 'WebCollectorEngine' object has no attribute '_load_storage_state'`

- [ ] **Step 3: 구현**

`core/web_collector.py`의 `WebCollectorEngine` 클래스, `_find_element` staticmethod 다음에
추가:

```python
    # -- 로그인 세션 --------------------------------------------------------

    def _load_storage_state(self) -> dict | None:
        if _STORAGE_STATE_PATH.exists():
            try:
                return json.loads(_STORAGE_STATE_PATH.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"로그인 세션 로드 실패: {e}")
        return None

    def _save_storage_state(self, context) -> None:
        try:
            _STORAGE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            state = context.storage_state()
            _STORAGE_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning(f"로그인 세션 저장 실패: {e}")
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `python -m tests.test_web_collector_engine`
Expected: 9개 테스트 모두 통과, exit code 0

- [ ] **Step 5: 커밋**

```bash
git add core/web_collector.py tests/test_web_collector_engine.py
git commit -m "feat: 웹 수집 엔진 - 로그인 세션(storage_state) 저장/로드"
```

---

### Task 5: `run()` 전체 루프 통합 (관찰→판단→실행 반복 + xlsx 저장)

**Files:**
- Modify: `core/web_collector.py`
- Test: `tests/test_web_collector_engine.py`

**Interfaces:**
- Consumes: `skills.agent_tools.file_tool.save_xlsx(rows: list[list], headers: list[str] | None
  = None, filename: str = "") -> dict` (기존 유틸, 시그니처 변경 없음).
- Produces: `WebCollectorEngine.run(self, task: str) -> str`,
  `WebCollectorEngine._finish(self, action: dict, records: list[dict]) -> str`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_web_collector_engine.py`에 추가:

```python
class _FixtureHTTPHandler(http.server.BaseHTTPRequestHandler):
    html_body = b""

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(self.html_body)

    def log_message(self, format, *args) -> None:
        pass


def _serve_html(html: str) -> http.server.HTTPServer:
    """테스트용 픽스처 HTML을 127.0.0.1의 임시 포트로 서빙한다.

    Chromium은 최신 버전에서 최상위 프레임의 data: URL 직접 탐색을 보안상 막는
    경우가 있어(crbug.com/1231433), 실제 HTTP 내비게이션으로 navigate 액션을
    검증한다 — 프로덕션에서도 항상 http(s):// 사이트로만 이동하므로 이쪽이 더
    실제 동작에 가깝다.
    """
    handler_cls = type("_Handler", (_FixtureHTTPHandler,), {"html_body": html.encode("utf-8")})
    server = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_run_loop_end_to_end() -> None:
    import skills.agent_tools.file_tool as file_tool_mod

    html = '<html><body><li class="title">노트북 A</li><li class="price">100000</li></body></html>'
    server = _serve_html(html)
    try:
        url = f"http://127.0.0.1:{server.server_port}/"
        script = [
            {"action": "navigate", "url": url},
            {"action": "extract", "record": {"제목": 1, "가격": 2}},
            {"action": "done", "message": "1건 수집 완료"},
        ]

        class _FakeEngine:
            def __init__(self, script):
                self._script = list(script)
                self.calls = 0

            def decide(self, prompt, session_id=None):
                self.calls += 1
                action = self._script.pop(0) if self._script else {"action": "fail", "message": "스크립트 소진"}
                return json.dumps(action, ensure_ascii=False), "fake-session"

        saved = {}

        def _fake_save_xlsx(rows, headers=None, filename=""):
            saved["rows"] = rows
            saved["headers"] = headers
            return {"ok": True, "data": "C:\\fake\\jarvis_test.xlsx", "error": ""}

        original_save = file_tool_mod.save_xlsx
        file_tool_mod.save_xlsx = _fake_save_xlsx
        try:
            engine = WebCollectorEngine(headless=True)
            fake_engine = _FakeEngine(script)
            engine._engine = fake_engine

            result = engine.run(task="노트북 A 정보 수집해줘")

            assert fake_engine.calls == 3, f"decide() 호출 횟수 불일치: {fake_engine.calls}"
            assert "1건 수집 완료" in result, f"결과 메시지에 done 메시지 누락: {result}"
            assert "jarvis_test.xlsx" in result, f"결과 메시지에 저장 경로 누락: {result}"
            assert saved["headers"] == ["제목", "가격"], f"헤더 불일치: {saved['headers']}"
            assert saved["rows"] == [["노트북 A", "100000"]], f"행 데이터 불일치: {saved['rows']}"
        finally:
            file_tool_mod.save_xlsx = original_save
    finally:
        server.shutdown()
        server.server_close()

    print("test_run_loop_end_to_end 통과")


def test_run_loop_max_steps_cutoff() -> None:
    class _FakeEngine:
        def __init__(self):
            self.calls = 0

        def decide(self, prompt, session_id=None):
            self.calls += 1
            return json.dumps({"action": "wait", "seconds": 0.1}), "fake-session"

    engine = WebCollectorEngine(headless=True)
    fake_engine = _FakeEngine()
    engine._engine = fake_engine

    result = engine.run(task="절대 안 끝나는 태스크")

    assert fake_engine.calls == 15, f"최대 스텝을 넘겨 호출됨: {fake_engine.calls}"
    assert "끝내지 못했습니다" in result, f"타임아웃 메시지 누락: {result}"

    print("test_run_loop_max_steps_cutoff 통과")
```

파일 상단 import 구역에 `import http.server`, `import json`, `import threading`을 추가한다
(`json`은 Task 1에서 이미 추가됨 — 없다면 추가). `main()`에 두 함수 호출을 추가한다.

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m tests.test_web_collector_engine`
Expected: `AttributeError: 'WebCollectorEngine' object has no attribute 'run'`

- [ ] **Step 3: 구현**

`core/web_collector.py`의 `WebCollectorEngine` 클래스, `_get_engine` 메서드 다음(그리고
`_collect_elements` 이전)에 추가:

```python
    # -- 공개 진입점 -------------------------------------------------------

    def run(self, task: str) -> str:
        """관찰→판단→실행을 반복하며 데이터를 검색·수집한다 (읽기 전용).

        매 스텝 Playwright로 현재 페이지의 DOM 요소를 텍스트로 뽑아 클로드에게
        "행동 1개"만 JSON으로 판단하게 한 뒤, 실행은 이 메서드가 직접 담당한다.
        """
        from playwright.sync_api import sync_playwright

        records: list[dict] = []
        history: list[str] = []
        session_id: str | None = None

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self._headless)
            try:
                context = browser.new_context(storage_state=self._load_storage_state())
                page = context.new_page()
                try:
                    for step in range(1, _MAX_STEPS + 1):
                        elements = self._collect_elements(page)
                        prompt = _build_decision_prompt(task, elements, history, page.url)
                        raw, session_id = self._get_engine().decide(prompt, session_id=session_id)

                        try:
                            action = _parse_action(raw)
                        except ValueError as e:
                            logger.warning(f"행동 파싱 실패 (step {step}): {e}")
                            history.append(f"{step}) 판단 결과를 해석하지 못함 - 재시도")
                            continue

                        outcome = self._execute_action(action, elements, page, records)
                        if self._on_chunk:
                            self._on_chunk(outcome)
                        history.append(f"{step}) {outcome}")
                        logger.info(f"[web-collector step {step}] {outcome}")

                        if action.get("action") in ("done", "fail"):
                            return self._finish(action, records)

                    return self._finish(
                        {"message": f"최대 {_MAX_STEPS}단계 안에 작업을 끝내지 못했습니다."},
                        records,
                    )
                finally:
                    self._save_storage_state(context)
                    context.close()
            finally:
                browser.close()

    def _finish(self, action: dict, records: list[dict]) -> str:
        message = str(action.get("message") or "")
        if not records:
            return message or "수집된 데이터가 없습니다."

        from skills.agent_tools.file_tool import save_xlsx
        headers = list(records[0].keys())
        rows = [[record.get(h, "") for h in headers] for record in records]
        result = save_xlsx(rows, headers=headers)
        if result["ok"]:
            return f"{message} {len(records)}건을 {result['data']}에 저장했습니다.".strip()
        return f"{message} (파일 저장 실패: {result['error']})".strip()
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `python -m tests.test_web_collector_engine`
Expected: 11개 테스트 모두 통과, exit code 0 (`test_run_loop_max_steps_cutoff`는
`time.sleep(0.1)`을 15번 실행하므로 약 1.5초 더 걸린다 — 정상)

- [ ] **Step 5: 커밋**

```bash
git add core/web_collector.py tests/test_web_collector_engine.py
git commit -m "feat: 웹 수집 엔진 - run() 관찰-판단-실행 루프 통합 + xlsx 저장"
```

---

### Task 6: `skill_web_collector.py` 스킬 어댑터 + 라우터 스코어링

**Files:**
- Create: `skills/skill_web_collector.py`
- Test: `tests/test_skill_web_collector.py`
- Modify: `CLAUDE.md:145-155` (Architecture 섹션에 신규 스킬 설명 추가)

**Interfaces:**
- Consumes: `core.web_collector.WebCollectorEngine` (Task 1-5), `core.skill_base.Skill`,
  `core.skill_base.SkillResult`, `core.status_events.broadcaster`.
- Produces: `skills.skill_web_collector.WebCollectorSkill` (`name = "web_collector"`).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_skill_web_collector.py` 새로 작성:

```python
"""skill_web_collector.py streaming 상태 emit + 라우팅 스코어링 검증 (plain assert 스크립트).

실행: python -m tests.test_skill_web_collector  (프로젝트 루트에서)
"""
import skills.skill_web_collector as mod
from skills.skill_agent import AgentSkill
from core.status_events import broadcaster


def test_streaming_state_before_run() -> None:
    observed: dict = {}

    class _FakeEngine:
        def __init__(self, on_chunk=None) -> None:
            self.on_chunk = on_chunk

        def run(self, task: str) -> str:
            observed["state"] = broadcaster.get_current().state
            return "수집 완료"

    original_engine = mod.WebCollectorEngine
    mod.WebCollectorEngine = _FakeEngine
    try:
        skill = mod.WebCollectorSkill()
        result = skill.execute("네이버 부동산에서 대전 아파트 수집해줘", {})
    finally:
        mod.WebCollectorEngine = original_engine

    assert observed.get("state") == "streaming", f"engine.run() 호출 시점 상태: {observed.get('state')}"
    assert result.success
    assert result.speech == "수집 완료"

    print("test_streaming_state_before_run 통과")


def test_routing_priority_over_agent_skill() -> None:
    text = "네이버 부동산에서 대전 아파트 수집해줘"
    collector_score = mod.WebCollectorSkill().can_handle("", text)
    agent_score = AgentSkill().can_handle("", text)

    assert collector_score == 0.93, f"web_collector 점수 불일치: {collector_score}"
    assert agent_score == 0.9, f"agent 점수 불일치: {agent_score}"
    assert collector_score > agent_score, "사이트+수집 문장에서 web_collector가 agent를 이겨야 함"

    print("test_routing_priority_over_agent_skill 통과")


def test_routing_falls_back_for_generic_research() -> None:
    text = "인공지능 트렌드 조사해줘"
    collector_score = mod.WebCollectorSkill().can_handle("", text)
    agent_score = AgentSkill().can_handle("", text)

    assert collector_score == 0.0, f"일반 리서치 문장에 web_collector가 반응함: {collector_score}"
    assert agent_score == 0.9, f"agent 점수 회귀: {agent_score}"

    print("test_routing_falls_back_for_generic_research 통과")


def test_strong_trigger_scores_highest() -> None:
    text = "브라우저로 수집해서 알려줘"
    score = mod.WebCollectorSkill().can_handle("", text)
    assert score == 0.95, f"강한 트리거 점수 불일치: {score}"

    print("test_strong_trigger_scores_highest 통과")


def main() -> None:
    test_streaming_state_before_run()
    test_routing_priority_over_agent_skill()
    test_routing_falls_back_for_generic_research()
    test_strong_trigger_scores_highest()
    print("\ntest_skill_web_collector 검증 통과")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m tests.test_skill_web_collector`
Expected: `ModuleNotFoundError: No module named 'skills.skill_web_collector'`

- [ ] **Step 3: `skills/skill_web_collector.py` 구현**

```python
"""Playwright 기반 웹 수집·검색 확인 스킬 (읽기 전용).

skill_agent.py(클로드 내장 WebFetch — 정적 HTML만)가 다루지 못하는 자바스크립트
렌더링·로그인·필터·페이지네이션이 필요한 사이트에서, 실제 브라우저(Chromium)로
검색·수집·필터링·확인을 수행한다. 구매·결제·삭제 같은 되돌릴 수 없는 액션은
core/web_collector.py가 코드 레벨에서 차단한다 (이 스킬의 범위 밖).

트리거 예시:
  "네이버 부동산에서 대전 서구 아파트 매물 수집해줘"
  "당근마켓에서 노트북 검색해서 10만원 이하로 모아줘"
  "쿠팡에서 무선청소기 검색해서 리뷰 4점 이상만 모아줘"
"""
import logging

from core.skill_base import Skill, SkillResult
from core.status_events import broadcaster
from core.web_collector import WebCollectorEngine

logger = logging.getLogger(__name__)

_STRONG = ["브라우저로 수집", "브라우저에서 검색", "사이트에서 직접 수집", "웹사이트에서 수집", "브라우저로 검색"]
# skill_agent.py의 WebFetch(정적 HTML)로는 다루지 못하는, 실제 렌더링/상호작용이
# 흔히 필요한 사이트 카테고리 키워드 — 확장 가능한 리스트.
_SITE_KEYWORDS = ["부동산", "쇼핑몰", "중고거래", "당근마켓", "번개장터", "쿠팡", "지도"]
_ACTION_KEYWORDS = [
    "수집해줘", "수집해서", "검색해줘", "검색해서",
    "찾아줘", "필터링해줘", "필터해서", "모아줘", "모아서",
]


class WebCollectorSkill(Skill):
    """Playwright로 실제 브라우저를 띄워 임의 사이트를 탐색하며 정보를 검색·수집·필터링한다."""

    name = "web_collector"
    description = "Playwright로 실제 브라우저를 띄워 임의 사이트를 탐색하며 정보를 검색·수집·필터링한다"
    triggers = ["브라우저로 수집", "웹사이트에서 수집", "사이트에서 검색"]
    examples = [
        "당근마켓에서 노트북 검색해서 10만원 이하로 모아줘",
        "네이버 부동산에서 대전 서구 아파트 매물 수집해줘",
        "쿠팡에서 무선청소기 검색해서 리뷰 4점 이상만 모아줘",
    ]

    def can_handle(self, intent: str, text: str) -> float:
        if any(t in text for t in _STRONG):
            return 0.95
        # skill_agent.py의 _STRONG_TRIGGERS(0.9)와 겹치는 "수집해줘" 등이 있을 때,
        # 사이트 이름까지 함께 언급되면(실제 브라우저 렌더링이 필요할 가능성이 높음)
        # 이 스킬이 우선하도록 더 높은 점수를 준다.
        if any(s in text for s in _SITE_KEYWORDS) and any(a in text for a in _ACTION_KEYWORDS):
            return 0.93
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        tts_callback = None
        try:
            from voice import tts as _tts
            tts_callback = _tts.speak
        except Exception:
            pass

        broadcaster.emit(state="streaming")
        engine = WebCollectorEngine(on_chunk=tts_callback)
        result = engine.run(task=text)
        return SkillResult(speech=result, success=True, data={"task": text})
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `python -m tests.test_skill_web_collector`
Expected: 4개 테스트 모두 통과, exit code 0

- [ ] **Step 5: `CLAUDE.md`에 신규 스킬 설명 추가**

`CLAUDE.md`의 `core/weather_client.py` 불릿(145~154번째 줄) 다음, `### Two independent
runtime entry points`(156번째 줄) 이전에 빈 줄 하나를 사이에 두고 새 불릿을 추가한다:

```diff
   silently resolving to the wrong country. `skill_weather.py` claims "날씨"/"기온"/"미세먼지"/"체감온도"/
   "강수확률" at a flat 0.85 (no weak tier needed — these words are specific enough on their own).
 
+- **`core/web_collector.py`** (`WebCollectorEngine`) — Playwright 기반 읽기 전용 웹 수집 에이전트 for
+  `skills/skill_web_collector.py`. `core/hybrid_screen.py`와 같은 관찰→판단→실행 폐쇄 루프 패턴을 쓰지만,
+  스크린샷/UIA 대신 Playwright로 뽑은 DOM 텍스트 스냅샷을 `ClaudeCliEngine.decide()`에 넘긴다 — 이미지가
+  없어 매 스텝 Read 툴 왕복이 필요 없고 `hybrid_screen.py`보다 스텝당 빠르다. `skill_agent.py`의 내장
+  `WebFetch`가 다루지 못하는 자바스크립트 렌더링/로그인/필터/페이지네이션이 필요한 사이트(부동산, 쇼핑몰,
+  중고거래 등)를 대상으로 하며, 구매·결제·삭제·전송·제출처럼 되돌릴 수 없는 액션은 요소 텍스트에 그런
+  키워드가 보이면 클로드의 판단과 무관하게 코드 레벨에서 강제 차단한다(`_IRREVERSIBLE_ACTION_KEYWORDS`) —
+  `hybrid_screen.py`의 잠금화면 클릭 사고 사례와 동일한 이유. 로그인 세션은 Playwright의
+  `storage_state`를 `data/web_collector_state.json`에 저장해 재사용한다. 라우터 스코어링은
+  `skill_agent.py`와 겹치는 "수집해줘"류 트리거에서 사이트 이름(부동산/쇼핑몰 등)까지 함께 있으면 이
+  스킬이 더 높은 점수(0.93 > 0.9)로 우선한다 — 실제 렌더링이 필요할 가능성이 높다는 신호로 사용.
+
 ### Two independent runtime entry points
```

- [ ] **Step 6: 커밋**

```bash
git add skills/skill_web_collector.py tests/test_skill_web_collector.py CLAUDE.md
git commit -m "feat: skill_web_collector 스킬 추가 - Playwright 웹 수집 라우팅 + 문서화"
```

---

## 계획에 없는 것 (설계 문서의 "미결 사항" — 이번 계획에서 다루지 않음)

- 로그인 대기 UX(최초 로그인 시 사용자가 직접 로그인할 시간을 주는 흐름)는 이번 계획에서
  구현하지 않는다. `_load_storage_state()`가 `None`을 반환하면(세션 파일 없음) 헤디드
  브라우저가 뜬 채로 탐색을 시작하므로, 로그인이 필요한 사이트는 클로드가 "로그인 필요"로
  판단해 `fail`을 반환하는 것이 현재 동작이다 — 실제 사용자 테스트에서 이 흐름이 불편하면
  별도 후속 작업으로 다룬다.
- `_SITE_KEYWORDS`/`_ACTION_KEYWORDS` 초기 목록은 최소 구성이다 — 사용자가 실제 테스트하며
  라우팅이 원하는 스킬로 안 잡히는 사례를 발견하면 목록에 키워드를 추가한다(스킬 파일 하나만
  수정하면 되므로 저비용).

## 실행 후 확인 (Task 6 완료 후 사용자가 직접 진행)

자동화된 테스트는 로컬 HTML 픽스처와 페이크 Claude 엔진만 사용하므로, 실제 사이트 대상
동작은 사용자가 직접 확인해야 한다. 예:

```
"네이버 부동산에서 대전 서구 아파트 매물 3개만 수집해줘"
```

브라우저 창이 실제로 뜨는지, 검색·클릭이 눈에 보이게 실행되는지, 최종적으로 xlsx 파일이
바탕화면에 저장되는지 확인한다. 이 단계에서 실패하면(셀렉터가 안 맞음, 사이트 구조가 예상과
다름 등) 오류 메시지를 가지고 `_execute_action`/`_collect_elements`/프롬프트를 조정한다 —
필요하면 새 후속 계획으로 다룬다.
