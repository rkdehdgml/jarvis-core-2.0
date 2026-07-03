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
