// ============================================================
// Typed API client for the BusinessIntelligence.ai FastAPI
// backend. In dev, Vite proxies /api to http://localhost:8000.
// When the built bundle is served by FastAPI at /app, requests
// stay same-origin automatically.
// ============================================================

export const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? '';

export interface AuthUser {
  username: string;
  role: string;
  full_name: string | null;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in_minutes: number;
  user: AuthUser;
}

export interface KpiStatus {
  kpi_id: string;
  name: string;
  formula: string;
  access_roles: string[];
  sensitivity: string;
  status: string;
  latest_value: number;
  latest_date: string;
  previous_value: number;
  change_pct: number | null;
  z_score: number;
  baseline_mean: number;
  flagged: boolean;
  material: boolean;
  anomalous: boolean;
  adverse: boolean;
  reason: string;
}

export interface KpiStatusPayload {
  generated_at: string;
  warehouse: string;
  kpis_evaluated: number;
  flagged_count: number;
  kpis: Record<string, KpiStatus>;
}

export interface GmvEvent {
  event_group: number;
  event_start_date: string;
  event_end_date: string;
  anomalous_days: number;
  direction: string;
  event_type: string;
  investigation_priority: string;
  peak_change_abs: number;
  cumulative_absolute_impact: number;
  peak_z_score: number;
  coverage_status: string;
  event_priority_score: number;
}

export interface EventsPayload {
  count: number;
  events: GmvEvent[];
}

export interface RoiEvent {
  event_id: number;
  start_date: string;
  end_date: string;
  anomalous_days: number;
  at_risk_gmv: number;
  detection_lead_days: number;
  actionable: boolean;
  actionable_driver_count: number;
  main_action: string;
  main_decision: string;
  main_owner: string;
  recovery_rate_applied: number;
  estimated_recoverable_gmv: number;
}

export interface RoiSummary {
  generated_at: string;
  method: string;
  assumptions: Record<string, unknown>;
  summary: {
    events_analyzed: number;
    actionable_events: number;
    abstained_events: number;
    total_at_risk_gmv: number;
    estimated_recoverable_gmv: number;
    estimated_recoverable_gmv_upper: number;
    average_detection_lead_days: number;
  };
  hero_event: RoiEvent;
  events: RoiEvent[];
}

export interface ActionRow {
  event_id: number;
  driver_type: string;
  driver: string;
  contribution_share: number;
  confidence: number;
  evidence_status: string;
  decision: string | null;
  controllable_lever: string | null;
  action: string | null;
  owner: string | null;
  monitoring_plan: string | null;
}

export interface ActionsPayload {
  count: number;
  actions: ActionRow[];
}

export interface NarrativeTelemetry {
  model?: string;
  latency_ms?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  model_calls?: number;
  estimated_cost_usd?: number;
  [key: string]: unknown;
}

export interface NarrativeValidation {
  available?: boolean;
  passed?: boolean;
  violations?: unknown[];
  [key: string]: unknown;
}

export interface ExecutiveStoryPayload {
  insight_id: string;
  persona: string;
  story: string;
  validation?: NarrativeValidation;
  telemetry?: NarrativeTelemetry;
  [key: string]: unknown;
}

export interface EventNarrativePayload {
  event_id: number;
  event: Record<string, unknown>;
  executive: { story: string; telemetry?: NarrativeTelemetry; validation?: NarrativeValidation };
  operations: { story: string; telemetry?: NarrativeTelemetry; validation?: NarrativeValidation };
  validation: {
    passed: boolean;
    executive_passed: boolean;
    operations_passed: boolean;
    [key: string]: unknown;
  };
}

export interface InvestigationDriver {
  driver_type: string;
  driver: string;
  observed_contribution: { gmv_change: number; share: number };
  evidence: {
    review?: { status: string; event_records: number; comparison_records: number; directional_support: number };
    context?: { status: string; [key: string]: unknown };
  };
  confidence: {
    overall: number;
    structural: number;
    review: number;
    context: number;
    independent_sources: number;
  };
  status: string;
  action: {
    decision: string | null;
    lever: string | null;
    action: string | null;
    owner: string | null;
    monitoring_plan: string | null;
    action_type: string | null;
  };
}

export interface InvestigationPayload {
  insight_id?: string;
  kpi?: Record<string, unknown>;
  event: {
    event_id: number;
    start_date: string;
    end_date: string;
    duration_days: number;
    direction: string;
    event_type: string;
    investigation_priority: string;
    peak_change: number;
    peak_z_score: number;
    cumulative_absolute_impact: number;
    [key: string]: unknown;
  };
  movement: {
    comparison_period: { start: string; end: string };
    previous_gmv: number;
    current_gmv: number;
    gmv_change: number;
    previous_orders: number;
    current_orders: number;
    orders_change: number;
    previous_aov: number;
    current_aov: number;
    aov_change: number;
    volume_effect: number;
    aov_effect: number;
    residual_effect: number;
  };
  drivers: InvestigationDriver[];
  data_quality?: Record<string, unknown>;
  lineage?: Record<string, unknown>;
  llm_policy?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface SecurityTestPayload {
  security_model: string;
  roles: Record<string, { visible_sections: string[]; restricted_fields: string[] }>;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const TOKEN_KEY = 'bi_token';

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  if (init?.body) headers['Content-Type'] = 'application/json';

  const resp = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const body = await resp.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(resp.status, detail);
  }
  return (await resp.json()) as T;
}

export const api = {
  login: (username: string, password: string) =>
    request<LoginResponse>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

  me: () =>
    request<{ username: string; role: string; full_name: string | null; auth_enforced: boolean }>(
      '/api/auth/me',
    ),

  kpiStatus: () => request<KpiStatusPayload>('/api/kpis/status'),

  events: (limit = 20) => request<EventsPayload>(`/api/events?limit=${limit}`),

  roiSummary: () => request<RoiSummary>('/api/roi/summary'),

  actions: () => request<ActionsPayload>('/api/actions'),

  securityTest: () => request<SecurityTestPayload>('/api/security/test'),

  executiveStory: () => request<ExecutiveStoryPayload>('/api/insights/latest/executive'),

  operationsStory: () => request<ExecutiveStoryPayload>('/api/insights/latest/operations'),

  latestInsight: () => request<InvestigationPayload>('/api/insights/latest'),

  eventInvestigation: (eventId: number) =>
    request<InvestigationPayload>(`/api/insights/event/${eventId}`),

  eventNarrative: (eventId: number) =>
    request<EventNarrativePayload>(`/api/insights/event/${eventId}/narrative`, { method: 'POST' }),

  telemetry: () =>
    request<{
      executive: NarrativeTelemetry;
      operations: NarrativeTelemetry;
      validation: { executive_passed: boolean; operations_passed: boolean };
    }>('/api/telemetry'),

  validationScenarios: () => request<Record<string, unknown>>('/api/validation/scenarios'),

  sparseHistory: () => request<Record<string, unknown>>('/api/validation/sparse-history'),

  calibration: () => request<Record<string, unknown>>('/api/calibration'),

  feedback: () => request<Record<string, unknown>>('/api/feedback'),
};