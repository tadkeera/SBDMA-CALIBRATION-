# النشر على Vercel — SBDMA Calibration Platform

> هذا الدليل يشرح ما يمكن أن يعمل على Vercel، وما **لا يمكن** أن يعمل عليه، وكيف
> يعوّض النظام ذلك. القاعدة المتبعة في هذا المشروع: لا ميزة تُدّعى ثم تظهر معطّلة
> عند أول استخدام حقيقي.

---

## 1) ما نُشر فعلياً: خدمتان في مشروع واحد

`vercel.json` يستخدم **Vercel Services** (متاحة على كل الخطط، حالة Beta) لينشر
خدمتين من نفس المستودع، على نطاق واحد (`https://<project>.vercel.app`):

| الخدمة | الجذر | الإطار | ما تُقدّمه |
|---|---|---|---|
| `web` | `.` (جذر المستودع) | `nextjs` | الواجهة العربية RTL وكل لوحات `/control`, `/lab`, `/qa`, `/engineering` |
| `api` | `backend/` | `fastapi` (`entrypoint: app/main.py`) | كل مسارات `/api/v1/*` |

التوجيه عبر `rewrites`:

```
/api/:path*   →  خدمة api      (أولاً: الأكثر تخصيصاً)
/(.*)         →  خدمة web      (أخيراً: الالتقاط العام)
```

**الفائدة المعمارية:** الواجهة تنادي `/api/v1/*` على **نطاقها نفسه**، فتبقى الكوكيز
من نفس الموقع (`SameSite=Strict` كما هو مضبوط) ولا يوجد CORS ولا preflight، ولا
يحتاج المتصفح أن يعرف عنوان الخادم. هذا هو نفس المسار المستخدم في بيئة التطوير
(`next.config.js` يعيد التوجيه إلى `127.0.0.1:8000` محلياً)، فلا يوجد «مسار يعمل في
الإنتاج وآخر يعمل في التطوير».

### لماذا لم يُنشر الـAPI كحاوية على Vercel؟
لأن Vercel يُشغّل الخدمات كدوال (Functions) لكل طلب. وهذا يعني أن:

| المكوّن | على Vercel | العوض في هذا المستودع |
|---|---|---|
| FastAPI | ✅ يعمل | `backend/app/main.py` كـentrypoint |
| PostgreSQL | ✅ عبر مزوّد مُدار (Neon/Supabase) | `DATABASE_URL` + `alembic upgrade head` |
| Redis (حد الطلبات المشترك) | ✅ اختياري (Upstash `rediss://`) | بدونه: نافذة لكل نسخة دالة — أضعف ومُعلَنة في `/health` |
| Celery **worker** | ❌ لا يوجد عملية دائمة | — (المهام تُنفَّذ عند الطلب) |
| Celery **beat** | ❌ لا يوجد مجدول داخل العملية | **Vercel Cron** → `/api/v1/internal/jobs/*` |
| ملفات PDF/المرفقات على القرص | ⚠️ `/tmp` مؤقت لكل نسخة | غير مناسب للإنتاج — يلزم تخزين كائنات (بند مفتوح) |

**الخلاصة:** كل الوظائف **المتزامنة** (المعايرة، الحساب، الاعتماد، الشهادات عند
الطلب) تعمل على Vercel. أما **العمل المجدول** فيعمل عبر Cron، و**العمل الخلفي
الطويل** (تحليل ملفات LabSolutions، إعادة توليد ضخمة) يحتاج عاملاً — أي حاوية.

---

## 2) الجدولة بدون Celery: نفس الكود بمُشغّل ثانٍ

| المهمة | في الحاوية (Celery) | على Vercel (Cron) |
|---|---|---|
| إشعارات الانتهاء (يومياً 05:15) | `sbdma.notify.calibration_due` | `GET /api/v1/internal/jobs/calibration-due` |
| تقرير مؤشرات الأداء (أسبوعياً الاثنين 04:30) | `sbdma.reports.kpi_report` | `GET /api/v1/internal/jobs/kpi-report` |

المساران ينادوان **الخدمة نفسها**:
`NotificationService.generate_due_notices` و`kpi_report_service.build_kpi_report`.
لا نسخة ثانية من المنطق، فلا يمكن أن يصدر تقريران برقمين مختلفين لنفس السؤال.

**حراسة المسارات (`CRON_SECRET`):**
- بدون `CRON_SECRET` تُرجع المسارات **503** ولا تنفّذ شيئاً. مسار مفتوح يكتب إشعارات
  ويولّد PDF ويضيف إلى سلسلة التدقيق ليس تسهيلاً، بل باب دخول.
- المقارنة بـ`hmac.compare_digest` (لا تُسرّب السر بايتاً بايتاً).
- Vercel يرسل تلقائياً `Authorization: Bearer $CRON_SECRET` عند وجود المتغيّر.
- كل تشغيل يُسجَّل في سلسلة التدقيق بفاعل `system:vercel-cron` مع `x-vercel-id`
  وعنوان IP، فيبقى سؤال «ما الذي شغّل مهمة الليل» قابلاً للإجابة.
- المهمة **عاديّة التكرار**: تقرير الأسبوع لا يُسجَّل مرتين (يتحقق من سجل التدقيق)،
  و`?force=true` للتشغيل اليدوي المتعمد فقط.

---

## 3) خطوات النشر

### 3.1 المتطلبات
1. حساب Vercel (يُفضّل Pro: يسمح بجدولة cron أسبوعية ومدد تنفيذ أطول).
2. قاعدة PostgreSQL مُدارة — **Neon** أو **Supabase** (نسخة 16+). استخدم رابط
   التجميع (pooler) لأن الدوال تفتح اتصالات كثيرة قصيرة العمر.
3. (مستحسن) Redis مُدار — **Upstash** — ليعمل حدّ الطلبات مشتركاً.

### 3.2 متغيّرات البيئة (Settings → Environment Variables)

| المتغيّر | القيمة | ملاحظة |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@host/db?ssl=require` | **يجب** أن يكون `postgresql+asyncpg://` وإلا يرفض الإقلاع |
| `JWT_SECRET` | 64 حرفاً عشوائياً | أقل من 32 حرفاً أو كلمة مثل `change_me` ⇒ رفض الإقلاع في `production` |
| `MFA_ENCRYPTION_KEY` | 64 حرفاً عشوائياً | تُشفَّر به أسرار TOTP؛ تغييره يُبطل كل المسجّلين |
| `CRON_SECRET` | 32 حرفاً عشوائياً | بدونه مسارات الجدولة معطّلة (503) |
| `SCHEDULER` | `vercel-cron` | يجعل `/worker/status` يقول الحقيقة بدل جدول beat |
| `ENVIRONMENT` | `production` | يفعّل رفض الإعدادات الضعيفة |
| `COOKIE_SECURE` | `true` | |
| `COOKIE_SAMESITE` | `strict` | ممكن لأن الواجهة والـAPI على نفس النطاق |
| `CORS_ORIGINS` | `https://<project>.vercel.app` | لا يُستخدم فعلياً مع الـrewrites، لكنه يبقى مضبوطاً |
| `REDIS_URL` | `rediss://…` (Upstash) | اختياري؛ بدونه `rate_limit: memory` في `/health` |
| `RATE_LIMIT_BACKEND` | `redis` أو `auto` | `redis` يجعل انقطاع الوسيط خطأ إعداد ظاهراً |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `2` / `3` | لكل نسخة دالة؛ القيم الكبيرة تستنزف Postgres |
| `STORAGE_PATH` | `/tmp/sbdma-storage` | مؤقت — انظر القيود أدناه |
| `NEXT_PUBLIC_API_BASE_URL` | `/api/v1` | نسبي: يمرّ عبر الـrewrite على نفس النطاق |

### 3.3 النشر
```bash
# 1) الاستيراد من Git (الأسهل): vercel.com → Add New → Project → استورد المستودع
#    لا تضبط Root Directory: vercel.json يعرّف الخدمتين.
#    كل push إلى main يُنتج نشر إنتاج، وكل PR يُنتج Preview.

# 2) أو عبر CLI (يحتاج تسجيل دخول أو توكن):
npx vercel@latest link          # مرة واحدة
npx vercel@latest deploy --prod
```

### 3.4 الترحيلات (تُنفَّذ مرة، وليس من داخل الدالة)
```bash
cd backend
export DATABASE_URL='postgresql+asyncpg://…'      # نفس رابط Vercel
export JWT_SECRET='…'
python -m alembic upgrade head
python -m app.seed                                 # الأدوار والأقسام والبروتوكول والحسابات
```
> إنشاء المخطط من داخل دالة البناء (build) فكرة سيئة: البناء يُعاد بلا ضمان ترتيب،
> وقد يعمل مرتين على قاعدة واحدة في الوقت نفسه.

### 3.5 التحقق بعد النشر
```bash
curl -s https://<project>.vercel.app/api/v1/health | jq .data.components
# المتوقع: postgresql up · redis up|not_configured · celery not_configured · rate_limit redis|memory

curl -s -o /dev/null -w '%{http_code}\n' https://<project>.vercel.app/api/v1/internal/jobs/kpi-report
# المتوقع: 401 (بلا توكن) — أي شيء آخر يعني أن الحراسة لا تعمل

curl -s -H "Authorization: Bearer $CRON_SECRET" \
     'https://<project>.vercel.app/api/v1/internal/jobs/calibration-due?today=2026-11-25' | jq .data
```

---

## 4) القيود التي يجب أن تُقال صراحةً

1. **`celery: not_configured` في `/health` على Vercel هو الجواب الصحيح، لا عطل.**
   لا يوجد عامل دائم على منصة دوال. الجدولة تعمل عبر Cron، والعمل الطويل يحتاج حاوية.
2. **التخزين المؤقت للقرص:** ملفات PDF المولّدة والمرفقات تُكتب في `/tmp` الخاص بنسخة
   الدالة، وقد تختفي بعد دقائق. الشهادات تُطلب وتُسلَّم في نفس الطلب فتنجح، لكن
   «احفظ الشهادة للرجوع إليها» غير مضمون. الحل الصحيح: تخزين كائنات (S3/R2) — بند
   مفتوح ومعلَن في `docs/backend-roadmap.md`.
3. **مدة الدالة:** تقرير KPIs يولّد PDF للموقع ولكل قسم — عملية تستهلك ثوانيَ لا
   أجزاءً من الثانية. على خطة Hobby (مدد أقصر) قد تحتاج إلى تقسيمه لكل قسم.
4. **الجدولة على Hobby:** cron يومي فقط، والتوقيت لا يُضمن بالدقيقة. الأسبوعي يحتاج Pro
   أو تشغيله يدوياً بـ`force=true`.
5. **حدّ الطلبات:** بدون Redis يكون لكل نسخة دالة عدّادها — وعدد النسخ يتغيّر. `/health`
   يعلن `memory` بدل أن يدّعي تحكّماً مشتركاً غير موجود.
6. **مقياس الأداء (HPA) وPDB وbeat غير ذات صلة على Vercel** — تخص نشر Kubernetes،
   وتبقى للمسار الآخر أدناه.

---

## 5) أي نشر تختار؟

| السيناريو | التوصية |
|---|---|
| عرض/تجربة/تدريب، بيانات غير حرجة | **Vercel فقط** (هذا الملف): نشر بأمر واحد، واجهة وAPI على نطاق واحد |
| تشغيل فعلي في مختبر الهيئة (GxP) | **الواجهة على Vercel + الـAPI والعامل على حاوية** (`docker-compose.yml` أو K8s): يلزم عامل مستمر، تخزين ثابت، نسخ احتياطي PITR، وسجل تشغيل لا يضيع مع نسخة دالة |
| كل شيء داخل شبكة الهيئة | **Docker Compose كامل** على خادم داخلي (`docs/deployment.md`)، دون أي خدمة سحابية |

المساران يستخدمان نفس الشيفرة ونفس الاختبارات: الفرق في `SCHEDULER` و`REDIS_URL`
ووجود العامل، لا في منطق النظام.

---

## 6) الاختبار المحلي قبل النشر

```bash
npx vercel@latest dev      # يشغّل الخدمتين محلياً بنفس التوجيه (يتطلب تسجيل دخول)
```
وبدونه — وهو ما تستخدمه الاختبارات — شغّل الخدمتين يدوياً:
```bash
cd backend && uvicorn app.main:app --port 8000 &
npm run dev                                   # Next على 3000، يمرّر /api/v1 إلى 8000
```

ما يُتحقَّق آلياً في CI (`.github/workflows/ci.yml`):
`vercel.json` يُطابَق مع مخطط Vercel الرسمي، وكل `entrypoint` و`root` موجودان فعلاً،
وكل مسار في `crons` هو مسار حقيقي في تطبيق FastAPI، والتوجيه يضع `/api` قبل الالتقاط
العام. مسار cron يشير إلى مسار غير موجود يفشل بصمت في الإنتاج: Vercel ينادي، يحصل على
404، ولا يبلّغ أحداً.

---

## 7) ما نُشر فعلياً (سجل التنفيذ)

| البند | القيمة |
|---|---|
| مشروع Vercel | `sbdma-calibration` (فريق `tadkeeras-projects`) |
| النطاق العام | **https://sbdma-calibration.vercel.app** |
| Region | `hnd1` (طوكيو) — **مطابق لموقع قاعدة البيانات**، لا `fra1` |
| قاعدة البيانات | Supabase، مشروع `SBDMA-CALIBRATION`، PostgreSQL 17.12، `ap-northeast-1` |
| مستخدم قاعدة البيانات | `sbdma_app` (ليس `postgres`، ولا `SUPERUSER`) عبر **Session pooler** على المنفذ `5432` |
| المخطط | 23 جدولاً + 25 Trigger، عبر `alembic upgrade head` من خارج Vercel |
| الحسابات المزروعة | 9 حسابات بأدوارها (7 أدوار · 19 صلاحية) |

### ثلاثة أمور لا تظهر إلا عند النشر على مزوّد مُدار

1. **`sslmode` بصيغة libpq لا يفهمها asyncpg.** رابط Supabase الرسمي ينتهي بـ
   `?sslmode=require`؛ Alembic (psycopg) يفهمه، لكن SQLAlchemy يمرّر أي بارامتر
   استعلام غير معروف إلى `asyncpg.connect` ⇒
   `TypeError: connect() got an unexpected keyword argument 'sslmode'` والإقلاع يفشل.
   أُضيفت ترجمة صريحة في `app/core/database.py`، وهي تُعطي `sslmode` **معناه في libpq**:
   `require` = تشفير بلا تحقق من الشهادة (وهذا هو المقصود، وإلا فشل المصافحة بسلسلة
   شهادات المزوّد)، و`verify-full` = تحقق كامل. اختبارات في
   `tests/test_db_url_translation.py`.
2. **الاتصال المباشر IPv6 فقط:** `db.<ref>.supabase.co` غير قابل للوصول من شبكات
   IPv4 (ومنها دوال Vercel). الحل: pooler (`aws-1-<region>.pooler.supabase.com`)،
   وبصيغة المستخدم `<role>.<project-ref>`.
3. **Session pooler (5432) لا Transaction pooler (6543):** الثاني لا يحفظ الـprepared
   statements بين المعاملات. إن اضطررت إلى `6543` فاضبط
   `DB_DISABLE_PREPARED_STATEMENTS=true` (مُدعّم ويُترجَم إلى تعطيل كاش asyncpg).

### تحصين Supabase
Supabase يعرض مخطط `public` تلقائياً عبر PostgREST بمفتاح `anon` العام. جدول تدقيق
واحد مكشوف بهذه الطريقة يُبطل النظام كله، لذا نُفِّذ بعد الترحيلات:
```sql
REVOKE ALL ON SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
```
تحقّق: `has_table_privilege('anon','public.audit_logs','SELECT')` ⇒ `false`.
والتطبيق يتصل بدور `sbdma_app` لا بدور `postgres`، فلا يملك صلاحيات فوق ما يحتاجه.

### بيانات الدخول
تُسلَّم للحساب المسؤول خارج المستودع (لا أسرار في Git). الأدوار
`SUPER_ADMIN` و`QA_APPROVER` و`TECHNICAL_REVIEWER` تُلزِم التحقق بخطوتين عند أول
دخول — وهذا سلوك Part 11 المقصود، لا عطل: يُمسح رمز QR بتطبيق مصادقة ثم يُدخل الرمز.

### ما لا يعمل على هذه النسخة (بصراحة)
- **لا Redis** ⇒ `rate_limit: memory` في `/health`: النافذة لكل نسخة دالة.
- **`celery: not_configured`** ⇒ الجدولة تعمل عبر Cron فقط (وهي مضبوطة: يومي 05:15
  وأسبوعي الاثنين 04:30 بتوقيت UTC).
- **مزوّد بريد غير مربوط** ⇒ الإشعارات داخل التطبيق فقط.
- **التخزين مؤقت** ⇒ الشهادات تُنزَّل في نفس الطلب؛ لا أرشيف دائم على `/tmp`.
