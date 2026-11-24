# خادم FastAPI — الحالة الفعلية

> آخر تحديث: 2026-11-25 — **المرحلة A مكتملة وقيد التشغيل**. كل ما هو موسوم بـ«منجز»
> أدناه مُنفَّذ فعلياً ومُختبر على PostgreSQL حقيقي، ولا يوجد رمز وهمي أو نقطة نهاية مُعلنة بلا تنفيذ.

## المنجز

### البنية
```
backend/
├── app/
│   ├── main.py                 ✅ إنشاء التطبيق، lifespan، CORS، 3 أنواع Middleware
│   ├── core/
│   │   ├── config.py           ✅ Settings — يرفض الإقلاع بسر ضعيف في staging/production
│   │   ├── database.py         ✅ محرك async + SessionFactory + session_scope + ping
│   │   ├── security.py         ✅ Argon2id، JWT access/refresh، sha256، بصمة شهادة
│   │   ├── rbac.py             ✅ 15 صلاحية · 7 أدوار · Principal · فحص القسم · فصل المهام
│   │   ├── exceptions.py       ✅ 12 نوع خطأ + معالجات مركزية + الصيغة الموحدة
│   │   └── logging.py          ✅ JSON/plain + request_id + user + department
│   ├── models/                 ✅ 21 جدولاً (rbac, assets, protocol, runs, audit)
│   ├── schemas/                ✅ common, auth, runs, assets
│   ├── domain/
│   │   ├── math_engine/        ✅ AST آمن — لا eval/exec
│   │   ├── protocol/blueprint  ✅ 13 اختباراً · 108 حداً · 54 معادلة · مصفوفة أعطال
│   │   └── scoring/engine.py   ✅ محكمة الحوكمة + execute_run
│   ├── services/               ✅ auth_service · run_service · audit_service (سلسلة Hash)
│   ├── api/
│   │   ├── deps.py             ✅ JWT → Principal + نطاق القسم
│   │   ├── middleware.py       ✅ request-id · رؤوس أمان · حد طلبات بنافذة منزلقة
│   │   └── v1/                 ✅ health · auth · runs · catalogue (27 مساراً)
│   └── seed/                   ✅ rbac · protocol · assets · users — حتمية وقابلة للتكرار
├── alembic/versions/           ✅ 0001_initial · 0002_governance_triggers
├── docker-entrypoint.sh        ✅ alembic upgrade head قبل الإقلاع
└── tests/                      ✅ 70 اختباراً (منها 33 على HTTP + PostgreSQL حقيقي)
```

### الحواجز غير القابلة للتجاوز (مُختبرة بـ SQL مباشر)
| الحاجز | التنفيذ | الاختبار |
|---|---|---|
| سجل التدقيق ملحق فقط | `trg_audit_immutable` + `trg_audit_no_truncate` | `UPDATE`/`DELETE`/`TRUNCATE` مرفوضة |
| النتائج المقفلة | `trg_locked_result_guard` | تعديل/حذف 13 نتيجة مقفلة مرفوض |
| التشغيل المقفل | `trg_locked_run_guard` | إعادة الفتح/تغيير الشهادة/الحذف مرفوض |
| الأداة المرجعية المنتهية | `trg_expiry_guard` + خدمة | 422 `EXPIRY_GUARD` |
| حدود غير معتمدة | `evaluate_metric` ⇒ `UNDER_REVIEW` | الاعتماد محظور 422 `LIMIT_CONFLICT` |
| فصل المهام | `assert_segregation_of_duties` | 403 `SEGREGATION_OF_DUTIES` |
| عزل الأقسام | `Principal.assert_department` | 404 لا 403 (بلا تسريب وجود) |

## الخطوة التالية (المرحلة B)

1. **الربط الفعلي مع الواجهة:** استبدال طبقة IndexedDB في `src/core/db` بعميل HTTP
   (`fetch` مع `credentials: 'include'`) مع إبقاء الواجهة تعمل دون اتصال (تخزين مؤقت للقراءة فقط).
   **لا حذف للبيانات المحلية الموجودة** — تُستخدم كنسخة قراءة فقط عند انقطاع الشبكة.
2. **التقارير:** `/runs/{id}/certificate.pdf` (ReportLab + QR) و`/runs/{id}/export.xlsx` (openpyxl)
   مع نفس بصمة الشهادة المخزنة في القاعدة.
3. **المرفقات:** `POST /instruments/{id}/attachments` + تحقق SHA-256 + حد 25MB + `trg` يمنع الحذف.
4. **إدارة المستخدمين:** `/users` (إنشاء/تعطيل/إعادة تعيين كلمة المرور) بصلاحية `users.manage`
   مع منع تصعيد الصلاحيات (موجود في `Principal` ولم يُفتح بعد على مسار HTTP).
5. **2FA (TOTP):** الحقول موجودة في `users` (`totp_secret`, `totp_enabled`)؛ يلزم مسار التسجيل والتحقق.
6. **الانحرافات OOS:** جدول `deviations` + ربطه بالتشغيل الفاشل (حالياً الفشل يُسجّل تدقيقياً فقط).
7. **Celery:** إشعارات انتهاء المعايرة + تقرير KPIs مجدول + مهام PDF الثقيلة.
   (Redis/Celery غير مُعدّين حالياً — `health` يصرّح بذلك بدل ادّعاء الجاهزية.)
8. **حد الطلبات:** نقل النافذة المنزلقة من الذاكرة إلى Redis عند تشغيل أكثر من نسخة واحدة.
9. **تغطية الكود:** بوابة CI بـ`pytest --cov` بحد أدنى 80% على `app/core` و`app/services`.

## ما لم يُنفَّذ ويجب ألّا يُدّعى
- تكامل مزوّد بريد/SMS فعلي (المتغيرات موجودة، الإرسال غير مُبرمج).
- تحليل ملفات LabSolutions (`.lcd`) — مخطط فقط.
- WebSocket للتحديث الحيّ — مخطط فقط.
- Kubernetes manifests لم تُختبر على عنقود حقيقي.
