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


def _find_irreversible_keyword(text: str) -> str | None:
    return next((kw for kw in _IRREVERSIBLE_ACTION_KEYWORDS if kw in text), None)


def _clamp_wait_seconds(value) -> float:
    return min(max(float(value), 0.2), _MAX_WAIT_SECONDS)


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
