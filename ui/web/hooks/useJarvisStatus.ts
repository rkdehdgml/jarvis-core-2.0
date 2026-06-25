import { useCallback, useEffect, useRef, useState } from "react";

export type JarvisState = "idle" | "listening" | "processing" | "responded";

export interface ConversationTurn {
  role: "user" | "jarvis";
  text: string;
  timestamp: number;
}

export interface SystemInfo {
  cpuPercent: number;
  memoryPercent: number;
}

/** 현재 ai_chat 폴백이 쓰는 엔진(Groq 또는 Claude Code) 식별 정보. */
export interface EngineInfo {
  provider: string;
  model: string;
  connected: boolean;
}

export interface JarvisStatus {
  engineInfo: EngineInfo;
  usageToday: number | null;
  activeSkills: string[];
  systemInfo: SystemInfo | null;
  currentState: JarvisState;
  lastResponse: string | null;
  conversationLog: ConversationTurn[];
}

export interface UseJarvisStatusResult extends JarvisStatus {
  /** 채팅 메시지를 보낸다. 사용자 발화를 즉시 로그에 추가하고 /api/chat 으로 전송한다. */
  sendMessage: (text: string) => Promise<void>;
}

interface StatusApiResponse {
  state: JarvisState;
  lastResponse: string | null;
  timestamp: number;
  engineInfo: EngineInfo;
  activeSkills: string[];
  systemInfo: SystemInfo;
  usageToday: number | null;
}

interface WsPushPayload {
  state: JarvisState;
  lastResponse: string | null;
  timestamp: number;
  engineInfo: EngineInfo;
  systemInfo: SystemInfo;
  usageToday: number | null;
}

type HistoryApiResponse = ConversationTurn[];

const API_BASE = "http://127.0.0.1:8765";
const WS_URL = "ws://127.0.0.1:8765/ws";
const RECONNECT_DELAY_MS = 2000;

const initialStatus: JarvisStatus = {
  engineInfo: { provider: "-", model: "-", connected: false },
  usageToday: null,
  activeSkills: [],
  systemInfo: null,
  currentState: "idle",
  lastResponse: null,
  conversationLog: [],
};

/**
 * ui/server.py 의 /ws, /api/status 를 구독하는 공유 상태 훅.
 *
 * JarvisMinimal과 JarvisFull이 동일한 훅을 구독하고, 반환된 데이터를
 * 다르게 배치만 하면 된다. WebSocket 연결이 끊기면 자동으로 재연결한다.
 */
export function useJarvisStatus(): UseJarvisStatusResult {
  const [status, setStatus] = useState<JarvisStatus>(initialStatus);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 마지막으로 처리한 상태 이벤트의 timestamp. 백엔드의 3초 주기 시스템 정보
  // push는 새 이벤트가 없으면 같은 timestamp로 broadcaster.get_current()를
  // 그대로 재전송하므로, 이 값이 같으면 "새 응답"이 아니라 "재전송"이다.
  const lastEventTimestampRef = useRef<number | null>(null);

  const handlePush = useCallback((payload: WsPushPayload) => {
    const isNewEvent = payload.timestamp !== lastEventTimestampRef.current;
    lastEventTimestampRef.current = payload.timestamp;

    setStatus((prev) => {
      const next: JarvisStatus = {
        ...prev,
        currentState: payload.state,
        lastResponse: payload.lastResponse ?? prev.lastResponse,
        // 채팅 상태 변화든 주기적인 시스템 정보 틱이든, push될 때마다 최신값으로
        // 비동기 갱신한다 (페이지 로드 시 한 번만 받던 동기식 스냅샷을 대체).
        engineInfo: payload.engineInfo,
        systemInfo: payload.systemInfo,
        usageToday: payload.usageToday,
      };

      if (isNewEvent && payload.state === "responded" && payload.lastResponse) {
        next.conversationLog = [
          ...prev.conversationLog,
          { role: "jarvis", text: payload.lastResponse, timestamp: payload.timestamp },
        ];
      }

      return next;
    });
  }, []);

  const connect = useCallback(() => {
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onmessage = (event: MessageEvent<string>) => {
      try {
        const payload = JSON.parse(event.data) as WsPushPayload;
        handlePush(payload);
      } catch {
        // 파싱 실패한 페이로드는 무시
      }
    };

    ws.onclose = () => {
      // wsRef.current가 이미 다른 소켓으로 교체된 뒤라면 이 소켓은 의도적으로
      // 닫힌(StrictMode의 mount→unmount→remount, 혹은 재연결) "유령" 소켓이다.
      // 그 경우 재연결을 또 걸면 같은 채팅 응답을 두 개의 살아있는 소켓이
      // 동시에 받아 화면에 중복으로 쌓이게 된다.
      if (wsRef.current !== ws) return;
      reconnectTimerRef.current = setTimeout(connect, RECONNECT_DELAY_MS);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [handlePush]);

  const sendMessage = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;

    setStatus((prev) => ({
      ...prev,
      conversationLog: [
        ...prev.conversationLog,
        { role: "user", text: trimmed, timestamp: Date.now() },
      ],
    }));

    try {
      const res = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: trimmed }),
      });
      // 자비스의 응답은 보통 /ws 를 통해 "responded" 이벤트로 push되어
      // handlePush가 conversationLog에 자동으로 추가한다. "/clear"는 예외 —
      // 서버가 라우팅을 거치지 않고 즉시 cleared:true로 응답하므로, 방금 위에서
      // 낙관적으로 추가한 "/clear" 턴까지 포함해 화면을 통째로 비운다.
      const data = (await res.json()) as { cleared?: boolean };
      if (data.cleared) {
        setStatus((prev) => ({ ...prev, conversationLog: [] }));
      }
    } catch {
      // 네트워크 오류 시에도 사용자 본인의 발화는 이미 로그에 남아 있다.
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    fetch(`${API_BASE}/api/status`)
      .then((res) => res.json() as Promise<StatusApiResponse>)
      .then((data) => {
        if (cancelled) return;
        setStatus((prev) => ({
          ...prev,
          engineInfo: data.engineInfo,
          usageToday: data.usageToday,
          activeSkills: data.activeSkills,
          systemInfo: data.systemInfo,
          currentState: data.state,
          lastResponse: data.lastResponse,
        }));
      })
      .catch(() => {
        // 서버가 아직 안 떴을 수 있음. 초기값 유지하고 WebSocket 재연결에 맡긴다.
      });

    // 디스크에 저장된 이전 대화 기록을 불러와 새로고침/재시작에도 보이게 한다.
    fetch(`${API_BASE}/api/history`)
      .then((res) => res.json() as Promise<HistoryApiResponse>)
      .then((data) => {
        if (cancelled) return;
        setStatus((prev) => ({ ...prev, conversationLog: data }));
      })
      .catch(() => {
        // 서버가 아직 안 떴을 수 있음. 빈 기록으로 유지.
      });

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { ...status, sendMessage };
}
