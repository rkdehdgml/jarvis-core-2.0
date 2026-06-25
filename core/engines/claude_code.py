import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

from core import usage

logger = logging.getLogger(__name__)

_PERSONA_PATH = Path(__file__).parent.parent.parent / "config" / "persona.md"
# 헤드리스(-p) 호출은 웹검색이 끼면 평소보다 오래 걸려서 기본 타임아웃을 늘렸다.
_DEFAULT_TIMEOUT = 120

# Claude Code CLI 실행에 필요한 환경변수만 화이트리스트로 전달
_ENV_WHITELIST = [
    "PATH",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "TEMP",
    "TMP",
    "SYSTEMROOT",
    "ANTHROPIC_API_KEY",
]

# 헤드리스(-p) 모드는 터미널이 없어 권한 프롬프트를 띄울 수 없고, 사전 승인 안 된
# 도구는 전부 자동 거부된다(예: 날씨 질문에 WebSearch를 쓰려다 거부당하는 경우).
# 날씨/실시간 정보 조회에 필요한 웹검색만 명시적으로 허용하고, Bash/Edit/Write 등
# 위험할 수 있는 도구는 그대로 차단 상태로 둔다.
_ALLOWED_TOOLS = ["WebSearch", "WebFetch"]


class ClaudeCodeEngine:
    """Claude Code CLI를 headless(`-p`) 모드로 호출하는 AI 폴백 엔진.

    jarvis-core의 유일한 AI 엔진. 키워드 스킬이 아무도 못 잡은
    입력을 이 엔진에게 넘겨 자연어로 응답을 생성한다.
    """

    def __init__(self, timeout: int = _DEFAULT_TIMEOUT) -> None:
        self._timeout = timeout
        self._persona = self._load_persona()

    def ask(self, text: str) -> str:
        """사용자 입력을 Claude Code CLI에 전달해 응답 텍스트를 받는다.

        Args:
            text: 사용자 원문 입력.

        Returns:
            Claude의 응답 텍스트. 호출 실패/타임아웃 시 사용자에게
            보여줄 수 있는 안전한 에러 메시지를 반환한다(예외를 던지지 않음).
        """
        prompt = self._build_prompt(text)

        try:
            result = subprocess.run(
                [
                    "claude",
                    "-p",
                    prompt,
                    "--output-format",
                    "json",
                    "--allowedTools",
                    *_ALLOWED_TOOLS,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout,
                env=self._build_env(),
            )
        except subprocess.TimeoutExpired:
            logger.error(f"Claude Code 호출 타임아웃 ({self._timeout}초)")
            return "응답이 너무 오래 걸려 처리하지 못했습니다."
        except FileNotFoundError:
            logger.error("claude 명령을 찾을 수 없습니다. PATH 설정을 확인하세요.")
            return "AI 엔진을 찾을 수 없습니다."
        except Exception as e:
            logger.error(f"Claude Code 호출 오류: {e}")
            return "AI 응답 처리 중 오류가 발생했습니다."

        if result.returncode != 0:
            logger.error(f"Claude Code 비정상 종료 (code={result.returncode}): {result.stderr}")
            return "AI 응답을 받지 못했습니다."

        response = self._extract_response(result.stdout)
        if not response:
            logger.warning("Claude Code 응답이 비어 있습니다.")
            return "응답이 비어 있습니다."

        return response

    def _extract_response(self, stdout: str) -> str:
        """--output-format json 결과에서 응답 텍스트를 꺼내고, 호출 비용을 기록한다.

        JSON 파싱에 실패하면(예: CLI 버전 차이) 원문을 그대로 응답으로 쓴다.
        """
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            logger.warning("Claude Code JSON 응답 파싱 실패, 원문을 그대로 사용합니다.")
            return stdout.strip()

        cost_usd = data.get("total_cost_usd")
        if isinstance(cost_usd, (int, float)):
            usage.record_cost(cost_usd)

        return str(data.get("result", "")).strip()

    def _build_prompt(self, text: str) -> str:
        if self._persona:
            return f"{self._persona}\n\n---\n\n사용자: {text}"
        return text

    def _build_env(self) -> dict:
        return {k: v for k, v in os.environ.items() if k in _ENV_WHITELIST}

    def describe(self) -> dict:
        """UI(엔진/사용량 패널)에 보여줄 엔진 식별 정보. GroqEngine.describe()와 짝을 이룬다.

        claude -p는 --model을 지정하지 않으므로 실제 모델은 CLI 쪽 기본 설정에
        따라 달라진다 — 그래서 model 필드는 구체적인 모델명이 아니라 "Claude Code
        CLI"로 둔다.
        """
        return {
            "provider": "Claude Code",
            "model": "Claude Code CLI",
            "connected": shutil.which("claude") is not None,
            "usagePercent": usage.get_today_percent(),
        }

    def _load_persona(self) -> str:
        try:
            return _PERSONA_PATH.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            logger.warning(f"persona.md 를 찾을 수 없습니다: {_PERSONA_PATH}")
            return ""
