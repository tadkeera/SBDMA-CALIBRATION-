from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.api.deps import PrincipalDep, SessionDep, client_ip
from app.core.config import get_settings
from app.core.exceptions import AuthenticationError
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    MeOut,
    MfaCodeRequest,
    MfaDisableRequest,
    MfaRecoveryRequest,
)
from app.schemas.common import ok
from app.services.auth_service import AuthService, permissions_for_roles
from app.services.mfa_service import MfaService

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


def _set_auth_cookies(response: Response, tokens: dict[str, str]) -> None:
    response.set_cookie(
        "sbdma_access",
        tokens["access_token"],
        max_age=int(tokens["expires_in"]),
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )
    response.set_cookie(
        "sbdma_refresh",
        tokens["refresh_token"],
        max_age=int(tokens["refresh_expires_in"]),
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path=f"{settings.api_prefix}/auth",
    )


@router.post("/login", summary="تسجيل الدخول")
async def login(payload: LoginRequest, request: Request, response: Response, session: SessionDep):
    service = AuthService(session)
    user, principal, tokens = await service.authenticate(
        username=payload.username,
        password=payload.password,
        totp_code=payload.totp_code,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    await session.commit()
    _set_auth_cookies(response, tokens)
    return ok(
        {
            "access_token": tokens["access_token"],
            "token_type": "bearer",
            "expires_in": int(tokens["expires_in"]),
            "user": {
                "id": str(user.id),
                "username": user.username,
                "full_name_ar": user.full_name_ar,
                "full_name_en": user.full_name_en,
                "roles": principal.roles,
                "permissions": sorted(principal.permissions),
                "department_id": str(user.department_id) if user.department_id else None,
                "must_change_password": user.must_change_password,
                # the client needs this to route straight to enrolment instead of
                # stumbling into 403s on every page
                "mfa_enrolment_required": principal.mfa_enrolment_required,
            },
        }
    )


@router.post("/refresh", summary="تجديد الجلسة")
async def refresh(request: Request, response: Response, session: SessionDep):
    token = request.cookies.get("sbdma_refresh")
    if not token:
        raise AuthenticationError(
            message_ar="لا توجد جلسة قابلة للتجديد", message_en="No refreshable session"
        )
    service = AuthService(session)
    tokens = await service.refresh(token)
    await session.commit()
    _set_auth_cookies(response, tokens)
    return ok({"expires_in": int(tokens["expires_in"])})


@router.post("/logout", summary="تسجيل الخروج")
async def logout(request: Request, response: Response, session: SessionDep, principal: PrincipalDep):
    service = AuthService(session)
    await service.logout(
        user_id=principal.user_id,
        refresh_token=request.cookies.get("sbdma_refresh"),
        ip=client_ip(request),
    )
    await session.commit()
    response.delete_cookie("sbdma_access", path="/")
    response.delete_cookie("sbdma_refresh", path=f"{settings.api_prefix}/auth")
    return ok({"logged_out": True})


@router.get("/me", summary="بيانات المستخدم الحالي")
async def me(session: SessionDep, principal: PrincipalDep):
    from app.models.rbac import LabDepartment, User

    user = await session.get(User, principal.user_id)
    if user is None:
        raise AuthenticationError()
    department = (
        await session.get(LabDepartment, user.department_id) if user.department_id else None
    )
    return ok(
        MeOut(
            id=user.id,
            username=user.username,
            email=user.email,
            full_name_ar=user.full_name_ar,
            full_name_en=user.full_name_en,
            department_id=user.department_id,
            department_code=department.code if department else None,
            roles=principal.roles,
            permissions=permissions_for_roles(principal.roles),
            is_active=user.is_active,
            totp_enabled=user.totp_enabled,
            must_change_password=user.must_change_password,
            mfa_enrolment_required=principal.mfa_enrolment_required,
        ).model_dump(mode="json")
    )


@router.post("/change-password", summary="تغيير كلمة المرور")
async def change_password(
    payload: ChangePasswordRequest, request: Request, session: SessionDep, principal: PrincipalDep
):
    service = AuthService(session)
    await service.change_password(
        user_id=principal.user_id,
        current_password=payload.current_password,
        new_password=payload.new_password,
        reason=payload.reason,
    )
    await session.commit()
    return ok({"changed": True, "sessions_revoked": True})


# ─────────────────────── second factor (TOTP) ────────────────────────────────
# 21 CFR Part 11.200(a)(1)(i): a non-biometric signature needs two distinct
# components. These routes let the account owner enrol, prove possession,
# disable, and recover — each step audited, each demanding fresh proof.


@router.get("/mfa", summary="حالة التحقق بخطوتين")
async def mfa_status(session: SessionDep, principal: PrincipalDep):
    return ok(await MfaService(session).status(principal))


@router.post("/mfa/enrol", summary="بدء تسجيل تطبيق المصادقة")
async def mfa_enrol(session: SessionDep, principal: PrincipalDep):
    """Returns the secret and otpauth:// URI exactly once, for the QR code.

    The pending secret must be committed here: the next request (activation) reads
    it from the database in a different session, and an uncommitted write would be
    discarded when this request ends.
    """
    result = await MfaService(session).begin_enrolment(principal)
    await session.commit()
    return ok(result)


@router.get("/mfa/qr.svg", summary="رمز QR لتسجيل تطبيق المصادقة")
async def mfa_qr(session: SessionDep, principal: PrincipalDep):
    """Render the pending enrolment URI as SVG on the server.

    Doing it here (instead of shipping a JS QR library to the browser) keeps the
    secret out of client-side dependencies and means the scanned code is generated
    from the same value the server will verify against.
    """
    import io

    import qrcode
    import qrcode.image.svg

    service = MfaService(session)
    pending = await service.pending_uri(principal)
    factory = qrcode.image.svg.SvgPathImage
    img = qrcode.make(pending, image_factory=factory)
    buffer = io.BytesIO()
    img.save(buffer)
    return Response(content=buffer.getvalue(), media_type="image/svg+xml")


@router.post("/mfa/activate", summary="تفعيل التحقق بخطوتين برمز صحيح")
async def mfa_activate(
    payload: MfaCodeRequest, request: Request, session: SessionDep, principal: PrincipalDep
):
    result = await MfaService(session).activate(principal, payload.code, ip=client_ip(request))
    await session.commit()
    return ok(result)


@router.post("/mfa/disable", summary="إيقاف التحقق بخطوتين")
async def mfa_disable(
    payload: MfaDisableRequest, request: Request, session: SessionDep, principal: PrincipalDep
):
    result = await MfaService(session).disable(
        principal,
        password=payload.password,
        code=payload.code,
        ip=client_ip(request),
    )
    await session.commit()
    return ok(result)


@router.post("/mfa/recovery", summary="الدخول برمز استرداد عند فقد الجهاز")
async def mfa_recovery(payload: MfaRecoveryRequest, request: Request, session: SessionDep):
    """Consumes one recovery code and resets the factor for re-enrolment.

    Deliberately does not issue a session: the user signs in normally afterwards,
    now without a second factor but with a forced re-enrolment.
    """
    await MfaService(session).redeem_recovery_code(
        username=payload.username,
        password=payload.password,
        code=payload.code,
        ip=client_ip(request),
    )
    await session.commit()
    return ok({"recovered": True, "re_enrol_required": True})
