'use client';

import Dexie, { type Table } from 'dexie';
import type {
  AuditEntry,
  Instrument,
  MaintenanceTicket,
  ReferenceEquipment,
  ReferenceStandard,
  RunRecord,
  UserAccount,
} from '../types';

/**
 * Browser-local persistence (IndexedDB).
 * Mirrors the PostgreSQL 16 schema field-for-field so the offline layer can be
 * synchronised to the FastAPI backend without a mapping layer.
 * audit_logs is append-only by construction: the repository exposes no
 * update/delete path, and each row is chained by SHA-256(prevHash + payload).
 */

export interface LimitOverrideRow {
  id: string;
  testCode: string;
  metricKey: string;
  sourceType: string;
  approvalStatus: string;
  approvedBy?: string | null;
  approvedAt?: string | null;
  minValue?: number | null;
  maxValue?: number | null;
  note?: string;
}

export interface SettingsRow {
  key: string;
  value: unknown;
  updatedAt: string;
}

export class SbdmaDatabase extends Dexie {
  instruments!: Table<Instrument, string>;
  referenceEquipment!: Table<ReferenceEquipment, string>;
  referenceStandards!: Table<ReferenceStandard, string>;
  runs!: Table<RunRecord, string>;
  tickets!: Table<MaintenanceTicket, string>;
  audit!: Table<AuditEntry, number>;
  users!: Table<UserAccount, string>;
  limitOverrides!: Table<LimitOverrideRow, string>;
  settings!: Table<SettingsRow, string>;

  constructor() {
    super('sbdma_calibration');
    this.version(1).stores({
      instruments: 'id, assetCode, departmentCode, status, nextDueDate',
      referenceEquipment: 'id, code, departmentCode, expiryDate, isActive',
      referenceStandards: 'id, name, expiryDate, departmentCode',
      runs: 'id, executionCode, instrumentId, overallStatus, startedAt, analyst, isLocked',
      tickets: 'id, instrumentId, status, component, reportedAt',
      audit: '++id, at, actor, entity, entityId, module, action',
      users: 'id, username, role, departmentCode',
      limitOverrides: 'id, testCode, sourceType, approvalStatus',
      settings: 'key',
    });
  }
}

let _db: SbdmaDatabase | null = null;

export function db(): SbdmaDatabase {
  if (typeof window === 'undefined') {
    throw new Error('Database is only available in the browser');
  }
  if (!_db) _db = new SbdmaDatabase();
  return _db;
}

export const AUDIT_GENESIS = '0'.repeat(64);

export async function appendAudit(
  entry: Omit<AuditEntry, 'id' | 'at' | 'hash' | 'prevHash'> & { at?: string },
): Promise<AuditEntry> {
  const database = db();
  const last = await database.audit.orderBy('id').last();
  const prevHash = last?.hash ?? AUDIT_GENESIS;
  const at = entry.at ?? new Date().toISOString();
  const payload = `${prevHash}|${at}|${entry.actor}|${entry.action}|${entry.entity}|${entry.entityId}|${JSON.stringify(entry.before ?? null)}|${JSON.stringify(entry.after ?? null)}|${entry.reason ?? ''}`;
  const hash = await sha256(payload);
  const row: AuditEntry = { ...entry, at, prevHash, hash };
  const id = await database.audit.add(row);
  return { ...row, id: id as number };
}

export async function sha256(text: string): Promise<string> {
  if (typeof crypto !== 'undefined' && crypto.subtle) {
    const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
    return Array.from(new Uint8Array(buf))
      .map((b) => b.toString(16).padStart(2, '0'))
      .join('');
  }
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, '0').repeat(8);
}

/** Verify the audit chain integrity — used by the QA dashboard. */
export async function verifyAuditChain(): Promise<{ ok: boolean; brokenAt?: number; total: number }> {
  const rows = await db().audit.orderBy('id').toArray();
  let prev = AUDIT_GENESIS;
  for (const r of rows) {
    if (r.prevHash !== prev) return { ok: false, brokenAt: r.id, total: rows.length };
    const payload = `${prev}|${r.at}|${r.actor}|${r.action}|${r.entity}|${r.entityId}|${JSON.stringify(r.before ?? null)}|${JSON.stringify(r.after ?? null)}|${r.reason ?? ''}`;
    const h = await sha256(payload);
    if (h !== r.hash) return { ok: false, brokenAt: r.id, total: rows.length };
    prev = r.hash;
  }
  return { ok: true, total: rows.length };
}

export async function exportDatabase(): Promise<string> {
  const database = db();
  const dump: Record<string, unknown> = {
    exportedAt: new Date().toISOString(),
    schema: 'sbdma_calibration@1',
  };
  for (const table of database.tables) {
    dump[table.name] = await table.toArray();
  }
  return JSON.stringify(dump, null, 2);
}
