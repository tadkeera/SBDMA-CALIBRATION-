/**
 * Typed client for the SBDMA FastAPI backend.
 *
 * Rules encoded here:
 *  - the session lives in httpOnly cookies, so every request sends
 *    `credentials: 'include'` and no token ever touches JavaScript;
 *  - a 401 triggers exactly one refresh attempt, then the caller decides;
 *  - the server's unified envelope ({success, data, meta, errors}) is unwrapped
 *    into either a value or an ApiError that keeps both Arabic and English text;
 *  - downloads go through the same auth path (a bare <a href> would not carry
 *    the cookie on cross-origin setups and would bypass error handling).
 */

import type { Branding } from '@/core/branding';
import type {
  Instrument,
  LimitSource,
  ReferenceEquipment,
  ReferenceStandard,
  RunRecord,
  RunTestResult,
  Status,
  UserAccount,
} from '@/core/types';

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? '/api/v1';

export interface ApiErrorBody {
  code: string;
  field: string | null;
  message_ar: string;
  message_en: string;
  details?: Record<string, unknown>;
}

export class ApiError extends Error {
  readonly code: string;
  readonly field: string | null;
  readonly messageAr: string;
  readonly status: number;
  readonly details: Record<string, unknown>;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message_en);
    this.name = 'ApiError';
    this.status = status;
    this.code = body.code;
    this.field = body.field ?? null;
    this.messageAr = body.message_ar;
    this.details = body.details ?? {};
  }

  /** Localized message for a toast or inline error. */
  text(lang: 'ar' | 'en'): string {
    // `super.message` would read Error.prototype.message (always ""), so the
    // English text must come from the instance.
    return lang === 'ar' ? this.messageAr || this.message : this.message || this.messageAr;
  }
}

/** Thrown when the API is unreachable — the caller falls back to cached data. */
export class OfflineError extends Error {
  constructor(cause?: unknown) {
    super('api-unreachable');
    this.name = 'OfflineError';
    this.cause = cause;
  }
}

interface Envelope<T> {
  success: boolean;
  data: T | null;
  meta: Record<string, unknown> | null;
  errors: ApiErrorBody[];
}

let refreshInFlight: Promise<boolean> | null = null;

async function refreshSession(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const response = await fetch(`${API_BASE}/auth/refresh`, {
          method: 'POST',
          credentials: 'include',
          headers: { Accept: 'application/json' },
        });
        return response.ok;
      } catch {
        return false;
      } finally {
        // allow a later 401 to try again
        setTimeout(() => {
          refreshInFlight = null;
        }, 0);
      }
    })();
  }
  return refreshInFlight;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  retryOnUnauthorized = true,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      credentials: 'include',
      headers: {
        Accept: 'application/json',
        // FormData must keep the browser-generated multipart boundary; only
        // string/JSON bodies get the JSON content type set here.
        ...(init.body && !(init.body instanceof FormData)
          ? { 'Content-Type': 'application/json' }
          : {}),
        ...(init.headers ?? {}),
      },
    });
  } catch (error) {
    throw new OfflineError(error);
  }

  if (response.status === 401 && retryOnUnauthorized && !path.startsWith('/auth/login')) {
    const refreshed = await refreshSession();
    if (refreshed) return request<T>(path, init, false);
  }

  let body: Envelope<T> | null = null;
  try {
    body = (await response.json()) as Envelope<T>;
  } catch {
    body = null;
  }

  if (!response.ok || !body?.success) {
    const first = body?.errors?.[0];
    throw new ApiError(
      response.status,
      first ?? {
        code: 'HTTP_ERROR',
        field: null,
        message_ar: `فشل الطلب (${response.status})`,
        message_en: `Request failed (${response.status})`,
      },
    );
  }
  return body.data as T;
}

// ─────────────────────────────── DTO shapes ──────────────────────────────── //

export interface ServerUser {
  id: string;
  username: string;
  email?: string;
  full_name_ar: string;
  full_name_en: string;
  roles: string[];
  permissions: string[];
  department_id: string | null;
  department_code?: string | null;
  must_change_password?: boolean;
  mfa_enrolment_required?: boolean;
}

export interface ServerInstrument {
  id: string;
  department_id: string;
  asset_code: string;
  category: string;
  manufacturer: string;
  model: string;
  part_number: string | null;
  serial_number: string;
  software_version: string | null;
  calibration_freq_days: number;
  last_calibration_date: string | null;
  next_due_date: string | null;
  status: 'ACTIVE' | 'OUT_OF_SERVICE' | 'UNDER_MAINTENANCE';
  d2_lamp_hours: number;
}

export interface ServerReferenceEquipment {
  id: string;
  equipment_code: string;
  name_ar: string;
  name_en: string;
  serial_number: string;
  certificate_no: string;
  calibrated_by: string;
  calibration_date: string;
  expiry_date: string;
  correction_table_jsonb: number[][] | null;
  is_active: boolean;
  expired: boolean;
  days_to_expiry: number;
}

export interface ServerReferenceStandard {
  id: string;
  name: string;
  lot_number: string;
  purity_percent: string;
  prepared_at: string | null;
  expiry_date: string;
  expired: boolean;
  days_to_expiry: number;
}

export interface ServerRunSummary {
  id: string;
  execution_code: string;
  instrument_id: string;
  overall_status: Status;
  run_type: RunRecord['runType'];
  analyst_id: string;
  is_locked: boolean;
  started_at: string;
  completed_at: string | null;
}

export interface ServerMetricEvaluation {
  metric_key: string;
  value: string | null;
  unit: string;
  applied_limit_id: string | null;
  applied_source: LimitSource | null;
  comparator: string;
  limit_text: string;
  status: Status;
  message_ar?: string | null;
}

export interface ServerTestResult {
  test_code: string;
  status: Status;
  metric_evaluations: ServerMetricEvaluation[];
  notes_ar?: string | null;
  outputs?: Record<string, unknown>;
  /** Present on `GET /runs/{id}`: the inputs exactly as captured and signed. */
  raw_inputs?: Record<string, unknown>;
}

export interface ServerAttachment {
  id: string;
  instrument_id: string | null;
  run_id: string | null;
  test_result_id: string | null;
  file_name: string;
  mime_type: string;
  size_bytes: number;
  sha256_checksum: string;
  description_ar: string | null;
  supersedes_id: string | null;
  uploaded_by: string | null;
  created_at: string;
  download_url: string;
}

export interface ServerRun {
  id: string;
  execution_code: string;
  instrument_id: string;
  run_type: RunRecord['runType'];
  overall_status: Status;
  analyst_id: string;
  reviewer_id: string | null;
  qa_approver_id: string | null;
  limit_source_policy: LimitSource;
  ambient_temp_c: string | null;
  ambient_humidity: string | null;
  certificate_hash: string | null;
  is_locked: boolean;
  revision: number;
  started_at: string;
  completed_at: string | null;
  reviewed_at: string | null;
  qa_approved_at: string | null;
  breakdown_component: string | null;
  results: ServerTestResult[];
}

export interface ServerKpis {
  instruments: { total: number; in_calibration: number; due_within_30_days: number; overdue: number };
  runs: {
    completed: number;
    passed: number;
    pass_rate_percent: number | null;
    pending_qa_approval: number;
    locked: number;
    mean_approval_days: number | null;
  };
  compliance: {
    expired_reference_equipment: number;
    expired_reference_standards: number;
    open_maintenance_tickets: number;
    d2_lamp_alerts: number;
  };
  generated_at: string;
}

export interface ServerHealth {
  status: string;
  version: string;
  environment: string;
  components: Record<string, string>;
}

// ──────────────────────────────── endpoints ──────────────────────────────── //

export interface ServerManagedUser {
  id: string;
  username: string;
  email: string;
  full_name_ar: string;
  full_name_en: string;
  department_id: string | null;
  roles: string[];
  role_ranks: number[];
  is_active: boolean;
  must_change_password: boolean;
  is_locked: boolean;
  locked_until: string | null;
  failed_login_count: number;
  last_login_at: string | null;
  totp_enabled: boolean;
  created_at: string;
}

export interface ServerNotification {
  id: string;
  channel: string;
  severity: 'info' | 'warning' | 'critical' | string;
  title_ar: string;
  title_en: string | null;
  body_ar: string | null;
  payload: {
    kind?: string;
    code?: string;
    due_date?: string;
    days_remaining?: number;
    window?: string;
    entity_id?: string;
  } | null;
  created_at: string | null;
  sent_at: string | null;
  read_at: string | null;
}

export interface ServerWorkerStatus {
  broker_configured: boolean;
  broker: string;
  scheduled: { name: string; task: string; schedule: string }[];
  registered_tasks: string[];
  note_ar: string;
  note_en: string;
}

export interface ServerKpiReportResult {
  period: string;
  documents: { scope: string; document_id: string; path: string; bytes: number; sha256: string }[];
}

export interface ServerDeviation {
  id: string;
  reference: string;
  run_id: string;
  run_code: string | null;
  instrument_id: string;
  status: string;
  classification: string;
  title: string;
  description: string;
  root_cause_category: string | null;
  root_cause: string | null;
  immediate_action: string | null;
  capa_action: string | null;
  capa_notes: string | null;
  closure_notes: string | null;
  retest_run_id: string | null;
  raised_by: string;
  raised_at: string | null;
  investigated_by: string | null;
  investigated_at: string | null;
  closed_by: string | null;
  closed_at: string | null;
}

export interface ServerRoleOption {
  code: string;
  name_ar: string;
  name_en: string;
  rank: number;
  permissions: string[];
  /** false when the role outranks you or would break separation of duties */
  assignable: boolean;
}

export const api = {
  // auth
  login: (username: string, password: string, totpCode?: string) =>
    request<{ access_token: string; user: ServerUser }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password, totp_code: totpCode ?? null }),
    }),

  // second factor (21 CFR Part 11.200(a)(1)(i))
  mfaStatus: () =>
    request<{
      enabled: boolean;
      enrolled_at: string | null;
      recovery_codes_remaining: number;
      pending_enrolment: boolean;
    }>('/auth/mfa'),
  mfaEnrol: () =>
    request<{ secret: string; otpauth_uri: string; digits: number; period_seconds: number }>(
      '/auth/mfa/enrol',
      { method: 'POST' },
    ),
  mfaActivate: (code: string) =>
    request<{ enabled: boolean; recovery_codes: string[] }>('/auth/mfa/activate', {
      method: 'POST',
      body: JSON.stringify({ code }),
    }),
  mfaDisable: (password: string, code: string) =>
    request<{ enabled: boolean }>('/auth/mfa/disable', {
      method: 'POST',
      body: JSON.stringify({ password, code }),
    }),
  mfaRecovery: (username: string, password: string, code: string) =>
    request<{ recovered: boolean; re_enrol_required: boolean }>('/auth/mfa/recovery', {
      method: 'POST',
      body: JSON.stringify({ username, password, code }),
    }),
  logout: () => request<{ logged_out: boolean }>('/auth/logout', { method: 'POST' }),
  me: () => request<ServerUser>('/auth/me'),
  changePassword: (current_password: string, new_password: string, reason: string) =>
    request<{ changed: boolean }>('/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({ current_password, new_password, reason }),
    }),

  // system
  health: () => request<ServerHealth>('/health'),

  // report letterhead — the two reads are public: the sign-in screen needs them
  branding: () => request<Branding>('/branding'),
  updateBrandingHeader: (header_ar: string[], header_en: string[]) =>
    request<Branding>('/branding', {
      method: 'PUT',
      body: JSON.stringify({ header_ar, header_en }),
    }),
  resetBrandingHeader: () => request<Branding>('/branding/reset', { method: 'POST' }),
  uploadBrandingLogo: (file: File) => {
    const body = new FormData();
    body.append('file', file);
    return request<Branding>('/branding/logo', { method: 'POST', body });
  },
  deleteBrandingLogo: () => request<Branding>('/branding/logo', { method: 'DELETE' }),
  kpis: () => request<ServerKpis>('/kpis'),

  // catalogue
  instruments: () => request<ServerInstrument[]>('/instruments'),
  referenceEquipment: () => request<ServerReferenceEquipment[]>('/reference-equipment'),
  referenceStandards: () => request<ServerReferenceStandard[]>('/reference-standards'),
  departments: () =>
    request<Array<{ id: string; code: string; name_ar: string; name_en: string }>>('/departments'),
  protocols: () =>
    request<Array<{ id: string; protocol_code: string; version: string; status: string }>>('/protocols'),
  protocolDetail: (code: string) =>
    request<{
      id: string;
      protocol_code: string;
      version: string;
      status: string;
      tests: Array<{
        test_code: string;
        limits: Array<{
          id: string;
          metric_key: string;
          source_type: LimitSource;
          approval_status: string;
          operator: string;
          min_value: string | null;
          max_value: string | null;
          unit: string;
          flagged: boolean;
        }>;
      }>;
    }>(`/protocols/${code}`),

  // runs
  createRun: (payload: {
    instrument_id: string;
    reference_equipment_id?: string | null;
    run_type: RunRecord['runType'];
    ambient_temp_c?: number | null;
    ambient_humidity?: number | null;
    limit_source_policy: LimitSource;
    breakdown_component?: string | null;
  }) =>
    request<ServerRun>('/runs', {
      method: 'POST',
      // the server rejects runs without an idempotency key
      headers: { 'Idempotency-Key': `fe-${Date.now()}-${Math.random().toString(36).slice(2, 10)}` },
      body: JSON.stringify(payload),
    }),
  executeRun: (runId: string, raw_inputs: Record<string, Record<string, unknown>>, scope_tests?: string[]) =>
    request<{
      run: ServerRun;
      overall: Status;
      summary: { pass: number; fail: number; review: number; incomplete: number };
      results: ServerTestResult[];
    }>(`/runs/${runId}/execute`, {
      method: 'POST',
      body: JSON.stringify({ raw_inputs, scope_tests }),
    }),
  reviewRun: (runId: string, password: string, reason: string) =>
    request<ServerRun>(`/runs/${runId}/review`, {
      method: 'POST',
      body: JSON.stringify({ password, reason }),
    }),
  approveRun: (runId: string, password: string, reason: string) =>
    request<ServerRun>(`/runs/${runId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ password, reason }),
    }),
  runs: (params: { page?: number; page_size?: number; status?: string } = {}) => {
    const query = new URLSearchParams();
    if (params.page) query.set('page', String(params.page));
    if (params.page_size) query.set('page_size', String(params.page_size));
    if (params.status) query.set('status', params.status);
    return request<ServerRunSummary[]>(`/runs${query.size ? `?${query}` : ''}`);
  },
  run: (runId: string) => request<ServerRun>(`/runs/${runId}`),
  pendingApprovals: () => request<ServerRunSummary[]>('/runs/pending/approvals'),

  // governance
  approveLimit: (limitId: string, password: string, reason: string) =>
    request<{ id: string; approval_status: string }>(`/limits/${limitId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ password, reason }),
    }),

  // maintenance
  tickets: () =>
    request<
      Array<{
        id: string;
        instrument_id: string;
        component_affected: string;
        description: string;
        required_tests: string[];
        status: string;
        resolved_at: string | null;
      }>
    >('/maintenance/tickets'),
  createTicket: (instrument_id: string, component_affected: string, description: string) =>
    request<{ id: string; required_tests: string[]; status: string }>('/maintenance/tickets', {
      method: 'POST',
      body: JSON.stringify({ instrument_id, component_affected, description }),
    }),
  resolveTicket: (ticketId: string) =>
    request<{ id: string; status: string }>(`/maintenance/tickets/${ticketId}/resolve`, {
      method: 'POST',
    }),

  // audit
  audit: (params: { page?: number; page_size?: number; action?: string } = {}) => {
    const query = new URLSearchParams();
    if (params.page) query.set('page', String(params.page));
    if (params.page_size) query.set('page_size', String(params.page_size));
    if (params.action) query.set('action', params.action);
    return request<
      Array<{
        id: string;
        at: string;
        actor_label: string;
        role_label: string | null;
        action: string;
        entity_type: string;
        entity_id: string;
        reason: string | null;
        hash: string;
        prev_hash: string;
      }>
    >(`/audit${query.size ? `?${query}` : ''}`);
  },
  verifyAudit: () =>
    request<{ ok: boolean; total: number; head: string; broken_at?: string | null }>('/audit/verify'),

  // evidence attachments
  attachments: (instrumentId: string) =>
    request<ServerAttachment[]>(`/instruments/${instrumentId}/attachments`),
  /**
   * Multipart upload. The checksum is computed by the server — sending one from
   * the browser would let the client choose what the record claims, so we never do.
   */
  uploadAttachment: (
    instrumentId: string,
    file: File,
    description: string,
    supersedesId?: string | null,
  ) => {
    const form = new FormData();
    form.append('file', file);
    form.append('description', description);
    if (supersedesId) form.append('supersedes_id', supersedesId);
    return request<ServerAttachment>(`/instruments/${instrumentId}/attachments`, {
      method: 'POST',
      body: form,
    });
  },

  // user administration (requires users.manage)
  users: (params: { q?: string; active?: boolean } = {}) => {
    const search = new URLSearchParams();
    if (params.q) search.set('q', params.q);
    if (params.active !== undefined) search.set('active', String(params.active));
    const suffix = search.toString() ? `?${search}` : '';
    return request<ServerManagedUser[]>(`/users${suffix}`);
  },
  roleOptions: () => request<ServerRoleOption[]>('/users/roles'),
  /**
   * Creating an identity is a GxP event, so the reason travels as a query
   * parameter and is stored in the audit chain verbatim.
   */
  createUser: (body: {
    username: string;
    email: string;
    full_name_ar: string;
    full_name_en: string;
    password: string;
    roles: string[];
    department_id?: string | null;
    reason: string;
  }) => {
    const { reason, ...payload } = body;
    return request<ServerManagedUser>(`/users?reason=${encodeURIComponent(reason)}`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
  updateUser: (
    userId: string,
    changes: {
      roles?: string[];
      is_active?: boolean;
      department_id?: string | null;
      email?: string;
      full_name_ar?: string;
      full_name_en?: string;
      reason: string;
    },
  ) => request<ServerManagedUser>(`/users/${userId}`, { method: 'PATCH', body: JSON.stringify(changes) }),
  resetUserPassword: (userId: string, newPassword: string, reason: string) =>
    request<{ user_id: string; must_change_password: boolean }>(`/users/${userId}/reset-password`, {
      method: 'POST',
      body: JSON.stringify({ new_password: newPassword, reason }),
    }),
  unlockUser: (userId: string, reason: string) =>
    request<{ user_id: string; is_locked: boolean }>(`/users/${userId}/unlock`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),
  revokeUserSessions: (userId: string, reason: string) =>
    request<{ user_id: string; revoked: number }>(`/users/${userId}/revoke-sessions`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),

  // ── notifications & background jobs ───────────────────────────────────── //
  // A notice is addressed to a person, not to a department: these calls carry no
  // scope filter because the server derives the scope from the session.
  notifications: (params: { unreadOnly?: boolean; limit?: number } = {}) => {
    const search = new URLSearchParams();
    if (params.unreadOnly) search.set('unread_only', 'true');
    if (params.limit) search.set('limit', String(params.limit));
    const suffix = search.toString() ? `?${search}` : '';
    return request<ServerNotification[]>(`/notifications${suffix}`);
  },
  unreadNotificationCount: () =>
    request<{ unread: number }>('/notifications/unread-count'),
  markNotificationRead: (id: string) =>
    request<{ id: string; marked: boolean }>(`/notifications/${id}/read`, { method: 'POST' }),
  duePreview: () =>
    request<{ due_items: number; created: number; skipped_duplicates: number; dry_run: boolean }>(
      '/notifications/due-preview',
    ),
  generateNotifications: () =>
    request<{ due_items: number; created: number; skipped_duplicates: number }>(
      '/notifications/generate',
      { method: 'POST' },
    ),
  runKpiReport: (forDate?: string) =>
    request<ServerKpiReportResult>(
      `/reports/kpi/run${forDate ? `?for_date=${forDate}` : ''}`,
      { method: 'POST' },
    ),
  workerStatus: () => request<ServerWorkerStatus>('/worker/status'),

  // ── OOS deviations ────────────────────────────────────────────────────── //
  // Three phases, three permissions. The server refuses a phase to a principal
  // who lacks its permission, so the UI's job is to show the next step and the
  // reason it may be refused — not to decide whether it is allowed.
  deviations: (params: { status?: string; run_id?: string } = {}) => {
    const search = new URLSearchParams();
    if (params.status) search.set('status', params.status);
    if (params.run_id) search.set('run_id', params.run_id);
    const suffix = search.toString() ? `?${search}` : '';
    return request<ServerDeviation[]>(`/deviations${suffix}`);
  },
  deviation: (deviationId: string) => request<ServerDeviation>(`/deviations/${deviationId}`),
  raiseDeviation: (body: {
    run_id: string;
    title: string;
    description: string;
    classification: string;
  }) => request<ServerDeviation>('/deviations', { method: 'POST', body: JSON.stringify(body) }),
  startInvestigation: (deviationId: string, plan: string) =>
    request<ServerDeviation>(`/deviations/${deviationId}/investigate/start`, {
      method: 'POST',
      body: JSON.stringify({ plan }),
    }),
  recordInvestigation: (
    deviationId: string,
    body: { root_cause_category: string; root_cause: string; immediate_action: string },
  ) =>
    request<ServerDeviation>(`/deviations/${deviationId}/investigate`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  closeDeviation: (
    deviationId: string,
    body: {
      capa_action: string;
      capa_notes: string;
      closure_notes: string;
      retest_run_id?: string | null;
    },
  ) =>
    request<ServerDeviation>(`/deviations/${deviationId}/close`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  cancelDeviation: (deviationId: string, reason: string) =>
    request<ServerDeviation>(`/deviations/${deviationId}/cancel`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),
};


/** Download a server-generated report (PDF / XLSX) through the authenticated path. */
export async function downloadReport(path: string, fallbackName: string): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { credentials: 'include' });
  } catch (error) {
    throw new OfflineError(error);
  }
  if (response.status === 401) {
    const refreshed = await refreshSession();
    if (refreshed) {
      response = await fetch(`${API_BASE}${path}`, { credentials: 'include' });
    }
  }
  if (!response.ok) {
    let body: Envelope<unknown> | null = null;
    try {
      body = (await response.json()) as Envelope<unknown>;
    } catch {
      body = null;
    }
    throw new ApiError(
      response.status,
      body?.errors?.[0] ?? {
        code: 'DOWNLOAD_FAILED',
        field: null,
        message_ar: 'تعذر توليد الملف',
        message_en: 'The file could not be generated',
      },
    );
  }

  const disposition = response.headers.get('content-disposition') ?? '';
  const match = /filename\*=UTF-8''([^;]+)/.exec(disposition);
  const filename = match ? decodeURIComponent(match[1]) : fallbackName;

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

// ────────────────────────────── adapters ─────────────────────────────────── //
// The browser types are camelCase and the API is snake_case; these adapters keep
// the UI unchanged and are covered by tests/api.test.ts.

export function toInstrument(row: ServerInstrument, departmentCode = '—'): Instrument {
  return {
    id: row.id,
    assetCode: row.asset_code,
    departmentCode,
    category: row.category,
    manufacturer: row.manufacturer,
    model: row.model,
    partNumber: row.part_number ?? '',
    serialNumber: row.serial_number,
    softwareVersion: row.software_version ?? '',
    calibrationFreqDays: row.calibration_freq_days,
    lastCalibrationDate: row.last_calibration_date,
    nextDueDate: row.next_due_date,
    status: row.status,
    d2LampHours: row.d2_lamp_hours,
  };
}

export function toReferenceEquipment(row: ServerReferenceEquipment, departmentCode = '—'): ReferenceEquipment {
  return {
    id: row.id,
    departmentCode,
    code: row.equipment_code,
    nameAr: row.name_ar,
    nameEn: row.name_en,
    serialNumber: row.serial_number,
    certificateNo: row.certificate_no,
    calibratedBy: row.calibrated_by,
    calibrationDate: row.calibration_date,
    expiryDate: row.expiry_date,
    correctionTable: row.correction_table_jsonb ?? [],
    isActive: row.is_active,
  };
}

export function toReferenceStandard(row: ServerReferenceStandard) {
  return {
    id: row.id,
    name: row.name,
    lotNumber: row.lot_number,
    purityPercent: Number(row.purity_percent),
    preparedAt: row.prepared_at,
    expiryDate: row.expiry_date,
    expired: row.expired,
    daysToExpiry: row.days_to_expiry,
  };
}

export function toUserAccount(row: ServerUser, departmentCode = '—'): UserAccount {
  const role = (row.roles[0] ?? 'VIEWER') as UserAccount['role'];
  return {
    id: row.id,
    username: row.username,
    fullNameAr: row.full_name_ar,
    fullNameEn: row.full_name_en,
    role,
    departmentCode: row.department_code ?? departmentCode,
    isActive: true,
    lastLoginAt: null,
  };
}

/** Server test results → the shape the charts and tables already consume. */
/**
 * The API serialises `Decimal` as a JSON string to avoid binary-float drift. The
 * engines and charts work on numbers, so revive numeric strings here — once, at
 * the boundary — instead of letting `Number.isFinite` silently fail downstream.
 */
function reviveNumeric(value: unknown): unknown {
  if (typeof value === 'string') {
    if (value.trim() === '') return value;
    const n = Number(value);
    return Number.isFinite(n) ? n : value;
  }
  if (Array.isArray(value)) return value.map(reviveNumeric);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, reviveNumeric(v)]),
    );
  }
  return value;
}

export function toRunTestResults(results: ServerTestResult[]): RunTestResult[] {
  return results.map((result) => ({
    testCode: result.test_code,
    rawInputs: (result.raw_inputs ? reviveNumeric(result.raw_inputs) : {}) as RunTestResult['rawInputs'],
    outputs: (result.outputs ? reviveNumeric(result.outputs) : {}) as RunTestResult['outputs'],
    status: result.status,
    notes: result.notes_ar ?? undefined,
    metricEvaluations: result.metric_evaluations.map((m) => ({
      metricKey: m.metric_key,
      value: m.value === null ? null : Number(m.value),
      unit: m.unit,
      appliedLimitId: m.applied_limit_id,
      appliedSource: m.applied_source,
      comparator: m.comparator,
      limitText: m.limit_text,
      status: m.status,
      message: m.message_ar ?? undefined,
    })),
  }));
}

export function toRunRecord(
  run: ServerRun,
  opts: { instrumentName: string; analyst: string; reviewer?: string | null; qaApprover?: string | null },
): RunRecord {
  return {
    id: run.id,
    executionCode: run.execution_code,
    instrumentId: run.instrument_id,
    instrumentName: opts.instrumentName,
    protocolCode: 'SHIMADZU-LC2050C-UV-CAL',
    runType: run.run_type,
    ambientTempC: run.ambient_temp_c ? Number(run.ambient_temp_c) : 0,
    ambientHumidity: run.ambient_humidity ? Number(run.ambient_humidity) : 0,
    analyst: opts.analyst,
    reviewer: opts.reviewer ?? null,
    qaApprover: opts.qaApprover ?? null,
    overallStatus: run.overall_status,
    results: toRunTestResults(run.results),
    startedAt: run.started_at,
    completedAt: run.completed_at,
    isLocked: run.is_locked,
    certificateHash: run.certificate_hash,
    breakdownComponent: run.breakdown_component,
    revision: run.revision,
  };
}
