"""Claude Code CLI 기반 통합 엔진 (jarvis-core 2.0).

두 가지 실행 모드:
  ask() / generate()
    → claude -p <prompt> --output-format json --allowedTools WebSearch WebFetch
    → 날씨·웹검색·농담·AI 대화 등 단순 Q&A에 사용 (안전 모드)

  run_task()
    → claude -p <prompt> --dangerously-skip-permissions --output-format stream-json
    → computer_use·Bash·Edit·Write 전체 툴 해제
    → 화면 제어·멀티스텝 에이전트 작업에 사용 (풀파워 모드)

기존 ClaudeCodeEngine(claude_code.py)을 대체한다.
Groq·Ollama 의존성을 완전히 제거하고 Claude Code CLI 단일 엔진으로 통합.
"""
import json
import logging
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable

from core import usage

logger = logging.getLogger(__name__)

_PERSONA_PATH = Path(__file__).parent.parent.parent / "config" / "persona.md"

_DEFAULT_TIMEOUT = 120   # ask / generate 최대 대기 (초)
_TASK_TIMEOUT    = 600   # run_task computer_use / 에이전트 최대 대기 (초)

_ENV_WHITELIST = [
    "PATH", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
    "TEMP", "TMP", "SYSTEMROOT", "ANTHROPIC_API_KEY",
]

_SAFE_TOOLS = ["WebSearch", "WebFetch"]

# decide()(화면 제어 단일 행동 판단)는 "다음 행동 1개 고르기" 수준의 판단이라
# 최상위 모델이 필요 없다 - 프로파일링 결과 스텝당 평균 17.4초 중 87%가 이
# 호출 하나에 쓰이고 있어 속도 우선으로 가벼운 모델을 지정한다.
_DECIDE_MODEL = "haiku"


class _SentenceBuffer:
    """텍스트 청크를 모았다가 문장 종결부호를 만나면 on_chunk로 흘려보낸다.

    stream-json의 assistant 텍스트 블록이 문장 중간에서 쪼개져 오면 TTS가
    어색하게 끊기는 문제를 막기 위함 — 종결부호를 볼 때까지 누적한다.
    """

    _SENTENCE_END = (".", "!", "?", "。", "\n")

    def __init__(self, on_chunk: Callable[[str], None] | None) -> None:
        self._on_chunk = on_chunk
        self._buf = ""

    def feed(self, chunk: str) -> None:
        self._buf += chunk
        if self._on_chunk and self._buf.rstrip().endswith(self._SENTENCE_END):
            sentence = self._buf.strip()
            if sentence:
                self._on_chunk(sentence)
            self._buf = ""

    def flush(self) -> None:
        if self._on_chunk and self._buf.strip():
            self._on_chunk(self._buf.strip())
        self._buf = ""


class ClaudeCliEngine:
    """Claude Code CLI를 두 가지 모드로 구동하는 통합 엔진."""

    def __init__(self, timeout: int = _DEFAULT_TIMEOUT) -> None:
        self._timeout = timeout
        self._persona = self._load_persona()

    # ── 안전 모드: Q&A / 텍스트 생성 ─────────────────────────────────────────

    def ask(self, text: str) -> str:
        """사용자 입력을 Claude Code CLI에 전달해 응답을 받는다 (웹검색만 허용)."""
        result, _ = self._run_safe(self._build_prompt(text))
        return result

    def generate(self, prompt: str, system: str | None = None) -> str:
        """persona.md에 system을 덧붙여 Claude Code CLI를 호출한다.

        system은 persona.md를 대체하지 않고 보강한다.
        날씨·웹검색 스킬처럼 검색 결과를 컨텍스트로 주입할 때 사용.
        """
        if system and self._persona:
            full_prompt = f"{self._persona}\n\n{system}\n\n---\n\n사용자: {prompt}"
        elif system:
            full_prompt = f"{system}\n\n---\n\n사용자: {prompt}"
        else:
            full_prompt = self._build_prompt(prompt)
        result, _ = self._run_safe(full_prompt)
        return result

    def decide(self, prompt: str, session_id: str | None = None) -> tuple[str, str | None]:
        """읽기 전용 판단 모드: Read 툴만 허용해 화면 상태(이미지)를 보고 답하게 한다.

        화면 제어 실행 루프(core/hybrid_screen.py)에서 사용 — Claude는 "다음에 할
        행동 1개"만 텍스트(JSON)로 결정하고, 실제 클릭·입력 실행은 호출자(Python)가
        담당한다. Bash·Edit·Write가 필요 없으므로 --dangerously-skip-permissions
        없이도 동작해 run_task()보다 안전하다. 속도 우선으로 _DECIDE_MODEL(haiku)을
        사용한다 - "다음 행동 1개 고르기"는 최상위 모델까지 필요하지 않은 판단.

        session_id를 주면 --resume으로 기존 대화를 이어간다 - CLAUDE.md/시스템
        프롬프트를 매 스텝 새로 로드하지 않아 훨씬 빠르다 (WhisperFlow의
        assistant_session.py에서 확인한 --resume 세션 재사용 패턴). 반환값의
        session_id를 다음 호출에 그대로 넘기면 같은 화면 제어 태스크 동안 세션이
        유지된다. 실패 시 session_id는 None으로 반환되어 다음 호출은 새 세션으로
        자연스럽게 폴백한다.

        Returns:
            (응답 텍스트, 다음 호출에 넘길 session_id 또는 None)
        """
        return self._run_safe(prompt, tools=["Read"], model=_DECIDE_MODEL, session_id=session_id)

    def _run_safe(
        self,
        prompt: str,
        tools: list[str] | None = None,
        model: str | None = None,
        session_id: str | None = None,
    ) -> tuple[str, str | None]:
        cmd = [
            "claude", "-p", prompt,
            "--output-format", "json",
            "--allowedTools", *(tools or _SAFE_TOOLS),
        ]
        if model:
            cmd += ["--model", model]
        if session_id:
            cmd += ["--resume", session_id]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout,
                env=self._build_env(),
            )
        except subprocess.TimeoutExpired:
            logger.error(f"Claude CLI 타임아웃 ({self._timeout}초)")
            return "응답이 너무 오래 걸려 처리하지 못했습니다.", None
        except FileNotFoundError:
            logger.error("claude 명령을 찾을 수 없습니다. PATH를 확인하세요.")
            return "Claude Code CLI를 찾을 수 없습니다. 설치 여부와 PATH를 확인해주세요.", None
        except Exception as e:
            logger.error(f"Claude CLI 호출 오류: {e}")
            return f"AI 응답 처리 중 오류가 발생했습니다: {e}", None

        if result.returncode != 0:
            logger.error(f"claude 비정상 종료 (code={result.returncode}): {result.stderr[:300]}")
            return "AI 응답을 받지 못했습니다.", None

        return self._parse_json_result(result.stdout)

    # ── 풀파워 모드: computer_use / 에이전트 ─────────────────────────────────

    def run_task(
        self,
        task: str,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        """--dangerously-skip-permissions으로 모든 툴을 해제하고 태스크를 실행한다.

        computer_use, Bash, Edit, Write 등 Claude Code 전체 툴이 활성화된다.
        화면 캡처 → Claude Vision 인식 → 마우스/키보드 제어가 자동으로 이루어진다.

        Args:
            task: 실행할 태스크 설명 (자연어).
            on_chunk: 스트리밍 텍스트 청크를 실시간으로 받을 콜백.
                      진행 상황을 TTS로 알리거나 UI에 표시할 때 사용.

        Returns:
            최종 응답 텍스트. 스트리밍 완료 후 result 이벤트에서 추출.
        """
        prompt = self._build_prompt(task)
        try:
            proc = subprocess.Popen(
                [
                    "claude", "-p", prompt,
                    "--dangerously-skip-permissions",
                    "--output-format", "stream-json",
                    "--verbose",  # CLI가 --output-format=stream-json에 필수로 요구
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=self._build_env(),
            )
        except FileNotFoundError:
            return "Claude Code CLI를 찾을 수 없습니다. 설치 여부와 PATH를 확인해주세요."
        except Exception as e:
            logger.error(f"Claude CLI Popen 오류: {e}")
            return f"Claude CLI 실행 오류: {e}"

        # stderr를 별도 스레드로 계속 비워준다 - 안 그러면 파이프가 가득 찼을 때
        # 자식 프로세스가 write()에서 멈춰버리고(stdout 쪽만 읽는 메인 루프와 교착),
        # 에러 메시지도 읽지 못한 채 조용히 사라진다.
        stderr_lines: list[str] = []

        def _drain_stderr() -> None:
            assert proc.stderr
            for line in proc.stderr:
                stderr_lines.append(line)

        stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
        stderr_thread.start()

        collected: list[str] = []
        sentence_buffer = _SentenceBuffer(on_chunk)
        try:
            assert proc.stdout
            for raw_line in proc.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event_type = obj.get("type", "")

                if event_type == "assistant":
                    for block in obj.get("message", {}).get("content", []):
                        if isinstance(block, dict) and block.get("type") == "text":
                            chunk = block["text"]
                            collected.append(chunk)
                            sentence_buffer.feed(chunk)

                elif event_type == "result":
                    cost = obj.get("total_cost_usd")
                    if isinstance(cost, (int, float)):
                        usage.record_cost(cost)
                    final = str(obj.get("result", "")).strip()
                    if final:
                        return final

        except Exception as e:
            logger.error(f"stream-json 파싱 오류: {e}")
        finally:
            try:
                proc.wait(timeout=_TASK_TIMEOUT)
            except subprocess.TimeoutExpired:
                logger.error("run_task 타임아웃 — 프로세스 강제 종료")
                proc.kill()
            stderr_thread.join(timeout=2)
            sentence_buffer.flush()

        result = "".join(collected).strip()
        if result:
            return result

        if proc.returncode:
            err = "".join(stderr_lines).strip()[:300]
            logger.error(f"claude 비정상 종료 (code={proc.returncode}): {err}")
            return f"작업 실행 중 오류가 발생했습니다: {err}" if err else "작업 실행에 실패했습니다."

        return "작업을 완료했습니다."

    # ── 공통 유틸 ─────────────────────────────────────────────────────────────

    def _build_prompt(self, text: str) -> str:
        if self._persona:
            return f"{self._persona}\n\n---\n\n사용자: {text}"
        return text

    def _build_env(self) -> dict:
        return {k: v for k, v in os.environ.items() if k in _ENV_WHITELIST}

    def _parse_json_result(self, stdout: str) -> tuple[str, str | None]:
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            logger.warning("JSON 파싱 실패, 원문 반환")
            return stdout.strip(), None
        cost = data.get("total_cost_usd")
        if isinstance(cost, (int, float)):
            usage.record_cost(cost)
        session_id = data.get("session_id")
        return (
            str(data.get("result", "")).strip(),
            session_id if isinstance(session_id, str) else None,
        )

    def _load_persona(self) -> str:
        try:
            return _PERSONA_PATH.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            logger.warning(f"persona.md를 찾을 수 없습니다: {_PERSONA_PATH}")
            return ""

    def describe(self) -> dict:
        """UI 엔진 패널에 보여줄 식별 정보."""
        return {
            "provider": "Claude Code",
            "model": "Claude Code CLI",
            "connected": shutil.which("claude") is not None,
            "usagePercent": usage.get_today_percent(),
        }
