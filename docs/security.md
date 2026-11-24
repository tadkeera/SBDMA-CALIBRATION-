# الأمان والامتثال

## المصادقة والجلسات
- **Argon2id** (`time_cost=3`, `memory_cost=64MB`, `parallelism=4`) — لا MD5/SHA1/bcrypt.
- JWT Access (30 دقيقة) + Refresh (7 أيام) في كوكيز `HttpOnly; Secure; SameSite=Strict`.
- 2FA اختياري (TOTP) للأدوار الحساسة (`QA_APPROVER`, `SUPER_ADMIN`).
- قفل الحساب بعد 5 محاولات فاشلة (`locked_until`)، وإلغاء كل الجلسات عند تغيير كلمة المرور.

## OWASP Top 10 — التحكم المنفَّذ

| التهديد | التحكم |
|---|---|
| A01 Broken Access Control | RBAC على الخادم لكل طلب + عزل `department_id` + `404` بدل `403` ضد IDOR |
| A02 Cryptographic Failures | Argon2id · TLS 1.2+ فقط · HSTS preload · لا أسرار في الكود (`.env` فقط) |
| A03 Injection | SQLAlchemy مُعامَل · **AST Parser آمن بلا `eval`/`exec`** · تحقق Pydantic صارم |
| A04 Insecure Design | حوكمة حدود القبول · فصل مهام · إقفال النتائج بعد الاعتماد |
| A05 Security Misconfiguration | Security Headers + CSP · `server_tokens off` · حاويات `readOnlyRootFilesystem` |
| A06 Vulnerable Components | `npm audit` / `pip-audit` في CI · تثبيت الإصدارات |
| A07 Auth Failures | Rate limit 5/دقيقة على `/auth/*` · قفل الحساب · كشف رسائل موحّد |
| A08 Integrity Failures | SHA-256 لكل مرفق وشهادة · سلسلة تدقيق متسلسلة قابلة للتحقق |
| A09 Logging Failures | سجل تدقيق غير قابل للتعديل + Request-ID لكل طلب |
| A10 SSRF | لا طلبات خارجية من مدخلات المستخدم · allowlist للنطاقات |

## رفع الملفات
- تحقق من MIME الحقيقي (magic bytes) لا الامتداد.
- حد أقصى 25 MB · `sha256_checksum` مُخزَّن ومُتحقَّق.
- التخزين خارج `public/` مع `Content-Disposition: attachment` و`X-Content-Type-Options: nosniff`.
- منع تنفيذ أي ملف داخل مجلد الرفع (لا CGI ولا تفسير سكربتات).

## التوقيع الإلكتروني (21 CFR Part 11)
كل توقيع في النظام يتطلب:
1. إعادة إدخال كلمة المرور.
2. **سبباً موثقاً لا يقل عن 8 أحرف** (يُرفض ما دونه في `SignatureDialog`).
3. تسجيل: المستخدم، الدور، الختم الزمني UTC، وقيمة `old_values`/`new_values`، والبصمة.

## سلسلة التدقيق
كل سجل يحمل `prevHash` و`hash = SHA-256(prevHash|at|actor|action|entity|entityId|before|after|reason)`.
`verifyAuditChain()` يعيد بناء السلسلة كاملة ويكشف أول سجل مكسور. السجل لا يوفر أي مسار
تعديل أو حذف — والـ Trigger في PostgreSQL يمنع ذلك على مستوى قاعدة البيانات أيضاً.
