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


def main() -> None:
    test_collect_elements()
    test_execute_click_and_type()
    test_execute_click_blocks_irreversible_action()
    test_execute_extract_appends_record()
    test_clamp_wait_seconds()
    test_build_decision_prompt_includes_task_and_elements()
    test_parse_action_extracts_json_from_markdown_fence()
    test_parse_action_raises_on_missing_action_field()
    print("\ntest_web_collector_engine (Task 1-3) 검증 통과")


if __name__ == "__main__":
    main()
