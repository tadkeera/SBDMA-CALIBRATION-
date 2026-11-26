'use client';

import { LIMITS, TESTS } from '../protocol';
import type {
  Instrument,
  ReferenceEquipment,
  ReferenceStandard,
  UserAccount,
} from '../types';
import { appendAudit, db } from './database';

const TODAY = () => new Date();
const iso = (d: Date) => d.toISOString().slice(0, 10);
const addDays = (d: Date, n: number) => {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
};

export const SEED_USERS: UserAccount[] = [
  {
    id: 'usr-001',
    username: 'admin',
    fullNameAr: 'مدير النظام الأعلى',
    fullNameEn: 'Super Administrator',
    role: 'SUPER_ADMIN',
    departmentCode: 'CHEM-QC',
    isActive: true,
  },
  {
    id: 'usr-002',
    username: 'analyst',
    fullNameAr: 'أ. سامي الحداد — محلل أول',
    fullNameEn: 'Sami Al-Haddad — Senior Analyst',
    role: 'ANALYST',
    departmentCode: 'CHEM-QC',
    isActive: true,
  },
  {
    id: 'usr-003',
    username: 'reviewer',
    fullNameAr: 'د. منى الشامي — مراجع فني',
    fullNameEn: 'Dr. Muna Al-Shami — Lab Supervisor',
    role: 'SUPERVISOR',
    departmentCode: 'CHEM-QC',
    isActive: true,
  },
  {
    id: 'usr-004',
    username: 'qa',
    fullNameAr: 'أ. نادية باشراحيل — معتمد ضمان الجودة',
    fullNameEn: 'Nadia Bashaarheel — QA Approver',
    role: 'QA_APPROVER',
    departmentCode: 'CHEM-QC',
    isActive: true,
  },
  {
    id: 'usr-005',
    username: 'engineer',
    fullNameAr: 'م. فؤاد الجابري — هندسة وصيانة',
    fullNameEn: 'Fouad Al-Jabri — Engineering',
    role: 'ENGINEERING_SERVICE',
    departmentCode: 'CHEM-QC',
    isActive: true,
  },
  {
    id: 'usr-006',
    username: 'viewer',
    fullNameAr: 'مستخدم استعراض',
    fullNameEn: 'Viewer',
    role: 'VIEWER',
    departmentCode: 'CHEM-QC',
    isActive: true,
  },
];

export const SEED_INSTRUMENTS: Instrument[] = [
  {
    id: 'ins-lc2050c-01',
    assetCode: 'SBDMA-CHEM-HPLC-001',
    departmentCode: 'CHEM-QC',
    category: 'HPLC',
    manufacturer: 'Shimadzu',
    model: 'i-Series LC-2050C (UV Detector + Sample Cooler)',
    partNumber: 'S228-65821-58',
    serialNumber: 'L22976302572',
    softwareVersion: 'LabSolutions 6.9x',
    calibrationFreqDays: 180,
    lastCalibrationDate: iso(addDays(TODAY(), -97)),
    nextDueDate: iso(addDays(TODAY(), 83)),
    status: 'ACTIVE',
    d2LampHours: 1420,
  },
  {
    id: 'ins-hplc-02',
    assetCode: 'SBDMA-CHEM-HPLC-002',
    departmentCode: 'CHEM-QC',
    category: 'HPLC',
    manufacturer: 'Shimadzu',
    model: 'LC-2030 Plus (UV Detector)',
    partNumber: 'S228-65700-41',
    serialNumber: 'L22011400331',
    softwareVersion: 'LabSolutions 5.9x',
    calibrationFreqDays: 180,
    lastCalibrationDate: iso(addDays(TODAY(), -172)),
    nextDueDate: iso(addDays(TODAY(), 8)),
    status: 'ACTIVE',
    d2LampHours: 1865,
  },
  {
    id: 'ins-uvvis-01',
    assetCode: 'SBDMA-PHYS-UVVIS-001',
    departmentCode: 'PHYS-QC',
    category: 'UV-Vis',
    manufacturer: 'Shimadzu',
    model: 'UV-1900i',
    partNumber: '206-24000-38',
    serialNumber: 'A11655407123',
    softwareVersion: 'UVProbe 2.7x',
    calibrationFreqDays: 365,
    lastCalibrationDate: iso(addDays(TODAY(), -300)),
    nextDueDate: iso(addDays(TODAY(), 65)),
    status: 'ACTIVE',
    d2LampHours: 640,
  },
  {
    id: 'ins-balance-01',
    assetCode: 'SBDMA-CHEM-BAL-001',
    departmentCode: 'CHEM-QC',
    category: 'Analytical Balance',
    manufacturer: 'Mettler Toledo',
    model: 'XPR205',
    partNumber: '30254539',
    serialNumber: 'B938422011',
    softwareVersion: 'Firmware 3.2',
    calibrationFreqDays: 180,
    lastCalibrationDate: iso(addDays(TODAY(), -184)),
    nextDueDate: iso(addDays(TODAY(), -4)),
    status: 'UNDER_MAINTENANCE',
    d2LampHours: 0,
  },
  {
    id: 'ins-gc-01',
    assetCode: 'SBDMA-CHEM-GC-001',
    departmentCode: 'CHEM-QC',
    category: 'GC',
    manufacturer: 'Shimadzu',
    model: 'GC-2030 AF',
    partNumber: '221-97300-41',
    serialNumber: 'C12904400112',
    softwareVersion: 'LabSolutions 6.9x',
    calibrationFreqDays: 365,
    lastCalibrationDate: iso(addDays(TODAY(), -120)),
    nextDueDate: iso(addDays(TODAY(), 245)),
    status: 'ACTIVE',
    d2LampHours: 0,
  },
  {
    id: 'ins-dissolution-01',
    assetCode: 'SBDMA-PHYS-DIS-001',
    departmentCode: 'PHYS-QC',
    category: 'Dissolution',
    manufacturer: 'Agilent',
    model: '708-DS',
    partNumber: '708-0001',
    serialNumber: 'DS22045577',
    softwareVersion: 'Dissolution Workstation 2.3',
    calibrationFreqDays: 180,
    lastCalibrationDate: iso(addDays(TODAY(), -60)),
    nextDueDate: iso(addDays(TODAY(), 120)),
    status: 'ACTIVE',
    d2LampHours: 0,
  },
  {
    id: 'ins-autoclave-01',
    assetCode: 'SBDMA-MICRO-AUT-001',
    departmentCode: 'MICRO-QC',
    category: 'Autoclave',
    manufacturer: 'Tuttnauer',
    model: '3870 ELV',
    partNumber: '3870ELV',
    serialNumber: 'TU19082211',
    softwareVersion: 'Controller 1.8',
    calibrationFreqDays: 365,
    lastCalibrationDate: iso(addDays(TODAY(), -30)),
    nextDueDate: iso(addDays(TODAY(), 335)),
    status: 'ACTIVE',
    d2LampHours: 0,
  },
  {
    id: 'ins-chamber-01',
    assetCode: 'SBDMA-STAB-CHM-001',
    departmentCode: 'STABILITY-QC',
    category: 'Stability Chamber',
    manufacturer: 'Binder',
    model: 'KBF 720',
    partNumber: '9020-0331',
    serialNumber: 'KB2113345',
    softwareVersion: 'APT-COM 4',
    calibrationFreqDays: 180,
    lastCalibrationDate: iso(addDays(TODAY(), -45)),
    nextDueDate: iso(addDays(TODAY(), 135)),
    status: 'ACTIVE',
    d2LampHours: 0,
  },
];

export const SEED_REFERENCE_EQUIPMENT: ReferenceEquipment[] = [
  {
    id: 'ref-thermo-01',
    departmentCode: 'CHEM-QC',
    code: 'REF-TH-014',
    nameAr: 'مقياس حرارة رقمي معاير (JIS Cl.1)',
    nameEn: 'Calibrated digital thermometer (JIS Cl.1)',
    serialNumber: 'TH-2291',
    certificateNo: 'CAL-2026-0148',
    calibratedBy: 'مركز المعايرة الوطني — عدن',
    calibrationDate: iso(addDays(TODAY(), -200)),
    expiryDate: iso(addDays(TODAY(), 165)),
    correctionTable: [
      [0, 0.12],
      [20, 0.08],
      [40, 0.05],
      [50, 0.04],
      [70, 0.02],
    ],
    isActive: true,
  },
  {
    id: 'ref-thermo-02',
    departmentCode: 'CHEM-QC',
    code: 'REF-TH-015',
    nameAr: 'مقياس حرارة رقمي احتياطي',
    nameEn: 'Backup digital thermometer',
    serialNumber: 'TH-3384',
    certificateNo: 'CAL-2025-0921',
    calibratedBy: 'مركز المعايرة الوطني — عدن',
    calibrationDate: iso(addDays(TODAY(), -380)),
    expiryDate: iso(addDays(TODAY(), -15)),
    correctionTable: [
      [0, 0.2],
      [25, 0.15],
      [50, 0.1],
    ],
    isActive: true,
  },
  {
    id: 'ref-stopwatch-01',
    departmentCode: 'CHEM-QC',
    code: 'REF-SW-007',
    nameAr: 'ساعة إيقاف معايرة',
    nameEn: 'Calibrated stopwatch',
    serialNumber: 'SW-77120',
    certificateNo: 'CAL-2026-0203',
    calibratedBy: 'مركز المعايرة الوطني — عدن',
    calibrationDate: iso(addDays(TODAY(), -120)),
    expiryDate: iso(addDays(TODAY(), 245)),
    isActive: true,
  },
  {
    id: 'ref-flask-5ml',
    departmentCode: 'CHEM-QC',
    code: 'REF-VF-5ML',
    nameAr: 'دورق حجمي 5 mL Class A',
    nameEn: 'Volumetric flask 5 mL Class A',
    serialNumber: 'VF-5-0912',
    certificateNo: 'CAL-2026-0311',
    calibratedBy: 'مركز المعايرة الوطني — عدن',
    calibrationDate: iso(addDays(TODAY(), -90)),
    expiryDate: iso(addDays(TODAY(), 275)),
    isActive: true,
  },
  {
    id: 'ref-weight-e2',
    departmentCode: 'CHEM-QC',
    code: 'REF-WT-E2',
    nameAr: 'أوزان معايرة E2',
    nameEn: 'E2 calibration weights set',
    serialNumber: 'WT-E2-2205',
    certificateNo: 'CAL-2026-0088',
    calibratedBy: 'مركز المعايرة الوطني — عدن',
    calibrationDate: iso(addDays(TODAY(), -150)),
    expiryDate: iso(addDays(TODAY(), 215)),
    isActive: true,
  },
  {
    id: 'ref-filter-jcrm',
    departmentCode: 'CHEM-QC',
    code: 'REF-AB-JCRM230A',
    nameAr: 'فلتر امتصاصية قياسي خارجي JCRM230A',
    nameEn: 'External absorbance standard filter JCRM230A',
    serialNumber: 'JCRM-230A-0041',
    certificateNo: 'CAL-2025-1777',
    calibratedBy: 'Shimadzu — شهادة المصنع',
    calibrationDate: iso(addDays(TODAY(), -420)),
    expiryDate: iso(addDays(TODAY(), -55)),
    isActive: true,
  },
];

export const SEED_REFERENCE_STANDARDS: ReferenceStandard[] = [
  {
    id: 'std-caffeine',
    departmentCode: 'CHEM-QC',
    name: 'كافيين (Caffeine) — مادة مرجعية',
    partNumber: '228-67619-41',
    lotNumber: 'CFN-24K0917',
    purityPercent: 99.82,
    preparedAt: iso(addDays(TODAY(), -25)),
    expiryDate: iso(addDays(TODAY(), 155)),
  },
  {
    id: 'std-acetone',
    departmentCode: 'CHEM-QC',
    name: 'أسيتون 0.1% (Acetone)',
    partNumber: '228-45725-06',
    lotNumber: 'ACT-24M0442',
    purityPercent: 99.5,
    preparedAt: iso(addDays(TODAY(), -12)),
    expiryDate: iso(addDays(TODAY(), 18)),
  },
  {
    id: 'std-water',
    departmentCode: 'CHEM-QC',
    name: 'ماء HPLC نقي (Type I)',
    partNumber: '—',
    lotNumber: 'WTR-2026-118',
    purityPercent: 100,
    preparedAt: iso(addDays(TODAY(), -2)),
    expiryDate: iso(addDays(TODAY(), 12)),
  },
  {
    id: 'std-methanol',
    departmentCode: 'CHEM-QC',
    name: 'ميثانول (HPLC grade)',
    partNumber: '—',
    lotNumber: 'MTH-24N1103',
    purityPercent: 99.9,
    preparedAt: iso(addDays(TODAY(), -40)),
    expiryDate: iso(addDays(TODAY(), 320)),
  },
];

export async function seedIfEmpty(): Promise<{ seeded: boolean }> {
  const database = db();
  const count = await database.instruments.count();
  if (count > 0) return { seeded: false };

  await database.transaction(
    'rw',
    [database.instruments, database.referenceEquipment, database.referenceStandards, database.users, database.audit, database.settings],
    async () => {
      await database.users.bulkPut(SEED_USERS);
      await database.instruments.bulkPut(SEED_INSTRUMENTS);
      await database.referenceEquipment.bulkPut(SEED_REFERENCE_EQUIPMENT);
      await database.referenceStandards.bulkPut(SEED_REFERENCE_STANDARDS);
      await database.settings.bulkPut([
        { key: 'defaultLimitSource', value: 'AUTHORITY_LIMIT', updatedAt: new Date().toISOString() },
        { key: 'protocolCode', value: 'SHIMADZU-LC2050C-UV-CAL', updatedAt: new Date().toISOString() },
        { key: 'protocolVersion', value: '1.0.0', updatedAt: new Date().toISOString() },
        { key: 'lang', value: 'ar', updatedAt: new Date().toISOString() },
        { key: 'theme', value: 'light', updatedAt: new Date().toISOString() },
      ]);
      await appendAudit({
        actor: 'SYSTEM (seeder)',
        role: 'SYSTEM_ADMIN',
        action: 'SEED_PROTOCOL_BLUEPRINT',
        entity: 'calibration_protocol',
        entityId: 'SHIMADZU-LC2050C-UV-CAL',
        module: 'system',
        after: {
          tests: TESTS.length,
          limits: LIMITS.length,
          instruments: SEED_INSTRUMENTS.length,
          referenceEquipment: SEED_REFERENCE_EQUIPMENT.length,
        },
        reason: 'تهيئة البيانات المرجعية للبروتوكول وأقسام الهيئة',
      });
    },
  );
  return { seeded: true };
}

export async function resetDatabase(): Promise<void> {
  const database = db();
  await Promise.all(database.tables.map((t) => t.clear()));
  await seedIfEmpty();
}
