import { useCallback, useEffect, useRef, useState } from "react";

export type JarvisState = "idle" | "listening" | "processing" | "responded" | "navigation_request" | "poi_request";

export interface ConversationTurn {
  role: "user" | "jarvis";
  text: string;
  timestamp: number;
  transient?: boolean;   // tool_action 진행 표시용 임시 말풍선
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

export interface NavigationData {
  destination: { lat: number; lng: number; name: string };
  origin: { lat: number; lng: number };
  routeType: string;
  distance: number;
  duration: number;
  distanceText: string;
  durationText: string;
  vertexes: [number, number][];
  fareToll: number;
  fareTaxi: number;
}

export interface PoiItem {
  id: string;
  name: string;
  address: string;
  lat: number;
  lng: number;
  categoryCode: string;
  phone: string;
  distance: number;  // 경로 샘플 지점으로부터의 거리 (미터)
}

export interface NavCandidate {
  name: string;
  address: string;
  lat: number;
  lng: number;
}

export interface PoiResult {
  pois: PoiItem[];
  searchRadiusM: number;  // 실제 사용된 검색 반경
  onRoute: boolean;       // true = 경로 500m 이내, false = 우회 필요
  categoryName: string;
  categoryCode: string;   // 레이어 식별용 (OL7, FD6 등)
}

export interface JarvisStatus {
  engineInfo: EngineInfo;
  usageToday: number | null;
  activeSkills: string[];
  systemInfo: SystemInfo | null;
  currentState: JarvisState;
  lastResponse: string | null;
  conversationLog: ConversationTurn[];
  navigationData: NavigationData | null;
  navigationCandidates: NavCandidate[] | null;
  poiResults: PoiResult[];  // 카테고리별 POI 레이어 배열 (누적)
  kakaoJsKey: string;
}

export interface UseJarvisStatusResult extends JarvisStatus {
  sendMessage: (text: string) => Promise<void>;
  clearNavigation: () => void;
  clearPoi: () => void;
  clearPoiLayer: (categoryCode: string) => void;  // 특정 레이어만 제거
  selectCandidate: (candidate: NavCandidate) => Promise<void>;
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
  extra?: Record<string, unknown>;
}

interface HookMessagePayload {
  type: "tool_action" | "output";
  value: string;
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
  navigationData: null,
  navigationCandidates: null,
  poiResults: [],
  kakaoJsKey: "",
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
  // .env의 KAKAO_DEFAULT_LAT/LNG로 설정된 기본 출발지 (Geolocation 대신 사용)
  const defaultOriginRef = useRef<{ lat: number; lng: number } | null>(null);
  // POI 검색 시 현재 경로 vertexes 참조용 (stale closure 방지)
  const navigationDataRef = useRef<NavigationData | null>(null);
  // 후보 선택 대기 중인 항법 파라미터 (candidates 반환 시 저장)
  const pendingNavOriginRef = useRef<{ lat: number; lng: number } | undefined>(undefined);
  const pendingNavOriginNameRef = useRef<string | undefined>(undefined);
  const pendingNavRouteTypeRef = useRef<string>("RECOMMEND");
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
        engineInfo: payload.engineInfo,
        systemInfo: payload.systemInfo,
        usageToday: payload.usageToday,
      };

      if (isNewEvent && payload.state === "responded") {
        const lastTurn = prev.conversationLog[prev.conversationLog.length - 1];
        const withoutTransient = lastTurn?.transient
          ? prev.conversationLog.slice(0, -1)
          : prev.conversationLog;
        next.conversationLog = payload.lastResponse
          ? [...withoutTransient, { role: "jarvis", text: payload.lastResponse, timestamp: payload.timestamp }]
          : withoutTransient;
      }

      return next;
    });

    // navigation_request 이벤트: 출발지 확정 후 /api/navigate 호출
    if (isNewEvent && payload.state === "navigation_request" && payload.extra?.destination) {
      const destination = payload.extra.destination as string;
      const routeType = (payload.extra.routeType as string) || "RECOMMEND";

      const originName = payload.extra.originName as string | null | undefined;

      const doNavigate = async (origin?: { lat: number; lng: number }) => {
        // 후보 선택 대기용 파라미터 저장 (candidates 반환 시 selectCandidate에서 사용)
        pendingNavOriginRef.current = origin;
        pendingNavOriginNameRef.current = originName ?? undefined;
        pendingNavRouteTypeRef.current = routeType;

        try {
          const body: Record<string, unknown> = { destination, routeType };
          if (originName) body.originName = originName;
          else if (origin) body.origin = origin;
          const res = await fetch(`${API_BASE}/api/navigate`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
          const data = (await res.json()) as NavigationData & { error?: string; candidates?: NavCandidate[] };
          if (data.candidates) {
            // 동일 이름의 장소가 여러 곳 — 사용자에게 선택 요청
            setStatus((prev) => ({
              ...prev,
              navigationCandidates: data.candidates!,
              conversationLog: [
                ...prev.conversationLog,
                {
                  role: "jarvis",
                  text: `'${destination}'에 대한 검색 결과가 ${data.candidates!.length}개입니다. 아래에서 원하는 곳을 선택해 주세요.`,
                  timestamp: Date.now(),
                },
              ],
            }));
          } else if (data.error) {
            setStatus((prev) => ({
              ...prev,
              conversationLog: [
                ...prev.conversationLog,
                { role: "jarvis", text: `경로 검색 실패: ${data.error}`, timestamp: Date.now() },
              ],
            }));
          } else {
            navigationDataRef.current = data;
            setStatus((prev) => ({ ...prev, navigationData: data, navigationCandidates: null, poiResults: [] }));
          }
        } catch {
          setStatus((prev) => ({
            ...prev,
            conversationLog: [
              ...prev.conversationLog,
              { role: "jarvis", text: "경로 검색 중 네트워크 오류가 발생했습니다.", timestamp: Date.now() },
            ],
          }));
        }
      };

      // 발화에 출발지 명시 → 서버 geocode (좌표 불필요)
      if (originName) {
        void doNavigate();
        return;
      }

      // .env 기본 좌표가 있으면 우선 사용, 없으면 Geolocation → IP 추정(서버)
      if (defaultOriginRef.current) {
        void doNavigate(defaultOriginRef.current);
        return;
      }

      if (!navigator.geolocation) {
        void doNavigate(); // origin 없이 → 서버가 IP로 추정
        return;
      }

      navigator.geolocation.getCurrentPosition(
        (position) => {
          void doNavigate({
            lat: position.coords.latitude,
            lng: position.coords.longitude,
          });
        },
        () => {
          void doNavigate(); // Geolocation 실패 → 서버가 IP로 추정
        },
        { timeout: 10000 },
      );
    }

    // poi_request 이벤트: 경로 vertexes를 서버에 전달해 POI 검색 (다중 카테고리)
    if (isNewEvent && payload.state === "poi_request") {
      const categories = (payload.extra?.categories as { categoryCode: string | null; keyword: string | null; categoryName: string }[] | null) ?? [];
      const labelName = (payload.extra?.categoryName as string) || "장소";

      const doPoiSearch = async () => {
        try {
          const vertexes = navigationDataRef.current?.vertexes ?? [];
          const res = await fetch(`${API_BASE}/api/navigate/poi`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ categories, vertexes }),
          });
          const data = (await res.json()) as { results?: PoiResult[]; error?: string };
          if (data.error || !data.results || data.results.length === 0) {
            setStatus((prev) => ({
              ...prev,
              conversationLog: [
                ...prev.conversationLog,
                { role: "jarvis", text: data.error ?? `${labelName} 검색 결과가 없습니다.`, timestamp: Date.now() },
              ],
            }));
          } else {
            const newResults = data.results;
            // 기존 레이어에 동일 categoryCode 있으면 교체, 없으면 추가
            setStatus((prev) => {
              const merged = [...prev.poiResults];
              for (const r of newResults) {
                const idx = merged.findIndex((x) => x.categoryCode === r.categoryCode && x.categoryName === r.categoryName);
                if (idx >= 0) merged[idx] = r;
                else merged.push(r);
              }
              const totalCount = newResults.reduce((s, r) => s + r.pois.length, 0);
              const summary = newResults
                .map((r) => {
                  const note = r.onRoute ? "" : ` (${(r.searchRadiusM / 1000).toFixed(1)}km)`;
                  return `${r.categoryName} ${r.pois.length}개${note}`;
                })
                .join(", ");
              return {
                ...prev,
                poiResults: merged,
                conversationLog: [
                  ...prev.conversationLog,
                  { role: "jarvis", text: `총 ${totalCount}개 발견 — ${summary}`, timestamp: Date.now() },
                ],
              };
            });
          }
        } catch {
          setStatus((prev) => ({
            ...prev,
            conversationLog: [
              ...prev.conversationLog,
              { role: "jarvis", text: "POI 검색 중 네트워크 오류가 발생했습니다.", timestamp: Date.now() },
            ],
          }));
        }
      };
      void doPoiSearch();
    }
  }, []);

  const handleHookMessage = useCallback((msg: HookMessagePayload) => {
    setStatus((prev) => {
      const lastTurn = prev.conversationLog[prev.conversationLog.length - 1];
      const isLastTransient = lastTurn?.transient === true;

      if (msg.type === "tool_action") {
        const updatedTurn: ConversationTurn = {
          role: "jarvis",
          text: msg.value,
          timestamp: Date.now(),
          transient: true,
        };
        const conversationLog = isLastTransient
          ? [...prev.conversationLog.slice(0, -1), updatedTurn]
          : [...prev.conversationLog, updatedTurn];
        return { ...prev, conversationLog };
      }

      // type === "output": 임시 말풍선 제거만 한다 — 실제 텍스트는 곧 오는
      // "responded" 상태 이벤트가 채운다.
      if (isLastTransient) {
        return { ...prev, conversationLog: prev.conversationLog.slice(0, -1) };
      }
      return prev;
    });
  }, []);

  const connect = useCallback(() => {
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onmessage = (event: MessageEvent<string>) => {
      try {
        const payload = JSON.parse(event.data) as WsPushPayload | HookMessagePayload;
        if ("type" in payload) {
          handleHookMessage(payload);
        } else {
          handlePush(payload);
        }
      } catch {
        // 파싱 실패한 페이로드는 무시
      }
    };

    ws.onclose = () => {
      if (wsRef.current !== ws) return;
      reconnectTimerRef.current = setTimeout(connect, RECONNECT_DELAY_MS);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [handlePush, handleHookMessage]);

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
      const data = (await res.json()) as { cleared?: boolean };
      if (data.cleared) {
        setStatus((prev) => ({ ...prev, conversationLog: [] }));
      }
    } catch {
      // 네트워크 오류 시에도 사용자 본인의 발화는 이미 로그에 남아 있다.
    }
  }, []);

  const clearNavigation = useCallback(() => {
    navigationDataRef.current = null;
    setStatus((prev) => ({ ...prev, navigationData: null, navigationCandidates: null, poiResults: [] }));
  }, []);

  const selectCandidate = useCallback(async (candidate: NavCandidate) => {
    const origin = pendingNavOriginRef.current;
    const originName = pendingNavOriginNameRef.current;
    const routeType = pendingNavRouteTypeRef.current;
    try {
      const body: Record<string, unknown> = {
        destination: candidate.name,
        destinationLat: candidate.lat,
        destinationLng: candidate.lng,
        routeType,
      };
      if (originName) body.originName = originName;
      else if (origin) body.origin = origin;
      const res = await fetch(`${API_BASE}/api/navigate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = (await res.json()) as NavigationData & { error?: string };
      if (data.error) {
        setStatus((prev) => ({
          ...prev,
          conversationLog: [
            ...prev.conversationLog,
            { role: "jarvis", text: `경로 검색 실패: ${data.error}`, timestamp: Date.now() },
          ],
        }));
      } else {
        navigationDataRef.current = data;
        setStatus((prev) => ({ ...prev, navigationData: data, navigationCandidates: null, poiResults: [] }));
      }
    } catch {
      setStatus((prev) => ({
        ...prev,
        conversationLog: [
          ...prev.conversationLog,
          { role: "jarvis", text: "경로 검색 중 네트워크 오류가 발생했습니다.", timestamp: Date.now() },
        ],
      }));
    }
  }, []);

  const clearPoi = useCallback(() => {
    setStatus((prev) => ({ ...prev, poiResults: [] }));
  }, []);

  const clearPoiLayer = useCallback((categoryCode: string) => {
    setStatus((prev) => ({
      ...prev,
      poiResults: prev.poiResults.filter((r) => r.categoryCode !== categoryCode),
    }));
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
      .catch(() => {});

    fetch(`${API_BASE}/api/history`)
      .then((res) => res.json() as Promise<HistoryApiResponse>)
      .then((data) => {
        if (cancelled) return;
        setStatus((prev) => ({ ...prev, conversationLog: data }));
      })
      .catch(() => {});

    // 카카오 JS 앱 키 + 기본 출발지 로드
    fetch(`${API_BASE}/api/config`)
      .then((res) => res.json() as Promise<{ kakaoJsKey: string; defaultOrigin?: { lat: number; lng: number } }>)
      .then((data) => {
        if (cancelled) return;
        if (data.defaultOrigin) defaultOriginRef.current = data.defaultOrigin;
        setStatus((prev) => ({ ...prev, kakaoJsKey: data.kakaoJsKey }));
      })
      .catch(() => {});

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { ...status, sendMessage, clearNavigation, clearPoi, clearPoiLayer, selectCandidate };
}
