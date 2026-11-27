/**
 * SBDMA Calibration Platform — Core domain types
 * Scientific reference: HPLC_LC2050C_UV_Calibration_Protocol_and_Comparative_Report.docx
 * All measurement values are kept at full precision and rounded only at presentation.
 */

export type Lang = 'ar' | 'en';
export type Status = 'PASS' | 'FAIL' | 'UNDER_REVIEW' | 'INCOMPLETE';

export const LIMIT_SOURCES = [
  'INTEGRITY_GUIDE_CH2',
  'IOQ_PROTOCOL_CH4',
  'MANUFACTURER_SPEC',
  'SOP_LIMIT',
  'AUTHORITY_LIMIT',
] as const;
export type LimitSource = (typeof LIMIT_SOURCES)[number];

export const SOURCE_LABELS: Record<LimitSource, { ar: string; en: string; short: string }> = {
  INTEGRITY_GUIDE_CH2: { ar: 'دليل شيمادزو — الفصل 2', en: 'Shimadzu Integrity Guide Ch.2', short: 'S1' },
  IOQ_PROTOCOL_CH4: { ar: 'بروتوكول iOQ — الفصل 4', en: 'Shimadzu iOQ Protocol Ch.4', short: 'S2' },
  MANUFACTURER_SPEC: { ar: 'مواصفات المصنع C196-E099B', en: 'Manufacturer Spec C196-E099B', short: 'S3' },
  SOP_LIMIT: { ar: 'إجراء التشغيل الداخلي SOP', en: 'Internal SOP RHPL/AD/044', short: 'S4' },
  AUTHORITY_LIMIT: { ar: 'الحد المعتمد من ضمان الجودة', en: 'QA Authority Limit', short: 'S5' },
};

export type ApprovalStatus = 'UNAPPROVED' | 'APPROVED' | 'CONFLICT_REQUIRES_QA' | 'REJECTED';

export interface AcceptanceLimit {
  id: string;
  testCode: string;
  metricKey: string;
  sourceType: LimitSource;
  operator: 'lte' | 'gte' | 'abs_lte' | 'between' | 'equals';
  minValue: number | null;
  maxValue: number | null;
  unit: string;
  approvalStatus: ApprovalStatus;
  approvedBy?: string | null;
  approvedAt?: string | null;
  note?: string;
  /** true when the source is known to carry a documented defect (e.g. SOP GAP-02 unit error) */
  flagged?: boolean;
}

export type FieldType = 'number' | 'integer' | 'series' | 'text' | 'select' | 'boolean' | 'spectrum';

export interface FieldSpec {
  key: string;
  labelAr: string;
  labelEn: string;
  type: FieldType;
  unit?: string;
  min?: number;
  max?: number;
  step?: number;
  options?: string[];
  /** number of expected values for series/spectrum inputs */
  length?: number;
  required?: boolean;
  hintAr?: string;
  hintEn?: string;
}

export interface FormulaSpec {
  key: string;
  expression: string; // safe AST expression (server-validated grammar)
  descriptionAr: string;
  descriptionEn: string;
  decimals: number;
}

export interface TestSpec {
  code: string;
  sequence: number;
  nameAr: string;
  nameEn: string;
  module:
    | 'AUTO'
    | 'PUMP'
    | 'GPV'
    | 'INJECTOR'
    | 'AUTOSAMPLER'
    | 'TEMPERATURE'
    | 'OVEN'
    | 'DETECTOR'
    | 'SYSTEM';
  standard: string;
  procedureAr: string[];
  /** Documented procedure in English (USP/ISO 17025 wording) — printed dir="ltr". */
  procedureEn: string[];
  fields: FieldSpec[];
  formulas: FormulaSpec[];
  metrics: string[]; // metric keys evaluated against limits
  chart: 'flow' | 'gradient' | 'linearity' | 'residual' | 'spectrum' | 'repeatability' | 'temperature' | 'bar' | 'none';
  mandatory: boolean;
}

export interface RunTestResult {
  testCode: string;
  rawInputs: Record<string, unknown>;
  outputs: Record<string, number | number[] | string>;
  metricEvaluations: MetricEvaluation[];
  status: Status;
  notes?: string;
}

export interface MetricEvaluation {
  metricKey: string;
  value: number | null;
  unit: string;
  appliedLimitId: string | null;
  appliedSource: LimitSource | null;
  comparator: string;
  limitText: string;
  status: Status;
  message?: string;
}

export interface RunRecord {
  id: string;
  executionCode: string;
  instrumentId: string;
  instrumentName: string;
  protocolCode: string;
  runType: 'ROUTINE' | 'POST_BREAKDOWN' | 'INSTALLATION' | 'ANNUAL';
  ambientTempC: number;
  ambientHumidity: number;
  analyst: string;
  reviewer?: string | null;
  qaApprover?: string | null;
  overallStatus: Status;
  results: RunTestResult[];
  startedAt: string;
  completedAt?: string | null;
  isLocked: boolean;
  certificateHash?: string | null;
  breakdownComponent?: string | null;
  revision: number;
}

export interface Instrument {
  id: string;
  assetCode: string;
  departmentCode: string;
  category: string;
  manufacturer: string;
  model: string;
  partNumber: string;
  serialNumber: string;
  softwareVersion: string;
  calibrationFreqDays: number;
  lastCalibrationDate: string | null;
  nextDueDate: string | null;
  status: 'ACTIVE' | 'OUT_OF_SERVICE' | 'UNDER_MAINTENANCE';
  d2LampHours: number;
}

export interface ReferenceEquipment {
  id: string;
  departmentCode: string;
  code: string;
  nameAr: string;
  nameEn: string;
  serialNumber: string;
  certificateNo: string;
  calibratedBy: string;
  calibrationDate: string;
  expiryDate: string;
  /** [temperatureC, correctionC] pairs — linear interpolation applied */
  correctionTable?: number[][];
  isActive: boolean;
}

export interface ReferenceStandard {
  id: string;
  departmentCode: string;
  name: string;
  partNumber: string;
  lotNumber: string;
  purityPercent: number;
  preparedAt: string;
  expiryDate: string;
}

export interface MaintenanceTicket {
  id: string;
  instrumentId: string;
  instrumentName: string;
  component: string;
  componentAr: string;
  description: string;
  requiredTests: string[];
  status: 'OPEN' | 'IN_PROGRESS' | 'RESOLVED' | 'CLOSED';
  reportedBy: string;
  reportedAt: string;
  resolvedBy?: string | null;
  resolvedAt?: string | null;
}

export interface AuditEntry {
  id?: number;
  at: string;
  actor: string;
  role: string;
  action: string;
  entity: string;
  entityId: string;
  reason?: string;
  before?: unknown;
  after?: unknown;
  module: string;
  hash: string;
  prevHash: string;
}

export interface UserAccount {
  id: string;
  username: string;
  fullNameAr: string;
  fullNameEn: string;
  role: RoleCode;
  departmentCode: string;
  isActive: boolean;
  lastLoginAt?: string | null;
}

export const ROLES = [
  'SUPER_ADMIN',
  'SYSTEM_ADMIN',
  'ANALYST',
  'SUPERVISOR',
  'QA_APPROVER',
  'ENGINEERING_SERVICE',
  'VIEWER',
] as const;
export type RoleCode = (typeof ROLES)[number];

export const ROLE_LABELS: Record<RoleCode, { ar: string; en: string }> = {
  SUPER_ADMIN: { ar: 'مدير النظام الأعلى', en: 'Super Admin' },
  SYSTEM_ADMIN: { ar: 'مسؤول النظام', en: 'System Admin' },
  ANALYST: { ar: 'محلل مختبر', en: 'Analyst' },
  SUPERVISOR: { ar: 'مشرف المختبر', en: 'Supervisor' },
  QA_APPROVER: { ar: 'معتمد ضمان الجودة', en: 'QA Approver' },
  ENGINEERING_SERVICE: { ar: 'هندسة وصيانة', en: 'Engineering & Service' },
  VIEWER: { ar: 'مستخدم استعراض', en: 'Viewer' },
};

export const PERMISSIONS = [
  'instruments.view',
  'instruments.create',
  'instruments.update',
  'instruments.delete',
  'calibration.run',
  'calibration.review',
  'calibration.approve',
  'limits.manage',
  'limits.approve',
  'formulas.manage',
  'reports.export',
  'audit.view',
  'settings.manage',
  'users.manage',
  'maintenance.manage',
  'attachments.manage',
  'deviations.raise',
  'deviations.investigate',
  'deviations.close',
  // granting an approval signature to another account (the administrator's "QA APPROVED"
  // authority). Separate from users.manage on purpose — see app/core/rbac.py.
  'authority.grant',
  'tests.manage_status',
] as const;
export type Permission = (typeof PERMISSIONS)[number];

export const ROLE_PERMISSIONS: Record<RoleCode, Permission[]> = {
  SUPER_ADMIN: [...PERMISSIONS],
  SYSTEM_ADMIN: [
    'instruments.view',
    'instruments.create',
    'instruments.update',
    'instruments.delete',
    'limits.manage',
    'formulas.manage',
    'tests.manage_status',
    'reports.export',
    'audit.view',
    'settings.manage',
    'users.manage',
    'maintenance.manage',
    'attachments.manage',
    // the approval office reads results and handles deviations; the administrator that
    // may appoint an approver must hold the same, or it could not confer them (2.4.0)
    'calibration.review',
    'deviations.raise',
    'deviations.investigate',
    'deviations.close',
    // 2.4.0: an administrator may award the QA signature. It still holds no signature of
    // its own — it cannot approve a run — and nobody signs a run they executed.
    'authority.grant',
  ],
  ANALYST: ['instruments.view', 'calibration.run', 'reports.export', 'deviations.raise'],
  SUPERVISOR: ['instruments.view', 'calibration.run', 'calibration.review', 'reports.export'],
  QA_APPROVER: [
    'instruments.view',
    'calibration.review',
    'calibration.approve',
    // QA may appoint a second approver: the office that owns the signature decides who
    // else may hold it, which is how a one-person QA unit survives an absence.
    'authority.grant',
    'limits.approve',
    'limits.manage',
    'reports.export',
    'audit.view',
    'deviations.raise',
    'deviations.investigate',
    'deviations.close',
  ],
  ENGINEERING_SERVICE: [
    'instruments.view',
    'maintenance.manage',
    'reports.export',
    'deviations.raise',
  ],
  VIEWER: ['instruments.view'],
};

export const DEPARTMENTS = [
  { code: 'CHEM-QC', nameAr: 'الكيمياء التحليلية', nameEn: 'Analytical Chemistry' },
  { code: 'PHYS-QC', nameAr: 'الفيزياء والصيدلانيات', nameEn: 'Physical & Pharmaceutical' },
  { code: 'MICRO-QC', nameAr: 'الميكروبيولوجي', nameEn: 'Microbiology' },
  { code: 'STABILITY-QC', nameAr: 'الثبات', nameEn: 'Stability Studies' },
  { code: 'ADEN-BR', nameAr: 'فرع عدن', nameEn: 'Aden Branch' },
];

export const PROTOCOL_CODE = 'SHIMADZU-LC2050C-UV-CAL';
export const PROTOCOL_VERSION = '1.0.0';
