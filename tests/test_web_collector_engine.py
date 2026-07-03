"""core/web_collector.py 단위 테스트 (plain assert 스크립트).

실행: python -m tests.test_web_collector_engine  (프로젝트 루트에서)
Playwright + Chromium이 설치되어 있어야 한다 (playwright install chromium).
"""
import http.server
import json
import threading

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


def test_collect_elements_excludes_visually_hidden_shims() -> None:
    """실사용 중 발견된 버그: 접근성용으로 화면에서 숨긴 네이티브 <select>가
    '클릭 가능한 요소'로 수집되면, 사람은 절대 못 누르는 요소를 클로드가
    클릭 대상으로 고르게 되고 Playwright가 "element is outside of the
    viewport"로 매번 실패한다 (네이버 부동산 지역선택 select.selectbox-source
    에서 실제로 재현됨). 진짜 클릭 가능한 요소만 수집돼야 한다.
    """
    from playwright.sync_api import sync_playwright

    html = """
    <html><body>
      <button>보이는 버튼</button>
      <select title="clip 트릭" style="position:absolute; width:1px; height:1px; overflow:hidden;">
        <option>1</option>
      </select>
      <select title="화면밖 트릭" style="position:absolute; left:-9999px; top:-9999px; width:100px; height:20px;">
        <option>2</option>
      </select>
    </body></html>
    """

    engine = WebCollectorEngine(headless=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.set_content(html)
            elements = engine._collect_elements(page)

            tags = [el.tag for el in elements]
            assert "button" in tags, f"보이는 버튼이 수집되지 않음: {tags}"
            assert "select" not in tags, f"화면에 안 보이는 select가 수집됨: {tags}"
        finally:
            browser.close()

    print("test_collect_elements_excludes_visually_hidden_shims 통과")


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


def main() -> None:
    test_collect_elements()
    test_collect_elements_excludes_visually_hidden_shims()
    test_execute_click_and_type()
    test_execute_click_blocks_irreversible_action()
    test_execute_extract_appends_record()
    test_clamp_wait_seconds()
    test_build_decision_prompt_includes_task_and_elements()
    test_parse_action_extracts_json_from_markdown_fence()
    test_parse_action_raises_on_missing_action_field()
    test_storage_state_roundtrip()
    test_run_loop_end_to_end()
    test_run_loop_max_steps_cutoff()
    print("\ntest_web_collector_engine (Task 1-5) 검증 통과")


if __name__ == "__main__":
    main()
