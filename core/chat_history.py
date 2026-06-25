"""대화 기록을 디스크에 저장해 프로세스 재시작 후에도 복원한다.

ui/server.py가 시작될 때 load_history()로 이전 대화를 _chat_context에
복원하고, 매 채팅 턴이 끝날 때마다 append_turn()으로 누적 저장한다.
clear_history()는 채팅("/clear")과 음성("채팅 목록 지워줘") 양쪽에서 호출되는
공유 동작이라 core/에 둔다(원래 ui/chat_history.py였다가 이 이유로 옮겨짐) —
voice 채널의 ConversationContext 자체는 디스크에 저장되지 않지만, "채팅 목록"이
가리키는 실제 데이터는 이 파일이라 음성 쪽 clear도 결국 여기를 지워야 한다.
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_HISTORY_PATH = Path(__file__).parent.parent / "data" / "chat_history.json"

# ConversationContext의 기본 max_history와 맞춰, 화면에 보여줄 만큼만 보존한다.
_MAX_STORED_TURNS = 20


def load_history() -> list[dict]:
    """저장된 대화 턴 목록을 시간순으로 반환한다. 없으면 빈 리스트."""
    try:
        return json.loads(_HISTORY_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def append_turn(turn: dict) -> None:
    """완료된 대화 턴 1개를 디스크에 누적 저장한다(최근 N개만 유지)."""
    history = load_history()
    history.append(turn)
    history = history[-_MAX_STORED_TURNS:]

    _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")


def clear_history() -> None:
    """저장된 대화 기록을 전부 비운다."""
    _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _HISTORY_PATH.write_text("[]", encoding="utf-8")
