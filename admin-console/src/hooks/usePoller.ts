import { useEffect, useRef } from 'react';
import { useGameStore } from '../store/gameStore';
import * as api from '../api/client';

export function usePoller(intervalMs = 3000) {
  const setStatus = useGameStore((s) => s.setStatus);
  const setCompanies = useGameStore((s) => s.setCompanies);
  const setClients = useGameStore((s) => s.setClients);
  const setAgents = useGameStore((s) => s.setAgents);
  const timerRef = useRef<ReturnType<typeof setInterval>>(undefined);

  useEffect(() => {
    async function poll() {
      try {
        const status = await api.getGameStatus();
        setStatus(status);
      } catch {
        // backend offline
      }

      try {
        const full = await api.getFullState();
        if (full.companies) {
          setCompanies(full.companies);
        }
      } catch {
        // ignore
      }

      try {
        const { clients } = await api.getClients();
        setClients(clients ?? []);
      } catch {
        // ignore
      }

      try {
        const { agents } = await api.listAgents();
        setAgents(agents ?? []);
      } catch {
        // ignore
      }
    }

    poll();
    timerRef.current = setInterval(poll, intervalMs);
    return () => clearInterval(timerRef.current);
  }, [intervalMs, setStatus, setCompanies, setClients, setAgents]);
}
