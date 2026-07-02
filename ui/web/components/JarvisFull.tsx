import { useEffect, useRef, useState } from "react";

import { useJarvisStatus, type JarvisState } from "../hooks/useJarvisStatus";
import { useMicLevels } from "../hooks/useMicLevels";
import { ChatInput } from "./ChatInput";
import { KakaoMap } from "./KakaoMap";
import { NavigationCandidates } from "./NavigationCandidates";
import "./JarvisFull.css";

const CORE_TEXT: Record<JarvisState, { main: string; sub: string }> = {
  idle: { main: "대기 중", sub: "STANDBY" },
  listening: { main: "듣고 있습니다", sub: "LISTENING" },
  processing: { main: "처리 중...", sub: "PROCESSING" },
  streaming: { main: "작업 진행 중...", sub: "STREAMING" },
  responded: { main: "응답 완료", sub: "DONE" },
  navigation_request: { main: "경로 검색 중", sub: "NAVIGATING" },
  poi_request: { main: "주변 검색 중", sub: "POI SEARCH" },
};

const WAVE_BAR_COUNT = 24;

function formatClock(date: Date): string {
  return date.toLocaleTimeString("ko-KR", { hour12: false });
}

function useClock(): string {
  const [now, setNow] = useState(() => formatClock(new Date()));

  useEffect(() => {
    const id = setInterval(() => setNow(formatClock(new Date())), 1000);
    return () => clearInterval(id);
  }, []);

  return now;
}

/**
 * 메인 HUD 화면. useJarvisStatus() 가 반환하는 데이터를 레이아웃에 배치만 한다.
 * 본체/상태 로직은 전혀 갖지 않는다.
 */
export function JarvisFull() {
  const status = useJarvisStatus();
  const clock = useClock();
  const micLevels = useMicLevels(status.currentState === "listening", WAVE_BAR_COUNT);
  const logRef = useRef<HTMLDivElement>(null);
  const { clearNavigation, clearPoi, clearPoiLayer, selectCandidate } = status;

  const coreText = CORE_TEXT[status.currentState];

  // 채팅/음성 어느 쪽이든 새 발화나 응답이 conversationLog에 추가되면 그쪽으로 포커스(스크롤) 이동.
  useEffect(() => {
    const el = logRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [status.conversationLog]);

  return (
    <div className="jarvis-full">
      <div className="jarvis-full__topbar">
        <span>J.A.R.V.I.S — FULL MODE</span>
        <span>{clock}</span>
      </div>

      <div className="jarvis-full__grid">
        <div className="jarvis-full__panel">
          <div className="jarvis-full__panel-row">
            <span>엔진</span>
            <span>{status.engineInfo.connected ? status.engineInfo.provider : "연결 끊김"}</span>
          </div>
          <div className="jarvis-full__panel-model">{status.engineInfo.model}</div>
          <div className="jarvis-full__panel-row">
            <span>사용량</span>
            <span>{status.usageToday !== null ? `${status.usageToday}%` : "—"}</span>
          </div>
          <div className="jarvis-full__gauge">
            <div
              className="jarvis-full__gauge-fill"
              style={{ width: `${status.usageToday ?? 0}%` }}
            />
          </div>
          <div className="jarvis-full__panel-row">
            <span>활성 스킬</span>
            <span>{status.activeSkills.length}개</span>
          </div>
        </div>

        <div className="jarvis-full__core">
          <div className="jarvis-full__rings">
            <div
              className={`jarvis-full__ring jarvis-full__ring--outer jarvis-full__ring--${status.currentState}`}
            />
            <div
              className={`jarvis-full__ring jarvis-full__ring--inner jarvis-full__ring--${status.currentState}`}
            />
            <div className="jarvis-full__core-text">
              <div className="jarvis-full__core-main">{coreText.main}</div>
              <div className="jarvis-full__core-sub">{coreText.sub}</div>
            </div>
          </div>
        </div>

        <div className="jarvis-full__panel">
          <div className="jarvis-full__panel-row">
            <span>CPU</span>
            <span>
              {status.systemInfo ? `${status.systemInfo.cpuPercent.toFixed(0)}%` : "—"}
            </span>
          </div>
          <div className="jarvis-full__panel-row">
            <span>메모리</span>
            <span>
              {status.systemInfo ? `${status.systemInfo.memoryPercent.toFixed(0)}%` : "—"}
            </span>
          </div>
        </div>
      </div>

      <div className="jarvis-full__chat-area">
        <div className="jarvis-full__chat-col">
          {status.currentState === "listening" && (
            <div className="jarvis-full__waveform">
              {Array.from({ length: WAVE_BAR_COUNT }, (_, i) => {
                const level = micLevels[i];
                if (level !== undefined) {
                  return (
                    <div
                      key={i}
                      className="jarvis-full__wave-bar"
                      style={{ height: `${Math.max(10, level * 100)}%`, animation: "none" }}
                    />
                  );
                }
                return (
                  <div
                    key={i}
                    className="jarvis-full__wave-bar jarvis-full__wave-bar--listening"
                    style={{ animationDelay: `${i * 0.05}s` }}
                  />
                );
              })}
            </div>
          )}

          <div className="jarvis-full__log" ref={logRef}>
            {status.conversationLog.map((turn, index) => (
              <div
                key={`${turn.timestamp}-${turn.role}-${index}`}
                className={`jarvis-full__bubble jarvis-full__bubble--${
                  turn.role === "user" ? "user" : "jarvis"
                }`}
              >
                {turn.text}
              </div>
            ))}
            {status.navigationCandidates && (
              <NavigationCandidates
                candidates={status.navigationCandidates}
                onSelect={selectCandidate}
                onCancel={clearNavigation}
              />
            )}
          </div>

          <ChatInput onSend={status.sendMessage} />
        </div>
      </div>

      {/* position:fixed — 레이아웃 흐름 밖에서 플로팅 */}
      {status.navigationData && status.kakaoJsKey && (
        <KakaoMap
          key={`${status.navigationData.destination.lat},${status.navigationData.destination.lng}-${status.navigationData.routeType}`}
          data={status.navigationData}
          jsKey={status.kakaoJsKey}
          poiResults={status.poiResults}
          onClose={clearNavigation}
          onClearPoi={clearPoi}
          onClearPoiLayer={clearPoiLayer}
        />
      )}
    </div>
  );
}
