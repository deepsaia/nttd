const BASE = '/api';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

function get<T>(path: string) {
  return request<T>(path);
}

function post<T>(path: string, body?: unknown) {
  return request<T>(path, {
    method: 'POST',
    body: body ? JSON.stringify(body) : undefined,
  });
}

function del<T>(path: string) {
  return request<T>(path, { method: 'DELETE' });
}

// ---------------------------------------------------------------------------
// Session lifecycle (admin)
// ---------------------------------------------------------------------------
export function createSession(name: string, settings: Record<string, string> = {}) {
  return post<{ session_id: string }>('/admin/sessions/new', { name, settings });
}

export function listSessions(status?: string) {
  const qs = status ? `?status=${status}` : '';
  return get<{ sessions: Session[]; count: number }>(`/admin/sessions${qs}`);
}

export function getSession(id: string) {
  return get<SessionDetail>(`/admin/sessions/${id}`);
}

export function updateSettings(id: string, settings: Record<string, string>) {
  return post<{ applied: boolean }>(`/admin/sessions/${id}/settings`, { settings });
}

export function startSession(id: string, mode = 'newgame', aiOpponents = 0) {
  return post<StartSessionResponse>(`/admin/sessions/${id}/start`, {
    mode,
    ai_opponents: aiOpponents,
  });
}

export function stopSession(id: string, reason = 'manual') {
  return post<{ status: string }>(`/admin/sessions/${id}/stop?end_reason=${reason}`);
}

export function deleteSession(id: string) {
  return del<{ status: string }>(`/admin/sessions/${id}`);
}

// ---------------------------------------------------------------------------
// Session-scoped: Control
// ---------------------------------------------------------------------------
export function getGameStatus(sessionId: string) {
  return get<GameStatus>(`/sessions/${sessionId}/status`);
}

export function pauseGame(sessionId: string) {
  return post<{ paused: boolean }>(`/sessions/${sessionId}/pause`);
}

export function unpauseGame(sessionId: string) {
  return post<{ paused: boolean }>(`/sessions/${sessionId}/unpause`);
}

// setGameSpeed was removed: OpenTTD 15.3 has no runtime game-speed setting.
// The endpoint now returns 400. The economy clock is fixed at 1 wall-minute per
// economy month; the calendar pace is a generation-time scenario setting.

export function sendRcon(sessionId: string, command: string) {
  return post<{ response: string[] }>(`/sessions/${sessionId}/rcon?command=${encodeURIComponent(command)}`);
}

export function saveGame(sessionId: string, filename: string) {
  return post<{ response: string[] }>(`/sessions/${sessionId}/save?filename=${encodeURIComponent(filename)}`);
}

export function loadGame(sessionId: string, filename: string) {
  return post<{ response: string[] }>(`/sessions/${sessionId}/load?filename=${encodeURIComponent(filename)}`);
}

// ---------------------------------------------------------------------------
// Session-scoped: Clients / Players
// ---------------------------------------------------------------------------
export function getClients(sessionId: string) {
  return get<{ clients: GameClient[]; connected: boolean }>(`/admin/sessions/${sessionId}/clients`);
}

export function getSpectators(sessionId: string) {
  return get<{ spectators: GameClient[] }>(`/admin/sessions/${sessionId}/spectators`);
}

export function moveClient(sessionId: string, clientId: number, companyId: number) {
  return post<{ response: string[] }>(`/admin/sessions/${sessionId}/clients/${clientId}/move?company_id=${companyId}`);
}

export function kickClient(sessionId: string, clientId: number, reason = '') {
  return post<{ response: string[] }>(`/admin/sessions/${sessionId}/clients/${clientId}/kick?reason=${reason}`);
}

// ---------------------------------------------------------------------------
// Session-scoped: Agents
// ---------------------------------------------------------------------------
export function listAgents(sessionId: string) {
  return get<Agent[]>(`/sessions/${sessionId}/agents/list`).then((data) => ({
    agents: Array.isArray(data) ? data : [],
  }));
}

// ---------------------------------------------------------------------------
// Session-scoped: Observation
// ---------------------------------------------------------------------------
export function getFullState(sessionId: string) {
  return get<FullState>(`/sessions/${sessionId}/state/full`);
}

export function getCompanyState(sessionId: string, companyId: number) {
  return get<CompanyDetail>(`/sessions/${sessionId}/state/company/${companyId}`);
}

// ---------------------------------------------------------------------------
// Session-scoped: Deity operations
// ---------------------------------------------------------------------------
export function deityChangeBalance(sessionId: string, companyId: number, delta: number) {
  return post(`/admin/sessions/${sessionId}/deity/change_balance`, { company_id: companyId, delta });
}

export function deitySetMaxLoan(sessionId: string, companyId: number, amount: number) {
  return post(`/admin/sessions/${sessionId}/deity/set_max_loan`, { company_id: companyId, amount });
}

export function deitySetSetting(sessionId: string, key: string, value: number) {
  return post(`/admin/sessions/${sessionId}/deity/set_setting`, { key, value });
}

export function deityFoundTown(sessionId: string, params: Record<string, unknown>) {
  return post(`/admin/sessions/${sessionId}/deity/found_town`, params);
}

export function deityCreateSubsidy(sessionId: string, params: Record<string, unknown>) {
  return post(`/admin/sessions/${sessionId}/deity/create_subsidy`, params);
}

// ---------------------------------------------------------------------------
// Metrics (session_id as query param — unchanged)
// ---------------------------------------------------------------------------
export function getTimeseries(sessionId: string, metricName: string, companyId?: number) {
  let qs = `?session_id=${sessionId}&metric_name=${metricName}`;
  if (companyId !== undefined) qs += `&company_id=${companyId}`;
  return get<{ data: MetricPoint[] }>(`/metrics/timeseries${qs}`);
}

export function getLatestMetrics(sessionId: string) {
  return get<{ companies: CompanyMetrics[] }>(`/metrics/latest?session_id=${sessionId}`);
}

export function getFinanceSeries(sessionId: string, companyId: number) {
  return get<{ data: FinancePoint[] }>(`/metrics/finances?session_id=${sessionId}&company_id=${companyId}`);
}

export function getAvailableMetrics(sessionId: string) {
  return get<{ metrics: string[] }>(`/metrics/available?session_id=${sessionId}`);
}

// ---------------------------------------------------------------------------
// Messages
// ---------------------------------------------------------------------------
export function sendMessage(sessionId: string, body: string, fromId?: string) {
  return post('/messages/send', { session_id: sessionId, body, from_id: fromId });
}

export function getMessageHistory(sessionId: string, limit = 100) {
  return get<{ messages: Message[] }>(`/messages/history?session_id=${sessionId}&limit=${limit}`);
}

// ---------------------------------------------------------------------------
// Leaderboard
// ---------------------------------------------------------------------------
export function getSessionLeaderboard(sessionId: string) {
  return get<{ leaderboard: LeaderboardEntry[] }>(`/leaderboard/session/${sessionId}`);
}

export function getGlobalLeaderboard() {
  return get<{ leaderboard: GlobalLeaderboardEntry[] }>('/leaderboard/global');
}

export function computeLeaderboard(sessionId: string) {
  return post<{ ranked: number }>(`/leaderboard/compute/${sessionId}`);
}

// ---------------------------------------------------------------------------
// Replay
// ---------------------------------------------------------------------------
export function getReplaySnapshots(sessionId: string) {
  return get<{ snapshots: ReplaySnapshot[] }>(`/replay/sessions/${sessionId}/snapshots`);
}

export function getReplayActions(sessionId: string) {
  return get<{ actions: ReplayAction[] }>(`/replay/sessions/${sessionId}/actions`);
}

export function getReplayEvents(sessionId: string) {
  return get<{ events: ReplayEvent[] }>(`/replay/sessions/${sessionId}/events`);
}

// ---------------------------------------------------------------------------
// Entity data
// ---------------------------------------------------------------------------
export function getDataTowns(sessionId: string) {
  return get<{ towns: Town[] }>(`/data/towns?session_id=${sessionId}`);
}

export function getDataIndustries(sessionId: string) {
  return get<{ industries: Industry[] }>(`/data/industries?session_id=${sessionId}`);
}

export function getDataStations(sessionId: string, companyId?: number) {
  let qs = `?session_id=${sessionId}`;
  if (companyId !== undefined) qs += `&company_id=${companyId}`;
  return get<{ stations: Station[] }>(`/data/stations${qs}`);
}

export function getDataVehicles(sessionId: string, companyId?: number) {
  let qs = `?session_id=${sessionId}`;
  if (companyId !== undefined) qs += `&company_id=${companyId}`;
  return get<{ vehicles: Vehicle[] }>(`/data/vehicles${qs}`);
}

export function getDataSubsidies(sessionId: string) {
  return get<{ subsidies: Subsidy[] }>(`/data/subsidies?session_id=${sessionId}`);
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------
export function getHealth() {
  return get<HealthResponse>('/health');
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
export interface GameStatus {
  game_date: number;
  paused: boolean;
  mode: string;
  speed: number;
  map_width: number;
  map_height: number;
  landscape: string;
}

export interface Session {
  session_id: string;
  name: string;
  status: string;
  created_at: string;
  ended_at: string | null;
  running?: boolean;
}

export interface SessionDetail extends Session {
  settings: Record<string, string>;
  participants: Participant[];
  game_start_date: number | null;
  game_end_date: number | null;
  end_reason: string | null;
  game_port: number | null;
  admin_port: number | null;
}

export interface StartSessionResponse {
  session_id: string;
  status: string;
  game_port: number;
  admin_port: number;
  pid: number | null;
}

export interface Participant {
  participant_id: string;
  participant_type: string;
  company_id: number;
  name: string;
}

export interface GameClient {
  client_id: number;
  name: string;
  company_id: number;
}

export interface Agent {
  agent_id: string;
  company_scope: number[];
  subscriptions: string[];
  connected_at: string;
}

export interface FullState {
  game: GameStatus;
  companies: Record<string, CompanyInfo>;
  towns: Record<string, TownInfo>;
  industries: Record<string, IndustryInfo>;
  stations: StationInfo[];
  vehicles: VehicleInfo[];
}

export interface CompanyInfo {
  id: number;
  name: string;
  is_ai: boolean;
  balance: number;
  loan: number;
  income: number;
  expenses: number;
  company_value: number;
  performance_rating: number;
}

export interface TownInfo {
  id: number;
  name: string;
  population: number;
  x: number;
  y: number;
}

export interface IndustryInfo {
  id: number;
  type_name: string;
  x: number;
  y: number;
}

export interface StationInfo {
  station_id: number;
  company_id: number;
  name: string;
  x: number;
  y: number;
}

export interface VehicleInfo {
  vehicle_id: number;
  company_id: number;
  type: number;
  name: string;
  profit_this_year: number;
  speed: number;
}

export interface CompanyDetail {
  company: CompanyInfo;
  stations: StationInfo[];
  vehicles: VehicleInfo[];
}

export interface MetricPoint {
  game_date: number;
  metric_value: number;
  company_id?: number;
}

export interface CompanyMetrics {
  company_id: number;
  [key: string]: unknown;
}

export interface FinancePoint {
  game_date: number;
  balance: number;
  loan: number;
  income: number;
  expenses: number;
  company_value: number;
  performance_rating: number;
  cargo_delivered: number;
}

export interface Message {
  message_id: string;
  message_type: string;
  from_id: string | null;
  to_id: string | null;
  body: string;
  game_date: number | null;
  created_at: string;
}

export interface LeaderboardEntry {
  company_id: number;
  participant_id: string | null;
  participant_type: string | null;
  rank: number;
  final_balance: number;
  final_value: number;
  final_rating: number;
  total_cargo: number;
  total_actions: number;
  action_success_rate: number;
}

export interface GlobalLeaderboardEntry {
  participant_id: string;
  participant_type: string;
  sessions: number;
  avg_rank: number;
  total_cargo: number;
  avg_success_rate: number;
}

export interface ReplaySnapshot {
  snapshot_id: string;
  game_date: number;
  tick: number;
  captured_at: string;
}

export interface ReplayAction {
  action_type: string;
  company_id: number;
  status: string;
  game_date: number;
}

export interface ReplayEvent {
  event_type: string;
  company_id: number | null;
  game_date: number;
}

export interface Town {
  town_id: number;
  name: string;
  population: number;
  x: number;
  y: number;
}

export interface Industry {
  industry_id: number;
  type_name: string;
  x: number;
  y: number;
}

export interface Station {
  station_id: number;
  company_id: number;
  name: string;
  x: number;
  y: number;
}

export interface Vehicle {
  vehicle_id: number;
  company_id: number;
  type: number;
  name: string;
}

export interface Subsidy {
  subsidy_id: number;
  cargo_id: number;
  src_type: number;
  src_id: number;
  dst_type: number;
  dst_id: number;
  remaining: number;
}

export interface HealthResponse {
  status: string;
  active_sessions: number;
  sessions: { session_id: string; game_port: number; admin_port: number; connected: boolean }[];
}
