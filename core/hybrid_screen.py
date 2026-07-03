"""UIA 트리 + Claude Vision 관찰-행동 루프 기반 화면 인식·제어 엔진.

전략 A: 인식은 두 레이어를 동시에 사용하고, 실행은 하네스(이 파일의 Python
코드)가 직접 담당하는 폐쇄 루프(closed-loop) 에이전트로 동작한다.

  레이어 1 - UIA (Windows UI Automation API)
    pyuiautomation으로 현재 포커스 앱의 UI 요소 트리를 수집한다.
    각 요소의 ControlType, Name, 화면 좌표, enabled 상태를 API에서 직접 읽는다.
    -> 픽셀 추정 없는 정밀 좌표 확보

  레이어 2 - Vision (스크린샷 -> 임시 파일 저장 -> Claude Read 툴로 확인)
    pyautogui로 스크린샷을 찍고 UIA 요소 위치에 번호 오버레이(SoM)를 그린다.
    이미지를 OS 임시 폴더에 PNG로 저장하고 경로를 Claude 프롬프트에 포함한다.
    Claude Code CLI에는 computer_use 툴이 없으므로(Read/Write/Edit/Bash/
    WebSearch/WebFetch만 존재), Read 툴로 그 파일을 직접 열어보게 한다.

  실행 - 관찰→판단→실행→재관찰 루프 (UFO·Anthropic computer_use 레퍼런스와 동일한 패턴)
    Claude(ClaudeCliEngine.decide(), Read 툴만 허용, --dangerously-skip-permissions
    불필요)는 매 스텝마다 "행동 1개"만 JSON으로 결정한다 — 실제 클릭·입력·스크롤은
    Claude가 아니라 이 파일의 _execute_action()이 UIA 좌표를 그대로 사용해 pyautogui로
    수행한다. 매 행동 후 화면을 다시 캡처해 다음 판단에 넘기므로, 이전 행동이 실제로
    성공했는지 확인하지 않고 다음 단계로 넘어가는 실패(stale state)를 구조적으로 막는다.
    Claude에게 셸 실행 권한을 주지 않으므로 임의 Bash 명령 실행 위험도 없다.

사용 흐름:
  engine = HybridScreenEngine()
  result = engine.run(task="네이버 검색창에 날씨 입력해줘")
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)

_MAX_STEPS = 15          # 무한 루프 방지 - 이 스텝 안에 done/fail이 안 나오면 중단
_MAX_WAIT_SECONDS = 3.0  # Claude가 "wait" 행동으로 요청 가능한 최대 대기 시간
_MAX_SCROLL_PX = 2000    # 스크롤 폭 상한 (오작동으로 인한 과도한 스크롤 방지)

_ACTION_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

# 클릭/입력 대상 요소 이름에 이 키워드가 포함되면 무조건 거부한다.
# [사고 사례] 2026-07-02 실 테스트에서 Claude가 "잠금 화면" 요소를 그대로 클릭해
# 실제로 Windows 세션이 잠긴 적이 있음 - 모델의 판단(프롬프트 지시)만으로는
# 막을 수 없어 코드 레벨에서 강제로 차단한다.
_DANGEROUS_ELEMENT_KEYWORDS = [
    "잠금", "로그아웃", "로그 아웃", "시스템 종료",
    "다시 시작", "재부팅", "영구 삭제", "초기화",
    "휴지통 비우기", "계정 삭제",
]

# UIA 요소 클릭을 거치지 않고 키보드 단축키만으로도 같은 부류의 사고(화면 잠금,
# 창 강제 종료, 시스템 재시작)가 날 수 있어 행동 자체를 차단한다.
_DANGEROUS_KEY_COMBOS = {"win+l", "alt+f4", "ctrl+alt+delete", "ctrl+alt+del"}

# [사고 사례] alt+tab처럼 결과가 예측 불가능한 창 전환 단축키는 실제 테스트에서
# 엉뚱한 창(테스트 터미널 등)으로 튀어 태스크 대상 창을 완전히 놓치게 만든 원인이었다.
# 다음 턴에 항상 새 스크린샷을 다시 보여주므로 이런 "눈감고 전환" 자체가 불필요하다.
_WINDOW_SWITCH_KEY_COMBOS = {"alt+tab", "win+tab", "win+d", "win+m"}


def _find_dangerous_keyword(name: str) -> str | None:
    return next((kw for kw in _DANGEROUS_ELEMENT_KEYWORDS if kw in name), None)

# UIA 컨트롤 타입 -> 한국어 레이블 (Claude 프롬프트 가독성용)
_CONTROL_LABEL: dict[str, str] = {
    "Button":        "버튼",
    "Edit":          "입력창",
    "Text":          "텍스트",
    "ComboBox":      "드롭다운",
    "CheckBox":      "체크박스",
    "RadioButton":   "라디오버튼",
    "ListItem":      "목록항목",
    "List":          "목록",
    "MenuItem":      "메뉴항목",
    "Menu":          "메뉴",
    "Tab":           "탭",
    "TabItem":       "탭항목",
    "TreeItem":      "트리항목",
    "Hyperlink":     "링크",
    "Image":         "이미지",
    "ScrollBar":     "스크롤바",
    "Slider":        "슬라이더",
    "Spinner":       "스피너",
    "Window":        "창",
    "Pane":          "패널",
    "Group":         "그룹",
    "ToolBar":       "툴바",
    "StatusBar":     "상태바",
    "Custom":        "커스텀",
    "DataItem":      "데이터항목",
    "DataGrid":      "데이터그리드",
    "Document":      "문서",
    "ProgressBar":   "진행바",
}

_MAX_ELEMENTS   = 60   # Claude 프롬프트 과부하 방지
_OVERLAY_RADIUS = 12   # SoM 번호 원 반지름 (픽셀)
_OVERLAY_FONT   = 14   # SoM 번호 폰트 크기


@dataclass
class UIAElement:
    """UIA에서 추출한 단일 UI 요소."""
    idx: int
    name: str
    control_type: str
    x: int
    y: int
    width: int
    height: int
    enabled: bool = True
    value: str = ""

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)

    def to_dict(self) -> dict:
        return {
            "번호": self.idx,
            "종류": _CONTROL_LABEL.get(self.control_type, self.control_type),
            "이름": self.name,
            "좌표": {"x": self.center[0], "y": self.center[1]},
            "활성": self.enabled,
            **({"값": self.value} if self.value else {}),
        }


class HybridScreenEngine:
    """UIA 트리 + Claude Vision 하이브리드 화면 인식·제어 엔진."""

    def __init__(self, on_chunk: Callable[[str], None] | None = None) -> None:
        self._on_chunk = on_chunk
        # Claude Code CLI 엔진 - lazy import로 순환 참조 방지
        self._engine = None
        # 태스크 대상으로 추적 중인 창의 OS 핸들 - launch 성공 시 기억해두고
        # 매 스텝 캡처 전에 강제로 다시 앞으로 가져온다 (다른 앱의 포커스 탈취에도
        # 같은 창을 계속 붙잡기 위함). run()이 새로 시작될 때마다 초기화된다.
        self._target_hwnd: int | None = None
        self._launched_apps: set[str] = set()

    def _get_engine(self):
        if self._engine is None:
            from core.engines.claude_cli_engine import ClaudeCliEngine
            self._engine = ClaudeCliEngine(timeout=600)
        return self._engine

    # -- 공개 진입점 -------------------------------------------------------

    def run(self, task: str) -> str:
        """관찰→판단→실행→재관찰을 반복하며 태스크를 끝까지 수행한다.

        매 스텝마다 화면을 새로 캡처하고 Claude에게 "행동 1개"만 JSON으로
        판단하게 한 뒤, 그 실행은 이 메서드가 직접 담당한다 (Claude는 셸 접근
        권한이 없다 - Read 툴로 스크린샷만 확인한다).
        """
        self._target_hwnd = None
        self._launched_apps = set()

        history: list[str] = []
        session_id: str | None = None
        for step in range(1, _MAX_STEPS + 1):
            self._reactivate_target()
            elements = self._collect_uia()
            orig_path, annotated_path = self._capture_annotated(elements)
            try:
                image_path = annotated_path or orig_path
                prompt = self._build_decision_prompt(task, elements, image_path, history)
                raw, session_id = self._get_engine().decide(prompt, session_id=session_id)

                try:
                    action = _parse_action(raw)
                except ValueError as e:
                    logger.warning(f"행동 파싱 실패 (step {step}): {e}")
                    history.append(f"{step}) 판단 결과를 해석하지 못함 - 재시도")
                    continue

                outcome = self._execute_action(action, elements)
                if self._on_chunk:
                    self._on_chunk(outcome)
                history.append(f"{step}) {outcome}")
                logger.info(f"[screen-loop step {step}] {outcome}")

                if action.get("action") in ("done", "fail"):
                    return str(action.get("message") or outcome)
            finally:
                _cleanup(orig_path)
                if annotated_path != orig_path:
                    _cleanup(annotated_path)

        return (
            f"최대 {_MAX_STEPS}단계 안에 작업을 끝내지 못했습니다. "
            f"지금까지 진행: " + " / ".join(history[-3:])
        )

    def capture_and_describe(self, question: str = "현재 화면을 설명해줘") -> str:
        """화면만 찍어서 Claude에게 설명 요청 - 제어 없이 분석만 (단발 호출)."""
        elements = self._collect_uia()
        orig_path, annotated_path = self._capture_annotated(elements)
        try:
            image_path = annotated_path or orig_path
            prompt = self._build_describe_prompt(question, elements, image_path)
            raw, _ = self._get_engine().decide(prompt)
            return raw
        finally:
            _cleanup(orig_path)
            if annotated_path != orig_path:
                _cleanup(annotated_path)

    # -- UIA 레이어 --------------------------------------------------------

    def _collect_uia(self) -> list[UIAElement]:
        """현재 포커스 윈도우의 UIA 요소 트리를 수집한다.

        uiautomation 패키지가 없거나 실패하면 빈 리스트를 반환한다.
        Vision 레이어가 단독으로 처리를 이어가므로 치명적이지 않다.
        """
        try:
            import uiautomation as auto  # type: ignore
        except ImportError:
            logger.warning("uiautomation 패키지 없음 - Vision 단독 모드로 실행")
            return []

        try:
            root = auto.GetForegroundControl()
            if root is None:
                return []
            elements: list[UIAElement] = []
            self._walk_uia(root, elements, max_count=_MAX_ELEMENTS)
            logger.info(f"UIA 수집: {len(elements)}개 요소")
            return elements
        except Exception as e:
            logger.warning(f"UIA 수집 실패: {e} - Vision 단독 모드")
            return []

    def _walk_uia(
        self,
        ctrl,
        out: list[UIAElement],
        max_count: int,
        depth: int = 0,
    ) -> None:
        if len(out) >= max_count or depth > 8:
            return
        try:
            rect = ctrl.BoundingRectangle
            if rect.width() > 0 and rect.height() > 0:
                name = (ctrl.Name or "").strip()
                ct   = ctrl.ControlTypeName or "Custom"
                val  = ""
                try:
                    val = (ctrl.GetValuePattern().Value or "").strip()[:80]
                except Exception:
                    pass

                if name or ct in ("Button", "Edit", "CheckBox", "RadioButton",
                                   "ComboBox", "ListItem", "MenuItem", "TabItem",
                                   "Hyperlink", "Spinner", "Slider"):
                    out.append(UIAElement(
                        idx          = len(out) + 1,
                        name         = name[:60],
                        control_type = ct,
                        x            = rect.left,
                        y            = rect.top,
                        width        = rect.width(),
                        height       = rect.height(),
                        enabled      = bool(ctrl.IsEnabled),
                        value        = val,
                    ))
        except Exception:
            pass

        try:
            for child in ctrl.GetChildren():
                self._walk_uia(child, out, max_count, depth + 1)
        except Exception:
            pass

    # -- Vision 레이어 (파일 저장 방식) ------------------------------------

    def _capture_annotated(
        self,
        elements: list[UIAElement],
    ) -> tuple[str, str]:
        """스크린샷 + SoM 오버레이를 임시 파일로 저장하고 경로를 반환한다.

        Returns:
            (원본 파일 경로, SoM 오버레이 파일 경로)
            실패 시 ("", "") 반환 - Vision 없이 UIA만으로 Claude가 동작.

        [설계 이유]
        Claude Code CLI -p 는 텍스트 입력만 받는다.
        base64를 프롬프트 문자열에 삽입해도 Claude Vision이 인식하지 못한다.
        파일로 저장해 경로를 프롬프트에 넣어주면 Claude가 Read 툴로 그 파일을
        직접 열어 확인할 수 있다.
        """
        try:
            import pyautogui  # type: ignore
            from PIL import Image, ImageDraw, ImageFont  # type: ignore

            # Windows에서 UAC 보안 데스크톱 전환·디스플레이 모드 변경 등으로
            # ImageGrab.grab()이 순간적으로 "screen grab failed"를 던지는 경우가
            # 있어 짧은 대기 후 한 번 재시도한다.
            try:
                pil_img = pyautogui.screenshot()
            except Exception as e:
                logger.warning(f"스크린샷 1차 실패, 재시도: {e}")
                time.sleep(0.5)
                pil_img = pyautogui.screenshot()

            # 원본 임시 파일 저장
            fd_orig, path_orig = tempfile.mkstemp(suffix=".png",
                                                   prefix="jarvis_screen_")
            os.close(fd_orig)
            pil_img.save(path_orig)

            if not elements:
                return path_orig, path_orig

            # SoM 오버레이 그리기
            annotated = pil_img.copy()
            draw = ImageDraw.Draw(annotated)
            try:
                font = ImageFont.truetype("arial.ttf", _OVERLAY_FONT)
            except Exception:
                font = ImageFont.load_default()

            for el in elements:
                cx, cy = el.center
                r = _OVERLAY_RADIUS
                color = (255, 80, 80) if el.enabled else (150, 150, 150)
                draw.ellipse((cx - r, cy - r, cx + r, cy + r),
                             fill=color, outline="white", width=2)
                label = str(el.idx)
                bbox = draw.textbbox((0, 0), label, font=font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                draw.text((cx - tw // 2, cy - th // 2), label,
                          fill="white", font=font)

            # 오버레이 임시 파일 저장
            fd_ann, path_ann = tempfile.mkstemp(suffix=".png",
                                                 prefix="jarvis_som_")
            os.close(fd_ann)
            annotated.save(path_ann)

            logger.info(f"스크린샷 저장: {path_orig}")
            logger.info(f"SoM 오버레이 저장: {path_ann}")
            return path_orig, path_ann

        except ImportError as e:
            logger.warning(f"스크린샷 패키지 없음: {e}")
            return "", ""
        except Exception as e:
            logger.error(f"스크린샷/오버레이 오류: {e}")
            return "", ""

    # -- Claude 통합 레이어 (판단 전용 - 실행은 하지 않는다) ----------------

    @staticmethod
    def _uia_section(elements: list[UIAElement]) -> str:
        if not elements:
            return "## UIA 정보 없음 - 스크린샷만 보고 판단할 것"
        uia_json = json.dumps(
            [el.to_dict() for el in elements],
            ensure_ascii=False,
            indent=2,
        )
        return (
            "## 현재 화면 UI 요소 목록 (Windows UI Automation API 직접 추출)\n"
            "아래 JSON의 좌표는 픽셀 추정값이 아닌 Windows API에서 읽은 정확한 값이다.\n"
            "클릭·입력 대상은 반드시 이 목록의 '번호'(idx)로 지정하라.\n\n"
            f"```json\n{uia_json}\n```"
        )

    def _build_decision_prompt(
        self,
        task: str,
        elements: list[UIAElement],
        image_path: str,
        history: list[str],
    ) -> str:
        """한 스텝의 "행동 1개"만 JSON으로 결정하게 하는 프롬프트.

        Claude는 Read 툴만 허용되어 실제 클릭·입력을 실행할 수 없다 — 대신
        어떤 행동을 할지 JSON으로 판단만 하고, 실행은 _execute_action()이
        UIA 좌표로 직접 수행한다. 매 스텝 화면을 새로 캡처해 여기로 다시
        전달하므로, 이전 행동이 실제로 성공했는지 다음 판단에서 확인된다.
        """
        history_section = "\n".join(history) if history else "(아직 없음)"
        image_section = (
            f"## 현재 화면 스크린샷\n파일 경로: {image_path}\n"
            "Read 툴로 이 파일을 반드시 먼저 확인한 뒤 판단하라. "
            "빨간 원 번호는 위 UIA 목록의 '번호'(idx)와 일치한다."
            if image_path else "## 스크린샷 없음 - UIA 목록만으로 판단할 것"
        )

        return (
            "너는 자비스(JARVIS)야. Windows 화면을 관찰하고 목표 달성을 위한 "
            '"행동 딱 1개"만 JSON으로 결정하는 에이전트다.\n'
            "실제 클릭·입력·스크롤은 네가 하지 않는다 — 네가 고른 행동을 시스템이 "
            "대신 실행하고, 그 결과가 반영된 화면을 다음 턴에 다시 보여준다.\n\n"
            f"## 최종 목표\n{task}\n\n"
            f"## 지금까지 실행한 행동과 결과\n{history_section}\n\n"
            f"{self._uia_section(elements)}\n\n"
            f"{image_section}\n\n"
            "## 응답 형식\n"
            "다른 설명 없이 아래 중 정확히 하나의 JSON 객체만 출력하라:\n"
            '- {"action": "launch", "app": "<Windows 실행 명령, 예: chrome, notepad, calc, explorer, msedge>"}\n'
            '- {"action": "click", "idx": <UIA 번호>}\n'
            '- {"action": "type", "idx": <UIA 번호>, "text": "<입력할 텍스트>"}\n'
            '- {"action": "key", "key": "<enter|esc|tab|backspace 등 또는 ctrl+a 같은 조합>"}\n'
            '- {"action": "scroll", "direction": "up|down", "amount": <픽셀, 기본 300>}\n'
            '- {"action": "wait", "seconds": <1~3 사이 숫자>}\n'
            '- {"action": "done", "message": "<목표 달성 - 사용자에게 들려줄 한국어 요약>"}\n'
            '- {"action": "fail", "message": "<더 진행할 수 없는 이유, 한국어>"}\n\n'
            "목표에 필요한 앱이 지금 화면(UIA 목록)에 보이지 않으면 클릭 대상을 "
            "억지로 추측하지 말고 launch로 먼저 실행하라 (app은 영문 실행 명령으로 "
            '변환해서 적을 것 — 예: "크롬" -> "chrome"). 단, 위 기록에 이미 launch로 '
            "실행한 앱은 절대 다시 launch하지 마라 — 창만 늘어나고 헷갈릴 뿐이다.\n"
            "'잠금'/'로그아웃'/'시스템 종료'/'재부팅'/'삭제'/'초기화' 등 이름의 요소는 "
            "절대 클릭하지 마라 (시스템에 의해 강제로 차단되며 스텝만 낭비된다).\n"
            "alt+tab 같은 창 전환 단축키도 쓰지 마라 — 결과가 무작위라 엉뚱한 창으로 "
            "튈 수 있다. 화면이 예상과 다르면 그냥 다음 스크린샷을 기다리며 판단하라.\n"
            "목표가 이미 달성됐다고 판단되면 반드시 done을 선택하라. "
            "위 기록에 이미 실행한 행동을 똑같이 반복하지 마라."
        )

    @staticmethod
    def _build_describe_prompt(
        question: str,
        elements: list[UIAElement],
        image_path: str,
    ) -> str:
        image_section = (
            f"## 현재 화면 스크린샷\n파일 경로: {image_path}\nRead 툴로 이 파일을 확인하라."
            if image_path else "## 스크린샷 없음 - UIA 목록만으로 답할 것"
        )
        return (
            "너는 자비스(JARVIS)야. PC 화면을 분석해 설명하는 에이전트다 (제어는 하지 않는다).\n\n"
            f"{HybridScreenEngine._uia_section(elements)}\n\n"
            f"{image_section}\n\n"
            "위 정보를 바탕으로 사용자 질문에 한국어로 구체적으로 답하라.\n"
            f"질문: {question}"
        )

    # -- 행동 실행 (Claude가 아니라 이 코드가 직접 수행) --------------------

    def _execute_action(self, action: dict, elements: list[UIAElement]) -> str:
        kind = action.get("action")
        try:
            if kind == "launch":
                app = str(action.get("app", "")).strip()
                if not app:
                    return "앱 실행 실패: app 값 없음"
                key = app.lower()
                if key in self._launched_apps:
                    return (f"앱 실행 생략: '{app}'은(는) 이번 작업에서 이미 실행했습니다. "
                            f"재실행하지 말고 현재 화면에서 이어서 진행하라.")
                self._launched_apps.add(key)
                outcome = self._launch_app(app)
                self._remember_foreground_as_target()
                return outcome

            if kind == "click":
                idx = int(action.get("idx", -1))
                el = self._find_element(elements, idx)
                if el is None:
                    return f"클릭 실패: 존재하지 않는 요소 번호 {idx}"
                danger = _find_dangerous_keyword(el.name)
                if danger:
                    return (f"클릭 거부: '{el.name}'은(는) 위험한 동작('{danger}')으로 "
                             f"판단되어 실행하지 않았습니다. 다른 방법을 시도하세요.")
                self.click_element(el)
                time.sleep(0.3)
                return f"클릭: [{idx}] {el.name or el.control_type}"

            if kind == "type":
                idx = int(action.get("idx", -1))
                text = str(action.get("text", ""))
                el = self._find_element(elements, idx)
                if el is None:
                    return f"입력 실패: 존재하지 않는 요소 번호 {idx}"
                danger = _find_dangerous_keyword(el.name)
                if danger:
                    return (f"입력 거부: '{el.name}'은(는) 위험한 동작('{danger}')으로 "
                             f"판단되어 실행하지 않았습니다. 다른 방법을 시도하세요.")
                self.type_into_element(el, text)
                time.sleep(0.2)
                return f"입력: [{idx}] {el.name or el.control_type} <- '{text}'"

            if kind == "key":
                key = str(action.get("key", "")).strip()
                if not key:
                    return "키 입력 실패: key 값 없음"
                normalized = key.lower().replace(" ", "")
                if normalized in _DANGEROUS_KEY_COMBOS:
                    return f"키 입력 거부: '{key}' 조합은 위험한 동작으로 판단되어 실행하지 않았습니다."
                if normalized in _WINDOW_SWITCH_KEY_COMBOS:
                    return (f"키 입력 거부: '{key}'처럼 결과를 예측할 수 없는 창 전환은 "
                            f"쓰지 않는다. 다음 스크린샷에서 현재 상태를 다시 확인하라.")
                self._press_key(key)
                time.sleep(0.2)
                return f"키 입력: {key}"

            if kind == "scroll":
                direction = str(action.get("direction", "down"))
                amount = int(action.get("amount", 300))
                self._scroll(direction, amount)
                time.sleep(0.2)
                return f"스크롤: {direction} {amount}px"

            if kind == "wait":
                seconds = min(max(float(action.get("seconds", 1)), 0.2), _MAX_WAIT_SECONDS)
                time.sleep(seconds)
                return f"대기: {seconds}초"

            if kind in ("done", "fail"):
                return str(action.get("message", ""))

            return f"알 수 없는 행동: {kind}"
        except Exception as e:
            logger.error(f"행동 실행 오류({kind}): {e}")
            return f"행동 실행 오류({kind}): {e}"

    @staticmethod
    def _find_element(elements: list[UIAElement], idx: int) -> UIAElement | None:
        return next((el for el in elements if el.idx == idx), None)

    @staticmethod
    def _launch_app(app: str) -> str:
        try:
            os.startfile(app)  # noqa: S606 - Claude가 골라준 알려진 실행 명령만 사용
            time.sleep(1.5)  # 창이 뜰 시간 확보
            return f"앱 실행: {app}"
        except Exception as e:
            return f"앱 실행 실패({app}): {e}"

    def _remember_foreground_as_target(self) -> None:
        """방금 뜬 창을 태스크 대상으로 기억해, 이후 스텝에서 계속 앞으로 가져온다."""
        try:
            import uiautomation as auto  # type: ignore
            win = auto.GetForegroundControl()
            self._target_hwnd = win.NativeWindowHandle if win else None
        except Exception:
            self._target_hwnd = None

    def _reactivate_target(self) -> None:
        """추적 중인 대상 창이 있으면 다른 앱에 포커스를 뺏겼어도 다시 앞으로 가져온다.

        [사고 사례] 이 재활성화가 없으면, Claude가 alt+tab 등으로 화면 상태를 확인하려다
        전혀 다른 창(예: 이 코드를 돌리는 터미널)으로 포커스가 튀어 태스크 대상 창을
        완전히 놓치는 문제가 실제로 발생했다. 대상 창이 이미 닫혔으면 조용히 건너뛴다.
        """
        if self._target_hwnd is None:
            return
        try:
            import uiautomation as auto  # type: ignore
            win = auto.ControlFromHandle(self._target_hwnd)
            if win and win.Exists(0):
                win.SetActive()
                time.sleep(0.2)
            else:
                self._target_hwnd = None
        except Exception:
            self._target_hwnd = None

    @staticmethod
    def _press_key(key: str) -> None:
        import pyautogui  # type: ignore
        key = key.lower().strip()
        if "+" in key:
            pyautogui.hotkey(*(p.strip() for p in key.split("+")))
        else:
            pyautogui.press(key)

    @staticmethod
    def _scroll(direction: str, amount: int) -> None:
        import pyautogui  # type: ignore
        amount = max(1, min(int(amount), _MAX_SCROLL_PX))
        pyautogui.scroll(amount if direction == "up" else -amount)

    # -- 직접 제어 유틸 (UIA 좌표 기반) -----------------------------------

    @staticmethod
    def click_element(element: UIAElement) -> None:
        """UIA 좌표로 요소 중앙을 정밀 클릭한다."""
        try:
            import pyautogui  # type: ignore
            cx, cy = element.center
            pyautogui.click(cx, cy)
            logger.debug(f"클릭: {element.name} ({cx}, {cy})")
        except Exception as e:
            logger.error(f"클릭 실패: {e}")

    @staticmethod
    def type_into_element(element: UIAElement, text: str) -> None:
        """UIA 좌표로 입력창을 클릭하고 텍스트를 입력한다."""
        try:
            import pyautogui  # type: ignore
            import pyperclip  # type: ignore
            cx, cy = element.center
            pyautogui.click(cx, cy)
            time.sleep(0.1)
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "a")
            pyautogui.hotkey("ctrl", "v")
            logger.debug(f"입력: '{text}' -> {element.name}")
        except Exception as e:
            logger.error(f"입력 실패: {e}")


def _cleanup(path: str) -> None:
    """임시 스크린샷 파일을 삭제한다. Claude 실행 완료 후 호출."""
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass


def _parse_action(raw: str) -> dict:
    """Claude의 판단 응답에서 행동 JSON 객체 하나를 추출한다.

    마크다운 코드펜스(```json ... ```)로 감싸거나 앞뒤에 설명을 붙이는 경우가
    흔해 첫 번째 {...} 블록만 관대하게 추출한다.
    """
    text = re.sub(r"```(?:json)?", "", raw).strip()
    match = _ACTION_JSON_RE.search(text)
    if not match:
        raise ValueError(f"JSON 행동을 찾을 수 없음: {raw[:200]}")
    obj = json.loads(match.group(0))
    if not isinstance(obj, dict) or "action" not in obj:
        raise ValueError(f"'action' 필드가 없는 응답: {raw[:200]}")
    return obj
