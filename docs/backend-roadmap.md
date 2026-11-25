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

## المرحلة B — ما أُنجز فعلياً

1. ~~**الربط الفعلي مع الواجهة**~~ ✅ — الواجهة لم تعد تقرأ من IndexedDB كمصدر حقيقة:
   - `src/core/api/client.ts`: عميل HTTP مطبوع الأنواع (`fetch` مع `credentials: 'include'`)،
     فكّ مغلّف `{success,data,meta,errors}`، تجديد جلسة أحادي (single-flight) عند 401،
     وتصنيف أخطاء (`ApiError` / `OfflineError`).
   - `src/core/api/mode.ts`: `DATA_MODE` و`SourceStamp` — كل بطاقة تُصرّح بمصدر بياناتها.
   - تسجيل الدخول صار من الخادم فقط؛ أُزيل تبديل الهوية من الواجهة نهائياً،
     والصلاحيات تُقرأ من `session.permissions` لا من عميل المتصفح.
   - `readThrough()`: يقرأ من الخادم، وعند الانقطاع يعود لنسخة **قراءة فقط** من الكاش المحلي.
     لا كتابة ولا حكم PASS من بيانات محلية.
   - `next.config.js`: تمرير `/api/v1/*` إلى `API_ORIGIN` حتى يبقى المتصفح على نفس الأصل (لا CORS في المتصفح، ولا `127.0.0.1` في كود الواجهة).
2. ~~**التقارير**~~ ✅ — `certificate.pdf` (ReportLab + QR) و`data.xlsx` و`register.xlsx` و`audit.xlsx` (openpyxl).
   الشهادة تُصدر فقط لتشغيل PASS معتمد ومقفل وموقَّع، والبصمة المطبوعة = `certificate_hash` المخزن،
   وQR يحمل `SBDMA|<run_code>|<hash>`. كل تنزيل يُسجَّل في سلسلة التدقيق.
   أُضيف كذلك `raw_inputs` إلى `GET /runs/{id}` حتى تُعاد البيانات الموقّعة كما هي (ALCOA+: Original).
3. ~~**المرفقات**~~ ✅ — `POST /instruments/{id}/attachments` مع:
   - بصمة SHA-256 تُحسب على الخادم أثناء البث، ثم **تُتحقق بقراءة الملف بعد الكتابة**؛
   - تخزين مُعنون بالمحتوى (`<yyyyMM>/<sha256[:6]>/<sha256><ext>`) وكتابة ذرّية عبر `os.replace`؛
   - حد 25 ميجابايت، أنواع مسموحة، رفض الملف الفارغ واسم الملف غير الصالح؛
   - `trg_attachment_immutable` + `trg_attachment_no_truncate` في PostgreSQL (ترحيل `0003_attachments`)؛
   - التصحيح بمرفق جديد يحمل `supersedes_id`، والأصل يبقى مقروءاً؛
   - تنزيل يعيد التحقق من البصمة ويرفض (409) تسليم ملف تغيّر على القرص؛
   - كل إرفاق/تنزيل/تكرار مرفوض مكتوب في سلسلة التدقيق.
   الواجهة: لوحة «ملف أدلة الجهاز» في `/engineering` مع قائمة وتنزيل موثّق ونموذج إرفاق
   يظهر فقط لمن يملك `attachments.manage`.

## الخطوات المتبقية (لم تُنفَّذ بعد)

4. ~~**إدارة المستخدمين:** `/users` بصلاحية `users.manage` مع منع تصعيد الصلاحيات.~~ ✅
   سبعة مسارات (سجل، أدوار، إنشاء، تحديث، إعادة تعيين، رفع قفل، إبطال جلسات).
   منع التصعيد: لا يُمنح دور أعلى من رتبتك ولا صلاحية لا تحملها، وأدوار الاعتماد
   محجوبة عن مسؤول الحسابات أصلاً (فصل مهام Part 11)، ولا تعديل ذاتي للأدوار/التفعيل،
   والحساب يُعطّل ولا يُحذف. الواجهة: صفحة `/users` في القائمة لمن يملك `users.manage`.
   ملاحظة أمان ظهرت أثناء التنفيذ: `must_change_password` كان يُبلَّغ ولا يُفرَض،
   فأصبح يُلزِم فعلياً (403 `PASSWORD_CHANGE_REQUIRED`) مع شاشة تغيير إلزامية في الواجهة.
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
