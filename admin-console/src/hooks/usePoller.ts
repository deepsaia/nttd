import { useEffect, useRef } from 'react';
import { useGameStore } from '../store/gameStore';
import * as api from '../api/client';

export function usePoller(intervalMs = 3000) {
  const setStatus = useGameStore((s) => s.setStatus);
  const setConnected = useGameStore((s) => s.setConnected);
  const setCompanies = useGameStore((s) => s.setCompanies);
  const setClients = useGameStore((s) => s.setClients);
  const setAgents = useGameStore((s) => s.setAgents);
  const activeSessionId = useGameStore((s) => s.activeSessionId);
  const timerRef = useRef<ReturnType<typeof setInterval>>(undefined);

  useEffect(() => {
    async function poll() {
      // Check nttd health
      try {
        const health = await api.getHealth();
        setConnected(health.status === 'ok');
      } catch {
        setConnected(false);
      }

      // Only poll session-scoped data if a session is active and running
      if (!activeSessionId) return;

      try {
        const status = await api.getGameStatus(activeSessionId);
        setStatus(status);
      } catch {
        // Session may not be running
      }

      try {
        const full = await api.getFullState(activeSessionId);
        if (full.companies) {
          setCompanies(full.companies);
        }
      } catch {
        // ignore
      }

      try {
        const { clients } = await api.getClients(activeSessionId);
        setClients(clients ?? []);
      } catch {
        // ignore
      }

      try {
        const { agents } = await api.listAgents(activeSessionId);
        setAgents(agents ?? []);
      } catch {
        // ignore
      }
    }

    poll();
    timerRef.current = setInterval(poll, intervalMs);
    return () => clearInterval(timerRef.current);
  }, [intervalMs, activeSessionId, setStatus, setConnected, setCompanies, setClients, setAgents]);
}
