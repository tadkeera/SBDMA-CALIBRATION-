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

## النقاط المُنفَّذة فعلياً (27 مساراً)

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

## رموز الأخطاء المستخدمة فعلياً

| الرمز | HTTP | المعنى |
|---|---|---|
| `AUTHENTICATION_REQUIRED` / `AUTHENTICATION_FAILED` | 401 | لا جلسة أو بيانات دخول خاطئة |
| `PERMISSION_DENIED` | 403 | الصلاحية غير متوفرة للدور |
| `SEGREGATION_OF_DUTIES` | 403 | المحلل ≠ المراجع ≠ معتمد الجودة |
| `NOT_FOUND` | 404 | يشمل حالة **IDOR**: جهاز/تشغيل قسم آخر يظهر كغير موجود |
| `RESULT_LOCKED` | 409 | تشغيل/نتيجة مقفلة لا تُعدّل |
| `CONFLICT` | 409 | اعتماد قبل مراجعة، تنفيذ مكرر، جهاز خارج الخدمة |
| `EXPIRY_GUARD` | 422 | أداة مرجعية منتهية الصلاحية |
| `LIMIT_CONFLICT` | 422 | حدود معتمدة مفقودة أو متعارضة ⇒ اعتماد محظور |
| `ACCOUNT_LOCKED` | 403 | تجاوز محاولات الدخول |
| `RATE_LIMITED` | 429 | تجاوز حد الطلبات |
| `VALIDATION_ERROR` | 422 | حقل ناقص أو غير صالح، `field` يحدد الموضع |

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

## مسارات مخطط لها ولم تُنفَّذ بعد
`GET /runs/{id}/certificate.pdf` · `GET /runs/{id}/export.xlsx` · `POST /instruments/{id}/attachments`
(رفع الملفات مع تحقق SHA-256) · `/users` (إدارة المستخدمين) · `/deviations` · WebSocket للتحديث الحيّ.
هذه مذكورة صراحةً هنا حتى لا تُعدَّ نقطة نهاية موجودة.
