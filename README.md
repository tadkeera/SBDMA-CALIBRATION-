# SBDMA · نظام إدارة ومعايرة الأجهزة المخبرية
### Laboratory Calibration & OQ Intelligence Platform — Supreme Board of Drugs & Medical Devices

[![Version](https://img.shields.io/badge/version-2.2.0-21695e)](VERSION)
[![ISO/IEC 17025](https://img.shields.io/badge/ISO%2FIEC-17025-21695e)](#الامتثال-التنظيمي)
[![21 CFR Part 11](https://img.shields.io/badge/21%20CFR-Part%2011-21695e)](#الامتثال-التنظيمي)
[![Tests](https://img.shields.io/badge/tests-366%20passing-16794f)](#الاختبارات-المنفذة)

---

## نظرة عامة

منصة إنتاجية لمعايرة وتحقق الأداء (Calibration & OQ) لأجهزة مختبرات الهيئة العليا للأدوية،
مبنية على بروتوكول **HPLC Shimadzu i-Series LC-2050C** الموحد (20 اختباراً)، وقابلة للتوسع
لكل فئات الأجهزة (HPLC, GC, UV-Vis, FTIR, Karl Fischer, Dissolution, Balances, Autoclaves,
Incubators, Stability Chambers).

**البروتوكول المدمج:** `HPLC-SHIMADZU-LC2050C-PROTOCOL` · الإصدار `2.0.0` · 20 اختباراً · 93 حد قبول · 77 حقلاً · 75 معادلة.
الجدولان (TypeScript وPython) والوثيقة [`docs/protocol.md`](docs/protocol.md) **مُولَّدون من
ملف واحد** (`blueprint.py`) بواسطة `scripts/export_protocol_ts.py` و`export_protocol_doc.py`،
و`--check` يُفشل البناء عند أي انحراف.

| المكوّن | التقنية |
|---|---|
| الواجهة الأمامية | Next.js 15 (App Router) · React 19 · TypeScript · Tailwind CSS |
| قاعدة البيانات المحلية | IndexedDB عبر Dexie 4 — وضع العمل دون اتصال داخل المتصفح |
| قاعدة البيانات المركزية | PostgreSQL 17 · SQLAlchemy 2.0 (asyncpg) · Alembic · **Triggers حوكمة** |
| الرسوم العلمية | Apache ECharts (انحدار OLS، بواقي، GPV، أطياف، مخططات تحكم) |
| محرك الحسابات (المتصفح) | AST Parser آمن + `decimal.js` — **بدون `eval()`** |
| محرك الحسابات (الخادم) | Python 3.12 · `decimal.Decimal` · AST مُتحقق منه — **بدون `eval()`** |
| خادم الإنتاج | FastAPI 0.165 (Async) · 65 عملية على 58 مساراً في `/api/v1` · Argon2id + JWT · تقارير PDF/Excel · مرفقات موقّعة بالبصمة |
| طبقة الحوكمة في القاعدة | 25 Trigger: تدقيق ملحق فقط، قفل النتائج، قفل التشغيل، حاجز الانتهاء، حُرّاس الانحرافات OOS، `updated_at` |
| الطوابير والكاش | Redis 8 · Celery Worker/Beat — إشعارات انتهاء المعايرة (يومياً) وتقرير مؤشرات أسبوعي، مُتحقَّق منهما بتشغيل مهام حقيقية |
| البنية التحتية | Docker Compose · Kubernetes (HPA + PDB + Rolling Updates) · Nginx |

---

## اللوحات الأربع (Panels)

| المسار | اللوحة | الجمهور |
|---|---|---|
| `/` | لوحة المؤشرات — KPIs حقيقية محسوبة من البيانات الفعلية | الجميع |
| `/lab` | لوحة المختبر — إدخال القراءات الخام، `Run Calibration` أو اختبار واحد، الرسوم، الإجراء الموثّق بالإنجليزية، شهادة لكل اختبار، مصفوفة ما بعد الأعطال | `ANALYST` |
| `/qa` | ضمان الجودة — مصفوفة حدود القبول، التعارضات، المراجعة الفنية، الاعتماد النهائي والإقفال | `QA_APPROVER` |
| `/engineering` | الصيانة والهندسة — تذاكر الأعطال وتفعيل الاختبارات الإلزامية | `ENGINEERING_SERVICE` |
| `/control` | الإدارة المركزية — الأجهزة، الأدوات المرجعية، المستخدمون، **حالة الاختبارات (تفعيل/تعطيل)**، **الدليل المرجعي (بحث + PDF)**، البروتوكول، النظام | `SYSTEM_ADMIN` |
| `/audit` | سجل التدقيق — سلسلة SHA-256 قابلة للتحقق | `QA_APPROVER` |

---

## التشغيل السريع

```bash
# 1) الواجهة الأمامية + قاعدة البيانات المحلية (بلا خادم خلفي)
npm install
npm run dev          # http://localhost:3000
npm test             # 22 اختباراً لمحرك الحسابات والبروتوكول

# 2) حزمة الإنتاج الكاملة (PostgreSQL + Redis + FastAPI + Celery + Nginx)
cp .env.example .env         # ثم غيّر كل CHANGE_ME
docker compose up -d --build
```

الحسابات التجريبية للعرض المحلي (لا كلمات مرور في الكود): `admin`, `analyst`, `reviewer`,
`qa`, `engineer`, `viewer` — تُختار من الشريط العلوي أو من `/login`.

---

## دورة عمل المعايرة والاعتماد

```text
اختيار الجهاز والأداة المرجعية (حاجز الصلاحية)
        │
        ├─ إن كانت الأداة منتهية  →  منع التشغيل + تسجيل المحاولة
        ▼
إدخال القراءات الخام للاختبارات الـ 13 (تحقق إلزامي للحقول)
        ▼
Run Calibration  →  محرك AST آمن  →  نتائج كاملة الدقة
        ▼
مقارنة مع الحد المعتمد (AUTHORITY_LIMIT) لكل مقياس
        ▼
PASS / FAIL / UNDER_REVIEW / INCOMPLETE
        ▼
حفظ التشغيل + بصمة SHA-256  →  سجل تدقيق (Append-only)
        ▼
توقيع المراجعة الفنية (21 CFR Part 11 — سبب + كلمة مرور)
        ▼
اعتماد QA نهائي  →  إقفال النتائج (is_locked)  →  شهادة غير قابلة للتعديل
```

**فصل المهام مُطبَّق:** `analyst ≠ reviewer ≠ qa_approver` لنفس التشغيل — يُمنع على مستوى
الواجهة والخادم معاً.

---

## الامتثال التنظيمي

| المتطلب | التنفيذ |
|---|---|
| **ISO/IEC 17025** | بروتوكول موثق، تتبع متري للأدوات المرجعية، حدود قبول معتمدة، سجلات غير قابلة للتعديل |
| **21 CFR Part 11** | توقيع إلكتروني (سبب + كلمة مرور + ختم زمني)، فصل مهام، إقفال السجلات، سلسلة تدقيق |
| **ALCOA+** | قيم خام كاملة الدقة (`NUMERIC(20,8)`)، بصمات SHA-256، منع التعديل والحذف، حفظ الإشارة السالبة |
| **WHO GMP** | إدارة الانحرافات OOS، حوكمة حدود القبول، منع `PASS` على حد غير معتمد |
| **OWASP Top 10** | Argon2id، JWT في كوكيز آمنة، RBAC + عزل أقسام، حماية IDOR، Rate Limiting، رفض التعبيرات غير الآمنة |

---

## المبادئ العلمية المحمية داخل المحرك

هذه القواعد مأخوذة حرفياً من التقرير العلمي المقارن، ومُفعَّلة كحواجز برمجية لا كملاحظات نصية:

1. **GAP-02 — وحدة الضجيج:** أي حد ضجيج بوحدة `AU/h` يُصنَّف `CONFLICT_REQUIRES_QA`، فلا يُنتج `PASS` أبداً.
2. **GAP-08 — موقع حساس المبرد:** الاختبار يفرض قارورة 1.5 mL بماء 1 mL في الموقع 27 على الصفيحة المعدنية، لا داخل فرن العمود.
3. **GAP-06 — الدقة مقابل التكرارية:** اختبار وزني مستقل لدقة حجم الحقن، منفصل تماماً عن تكرارية المساحة.
4. **GAP-03/05 — المعادلات:** معادلة GPV الرسمية من iOQ ص192، وحدود الخطية `R² ≥ 0.9990` (Ch.2 ±5% كمعيار مكمل).
5. **GAP-09 — المسح الطيفي:** مسح كامل 200–280 nm بخطوة 1 nm بقمم 205/273 وقاع 245 nm.
6. **الترحيل (Carryover):** الصيغ الثلاث محفوظة منفصلة (Ch.2 / iOQ / SOP) مع الإشارة السالبة دون تصفير صامت.
7. **التقريب:** كل القيم تُخزَّن كاملة الدقة، والتقريب يُطبَّق في طبقة العرض والتقارير فقط.

التفاصيل الكاملة في [`docs/protocol.md`](docs/protocol.md) و
[`docs/gap-closure-matrix.md`](docs/gap-closure-matrix.md).

---

## تشغيل الخادم الفعلي (PostgreSQL + FastAPI)

```bash
# 1) قاعدة البيانات
createdb sbdma_calibration && createdb sbdma_test

# 2) الترحيلات (تُنشئ 23 جدولاً + 25 Trigger حوكمة)
cd backend && alembic upgrade head

# 3) البيانات الأولية الحتمية (أقسام، أدوار، صلاحيات، مستخدمون، بروتوكول، جهاز، أدوات مرجعية)
export SBDMA_ADMIN_PASSWORD='...'   # إلزامي؛ وإلا تُولَّد كلمة مرور عشوائية في /tmp/sbdma-seed-credentials.txt
python -m app.seed

# 4) التشغيل
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- التوثيق التفاعلي: `http://localhost:8000/api/docs`
- فحص الجاهزية الحقيقي (يتصل بـ PostgreSQL فعلاً): `GET /api/v1/health/ready`
- الاختبارات: `cd backend && pytest -q` → **209 ناجحاً** على قاعدة `sbdma_test` حقيقية تُبنى بالترحيلات.

> **ملاحظة أمنية:** الحسابات المزروعة تحمل `must_change_password=true`، وكل من طلب
> `change-password` يُبطل جميع جلساته القائمة.

## النشر على Vercel

الواجهة والـAPI يُنشران في **مشروع Vercel واحد** كخدمتين (Vercel Services):

```
https://<project>.vercel.app/            →  web   (Next.js من جذر المستودع)
https://<project>.vercel.app/api/v1/*    →  api   (FastAPI من backend/، entrypoint: app/main.py)
```

الواجهة تنادي الـAPI على نطاقها نفسه، فالكوكيز `SameSite=Strict` تعمل بلا CORS.
وملصقة Vercel لا تُشغّل عملية دائمة، فالجَدولة عبر **Vercel Cron** إلى مسارين محميين
بـ`CRON_SECRET` ينادوان نفس خدمتَي الإشعارات والتقرير التي يناديها عامل Celery — لا
منطق مكرَّر.

الدليل الكامل (متغيّرات البيئة، الترحيل، القيود الصريحة): [`docs/vercel-deployment.md`](docs/vercel-deployment.md).
للتشغيل الفعلي في المختبر (عامل + تخزين ثابت + نسخ احتياطي) استخدم `docker-compose.yml`
كما في `docs/deployment.md`.

## الاختبارات المنفذة

| الحزمة | العدد | النتيجة | الأمر |
|---|---|---|---|
| محرك الحسابات والبروتوكول (TypeScript) | 25 | ✅ ناجحة | `npx vitest run` |
| طبقة التكيّف مع الخادم (TypeScript) | 15 | ✅ ناجحة | `npx vitest run` |
| توليد رمز TOTP للحزمة (TypeScript، متجهات RFC) | 4 | ✅ ناجحة | `npx vitest run` |
| محرك الحسابات + API + الحوكمة + التقارير + الترويسة + المرفقات + حدّ الطلبات + حراسة النشر + دورة حياة الاختبارات + الدليل المرجعي + حماية E2E (Python/PostgreSQL/Redis) | 299 | ✅ ناجحة | `cd backend && pytest` |
| بوابة CI (PostgreSQL 16 + Redis 8 خدميين، تغطية ≥ 85%) | 4 وظائف | ✅ | `.github/workflows/ci.yml` |
| بوابة الأمان (أسرار · ثغرات التبعيات · SBOM · تمرين استعادة) | 4 وظائف | ✅ | `.github/workflows/security.yml` |
| **حزمة E2E داخل المستودع** (Playwright/Chromium على بنية إنتاج) | **23 اختباراً** | ✅ دخول ← 20 اختباراً ← مراجعة ← اعتماد ← شهادة PDF/XLSX ← شهادة اختبار واحد ← تفعيل/تعطيل اختبار ← الإجراء الإنجليزي ← الدليل المرجعي وPDF ← سلسلة التدقيق ← إعداد الترويسة | `npm run e2e:prepare && npm run e2e` |

التغطية تشمل: أولويات العمليات، صيغ التدفق والتدرج والحقن الوزني، OLS، `%RSD`، الحساسية
النسبية، الترحيل، رفض التعبيرات الخطرة (`__import__`, `eval`, `open`, `;`, comprehensions)،
الحوكمة (لا `PASS` على حد متعارض)، ونقص البيانات (`INCOMPLETE`).

---

## الخادم الخلفي

**منفَّذ ويعمل فعلياً** (المراحل A وB وعامل ثانٍ وانحرافات OOS): 23 جدولاً + 25 Trigger حوكمة،
58 عملية REST،
Argon2id + JWT بتدوير رموز، توقيع إلكتروني، فصل مهام، عزل أقسام، وSeeders حتمية
من البروتوكول نفسه (93 حداً)، وشهادات PDF وملفات Excel مُدقَّقة التنزيل بترويسة رسمية.

**الواجهة لم تعد تعمل على بيانات محلية:** كل بطاقة تقرأ من `/api/v1` عبر عميل مطبوع الأنواع،
والصلاحيات تأتي من جلسة الخادم لا من المتصفح. عند انقطاع الشبكة تُعرض نسخة **قراءة فقط**
من الكاش مع وسم مصدرها — ولا يمكن إنتاج حكم `PASS` من بيانات محلية.

التفاصيل: [`docs/backend-roadmap.md`](docs/backend-roadmap.md)
· [`docs/api.md`](docs/api.md) · [`docs/testing.md`](docs/testing.md).

**أهم ما يُميّز الطبقة الخلفية:** الحواجز الحاسمة لا تعيش في Python وحده، بل في PostgreSQL:
سجل التدقيق يرفض `UPDATE`/`DELETE`/`TRUNCATE`، والنتائج المقفلة ترفض أي تعديل وتعديل التشغيل
المقفل مرفوض — مُختبرة بـ SQL مباشر عبر اتصال لا يمرّ بتطبيقنا أصلاً.

---

## البنية
```text
sbdma-platform/
├── src/
│   ├── app/            # المسارات: /, /lab, /qa, /engineering, /control, /audit, /settings, /login
│   ├── components/     # Design System + ECharts + TestCharts + Shell + Letterhead
│   └── core/
│       ├── engine/     # safeMath.ts (AST) · runEngine.ts (الحوكمة والحكم)
│       ├── db/         # database.ts (Dexie) · seed.ts (البيانات المرجعية)
│       ├── protocol.ts # مُولَّد: 20 اختباراً + 93 حد + 75 معادلة + مصفوفة الأعطال
│       └── types.ts    # النماذج والصلاحيات
├── backend/            # FastAPI + المحرك المرجعي + الاختبارات
├── infra/              # nginx · k8s · سكربتات النسخ الاحتياطي
├── docs/               # 14 وثيقة هندسية (منها protocol.md المُولَّدة وproduction-hardening.md)
├── scripts/            # مولّدات الوثيقة/الأنواع · load_test · restore_drill · SBOM · ماسح الأسرار
├── sbom/               # CycloneDX 1.5 للخادم والواجهة (مُولَّد ومُتحقَّق في CI)
├── tests/              # Vitest
├── docker-compose.yml · Dockerfile · .env.example
└── IMPLEMENTATION_PLAN.md
```

---

## الترخيص والحقوق

تطوير: **[تذكرة للحلول البرمجية والأنظمة](https://link.gettap.co/tadkrah)** — جميع حقوق التطوير محفوظة للهيئة العليا للأدوية.
