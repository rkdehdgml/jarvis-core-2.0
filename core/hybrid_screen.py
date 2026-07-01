"""UIA 트리 + Claude Vision 동시 실행 하이브리드 화면 인식·제어 엔진.

전략 A: 모든 화면에서 두 레이어를 동시에 사용한다.

  레이어 1 — UIA (Windows UI Automation API)
    pyuiautomation으로 현재 포커스 앱의 UI 요소 트리를 수집한다.
    각 요소의 ControlType(버튼/텍스트박스/체크박스 등), Name, 화면 좌표,
    enabled/visible 상태를 정확한 API 값으로 추출한다.
    → 픽셀 추정 없는 정밀 좌표 확보

  레이어 2 — Vision (Claude via ClaudeCliEngine)
    pyautogui로 스크린샷을 찍고, UIA로 얻은 요소 위치에 번호 오버레이를
    그려 넣는다(Set-of-Mark). 번호가 붙은 이미지와 UIA JSON을 함께 Claude에
    전달하면 Claude가 "3번 클릭" 같은 의미 기반 지시를 내린다.
    → 맥락·레이아웃·이미지 내용 이해

  실행:
    Claude의 지시(요소 번호 또는 좌표)를 UIA 좌표로 변환해 클릭·입력 수행.
    UIA가 커버하지 못하는 영역(웹 콘텐츠, 게임 등)은 Vision 좌표로 폴백.

사용 흐름 (skill_screen_agent.py가 호출):
  engine = HybridScreenEngine()
  result = engine.run(task="네이버 검색창에 '날씨' 입력해줘")
"""
from __future__ import annotations

import base64
import io
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)

# UIA 컨트롤 타입 → 한국어 레이블 (Claude 프롬프트 가독성용)
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

_MAX_ELEMENTS   = 60    # Claude 프롬프트 과부하 방지
_OVERLAY_RADIUS = 12    # SoM 번호 원 반지름 (픽셀)
_OVERLAY_FONT   = 14    # SoM 번호 폰트 크기


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

    # ── 공개 진입점 ───────────────────────────────────────────────────────────

    def run(self, task: str) -> str:
        """화면을 분석하고 태스크를 실행한 뒤 결과를 반환한다."""
        elements = self._collect_uia()
        screenshot_b64, annotated_b64 = self._capture_annotated(elements)
        return self._ask_claude(task, elements, screenshot_b64, annotated_b64)

    def capture_and_describe(self, question: str = "현재 화면을 설명해줘") -> str:
        """화면만 찍어서 Claude에게 설명 요청 — 제어 없이 분석만."""
        elements = self._collect_uia()
        screenshot_b64, annotated_b64 = self._capture_annotated(elements)
        return self._ask_claude(question, elements, screenshot_b64, annotated_b64,
                                control_mode=False)

    # ── UIA 레이어 ────────────────────────────────────────────────────────────

    def _collect_uia(self) -> list[UIAElement]:
        """현재 포커스 윈도우의 UIA 요소 트리를 수집한다.

        uiautomation 패키지가 없거나 실패하면 빈 리스트를 반환한다.
        Vision 레이어가 단독으로 처리를 이어가므로 치명적이지 않다.
        """
        try:
            import uiautomation as auto  # type: ignore
        except ImportError:
            logger.warning("uiautomation 패키지 없음 — Vision 단독 모드로 실행")
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
            logger.warning(f"UIA 수집 실패: {e} — Vision 단독 모드")
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
            if rect.width() <= 0 or rect.height() <= 0:
                pass
            else:
                name = (ctrl.Name or "").strip()
                ct   = ctrl.ControlTypeName or "Custom"
                val  = ""
                try:
                    val = (ctrl.GetValuePattern().Value or "").strip()[:80]
                except Exception:
                    pass

                # 의미 있는 요소만 포함 (이름 있거나 인터랙티브 컨트롤)
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

    # ── Vision 레이어 ─────────────────────────────────────────────────────────

    def _capture_annotated(
        self,
        elements: list[UIAElement],
    ) -> tuple[str, str]:
        """스크린샷을 찍고 UIA 요소에 번호 오버레이를 그려 두 이미지를 반환한다.

        Returns:
            (원본 base64, SoM 오버레이 base64) — 둘 다 PNG JPEG 혼용 가능
            uiautomation 없으면 원본만 반환하고 annotated는 원본과 동일.
        """
        try:
            import pyautogui  # type: ignore
            from PIL import Image, ImageDraw, ImageFont  # type: ignore

            pil_img = pyautogui.screenshot()

            # 원본 base64
            buf_orig = io.BytesIO()
            pil_img.save(buf_orig, format="PNG")
            b64_orig = base64.b64encode(buf_orig.getvalue()).decode()

            if not elements:
                return b64_orig, b64_orig

            # SoM 오버레이
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
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                draw.text((cx - tw // 2, cy - th // 2), label,
                          fill="white", font=font)

            buf_ann = io.BytesIO()
            annotated.save(buf_ann, format="PNG")
            b64_ann = base64.b64encode(buf_ann.getvalue()).decode()

            logger.info("SoM 오버레이 이미지 생성 완료")
            return b64_orig, b64_ann

        except ImportError as e:
            logger.warning(f"스크린샷 패키지 없음: {e}")
            return "", ""
        except Exception as e:
            logger.error(f"스크린샷/오버레이 오류: {e}")
            return "", ""

    # ── Claude 통합 레이어 ────────────────────────────────────────────────────

    def _ask_claude(
        self,
        task: str,
        elements: list[UIAElement],
        screenshot_b64: str,
        annotated_b64: str,
        control_mode: bool = True,
    ) -> str:
        """UIA JSON + SoM 이미지를 Claude에 전달해 분석·제어를 요청한다.

        Claude Code CLI는 --dangerously-skip-permissions 모드에서
        computer_use 툴로 마우스/키보드를 직접 제어할 수 있다.
        UIA 정보를 프롬프트에 주입해 Claude가 정확한 좌표를 알고 클릭하도록 한다.
        """
        from core.engines.claude_cli_engine import ClaudeCliEngine  # 순환 방지 lazy import

        # UIA JSON 섹션 구성
        uia_section = ""
        if elements:
            uia_json = json.dumps(
                [el.to_dict() for el in elements],
                ensure_ascii=False,
                indent=2,
            )
            uia_section = f"""
## 현재 화면 UI 요소 목록 (Windows UI Automation API 직접 추출)
아래 JSON의 좌표는 픽셀 추정값이 아닌 Windows API에서 직접 읽은 정확한 값이다.
클릭·입력 시 이 좌표를 우선 사용하라.

```json
{uia_json}
```
"""
        else:
            uia_section = "\n## UIA 정보 없음 — Vision만으로 분석 및 제어\n"

        # SoM 이미지 섹션 (base64 이미지 첨부 안내)
        image_note = ""
        if annotated_b64:
            image_note = (
                "\n## 첨부 이미지\n"
                "- 원본 스크린샷과 각 UI 요소에 번호가 붙은 오버레이 이미지를 첨부했다.\n"
                "- UIA 목록의 '번호' 필드와 이미지의 빨간 원 번호가 일치한다.\n"
            )

        if control_mode:
            action_instruction = (
                "위 정보를 바탕으로 다음 태스크를 수행하라.\n"
                "클릭이 필요하면 UIA 목록의 정확한 좌표를 사용하고, "
                "UIA 목록에 없는 영역(웹 콘텐츠, 이미지 등)은 Vision으로 판단하라.\n"
                "진행 상황을 한국어로 단계별로 설명하면서 실행하라.\n\n"
                f"태스크: {task}"
            )
        else:
            action_instruction = (
                "위 화면 정보를 바탕으로 사용자 질문에 한국어로 답하라.\n\n"
                f"질문: {task}"
            )

        prompt = f"""너는 자비스(JARVIS)야. PC 화면을 분석하고 제어하는 전문 에이전트다.

{uia_section}
{image_note}
{action_instruction}
"""
        # ClaudeCliEngine.run_task()로 실행 (--dangerously-skip-permissions + stream-json)
        engine = ClaudeCliEngine()
        return engine.run_task(prompt, on_chunk=self._on_chunk)

    # ── 직접 제어 유틸 (UIA 좌표 기반) ──────────────────────────────────────

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
            logger.debug(f"입력: '{text}' → {element.name}")
        except Exception as e:
            logger.error(f"입력 실패: {e}")
