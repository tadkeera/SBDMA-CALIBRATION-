# واجهة API — `/api/v1`

## الصيغة الموحدة
```json
{ "success": true, "data": { }, "meta": { "page": 1, "total": 0 }, "errors": [] }
```
```json
{ "success": false, "data": null, "meta": null,
  "errors": [{ "code": "LIMIT_CONFLICT", "field": "noise", "message_ar": "...", "message_en": "..." }] }
```

## النقاط الأساسية

| الطريقة | المسار | الصلاحية |
|---|---|---|
| POST | `/auth/login` · `/auth/refresh` · `/auth/logout` | عام |
| GET | `/auth/me` | مُصادَق |
| GET/POST/PATCH | `/departments` | `settings.manage` |
| GET/POST/PATCH/DELETE | `/instruments` | `instruments.*` + نطاق القسم |
| GET/POST | `/reference-equipment`, `/reference-standards` | `instruments.update` |
| GET | `/protocols`, `/protocols/{code}/tests` | `instruments.view` |
| GET/POST/PATCH | `/limits` | `limits.manage` |
| POST | `/limits/{id}/approve` | `limits.approve` (توقيع إلزامي) |
| GET/POST/PATCH | `/formulas` | `formulas.manage` |
| POST | `/runs` | `calibration.run` |
| POST | `/runs/{id}/execute` | `calibration.run` — يشغّل المحرك داخل Transaction |
| POST | `/runs/{id}/review` | `calibration.review` — توقيع فني |
| POST | `/runs/{id}/approve` | `calibration.approve` — يقفل النتائج |
| GET | `/runs/{id}/certificate.pdf` | `reports.export` |
| GET | `/runs/{id}/export.xlsx` | `reports.export` |
| GET | `/audit` | `audit.view` (ترقيم على الخادم) |
| GET | `/health` · `/health/live` · `/health/ready` | عام |
| GET | `/kpis` | `instruments.view` |

## قواعد إلزامية
- **Idempotency-Key** مطلوب على `POST /runs` و`/approve` لمنع الازدواج.
- **Pagination** على الخادم (`page`, `page_size ≤ 100`) — لا تحميل كامل للجداول.
- **Rate Limit** عبر Redis: 30 طلب/ث عامة، 5/دقيقة للمصادقة، 6/دقيقة للتصدير.
- **أكواد الحالة:** `400` تحقق، `401` غير مُصادَق، `403` صلاحية، `404` غير موجود **أو خارج نطاق قسمك**، `409` تعارض حالة، `422` خطأ دلالي، `429` تجاوز حد، `503` تبعية غير متاحة.
- لا يُعاد أي تفاصيل استثناء داخلية للمستخدم — تُسجَّل مع `request_id` وتُعاد رسالة عامة.
