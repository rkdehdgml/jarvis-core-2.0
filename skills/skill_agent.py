"""Claude Code CLI 기반 멀티스텝 에이전트 스킬.

기존: Groq native tool-calling 루프 (search, open_url, save_xlsx 등 수동 도구 체인)
2.0: claude_cli_engine.run_task() 로 완전 위임
     Claude Code 내장 툴(WebSearch, WebFetch, Write)로 동일 기능 수행
     Groq/Ollama 의존성 완전 제거

트리거 예시:
  "인공지능 트렌드 조사해줘"
  "삼성전자 최신 뉴스 찾아서 파일로 저장해줘"
  "파이썬 유용한 라이브러리 10개 수집해줘"
"""
import logging

from core.engines.claude_cli_engine import ClaudeCliEngine
from core.skill_base import Skill, SkillResult
from core.status_events import broadcaster

logger = logging.getLogger(__name__)

_STRONG_TRIGGERS = ["조사해줘", "조사해서", "수집해줘", "수집해서", "에이전트로"]
_MULTI_STEP_ACTIONS = ["찾아서", "검색해서"]
_SAVE_KEYWORDS = ["저장해줘", "엑셀로", "파일로 만들어줘", "파일로 정리"]


class AgentSkill(Skill):
    """웹 조사·수집·파일 저장 등 멀티스텝 작업을 Claude Code CLI 에이전트가 수행한다."""

    name = "agent"
    description = "웹 조사·수집·파일 저장 등 멀티스텝 작업을 Claude Code CLI 에이전트가 수행한다"
    triggers = ["조사", "수집", "에이전트"]
    examples = [
        "인공지능 트렌드 조사해줘",
        "삼성전자 최신 뉴스 찾아서 파일로 저장해줘",
        "파이썬 유용한 라이브러리 10개 수집해줘",
    ]

    def __init__(self) -> None:
        self._engine = ClaudeCliEngine(timeout=300)

    def can_handle(self, intent: str, text: str) -> float:
        if any(t in text for t in _STRONG_TRIGGERS):
            return 0.9
        if any(a in text for a in _MULTI_STEP_ACTIONS) and any(s in text for s in _SAVE_KEYWORDS):
            return 0.9
        return 0.0

    def execute(self, text: str, context: dict) -> SkillResult:
        tts_callback = None
        try:
            from voice import tts as _tts
            tts_callback = _tts.speak
        except Exception:
            pass

        broadcaster.emit(state="streaming")
        result = self._engine.run_task(text, on_chunk=tts_callback)
        return SkillResult(speech=result, success=True, data={"task": text})
