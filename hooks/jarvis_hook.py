"""Stop 훅 — Claude 최종 응답을 JARVIS UI WebSocket으로 전송한다.

.claude/settings.json 에 등록 예시:
  "hooks": {
    "Stop": [{"hooks": [{"type": "command",
        "command": "python hooks/jarvis_hook.py"}]}]
  }

stdin: {"result": "<최종 응답 텍스트>", ...}
"""
import json
import subprocess
import sys
from pathlib import Path

HOOK_DIR = Path(__file__).parent


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    response = str(data.get("result", "")).strip()
    if not response:
        return

    send_script = HOOK_DIR / "jarvis_send.py"
    if send_script.exists():
        subprocess.Popen(
            [sys.executable, str(send_script), "output", response[:500]],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


if __name__ == "__main__":
    main()
