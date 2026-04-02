import { useEffect, useRef } from 'react';
import { useGameStore } from '../store/gameStore';

function buildWsUrl(sessionId: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${window.location.host}/ws/${sessionId}/admin`;
}

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const pushEvent = useGameStore((s) => s.pushEvent);
  const setConnected = useGameStore((s) => s.setConnected);
  const activeSessionId = useGameStore((s) => s.activeSessionId);

  useEffect(() => {
    if (!activeSessionId) {
      // No active session — close any existing connection
      wsRef.current?.close();
      wsRef.current = null;
      return;
    }

    let reconnectTimer: ReturnType<typeof setTimeout>;
    let alive = true;

    function connect() {
      if (!alive || !activeSessionId) return;
      const ws = new WebSocket(buildWsUrl(activeSessionId));
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        pushEvent({
          id: 0,
          time: new Date().toLocaleTimeString(),
          type: 'system',
          message: `WebSocket connected to session ${activeSessionId}`,
        });
      };

      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          if (data.type === 'snapshot' || data.type === 'trigger') {
            pushEvent({
              id: 0,
              time: new Date().toLocaleTimeString(),
              type: data.type,
              message: data.message ?? data.type,
              companyId: data.company_id,
            });
          }
        } catch {
          // ignore non-JSON
        }
      };

      ws.onclose = () => {
        if (alive) {
          reconnectTimer = setTimeout(connect, 3000);
        }
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();

    return () => {
      alive = false;
      clearTimeout(reconnectTimer);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [activeSessionId, pushEvent, setConnected]);
}
