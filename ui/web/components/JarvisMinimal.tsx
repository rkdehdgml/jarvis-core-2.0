import { useEffect, useRef, useState } from "react";

import { useJarvisStatus } from "../hooks/useJarvisStatus";
import "./JarvisMinimal.css";

const STATE_LABEL: Record<string, string> = {
  idle: "대기 중",
  listening: "듣고 있습니다",
  processing: "처리 중...",
  streaming: "작업 진행 중...",
};

function statusText(currentState: string, lastResponse: string | null): string {
  if (currentState === "responded") {
    return lastResponse ?? "대기 중";
  }
  return STATE_LABEL[currentState] ?? "대기 중";
}

/**
 * 화면 귀퉁이에 항상 떠 있는 미니멀 모드 패널.
 * 클릭하면 펼쳐져 엔진 상태/스킬 목록/최근 대화를 보여준다.
 * 펼침 여부는 순수 로컬 state이며 본체와는 무관하다.
 */
export function JarvisMinimal() {
  const [expanded, setExpanded] = useState(false);
  const [mode, setMode] = useState<"voice" | "chat">("chat");
  const status = useJarvisStatus();
  const panelRef = useRef<HTMLDivElement>(null);

  const recentLog = status.conversationLog.slice(-5);

  // 패널이 펼쳐진 상태에서 새 발화/응답이 추가되면 그쪽으로 스크롤 이동.
  useEffect(() => {
    const el = panelRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [status.conversationLog, expanded]);

  return (
    <div className="jarvis-minimal" onClick={() => setExpanded((v) => !v)}>
      <div className="jarvis-minimal__header">
        <div className="jarvis-minimal__core">
          <div className={`jarvis-minimal__ring jarvis-minimal__ring--${status.currentState}`} />
          <div className="jarvis-minimal__dot" />
        </div>
        <div className="jarvis-minimal__status">
          {statusText(status.currentState, status.lastResponse)}
        </div>
        <button
          type="button"
          className="jarvis-minimal__mode-toggle"
          title={mode === "chat" ? "채팅 모드 (클릭하면 음성 모드로)" : "음성 모드 (클릭하면 채팅 모드로)"}
          onClick={(e) => {
            e.stopPropagation();
            setMode((m) => (m === "chat" ? "voice" : "chat"));
          }}
        >
          {mode === "chat" ? "⌨" : "🎙"}
        </button>
      </div>

      {expanded && (
        <div className="jarvis-minimal__panel" ref={panelRef} onClick={(e) => e.stopPropagation()}>
          <div className="jarvis-minimal__row">
            <span>엔진</span>
            <span>
              {status.engineInfo.connected ? status.engineInfo.provider : "연결 끊김"}
            </span>
          </div>

          <div className="jarvis-minimal__row">
            <span>활성 스킬</span>
            <span>{status.activeSkills.length}개</span>
          </div>
          <div className="jarvis-minimal__skills">
            {status.activeSkills.map((name) => (
              <span key={name} className="jarvis-minimal__skill-tag">
                {name}
              </span>
            ))}
          </div>

          <div className="jarvis-minimal__row">
            <span>최근 대화</span>
            <span></span>
          </div>
          {recentLog.length === 0 && (
            <div className="jarvis-minimal__log-item">대화 기록이 없습니다.</div>
          )}
          {recentLog.map((turn, index) => (
            <div
              key={`${turn.timestamp}-${turn.role}-${index}`}
              className={`jarvis-minimal__log-item${
                turn.role === "jarvis" ? " jarvis-minimal__log-item--jarvis" : ""
              }`}
            >
              {turn.role === "jarvis" ? "자비스: " : "나: "}
              {turn.text}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
