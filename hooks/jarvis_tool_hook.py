"""PreToolUse / PostToolUse 훅 — Claude Code 툴 사용 내역을 JARVIS UI에 시각화한다.

.claude/settings.json 에 등록 예시:
  "hooks": {
    "PostToolUse": [{"matcher": ".*", "hooks": [{"type": "command",
        "command": "python hooks/jarvis_tool_hook.py"}]}]
  }

stdin: Claude Code가 주는 JSON {"tool_name": ..., "tool_input": ..., "tool_response": ...}
stdout/stderr 출력은 무시됨 (훅 실패가 Claude 실행에 영향 없도록).
"""
import json
import subprocess
import sys
from pathlib import Path

HOOK_DIR = Path(__file__).parent

_LABEL = {
    "computer_use": "화면 제어",
    "Edit":         "파일 수정",
    "Write":        "파일 작성",
    "Read":         "파일 읽기",
    "Bash":         "명령 실행",
    "Grep":         "텍스트 검색",
    "Glob":         "파일 스캔",
    "WebSearch":    "웹 검색",
    "WebFetch":     "페이지 로드",
}


def build_label(data: dict) -> str:
    name = data.get("tool_name", "")
    inp  = data.get("tool_input", {})
    base = _LABEL.get(name, name)

    if name == "computer_use":
        action = inp.get("action", "")
        return f"화면 제어: {action}" if action else base

    if name in ("Edit", "Write", "Read"):
        path = inp.get("file_path", inp.get("path", ""))
        return f"{base}: {Path(path).name}" if path else base

    if name == "Bash":
        cmd = str(inp.get("command", ""))[:60]
        return f"명령 실행: {cmd}" if cmd else base

    if name == "WebSearch":
        q = str(inp.get("query", ""))[:50]
        return f"웹 검색: {q}" if q else base

    return f"{base} 중"


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    label = build_label(data)
    send_script = HOOK_DIR / "jarvis_send.py"
    if send_script.exists():
        subprocess.Popen(
            [sys.executable, str(send_script), "tool_action", label],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


if __name__ == "__main__":
    main()
