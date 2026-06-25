"""Groq Python SDK(llama-3.3-70b-versatile)를 호출하는 AI 폴백 엔진.

claude_code.py(ClaudeCodeEngine)를 대체하는 교체 후보. skill_ai_chat.py의 호출부가
`self._engine.ask(text)` 하나뿐이므로, 같은 ask(text:str)->str 인터페이스를 따라
import 한 줄만 바꿔 끼울 수 있게 맞췄다.

ask()는 persona.md를 시스템 프롬프트로 고정해서 쓰고, generate()는 system을 직접
지정할 수 있다(skill_web_search.py가 검색 결과를 컨텍스트로 주입할 때 사용).
둘 다 내부적으로 _complete()를 공유한다.

API 키는 .env 파일의 GROQ_API_KEY를 python-dotenv로 읽는다. 절대 코드에
하드코딩하지 않는다.
"""
import logging
import os
import re
from pathlib import Path

import yaml
from dotenv import load_dotenv
from groq import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    Groq,
    RateLimitError,
)

from core import groq_usage

load_dotenv()

logger = logging.getLogger(__name__)

_PERSONA_PATH = Path(__file__).parent.parent.parent / "config" / "persona.md"
_SETTINGS_PATH = Path(__file__).parent.parent.parent / "config" / "settings.yaml"

_DEFAULT_MODEL = "llama-3.3-70b-versatile"
_DEFAULT_MAX_TOKENS = 1024
_DEFAULT_TEMPERATURE = 0.7
_DEFAULT_TIMEOUT = 30

# 한국어 응답에 절대 나오면 안 되는 문자 — 한자(CJK 통합 한자 U+4E00~U+9FFF,
# 확장 A U+3400~U+4DBF), 히라가나(U+3040~U+309F), 가타카나(U+30A0~U+30FF).
# persona.md의 "한국어로만" 지시문만으론 막히지 않는 경우가 실제로 있어서
# (예: "더詳細한 정보"처럼 한자가 한 글자만 섞이는 경우) 코드로 한 번 더 검증한다.
_FOREIGN_SCRIPT = re.compile("[一-鿿㐀-䶿぀-ゟ゠-ヿ]")
_MAX_ATTEMPTS = 3  # 1회 시도 + 최대 2회 재시도


def _load_groq_settings() -> dict:
    """config/settings.yaml의 groq 섹션을 읽는다. 없거나 깨졌으면 빈 dict."""
    try:
        with _SETTINGS_PATH.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("groq") or {}
    except (FileNotFoundError, yaml.YAMLError) as e:
        logger.warning(f"settings.yaml의 groq 섹션을 읽지 못해 기본값을 사용합니다: {e}")
        return {}


class GroqEngine:
    """jarvis-core의 AI 폴백 엔진(Groq 버전). 키워드 스킬이 못 잡은 입력을 받아 응답한다."""

    def __init__(self) -> None:
        settings = _load_groq_settings()
        self._model = settings.get("model", _DEFAULT_MODEL)
        self._max_tokens = settings.get("max_tokens", _DEFAULT_MAX_TOKENS)
        self._temperature = settings.get("temperature", _DEFAULT_TEMPERATURE)
        self._timeout = settings.get("timeout", _DEFAULT_TIMEOUT)
        self._persona = self._load_persona()
        # API 키 체크는 ask() 호출 시점까지 미룬다(lazy) — 레지스트리가 스킬을
        # 로딩하는 시점에 .env가 비어 있어도 여기서 죽지 않게 하기 위함.
        self._client: Groq | None = None

    def ask(self, text: str) -> str:
        """사용자 입력을 Groq API에 전달해 응답 텍스트를 받는다(시스템 프롬프트=persona.md).

        Args:
            text: 사용자 원문 입력.

        Returns:
            모델의 응답 텍스트. 호출 실패/타임아웃 시 사용자에게 보여줄 수 있는
            안전한 한국어 에러 메시지를 반환한다(예외를 던지지 않음).
        """
        return self._complete(text, system=self._persona)

    def generate(self, prompt: str, system: str | None = None) -> str:
        """persona.md에 system(있으면)을 덧붙여 Groq API를 호출한다.

        system은 persona.md를 "대체"하지 않고 "보강"한다 — persona.md의 "한국어로
        응답합니다" 같은 기본 제약이 검색 결과/날씨 데이터처럼 영어가 섞인 컨텍스트를
        프롬프트에 넣을 때도 항상 함께 적용되도록 하기 위함(이게 빠지면 Llama가
        영어/일본어 단어를 섞어 응답하는 경우가 실제로 있었다).

        Args:
            prompt: 사용자 메시지로 보낼 텍스트.
            system: persona.md에 덧붙일 추가 지시문. None이면 persona.md만 쓴다(ask()와 동일).

        Returns:
            ask()와 동일한 규약 — 실패 시에도 예외 대신 한국어 에러 메시지를 반환한다.
        """
        if system and self._persona:
            combined_system = f"{self._persona}\n\n{system}"
        else:
            combined_system = system or self._persona
        return self._complete(prompt, system=combined_system)

    def _complete(self, text: str, system: str) -> str:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            logger.error("GROQ_API_KEY가 설정되지 않았습니다.")
            return (
                "GROQ API 키가 설정되지 않았습니다. "
                "프로젝트 루트의 .env 파일에 GROQ_API_KEY=gsk_... 를 추가해주세요."
            )

        if self._client is None:
            self._client = Groq(api_key=api_key)

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": text})

        content = ""
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    max_tokens=self._max_tokens,
                    temperature=self._temperature,
                    timeout=self._timeout,
                )
            except AuthenticationError as e:
                logger.error(f"Groq 인증 오류: {e}")
                return "Groq API 키가 유효하지 않습니다. .env 파일의 GROQ_API_KEY 값을 확인해주세요."
            except RateLimitError as e:
                logger.error(f"Groq 요청 한도 초과: {e}")
                return "Groq API 요청 한도를 초과했습니다. 잠시 후 다시 시도해주세요."
            except APITimeoutError as e:
                # APITimeoutError는 APIConnectionError의 하위 클래스라 반드시 그보다 먼저 잡아야 한다.
                logger.error(f"Groq 응답 타임아웃: {e}")
                return "Groq API 응답 시간이 초과됐습니다."
            except APIConnectionError as e:
                logger.error(f"Groq 연결 오류: {e}")
                return "Groq 서버에 연결할 수 없습니다. 네트워크 상태를 확인해주세요."
            except Exception as e:
                logger.error(f"Groq 엔진 오류: {e}")
                return f"Groq 엔진 오류: {e}"

            if response.usage:
                # 재시도도 실제 API 호출이라 토큰을 소비하므로, 시도마다 기록한다.
                groq_usage.record_tokens(response.usage.total_tokens)

            content = response.choices[0].message.content or ""
            if not _FOREIGN_SCRIPT.search(content):
                break
            logger.warning(
                f"응답에 한자/가나가 섞여 재시도합니다 ({attempt}/{_MAX_ATTEMPTS}): {content!r}"
            )

        if not content:
            logger.warning("Groq 응답이 비어 있습니다.")
            return "응답이 비어 있습니다."

        if _FOREIGN_SCRIPT.search(content):
            # 재시도로도 안 지워지면 마지막 수단으로 해당 문자만 제거한다(문장이 약간
            # 어색해질 수 있지만, 한자/가나가 그대로 노출되는 것보다는 낫다).
            logger.warning(f"재시도 후에도 한자/가나가 남아 해당 문자를 제거합니다: {content!r}")
            content = _FOREIGN_SCRIPT.sub("", content)
            content = re.sub(r"\s+", " ", content)

        return content.strip()

    def describe(self) -> dict:
        """UI(엔진/사용량 패널)에 보여줄 엔진 식별 정보.

        claude_code.py의 ClaudeCodeEngine도 같은 모양의 describe()를 구현한다 —
        ui/server.py는 skill_ai_chat.py가 실제로 어느 엔진을 import했는지 몰라도
        되고, 그냥 활성 엔진의 describe()를 그대로 중계한다.
        """
        return {
            "provider": "Groq",
            "model": self._model,
            "connected": bool(os.getenv("GROQ_API_KEY")),
            "usagePercent": groq_usage.get_today_percent(),
        }

    def _load_persona(self) -> str:
        try:
            return _PERSONA_PATH.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            logger.warning(f"persona.md 를 찾을 수 없습니다: {_PERSONA_PATH}")
            return ""
