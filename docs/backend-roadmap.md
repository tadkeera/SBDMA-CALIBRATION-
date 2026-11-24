# خادم FastAPI — المواصفة القابلة للتنفيذ

## المنجز فعلياً
- `backend/app/domain/math_engine/ast_engine.py` — المحرك المرجعي الكامل:
  AST مُتحقق منه، `Decimal` بعمق 40، إحصاء (mean, sd n−1, rsd, OLS, rs_deviation)،
  رفض كل بناء غير مسموح. **21/21 اختباراً ناجحاً**.
- `backend/requirements.txt` — تثبيت كل التبعيات بإصدارات محددة.
- `backend/Dockerfile` — صورة إنتاج غير جذرية مع Healthcheck.
- `backend/pytest.ini`.

## الهيكل المطلوب إكماله
```
backend/app/
├── main.py                  # تجميع التطبيق + middleware + routers
├── core/
│   ├── config.py            # Pydantic Settings — يرفض الإقلاع بسر ضعيف/افتراضي
│   ├── security.py          # Argon2id + JWT (access/refresh) + TOTP
│   ├── rbac.py              # Permission dependency + فحص النطاق
│   ├── exceptions.py        # معالجة مركزية + صيغة الاستجابة الموحدة
│   └── logging.py           # JSON logs + request_id
├── api/v1/                  # auth, departments, instruments, protocols, limits,
│                            # formulas, runs, reports, audit, settings, health, kpis
├── models/                  # SQLAlchemy 2.0 async — مطابق docs/database.md
├── schemas/                 # Pydantic v2 DTOs
├── repositories/            # استعلامات معزولة + ترقيم على الخادم
├── services/                # calibration, approval, audit, notification
├── workers/                 # celery_app.py + tasks/
└── integrations/            # email/, sms/, storage/, labsolutions_parser/
```

## ترتيب التنفيذ الموصى به
1. `config` + `logging` + `exceptions` + `/health` → أساس قابل للتشغيل.
2. `security` + `rbac` + `auth` → أول نقطة محمية حقيقية.
3. `models` + Alembic + Triggers + Seeders → قاعدة البيانات.
4. `limits` + `formulas` + `runs/execute` (يربط المحرك الجاهز) → القيمة الأساسية.
5. `review` + `approve` (فصل مهام + إقفال) → الامتثال.
6. `workers` (PDF/Excel/QR/تنبيهات) → المخرجات الرسمية.
7. `kpis` + `audit` + `settings` → الإدارة والمراقبة.

## عقود يجب ألا تُخالف
- `runs/execute` يستدعي `ast_engine.evaluate` فقط — لا حساب داخل الـ route.
- `approve` يفرض `analyst ≠ reviewer ≠ qa_approver` داخل Transaction مع `SELECT ... FOR UPDATE`.
- كل `UPDATE`/`DELETE` على `audit_logs` و`calibration_test_results(is_locked)` يفشل بـ Trigger.
- الاستجابة لا تكشف استثناءات داخلية؛ `request_id` يُعاد للمستخدم ويُربط بالسجل.
- `Decimal` يُحوَّل لـ `str` في JSON (لا `float`) للحفاظ على الدقة عبر الحدود.

## بوابة القبول قبل الانتقال للواجهة السحابية
- [ ] `pytest` يشمل Auth, RBAC Isolation, IDOR, Locked guard, Audit immutability.
- [ ] `alembic upgrade head` من قاعدة فارغة يعمل بلا أخطاء.
- [ ] Seeders تُنشئ البروتوكول و13 اختباراً و108 حد قبول و5 أقسام.
- [ ] `/health` يفحص PostgreSQL + Redis + Celery + Storage فعلياً.
- [ ] لا سر مكتوب في الكود (`git grep` على الأنماط الحساسة).
