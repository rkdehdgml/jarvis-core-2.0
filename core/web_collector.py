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


def _find_irreversible_keyword(text: str) -> str | None:
    return next((kw for kw in _IRREVERSIBLE_ACTION_KEYWORDS if kw in text), None)


def _clamp_wait_seconds(value) -> float:
    return min(max(float(value), 0.2), _MAX_WAIT_SECONDS)
