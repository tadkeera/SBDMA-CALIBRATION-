"""Central error handling with the unified response envelope.

Invariant: no internal exception detail ever reaches the client. The client gets a
stable code, bilingual messages and a request_id that correlates to the server log.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger, request_id_ctx


class AppError(Exception):
    """Base class for all domain errors."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "APP_ERROR"
    message_ar: str = "حدث خطأ في معالجة الطلب"
    message_en: str = "The request could not be processed"
    field: str | None = None

    def __init__(
        self,
        message_ar: str | None = None,
        message_en: str | None = None,
        *,
        field: str | None = None,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        self.message_ar = message_ar or self.message_ar
        self.message_en = message_en or self.message_en
        self.field = field or self.field
        self.details = details or {}
        if status_code:
            self.status_code = status_code
        super().__init__(self.message_en)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"
    message_ar = "العنصر غير موجود أو خارج نطاق صلاحيتك"
    message_en = "Resource not found or outside your scope"


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "PERMISSION_DENIED"
    message_ar = "لا تملك الصلاحية لتنفيذ هذا الإجراء"
    message_en = "You are not permitted to perform this action"


class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "AUTHENTICATION_FAILED"
    message_ar = "بيانات الدخول غير صحيحة"
    message_en = "Authentication failed"


class AccountLockedError(AppError):
    status_code = status.HTTP_423_LOCKED
    code = "ACCOUNT_LOCKED"
    message_ar = "الحساب مقفل مؤقتاً بسبب محاولات دخول فاشلة متكررة"
    message_en = "Account temporarily locked after repeated failed sign-ins"


class ValidationFailedError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "VALIDATION_FAILED"
    message_ar = "البيانات المدخلة غير صحيحة"
    message_en = "The submitted data is invalid"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"
    message_ar = "تعارض في حالة العنصر"
    message_en = "Resource state conflict"


class ExpiryGuardError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "EXPIRY_GUARD"
    message_ar = "لا يمكن استخدام أداة مرجعية أو مادة قياسية منتهية الصلاحية"
    message_en = "Expired reference equipment or standard cannot be used"


class SegregationOfDutiesError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "SEGREGATION_OF_DUTIES"
    message_ar = "فصل المهام: لا يجوز أن يكون المحلل هو المراجع أو معتمد ضمان الجودة لنفس التشغيل"
    message_en = "Segregation of duties: analyst, reviewer and QA approver must be different users"


class LockedResultError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "RESULT_LOCKED"
    message_ar = "النتائج مقفلة بعد الاعتماد النهائي ولا يمكن تعديلها"
    message_en = "Results are locked after final approval and cannot be modified"


class LimitGovernanceError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "LIMIT_CONFLICT"
    message_ar = "حد القبول غير معتمد أو متعارض — لا يمكن إصدار حكم PASS"
    message_en = "Acceptance limit unapproved or in conflict — PASS cannot be issued"


class UnsafeExpressionError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "UNSAFE_EXPRESSION"
    message_ar = "التعبير الحسابي مرفوض لأسباب أمنية"
    message_en = "The expression was rejected for security reasons"


class SignatureRequiredError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "SIGNATURE_REQUIRED"
    message_ar = "التوقيع الإلكتروني يتطلب سبباً موثقاً وتأكيد كلمة المرور"
    message_en = "An electronic signature requires a documented reason and password confirmation"


def envelope(
    *,
    success: bool,
    data: Any = None,
    meta: dict[str, Any] | None = None,
    errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {"success": success, "data": data, "meta": meta, "errors": errors or []}


def _error_payload(exc: AppError) -> dict[str, Any]:
    return {
        "code": exc.code,
        "field": exc.field,
        "message_ar": exc.message_ar,
        "message_en": exc.message_en,
        "details": exc.details,
    }


def register_exception_handlers(app: FastAPI) -> None:
    log = get_logger("sbdma.errors")

    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        log.warning(
            "domain error",
            extra={"extra_fields": {"code": exc.code, "path": request.url.path, "field": exc.field}},
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=envelope(success=False, errors=[_error_payload(exc)]),
            headers={"X-Request-Id": request_id_ctx.get()},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", []) if p not in ("body", "query", "path"))
            errors.append(
                {
                    "code": "VALIDATION_FAILED",
                    "field": loc or None,
                    "message_ar": f"قيمة غير صالحة في الحقل: {loc or 'body'}",
                    "message_en": err.get("msg", "invalid value"),
                    "details": {},
                }
            )
        log.warning("validation error", extra={"extra_fields": {"path": request.url.path}})
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=envelope(success=False, errors=errors),
            headers={"X-Request-Id": request_id_ctx.get()},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        try:
            phrase_ar = {
                400: "طلب غير صالح",
                401: "يلزم تسجيل الدخول",
                403: "الصلاحية غير كافية",
                404: "المسار غير موجود",
                405: "الطريقة غير مسموحة",
                429: "تم تجاوز حد الطلبات المسموح",
                503: "الخدمة غير متاحة مؤقتاً",
            }.get(exc.status_code, "خطأ في الطلب")
        except Exception:  # pragma: no cover
            phrase_ar = "خطأ في الطلب"
        return JSONResponse(
            status_code=exc.status_code,
            content=envelope(
                success=False,
                errors=[
                    {
                        "code": f"HTTP_{exc.status_code}",
                        "field": None,
                        "message_ar": phrase_ar,
                        "message_en": HTTPStatus(exc.status_code).phrase
                        if exc.status_code in HTTPStatus._value2member_map_
                        else "Request error",
                        "details": {},
                    }
                ],
            ),
            headers={"X-Request-Id": request_id_ctx.get()},
        )

    @app.exception_handler(IntegrityError)
    async def _integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        log.error("integrity error", extra={"extra_fields": {"path": request.url.path}})
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=envelope(
                success=False,
                errors=[
                    {
                        "code": "CONSTRAINT_VIOLATION",
                        "field": None,
                        "message_ar": "العملية تخالف قيداً في قاعدة البيانات (تكرار أو مرجع غير صالح)",
                        "message_en": "The operation violates a database constraint",
                        "details": {},
                    }
                ],
            ),
            headers={"X-Request-Id": request_id_ctx.get()},
        )

    @app.exception_handler(SQLAlchemyError)
    async def _db_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        log.exception("database error")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=envelope(
                success=False,
                errors=[
                    {
                        "code": "DATABASE_UNAVAILABLE",
                        "field": None,
                        "message_ar": "خدمة قاعدة البيانات غير متاحة حالياً",
                        "message_en": "The database service is currently unavailable",
                        "details": {},
                    }
                ],
            ),
            headers={"X-Request-Id": request_id_ctx.get()},
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=envelope(
                success=False,
                errors=[
                    {
                        "code": "INTERNAL_ERROR",
                        "field": None,
                        "message_ar": "حدث خطأ داخلي. تم تسجيله بالمعرّف المرفق.",
                        "message_en": "An internal error occurred. It was logged with the attached id.",
                        "details": {},
                    }
                ],
            ),
            headers={"X-Request-Id": request_id_ctx.get()},
        )
