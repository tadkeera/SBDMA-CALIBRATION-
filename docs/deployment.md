# النشر والتشغيل

## 1) Docker Compose (بيئة اختبار/تحقق)
```bash
cp .env.example .env      # غيّر كل CHANGE_ME — الخادم يرفض الإقلاع بسر افتراضي
docker compose up -d --build
docker compose ps
curl -fsS http://localhost/api/v1/health | jq
```
الخدمات: `postgres`, `redis`, `api`, `worker`, `beat`, `web`, `nginx`.

## 2) Kubernetes (إنتاج)
```bash
kubectl create namespace sbdma
kubectl -n sbdma create secret generic sbdma-secrets \
  --from-literal=DATABASE_URL=... \
  --from-literal=JWT_SECRET=... \
  --from-literal=REDIS_URL=...
kubectl -n sbdma apply -f infra/k8s/
kubectl -n sbdma rollout status deploy/sbdma-api
```

**ضمانات عدم التوقف المُهيَّأة:**
- `maxUnavailable: 0` مع `maxSurge: 1` → تحديث تدريجي بلا انقطاع.
- `startupProbe` / `readinessProbe` / `livenessProbe` منفصلة (منع إعادة التشغيل أثناء الإقلاع البطيء).
- `HorizontalPodAutoscaler` 3→12 نسخة على CPU 70% وذاكرة 80%.
- `PodDisruptionBudget minAvailable: 2` يحمي من إخلاء العقد.
- `terminationGracePeriodSeconds: 45` لإكمال الطلبات الجارية.
- `beat` بنسخة واحدة فقط (تكرار المُجدول يضاعف التنبيهات).

## 3) Nginx
TLS 1.2/1.3 فقط · HSTS preload · CSP صارم · `X-Frame-Options` · `X-Content-Type-Options` ·
`Referrer-Policy` · `Permissions-Policy` · حدود معدل منفصلة للمصادقة والتصدير · `server_tokens off`.

## 4) النسخ الاحتياطي والاستعادة
```bash
# نسخ يومي 02:00 UTC (cron أو Celery beat)
0 2 * * * /srv/sbdma/infra/scripts/backup_postgres.sh >> /var/log/sbdma-backup.log 2>&1

# استعادة موثقة (تتحقق من البصمة وتطلب تأكيداً كتابياً)
./infra/scripts/restore_postgres.sh /srv/backups/sbdma_sbdma_calibration_20261125T020000Z.dump
```
- `pg_dump -Fc` مضغوط + `sha256` + اختبار `pg_restore --list` قبل الاعتماد.
- أرشفة WAL مفعّلة (`archive_mode=on`) لدعم **PITR**.
- الاستعادة تُنفَّذ على نسخة أولاً — الاستعادة فوق الإنتاج مباشرة ممنوعة بالإجراء.

## 5) فحص ما بعد النشر
1. `/api/v1/health` أخضر لكل التبعيات.
2. تسجيل دخول بدور `ANALYST` وتشغيل اختبار واحد.
3. التحقق من `SELECT count(*) FROM audit_logs` بعد العملية.
4. تنفيذ استعادة تجريبية على بيئة staging ومقارنة عدد السجلات.
