# مخطط قاعدة البيانات — PostgreSQL 16+

مطابق لمخطط البرومبت الرئيسي (البند 05) ومُنفَّذ فعلياً كطبقة IndexedDB في
`src/core/db/database.ts` بنفس الأسماء والحقول، لتكون المزامنة مباشرة بلا طبقة تحويل.

## القواعد الإلزامية
- `NUMERIC(20,8)` لكل قراءة خام أو نتيجة محسوبة أو معامل إحصائي أو حد قبول. **يُمنع `FLOAT`/`REAL`**.
- `TIMESTAMPTZ` مع تخزين UTC داخلياً وعرض بتوقيت المستخدم.
- `UUID` كمفتاح أساسي (v7 لتقليل تجزئة الفهارس).
- `JSONB` + فهارس `GIN` للبيانات المرنة الموثقة فقط.
- تقسيم `audit_logs` سنوياً (`PARTITION BY RANGE (created_at)`).
- Soft delete (`deleted_at`) للكيانات الإدارية فقط: `lab_departments`, `users`, `instruments`.
- كل عمليات المعايرة والاعتماد داخل `SERIALIZABLE` transaction.

## الجداول

| الجدول | الغرض | أعمدة مفتاحية |
|---|---|---|
| `lab_departments` | أقسام ومختبرات الهيئة | `code UNIQUE`, `name_ar`, `name_en`, `location`, `is_active`, `deleted_at` |
| `roles` / `permissions` / `role_permissions` / `user_roles` | RBAC ديناميكي | `code`, `permission_code`, `department_id` في `user_roles` |
| `users` | المستخدمون | `username UNIQUE`, `password_hash` (Argon2id), `failed_login_count`, `locked_until`, `deleted_at` |
| `instruments` | سجل الأجهزة | `asset_code UNIQUE`, `category`, `manufacturer`, `model`, `part_number`, `serial_number`, `software_version`, `configuration_jsonb`, `calibration_freq_days`, `next_due_date`, `status` |
| `reference_equipment` | الأدوات المرجعية | `certificate_no`, `calibration_date`, `expiry_date`, `correction_table_jsonb`, `CHECK (expiry_date > calibration_date)` |
| `reference_standards` | المواد والمحاليل القياسية | `lot_number`, `purity_percent NUMERIC(10,4)`, `expiry_date` |
| `calibration_protocols` | البروتوكولات | `protocol_code UNIQUE`, `version`, `status`, `approved_by`, `approved_at` |
| `test_definitions` | تعريف الاختبارات الـ13 | `test_code`, `sequence_order`, `input_schema_jsonb`, `chart_config_jsonb`, `is_mandatory` |
| `acceptance_limits` | حدود القبول متعددة المصادر | `metric_key`, `source_type`, `operator`, `min_value`, `max_value`, `unit`, `approval_status`, `approved_by` |
| `formula_definitions` | المعادلات وإصداراتها | `expression_text`, `variables_jsonb`, `rounding_decimals`, `version`, `is_active` |
| `calibration_runs` | التشغيلات | `execution_code UNIQUE`, `run_type`, `overall_status`, `analyst_id`, `reviewer_id`, `qa_approver_id`, `certificate_hash CHAR(64)`, `is_locked` |
| `calibration_test_results` | نتائج الاختبارات | `raw_inputs_jsonb`, `calculated_outputs_jsonb`, `chart_series_jsonb`, `applied_limit_id`, `status`, `is_locked` |
| `calibration_attachments` | المرفقات | `sha256_checksum CHAR(64)`, `mime_type`, `storage_path` |
| `maintenance_tickets` | الأعطال والصيانة | `component_affected`, `required_tests_jsonb`, `status` |
| `system_settings` | الإعدادات المركزية | `key UNIQUE`, `value_jsonb`, `category` |
| `notifications` | الإشعارات | `channel`, `scheduled_at`, `sent_at`, `payload_jsonb` |
| `audit_logs` | سجل التدقيق (مقسم سنوياً) | `action`, `entity_type`, `entity_id`, `old_values`, `new_values`, `reason`, `ip_address INET`, `request_id` |

## Triggers الإلزامية

```sql
-- 1) منع أي تعديل أو حذف على سجل التدقيق
CREATE OR REPLACE FUNCTION trg_audit_immutable() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'audit_logs is append-only (ALCOA+ / 21 CFR Part 11)';
END; $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_audit_immutable
  BEFORE UPDATE OR DELETE ON audit_logs
  FOR EACH ROW EXECUTE FUNCTION trg_audit_immutable();

-- 2) منع تعديل النتائج المقفلة
CREATE OR REPLACE FUNCTION trg_locked_result_guard() RETURNS trigger AS $$
BEGIN
  IF OLD.is_locked THEN
    RAISE EXCEPTION 'calibration result % is locked after QA approval', OLD.id;
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_locked_result_guard
  BEFORE UPDATE OR DELETE ON calibration_test_results
  FOR EACH ROW EXECUTE FUNCTION trg_locked_result_guard();
```

## فهارس حرجة للأداء
```sql
CREATE INDEX CONCURRENTLY idx_runs_instrument_started ON calibration_runs (instrument_id, started_at DESC);
CREATE INDEX CONCURRENTLY idx_results_run ON calibration_test_results (run_id);
CREATE INDEX CONCURRENTLY idx_audit_created ON audit_logs USING brin (created_at);
CREATE INDEX CONCURRENTLY idx_audit_entity ON audit_logs (entity_type, entity_id);
CREATE INDEX CONCURRENTLY idx_limits_lookup ON acceptance_limits (test_definition_id, metric_key, source_type);
CREATE INDEX CONCURRENTLY idx_instruments_due ON instruments (next_due_date) WHERE deleted_at IS NULL;
CREATE INDEX CONCURRENTLY idx_runs_config_gin ON instruments USING gin (configuration_jsonb);
```

## عزل الأقسام (RLS)
```sql
ALTER TABLE calibration_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY runs_department_isolation ON calibration_runs
  USING (
    department_id = current_setting('app.department_id', true)::uuid
    OR current_setting('app.is_supervisor', true) = 'true'
  );
```
`app.department_id` و`app.is_supervisor` تُضبَط من طبقة الـ session في SQLAlchemy بعد
التحقق من JWT — لا تُقبل من العميل مطلقاً.
