/**
 * Thin HTTP client for the FastAPI backend, used by the suite for *setup* and for
 * reading state it has to assert on.
 *
 * The user-facing behaviour is always driven through the browser; this exists so a
 * test can ask "which run did the analyst just create?" without scraping the DOM,
 * and so global setup can enrol the second factor before any page loads.
 *
 * Authentication is cookie-based (`sbdma_access` / `sbdma_refresh`, httpOnly), so a
 * context that has signed in keeps its session automatically.
 */

import type { APIRequestContext } from '@playwright/test';
import { request as playwrightRequest } from '@playwright/test';

export const API_ORIGIN = process.env.E2E_API_ORIGIN ?? 'http://127.0.0.1:8000';
const API = `${API_ORIGIN}/api/v1`;

export interface Envelope<T> {
  success: boolean;
  data: T;
  meta?: Record<string, unknown>;
  errors?: Array<{ code: string; message_ar: string; message_en: string }>;
}

export class ApiFailure extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

/** A fresh, independent session (its own cookie jar). Call `dispose()` when done. */
export async function newApiSession(): Promise<APIRequestContext> {
  return playwrightRequest.newContext({
    baseURL: API,
    extraHTTPHeaders: { Accept: 'application/json' },
  });
}

async function call<T>(
  context: APIRequestContext,
  method: 'GET' | 'POST',
  path: string,
  body?: unknown,
  expectStatus?: number,
): Promise<{ data: T; status: number; meta?: Record<string, unknown> }> {
  const response =
    method === 'GET'
      ? await context.get(`${API}${path}`)
      : await context.post(`${API}${path}`, { data: body ?? {} });
  const status = response.status();
  let parsed: Envelope<T> | null = null;
  const text = await response.text();
  try {
    parsed = text ? (JSON.parse(text) as Envelope<T>) : null;
  } catch {
    parsed = null;
  }
  if (expectStatus !== undefined && status === expectStatus) {
    return { data: (parsed?.data as T) ?? (null as T), status, meta: parsed?.meta };
  }
  if (!response.ok() || !parsed || parsed.success === false) {
    const error = parsed?.errors?.[0];
    throw new ApiFailure(
      status,
      error?.code ?? 'HTTP_ERROR',
      `${method} ${path} → ${status}: ${error?.message_en ?? text.slice(0, 200)}`,
    );
  }
  return { data: parsed.data, status, meta: parsed.meta };
}

export interface SessionUser {
  id: string;
  username: string;
  roles: string[];
  permissions: string[];
  mfa_enrolment_required: boolean;
}

export interface LoginResult {
  access_token: string;
  user: SessionUser;
}

/**
 * Password sign-in. A role that mandates a second factor but has not enrolled
 * still returns a restricted session, flagged by `mfa_enrolment_required`.
 */
export async function login(
  context: APIRequestContext,
  username: string,
  password: string,
  totpCode?: string,
): Promise<LoginResult> {
  const { data } = await call<LoginResult>(context, 'POST', '/auth/login', {
    username,
    password,
    ...(totpCode ? { totp_code: totpCode } : {}),
  });
  return data;
}

/** Start enrolment: the secret is returned exactly once, for the QR code. */
export async function enrol(context: APIRequestContext): Promise<{ secret: string }> {
  const { data } = await call<{ secret: string; otpauth_uri: string }>(
    context,
    'POST',
    '/auth/mfa/enrol',
  );
  return data;
}

/** Prove possession of the pending secret; returns the recovery codes once. */
export async function activate(
  context: APIRequestContext,
  code: string,
): Promise<{ recovery_codes?: string[] }> {
  const { data } = await call<{ recovery_codes?: string[] }>(
    context,
    'POST',
    '/auth/mfa/activate',
    { code },
  );
  return data;
}

export interface RunSummary {
  id: string;
  execution_code: string;
  overall_status: string;
  is_locked: boolean;
  analyst_id: string;
  started_at: string | null;
}

/** Runs visible to the signed-in principal, newest page first. */
export async function listRuns(
  context: APIRequestContext,
  pageSize = 10,
): Promise<RunSummary[]> {
  const { data } = await call<RunSummary[]>(context, 'GET', `/runs?page=1&page_size=${pageSize}`);
  return data;
}

export interface RunDetail extends RunSummary {
  reviewer_id: string | null;
  qa_approver_id: string | null;
  reviewed_at: string | null;
  qa_approved_at: string | null;
  certificate_hash: string | null;
  results: Array<{
    test_code: string;
    status: string;
    metric_evaluations: unknown[];
    raw_inputs: Record<string, unknown>;
    outputs: Record<string, unknown>;
  }>;
}

export async function getRun(context: APIRequestContext, id: string): Promise<RunDetail> {
  const { data } = await call<RunDetail>(context, 'GET', `/runs/${id}`);
  return data;
}

export async function instruments(
  context: APIRequestContext,
): Promise<Array<{ id: string; code: string; name: string }>> {
  const { data } = await call<Array<{ id: string; code: string; name: string }>>(
    context,
    'GET',
    '/instruments',
  );
  return data;
}

export interface HealthReport {
  status: string;
  components?: Record<string, string>;
}

/** Readiness probe used by global setup: the suite refuses to start on a dead API. */
export async function health(context: APIRequestContext): Promise<HealthReport> {
  const response = await context.get(`${API}/health`);
  if (!response.ok()) {
    throw new Error(`API health probe failed: ${response.status()} ${await response.text()}`);
  }
  const envelope = (await response.json()) as Envelope<HealthReport>;
  if (!envelope.data) throw new Error(`API health returned no data: ${JSON.stringify(envelope)}`);
  return envelope.data;
}
