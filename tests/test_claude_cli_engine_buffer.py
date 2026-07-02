"""ClaudeCliEngine._SentenceBuffer 문장 버퍼링 검증 (plain assert 스크립트).

실행: python -m tests.test_claude_cli_engine_buffer  (프로젝트 루트에서)
"""
from core.engines.claude_cli_engine import _SentenceBuffer


def main() -> None:
    received: list[str] = []
    buf = _SentenceBuffer(received.append)

    # 문장이 여러 청크로 쪼개져 들어와도 종결부호를 만나기 전까지는 호출되지 않는다.
    buf.feed("안녕")
    buf.feed("하세요")
    assert received == [], f"종결부호 전에는 호출되면 안 됨: {received}"

    buf.feed(".")
    assert received == ["안녕하세요."], f"문장 종결 시 1회 호출돼야 함: {received}"

    # 다음 문장 조각들도 동일하게 동작
    buf.feed(" 반갑")
    buf.feed("습니다!")
    assert received == ["안녕하세요.", "반갑습니다!"], received

    # 잔여 버퍼는 flush()로만 방출된다
    buf.feed("마무리 중")
    assert received == ["안녕하세요.", "반갑습니다!"], "flush 전에는 방출되면 안 됨"
    buf.flush()
    assert received == ["안녕하세요.", "반갑습니다!", "마무리 중"], received

    # flush 이후 버퍼는 비어 있어 다시 flush해도 추가 호출이 없다
    buf.flush()
    assert received == ["안녕하세요.", "반갑습니다!", "마무리 중"], "빈 버퍼 flush는 무동작이어야 함"

    # on_chunk가 None이면 아무 것도 호출하지 않고 조용히 무시
    silent_buf = _SentenceBuffer(None)
    silent_buf.feed("아무 일도 안 일어남.")
    silent_buf.flush()  # 예외 없이 통과하면 성공

    print("\ntest_claude_cli_engine_buffer 검증 통과")


if __name__ == "__main__":
    main()
