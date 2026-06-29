"""pyautogui + pytesseract OCR + Groq/Ollama 루프로 PC 화면을 인식하고 제어하는 에이전트 스킬.

화면 텍스트를 번호가 매겨진 요소 목록으로 변환해 LLM이 좌표 기반으로 제어한다.
Groq 일일 토큰 소진(RateLimitError) 시 자동으로 Ollama(로컬)로 전환한다.

트리거 예시:
  "화면 제어로 네이버 부동산 켜서 대전 서구 아파트 수집해줘"
  "직접 제어해서 크롬에서 유튜브 열고 자비스 검색해줘"
  "화면 에이전트로 엑셀 열고 데이터 입력해줘"
  "네이버 켜서 뉴스 목록 수집해서 저장해줘"
"""
import json
import logging
import os
import re

import requests as _requests
from dotenv import load_dotenv
from groq import BadRequestError, Groq, RateLimitError

from core.skill_base import Skill, SkillResult
from skills.agent_tools import reporter_tool, screen_tool

load_dotenv()
logger = logging.getLogger(__name__)

_GROQ_MODEL   = "llama-3.3-70b-versatile"
_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
_OLLAMA_HOST  = os.getenv("OLLAMA_HOST", "localhost:11434")
_MAX_TURNS    = 25
_MAX_TOKENS   = 2048
_MAX_OUT      = 3000   # 도구 결과 최대 전달 길이

_SYSTEM_PROMPT = (
    "You are Jarvis, a PC screen control agent. Control the user's Windows computer to complete tasks.\n\n"
    "Tools:\n"
    "- screenshot_read: Capture screen → numbered text elements with (x,y) coords. Call FIRST and AFTER every action.\n"
    "- mouse_click: Click at (x,y). Use coordinates from screenshot_read.\n"
    "- keyboard_type: Type text (Korean supported via clipboard).\n"
    "- keyboard_key: Press keys: enter, tab, escape, backspace, ctrl+c, ctrl+v, ctrl+a, ctrl+w, ctrl+l, ctrl+r, ctrl+t, win, alt+f4, page_down, page_up, f5.\n"
    "- mouse_scroll: Scroll up or down.\n"
    "- get_windows: List all open windows.\n"
    "- focus_window: Bring window to front by partial title.\n"
    "- open_app: Open URL (full https:// URL) or launch app by name.\n"
    "- report: Send Korean progress message to user.\n\n"
    "Workflow:\n"
    "1. report() what you plan to do\n"
    "2. screenshot_read() to see current screen state\n"
    "3. Execute one action\n"
    "4. screenshot_read() again to verify the result\n"
    "5. Repeat until task is complete\n\n"
    "Rules:\n"
    "- Always screenshot_read() before and after each action\n"
    "- For web: use open_app() with full https:// URL, then screenshot_read() after page load\n"
    "- For address bar: use keyboard_key('ctrl+l') to focus, then keyboard_type(url), then keyboard_key('enter')\n"
    "- Collect requested data by reading screenshot_read() summaries and include it in your final response\n"
    "- Respond ONLY in Korean when done. Be friendly and natural."
)

_XML_TOOL_RE = re.compile(r'<function=(\w+)\s*(\{[^<]*?\})?>', re.DOTALL)

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "screenshot_read",
            "description": "Capture screen and extract numbered text elements with (x,y) coordinates. Call FIRST and after every action to see current screen state.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mouse_click",
            "description": "Click at screen coordinates. Use x, y from screenshot_read results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "X coordinate"},
                    "y": {"type": "integer", "description": "Y coordinate"},
                    "button": {"type": "string", "description": "left (default), right, or double"},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "keyboard_type",
            "description": "Type text into focused input. Supports Korean and English.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to type"},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "keyboard_key",
            "description": "Press a key or shortcut. Examples: enter, tab, escape, backspace, ctrl+c, ctrl+v, ctrl+a, ctrl+w, ctrl+l, ctrl+r, ctrl+t, win, alt+f4, page_down, f5",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Key name or combination (use + for combos)"},
                },
                "required": ["key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mouse_scroll",
            "description": "Scroll the mouse wheel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "description": "up or down"},
                    "amount": {"type": "integer", "description": "Scroll clicks (default 3)"},
                    "x": {"type": "integer", "description": "X position (optional)"},
                    "y": {"type": "integer", "description": "Y position (optional)"},
                },
                "required": ["direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_windows",
            "description": "Get list of open windows and the active window.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "focus_window",
            "description": "Bring a window to front by partial title match.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Window title (partial)"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "Open a URL in the browser or launch an application by name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "Full URL (https://...) or app name (chrome, notepad, explorer)"},
                },
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "report",
            "description": "Report current progress to user in Korean.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Progress message"},
                },
                "required": ["message"],
            },
        },
    },
]

# ── 라우팅 키워드 ──────────────────────────────────────────────────────────────
_STRONG = ["화면 제어", "화면 에이전트", "직접 제어", "화면으로 제어", "스크린 에이전트"]
_OPEN   = ["켜서", "열어서", "직접 열어", "직접 켜서"]
_SAVE   = ["수집해줘", "수집해서", "저장해줘", "긁어줘", "스크래핑"]


class ScreenAgentSkill(Skill):
    """PC 화면을 직접 제어해 브라우저·앱을 조작하고 데이터를 수집·저장하는 에이전트."""

    name = "screen_agent"
    description = "화면 OCR + 마우스/키보드 제어로 어떤 앱·사이트든 직접 조작한다"
    triggers = ["화면 제어", "화면 에이전트", "직접 제어"]
    examples = [
        "화면 제어로 네이버 부동산 켜서 대전 서구 아파트 수집해줘",
        "직접 제어해서 크롬으로 유튜브 자비스 검색해줘",
        "화면 에이전트로 네이버 켜서 뉴스 저장해줘",
        "네이버 켜서 검색결과 수집해줘",
    ]

    def can_handle(self, intent: str, text: str) -> float:
        if any(t in text for t in _STRONG):
            return 0.95
        if any(o in text for o in _OPEN) and any(s in text for s in _SAVE):
            return 0.91
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        try:
            from voice import tts as _tts
            reporter_tool.set_callback(_tts.speak)
        except Exception:
            reporter_tool.set_callback(None)

        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            return SkillResult(
                speech="GROQ_API_KEY가 없습니다. .env 파일을 확인해주세요.",
                success=False,
            )

        result = self._run_agent(api_key, text)
        return SkillResult(speech=result, success=True, data={"task": text})

    # ── 에이전트 루프 ──────────────────────────────────────────────────────────

    def _run_agent(self, api_key: str, task: str) -> str:
        groq_client = Groq(api_key=api_key)
        use_ollama = False

        messages: list[dict] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": task},
        ]

        for turn in range(_MAX_TURNS):
            tool_calls, content, should_switch = self._call_llm(
                groq_client, messages, use_ollama
            )

            # Groq 토큰 소진 → Ollama로 전환 후 같은 턴 재시도
            if should_switch:
                logger.warning("Groq 토큰 소진 → Ollama로 전환")
                reporter_tool.report("Groq 토큰이 소진되어 Ollama로 전환합니다.")
                use_ollama = True
                tool_calls, content, _ = self._call_llm(groq_client, messages, True)

            if tool_calls is None:
                return content or "에이전트 실행 중 오류가 발생했습니다."

            # 도구 호출 없음 → 최종 응답
            if not tool_calls:
                return content or "작업을 완료했습니다."

            # assistant 메시지 기록
            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["arguments"],
                        },
                    }
                    for tc in tool_calls
                ],
            })

            # 각 도구 실행 후 결과 기록
            for tc in tool_calls:
                fn_name = tc["name"]
                try:
                    fn_args = json.loads(tc["arguments"])
                except json.JSONDecodeError:
                    fn_args = {}

                result = self._dispatch_tool(fn_name, fn_args)
                result_str = json.dumps(result, ensure_ascii=False)[:_MAX_OUT]
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result_str,
                })

        logger.warning(f"ScreenAgentSkill: {_MAX_TURNS}턴 초과 — task: {task!r}")
        return "최대 반복 횟수에 도달했습니다. 작업 일부만 완료됐을 수 있습니다."

    # ── LLM 호출 (Groq SDK / Ollama requests 통합) ─────────────────────────────

    def _call_llm(
        self, groq_client: Groq, messages: list, use_ollama: bool
    ) -> tuple[list | None, str, bool]:
        """LLM을 호출하고 (tool_calls, content, switch_to_ollama) 를 반환한다.

        tool_calls: [{id, name, arguments}, ...] 또는 [] (최종 응답) 또는 None (오류)
        switch_to_ollama: True이면 호출자가 Ollama로 재시도해야 함
        """
        if use_ollama:
            return self._call_ollama(messages)
        return self._call_groq(groq_client, messages)

    def _call_groq(
        self, client: Groq, messages: list
    ) -> tuple[list | None, str, bool]:
        try:
            resp = client.chat.completions.create(
                model=_GROQ_MODEL,
                messages=messages,
                tools=_TOOLS,
                tool_choice="auto",
                max_tokens=_MAX_TOKENS,
                timeout=60,
            )
            msg = resp.choices[0].message
            tool_calls = []
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_calls.append({
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    })
            return tool_calls, msg.content or "", False

        except RateLimitError:
            return None, "", True   # switch signal

        except BadRequestError as exc:
            # Groq가 XML 형식으로 도구를 호출했을 때 파싱해서 재처리
            try:
                body = getattr(exc, "body", {}) or {}
                err = body.get("error", {}) if isinstance(body, dict) else {}
                failed_gen = err.get("failed_generation", "")
                if failed_gen and "function=" in failed_gen:
                    tool_calls = self._parse_xml_tool_calls(failed_gen)
                    if tool_calls:
                        logger.warning(f"Groq XML 도구 호출 파싱 재처리: {[t['name'] for t in tool_calls]}")
                        return tool_calls, "", False
            except Exception:
                pass
            logger.error(f"Groq BadRequest (턴): {exc}")
            return None, f"Groq 요청 오류: {exc}", False

        except Exception as exc:
            logger.error(f"Groq 호출 실패: {exc}")
            return None, f"오류: {exc}", False

    def _call_ollama(self, messages: list) -> tuple[list | None, str, bool]:
        host = _OLLAMA_HOST
        if not host.startswith("http"):
            host = f"http://{host}"
        try:
            resp = _requests.post(
                f"{host}/v1/chat/completions",
                json={
                    "model": _OLLAMA_MODEL,
                    "messages": messages,
                    "tools": _TOOLS,
                    "tool_choice": "auto",
                    "max_tokens": _MAX_TOKENS,
                    "stream": False,
                },
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            msg = data["choices"][0]["message"]
            content = msg.get("content") or ""

            raw_tcs = msg.get("tool_calls") or []
            tool_calls = []
            for tc in raw_tcs:
                fn = tc.get("function", {})
                args = fn.get("arguments", "{}")
                if not isinstance(args, str):
                    args = json.dumps(args, ensure_ascii=False)
                tool_calls.append({
                    "id": tc.get("id", f"ollama_{len(tool_calls)}"),
                    "name": fn.get("name", ""),
                    "arguments": args,
                })
            return tool_calls, content, False

        except _requests.exceptions.ConnectionError:
            logger.error(f"Ollama 연결 실패: {host}")
            return None, f"Ollama 서버에 연결할 수 없습니다 ({host}). 데스크탑에서 'ollama serve'를 실행해주세요.", False
        except Exception as exc:
            logger.error(f"Ollama 호출 실패: {exc}")
            return None, f"Ollama 오류: {exc}", False

    def _parse_xml_tool_calls(self, text: str) -> list[dict]:
        """<function=NAME {ARGS}></function> XML 형식을 tool_calls 목록으로 변환한다."""
        tool_calls = []
        for i, m in enumerate(_XML_TOOL_RE.finditer(text)):
            tool_calls.append({
                "id": f"xml_{i}",
                "name": m.group(1),
                "arguments": (m.group(2) or "{}").strip(),
            })
        return tool_calls

    # ── 도구 디스패치 ──────────────────────────────────────────────────────────

    def _dispatch_tool(self, name: str, args: dict) -> dict:
        if name == "screenshot_read":
            return screen_tool.screenshot_read()
        if name == "mouse_click":
            return screen_tool.mouse_click(
                args.get("x", 0), args.get("y", 0), args.get("button", "left")
            )
        if name == "keyboard_type":
            return screen_tool.keyboard_type(args.get("text", ""))
        if name == "keyboard_key":
            return screen_tool.keyboard_key(args.get("key", ""))
        if name == "mouse_scroll":
            return screen_tool.mouse_scroll(
                args.get("direction", "down"),
                args.get("amount", 3),
                args.get("x"),
                args.get("y"),
            )
        if name == "get_windows":
            return screen_tool.get_windows()
        if name == "focus_window":
            return screen_tool.focus_window(args.get("title", ""))
        if name == "open_app":
            return screen_tool.open_app(args.get("target", ""))
        if name == "report":
            return reporter_tool.report(args.get("message", ""))
        logger.warning(f"ScreenAgentSkill: 알 수 없는 도구 '{name}'")
        return {"ok": False, "data": None, "error": f"알 수 없는 도구: {name}"}
