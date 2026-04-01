import { useEffect, useRef } from 'react';
import { useGameStore } from '../store/gameStore';

const WS_URL = `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws/admin`;

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const pushEvent = useGameStore((s) => s.pushEvent);
  const setConnected = useGameStore((s) => s.setConnected);

  useEffect(() => {
    let reconnectTimer: ReturnType<typeof setTimeout>;
    let alive = true;

    function connect() {
      if (!alive) return;
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        pushEvent({
          id: 0,
          time: new Date().toLocaleTimeString(),
          type: 'system',
          message: 'WebSocket connected',
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
        setConnected(false);
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
    };
  }, [pushEvent, setConnected]);
}
