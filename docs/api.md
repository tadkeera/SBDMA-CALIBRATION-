# واجهة API — `/api/v1`

الخادم: FastAPI 0.165 (async) + PostgreSQL. التوثيق التفاعلي المباشر: `/api/docs` · OpenAPI: `/api/openapi.json`.

## الصيغة الموحدة
```json
{ "success": true, "data": { }, "meta": { "page": 1, "total": 0 }, "errors": [] }
```
```json
{ "success": false, "data": null, "meta": null,
  "errors": [{ "code": "LIMIT_CONFLICT", "field": null,
               "message_ar": "...", "message_en": "...", "details": {} }] }
```

## المصادقة
- `POST /auth/login` يعيد `access_token` **ويضبط** كوكيز `httpOnly`:
  `sbdma_access` (30 دقيقة) و`sbdma_refresh` (7 أيام، مساره `/api/v1/auth` فقط).
- يقبل الطلب الهيدر `Authorization: Bearer <token>` **أو** الكوكي؛ الهيدر له الأولوية.
- `POST /auth/refresh` يستهلك رمز التحديث المقدَّم مرة واحدة (تدوير إجباري)؛ إعادة استخدام رمز
  مُستهلك تُرجع `401`.
- `POST /auth/logout` يُبطل جلسة التحديث الحالية (أو كل الجلسات عند غياب الرمز).
- `POST /auth/change-password` يتحقق من قوة كلمة المرور ويُبطل **كل** الجلسات القائمة.
- قفل الحساب: 5 محاولات فاشلة ⇒ قفل 15 دقيقة (قابل للضبط).
- حد الطلبات: 5/دقيقة على `/auth/*`، 120/دقيقة على بقية الـ API (429 مع `Retry-After`).

## النقاط المُنفَّذة فعلياً (58 عملية على 45 مساراً)

| الطريقة | المسار | الصلاحية | ملاحظات |
|---|---|---|---|
| GET | `/health` · `/health/live` · `/health/ready` | عام | `ready` يفحص اتصال PostgreSQL فعلياً |
| POST | `/auth/login` · `/auth/refresh` · `/auth/logout` | عام / مُصادَق | كوكيز + رموز |
| GET | `/auth/me` | مُصادَق | الأدوار + الصلاحيات + القسم |
| POST | `/auth/change-password` | مُصادَق | توقيع إرشادي + إبطال الجلسات |
| GET | `/departments` | `instruments.view` | |
| GET | `/instruments` | `instruments.view` | مُقيَّد بالقسم تلقائياً |
| POST · PATCH · DELETE | `/instruments` · `/instruments/{id}` | `instruments.create` / `.update` / `.delete` | حذف ناعم فقط |
| GET | `/reference-equipment` · `/reference-standards` | `instruments.view` | يُرجع `expired` و`days_to_expiry` |
| GET | `/protocols` · `/protocols/{code}` | `instruments.view` | 13 اختباراً و108 حد |
| POST | `/limits/{id}/approve` | `limits.approve` | توقيع إلكتروني (كلمة مرور + سبب) |
| POST | `/runs` | `calibration.run` | يتطلب هيدر `Idempotency-Key` |
| POST | `/runs/{id}/execute` | `calibration.run` | يشغّل المحرك داخل Transaction واحدة |
| POST | `/runs/{id}/review` | `calibration.review` | فصل مهام + توقيع |
| POST | `/runs/{id}/approve` | `calibration.approve` | يقفل التشغيل ونتائجه ويثبّت بصمة الشهادة |
| GET | `/runs` · `/runs/{id}` · `/runs/pending/approvals` | `instruments.view` / `calibration.approve` | |
| GET · POST | `/maintenance/tickets` | `maintenance.manage` (POST) | تستنتج اختبارات ما بعد الأعطال |
| POST | `/maintenance/tickets/{id}/resolve` | `maintenance.manage` | يُعيد الجهاز إلى `ACTIVE` |
| GET | `/audit` · `/audit/verify` | `audit.view` | التحقق يعيد `{ok, total, head, broken_at}` |
| GET | `/kpis` | `instruments.view` | كل الأرقام من صفوف حقيقية، بلا قيم اصطناعية |
| GET | `/reports/runs/{id}/certificate.pdf` | `calibration.approve` | شهادة PDF (شهادات: تُصدر فقط لتشغيل **معتمد + مقفل + موقَّع + PASS**) |
| GET | `/reports/runs/{id}/data.xlsx` | `reports.export` | المدخلات الخام + تقييم المقاييس + الحدود المطبقة + سجل التدقيق |
| GET | `/reports/runs/register.xlsx` | `reports.export` | سجل التشغيلات الكامل |
| GET | `/reports/audit.xlsx` | `audit.view` | سجل التدقيق كما هو معروف في قاعدة البيانات |
| POST | `/instruments/{id}/attachments` | `attachments.manage` | multipart: `file` + `description` (+`supersedes_id`) — البصمة تُحسب على الخادم |
| GET | `/instruments/{id}/attachments` | `instruments.view` | قائمة مرفقات الجهاز مع بصمة كل ملف |
| GET | `/instruments/attachments/{id}/content` | `instruments.view` | تنزيل بعد **إعادة التحقق** من البصمة — 409 عند عدم التطابق |
| GET | `/users` | `users.manage` | سجل المستخدمين مع الحالة والأدوار وسبب التعطيل (مُقيَّد بالقسم لغير المشرفين) |
| GET | `/users/roles` | `users.manage` | الأدوار为载体 و`assignable=false` لما لا يجوز إسناده |
| POST | `/users` | `users.manage` | يتطلب `?reason=` (8 أحرف) — الحساب يبدأ بـ`must_change_password=true` |
| PATCH | `/users/{id}` | `users.manage` | الأدوار/القسم/التفعيل + سبب إلزامي في الجسم |
| POST | `/users/{id}/reset-password` | `users.manage` | يبطل كل جلسات المستخدم ويُعيد تفعيل طلب التغيير |
| POST | `/users/{id}/unlock` | `users.manage` | 409 إذا لم يكن الحساب مقفلاً |
| POST | `/users/{id}/revoke-sessions` | `users.manage` | سحب فوري: رمز الوصول الموجود يتوقف عن العمل |
| GET | `/auth/mfa` | مُصادَق | حالة العامل الثاني وعدد أكواد الاسترداد المتبقية |
| POST | `/auth/mfa/enrol` | مُصادَق | يصدر سراً **معلّقاً** + `otpauth://` — لا يُفعّل شيئاً |
| GET | `/auth/mfa/qr.svg` | مُصادَق | رمز QR يُرسم على الخادم من السر المعلّق نفسه |
| POST | `/auth/mfa/activate` | مُصادَق | يتطلب رمزاً صحيحاً — إثبات الحيازة قبل التفعيل |
| POST | `/auth/mfa/disable` | مُصادَق | يتطلب **كلمة المرور + رمزاً** معاً |
| POST | `/auth/mfa/recovery` | عام | يستهلك كود استرداد ويعيد ضبط العامل لإعادة التسجيل |

## رموز الأخطاء المستخدمة فعلياً

| الرمز | HTTP | المعنى |
|---|---|---|
| `AUTHENTICATION_REQUIRED` / `AUTHENTICATION_FAILED` | 401 | لا جلسة أو بيانات دخول خاطئة |
| `PERMISSION_DENIED` | 403 | الصلاحية غير متوفرة للدور |
| `PASSWORD_CHANGE_REQUIRED` | 403 | ما زال الحساب على كلمة مرور أصدرها المسؤول — لا يُسمح إلا بـ`me`/`change-password`/`logout` |
| `SECOND_FACTOR_REQUIRED` | 401 | كلمة المرور صحيحة والخادم يطلب رمز التحقق (أو الرمز خاطئ/مستهلك) |
| `MFA_ENROLMENT_REQUIRED` | 403 | دورك يفرض عاملَين ولم تسجّل بعد — الجلسة محصورة بمسارات التسجيل |
| `SEGREGATION_OF_DUTIES` | 403 | المحلل ≠ المراجع ≠ معتمد الجودة |
| `NOT_FOUND` | 404 | يشمل حالة **IDOR**: جهاز/تشغيل قسم آخر يظهر كغير موجود |
| `RESULT_LOCKED` | 409 | تشغيل/نتيجة مقفلة لا تُعدّل |
| `CONFLICT` | 409 | اعتماد قبل مراجعة، تنفيذ مكرر، جهاز خارج الخدمة |
| `EXPIRY_GUARD` | 422 | أداة مرجعية منتهية الصلاحية |
| `LIMIT_CONFLICT` | 422 | حدود معتمدة مفقودة أو متعارضة ⇒ اعتماد محظور |
| `ACCOUNT_LOCKED` | 403 | تجاوز محاولات الدخول |
| `RATE_LIMITED` | 429 | تجاوز حد الطلبات |
| `VALIDATION_FAILED` | 422 | حقل ناقص أو غير صالح، `field` يحدد الموضع |

## أمثلة

```bash
# 1) دخول
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"analyst.phys","password":"<password>"}'

# 2) إنشاء تشغيل (Idempotency-Key إلزامي)
curl -s -X POST http://localhost:8000/api/v1/runs \
  -H "Authorization: Bearer $TOKEN" -H 'Idempotency-Key: run-2026-11-25-01' \
  -H 'Content-Type: application/json' \
  -d '{"instrument_id":"<uuid>","run_type":"ROUTINE","limit_source_policy":"AUTHORITY_LIMIT"}'

# 3) تنفيذ المحرك
curl -s -X POST http://localhost:8000/api/v1/runs/$RUN/execute \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"raw_inputs": {"T02": {"set_flow":[0.5,1,2],"collected_vol":[5,5,5],"actual_time":[599.9,299.4,150.1]}}}'

# 4) مراجعة فنية ثم اعتماد ضمان الجودة (توقيع بكلمة المرور + سبب)
curl -s -X POST http://localhost:8000/api/v1/runs/$RUN/review \
  -H "Authorization: Bearer $REVIEWER" -H 'Content-Type: application/json' \
  -d '{"password":"<pw>","reason":"مراجعة فنية للقراءات مقابل البروتوكول"}'
curl -s -X POST http://localhost:8000/api/v1/runs/$RUN/approve \
  -H "Authorization: Bearer $QA" -H 'Content-Type: application/json' \
  -d '{"password":"<pw>","reason":"اعتماد ضمان الجودة وإصدار الشهادة"}'
```

## تقارير التشغيل

### `GET /reports/runs/{id}/certificate.pdf`
الشهادة **لا تُصدر** إلا إذا تحققت كل الشروط التالية، وإلا عاد الطلب بخطأ صريح:

| الشرط | رمز الرفض عند الإخلال |
|---|---|
| تشغيل بحالة `PASS` | `CONFLICT` (409) |
| موقَّع من المراجع الفني **و** معتمد من ضمان الجودة | `CONFLICT` (409) |
| مقفل (`is_locked = true`) وله `certificate_hash` | `RESULT_LOCKED` (409) |
| بصمة الشهادة المطبوعة = `certificate_hash` المخزن | `CONFLICT` (409) |

- البصمة تُطبع كاملة (64 خانة سادس عشرية) ومكرَّرة في رمز QR بالصيغة `SBDMA|<run_code>|<hash>`،
  فيمكن التحقق منها دون الرجوع للخادم.
- الشهادة ثنائية اللغة: العربية أولاً (RTL) والإنجليزية كلغة مرجعية حاكمة عند التعارض.
- كل قيمة علمية في الشهادة مصدرها صفوف مخزنة أو البروتوكول المعتمد — لا أرقام مُولَّدة عند الطباعة.

### `GET /reports/runs/{id}/data.xlsx`
ورقة عمل تحتوي على: المدخلات الخام كما وُقّعت، تقييم كل مقياس مع الحد المطبق ومصدره،
وحالة الحكم، ثم سجل التدقيق المرتبط بالتشغيل.

### التدقيق
كل تنزيل (شهادة أو Excel) يُسجَّل في سلسلة التدقيق مع المستخدم والبصمة والطابع الزمني،
حتى لو تكرر التنزيل. لا يوجد مسار تنزيل «صامت».

## المرفقات (الأدلة المخبرية)

| القاعدة | التنفيذ |
|---|---|
| البصمة تحدد الهوية | المسار التخزيني `<yyyyMM>/<sha256[:6]>/<sha256><ext>` — لا يُستبدل ملف بآخر |
| الخادم يحسب البصمة | لا يُقبل هاش من العميل؛ يُحسب أثناء البث ثم **يُعاد التحقق** بقراءة الملف بعد الكتابة |
| لا تكرار | نفس البايتات ⇒ يُعاد السجل القائم بـ`200` و`meta.duplicate=true` بدل إنشاء «أصل» ثانٍ |
| التصحيح مرفق جديد | `supersedes_id` يربط الجديد بالقديم، والقديم يبقى مقروءاً |
| لا تعديل ولا حذف | `trg_attachment_immutable` + `trg_attachment_no_truncate` — حتى بـ SQL مباشر |
| الحد والحجم والنوع | 25 ميجابايت، أنواع مسموحة فقط، الملف الفارغ مرفوض |
| عزل الأقسام | جهاز قسم آخر ⇒ 404 (بلا تسريب وجود) |
| كل عملية مُدقَّقة | `ATTACHMENT_UPLOADED` / `ATTACHMENT_DOWNLOADED` / `ATTACHMENT_DUPLICATE_REJECTED` |
| التنزيل يتحقق أولاً | إذا تغيّر الملف على القرص ⇒ 409 `CONFLICT` (حادثة سلامة بيانات) ولا يُسلَّم الملف |

> الأذونات: `attachments.manage` لأدوار `ANALYST` و`ENGINEERING_SERVICE` و`SYSTEM_ADMIN`
> و`SUPER_ADMIN`. المراجع الفني ومسؤول ضمان الجودة **يقرآن** الأدلة ولا يُرفقان —
> وهذه الحماية مقصودة: من يراجع الدليل لا يصنعه.

## إدارة المستخدمين وحماية الصلاحيات

| القاعدة | التنفيذ |
|---|---|
| لا تصعيد صلاحيات | لا يمنح المستخدمُ صلاحيةً لا يحملها (`assert_can_grant`) ولا دوراً أعلى من رتبته (`assert_role_assignable`) |
| فصل المهام | مسؤول الحسابات لا يُنشئ ولا يمنح دور اعتماد (`calibration.approve`/`limits.approve`) — وإلا أنشأ معتمداً واعتمد عمله |
| لا تعديل ذاتي | لا يمكنك تغيير أدوارك أو تعطيل نفسك أو إعادة تعيين كلمة مرورك من مسار الإدارة |
| كلمة مرور الزميل المعتمد | لا يعيد المعتمد تعيين كلمة مرور زميل معتمد (توقيع باسمه) |
| التعطيل فوري | `load_principal` يرفض الحساب المعطّل في كل طلب، لا عند الدخول فقط |
| السحب فوري | رمز الوصول يحمل `sid` لصفّ الجلسة؛ إبطال الجلسة يُبطل الرمز فوراً بدل انتظار انتهائه |
| **لا يُحذف حساب** | التعطيل بدل الحذف؛ ومفتاح أجنبي على `audit_logs` يمنع حذف أي حساب له سجل |
| كل تغيير مُدقَّق | `USER_CREATED` / `USER_UPDATED` / `USER_DISABLED` / `USER_PASSWORD_RESET` / `USER_UNLOCKED` / `USER_SESSIONS_REVOKED` + السبب |
| كلمة المرور المؤقتة مُلزِمة | `must_change_password` يُفرَض فعلياً: 403 `PASSWORD_CHANGE_REQUIRED` لكل مسار عدا `me`/`change-password`/`logout` |

> الأدوار القابلة للإسناد تظهر في `/users/roles` مع `assignable=false` لغير المسموح،
> فتعرضها الواجهة معطّلة مع السبب بدل إخفائها — والمصدر النهائي للحكم يبقى الخادم.

## التحقق بخطوتين (TOTP) — 21 CFR Part 11.200(a)(1)(i)

| القاعدة | التنفيذ |
|---|---|
| مكوّنان متميزان | كلمة المرور + رمز TOTP لستة أرقام، كل 30 ثانية |
| السر مُشفَّر | يُحفظ كـ Fernet (مفتاح مشتق من `mfa_encryption_key`)؛ قراءة العمود لا تكفي لتوليد رمز |
| الرمز أحادي الاستخدام | يُحفظ أعلى عدّاد مقبول؛ إعادة إرسال نفس الرمز داخل نافذته تُرفض (Part 11.300(b)) |
| التسجيل ليس تفعيلاً | السر يُصدر **معلّقاً**؛ لا يُفعَّل إلا برمز صحيح، فمسح QR خاطئ لا يقفل الحساب |
| الإيقاف يتطلب إثباتين | كلمة المرور **و** رمزاً — لأن إسقاط العامل الثاني أول ما يفعله من سرق كلمة المرور |
| أدوار مُلزَمة | `SUPER_ADMIN` و`SYSTEM_ADMIN` و`QA_APPROVER` و`TECHNICAL_REVIEWER` (قابلة للضبط) |
| جلسة مقيّدة لا رفض | دور مُلزَم بلا تسجيل يحصل على جلسة تصل مسارات التسجيل فقط — لا يُترك المستخدم في طريق مسدود |
| أكواد الاسترداد | 10 أكواد تُعرض مرة واحدة، تُحفظ كـ Argon2، كل كود يُستهلك مرة واحدة |
| الاسترداد يعيد الضبط | بعد استخدام كود استرداد يُعطَّل العامل ويُطلب تسجيل جديد، فالجهاز المفقود يتوقف عن العمل |
| كل حدث مُدقَّق | `MFA_ENROLMENT_STARTED` / `MFA_ENABLED` / `MFA_FAILED` / `MFA_DISABLE_FAILED` / `MFA_RECOVERY_USED` ... |

## الانحرافات خارج المواصفة (OOS)

رُبط التشغيل الفاشل بمسار قابل للتنفيذ. العيب الذي أُصلح: اعتماد ضمان الجودة كان يرفض
النتيجة غير المطابقة برسالة «يلزم فتح انحراف OOS» ولا يوجد جدول انحرافات — طلبٌ لإجراء
لا وجود له.

| المسار | الصلاحية | الغرض |
|---|---|---|
| `GET /deviations` | `instruments.view` | السجل، مرشّح بالحالة أو بالتشغيل، محدود بالقسم |
| `GET /deviations/{id}` | `instruments.view` | التفاصيل وخط الزمن |
| `POST /deviations` | `deviations.raise` | فتح انحراف على تشغيل `FAIL`/`INCOMPLETE` فقط |
| `POST /deviations/{id}/investigate/start` | `deviations.investigate` | بدء التحقيق (تاريخ البدء نفسه سجل) |
| `POST /deviations/{id}/investigate` | `deviations.investigate` | تسجيل السبب الجذري والإجراء الفوري |
| `POST /deviations/{id}/close` | `deviations.close` | قرار CAPA + ربط تشغيل إعادة الاختبار |
| `POST /deviations/{id}/cancel` | `deviations.close` | إلغاء انحراف فُتح بالخطأ (قبل التحقيق فقط) |

| القاعدة | التنفيذ |
|---|---|
| الانحراف لا يغيّر النتيجة | اعتماد التشغيل الفاشل يبقى مرفوضاً؛ الإغلاق يشير إلى `retest_run_id`، وتشغيل **إعادة الاختبار** هو ما يُعتمد |
| الرفض يدلّ لا يُغلق الطريق | الـ409 يحمل `details.deviation` و`details.hint` (الخطوة التالية) وتعرضهما الواجهة |
| فصل المهام | الفاتح لا يحقّق؛ والمحقّق لا يغلق انحرافاً **حرجاً** إن وُجد مسؤول جودة آخر |
| مراحل بلا رجوع | `OPEN → INVESTIGATING → PENDING_VERIFICATION → CLOSED`، و`CLOSED`/`CANCELLED` نهائيتان |
| انحراف مفتوح واحد لكل تشغيل | تحقيقان متوازيان قد يصلان إلى استنتاجين متعارضين ⇒ 409 |
| حراسة قاعدة بيانات | مشغّلات ترفض انحرافاً على `PASS`، وترفض تعديل الهوية/الموضوع/التصنيف، وترفض `DELETE` و`TRUNCATE`، وقيود CHECK لشكل التحقيق والإغلاق |
| كل مرحلة مُدقَّقة | `DEVIATION_RAISED` / `DEVIATION_INVESTIGATION_STARTED` / `DEVIATION_INVESTIGATED` / `DEVIATION_CLOSED` / `DEVIATION_CANCELLED` |

مرجع الانحراف: `DEV-YYYYMMDD-NNNN` متسلسل يومياً.

## مسارات مخطط لها ولم تُنفَّذ بعد
WebSocket للتحديث الحيّ · Celery للمهام المجدولة.
هذه مذكورة صراحةً هنا حتى لا تُعدَّ نقطة نهاية موجودة.

## ملاحظة على الأرقام
كل `Decimal` في الاستجابات يُسلَّم **كنص** (`"0.4"`) لا كرقم عشري ثنائي، حفاظاً على الدقة.
الواجهة تُحوّلها إلى أرقام عند حد التكيّف (adapters) في `src/core/api/client.ts`،
وأي مستهلك خارجي يجب أن يفعل الشيء نفسه قبل تنفيذ عمليات حسابية.
