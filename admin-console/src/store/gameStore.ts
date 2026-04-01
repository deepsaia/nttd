import { create } from 'zustand';
import type {
  GameStatus,
  Session,
  CompanyInfo,
  GameClient,
  Agent,
  ReplayEvent,
} from '../api/client';

interface GameState {
  // Connection
  connected: boolean;
  setConnected: (v: boolean) => void;

  // Game status (polled)
  status: GameStatus | null;
  setStatus: (s: GameStatus) => void;

  // Sessions
  sessions: Session[];
  activeSessionId: string | null;
  setSessions: (s: Session[]) => void;
  setActiveSession: (id: string | null) => void;

  // Companies (live)
  companies: Record<string, CompanyInfo>;
  setCompanies: (c: Record<string, CompanyInfo>) => void;

  // Clients & agents
  clients: GameClient[];
  agents: Agent[];
  setClients: (c: GameClient[]) => void;
  setAgents: (a: Agent[]) => void;

  // Event feed (ring buffer, last 200)
  events: EventEntry[];
  pushEvent: (e: EventEntry) => void;
  clearEvents: () => void;
}

export interface EventEntry {
  id: number;
  time: string;
  type: string;
  message: string;
  companyId?: number;
}

let _eventCounter = 0;

export const useGameStore = create<GameState>()((set) => ({
  connected: false,
  setConnected: (v) => set({ connected: v }),

  status: null,
  setStatus: (s) => set({ status: s }),

  sessions: [],
  activeSessionId: null,
  setSessions: (s) => set({ sessions: s }),
  setActiveSession: (id) => set({ activeSessionId: id }),

  companies: {},
  setCompanies: (c) => set({ companies: c }),

  clients: [],
  agents: [],
  setClients: (c) => set({ clients: c }),
  setAgents: (a) => set({ agents: a }),

  events: [],
  pushEvent: (e) =>
    set((state) => {
      const entry = { ...e, id: ++_eventCounter };
      const next = [entry, ...state.events].slice(0, 200);
      return { events: next };
    }),
  clearEvents: () => set({ events: [] }),
}));

// Helper to convert backend events to EventEntry
export function replayEventToEntry(e: ReplayEvent): EventEntry {
  return {
    id: 0,
    time: `Day ${e.game_date}`,
    type: e.event_type,
    message: `${e.event_type}${e.company_id !== null ? ` (company ${e.company_id})` : ''}`,
    companyId: e.company_id ?? undefined,
  };
}
