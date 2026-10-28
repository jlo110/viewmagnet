"""Authentication API routes.

Hardened with:
- Per-process DEV_MODE mock token (random per process, never the same across hosts)
- Rate limits on /signup, /login, /refresh
- Email verification flow (``/verify-email``, ``/resend-verification``)
- Optional TOTP 2FA (``/2fa/setup``, ``/2fa/enable``, ``/2fa/disable``)
- Audit log entries for every security-relevant action
- ``token_version`` embedded in every issued token (revocation support)
- ``/logout`` bumps the user's ``token_version`` to invalidate all outstanding tokens
"""
import secrets
import string
from datetime import datetime, timedelta
from typing import Optional

import pyotp
import structlog
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from src.api.limiter import Tier, limiter
from src.auth.admin import is_admin
from src.auth.audit import record_audit_event
from src.auth.dependencies import MOCK_TOKEN, get_current_user
from src.auth.emails import send_password_reset_email, send_verification_email
from src.auth.jwt import create_access_token, create_refresh_token, verify_token
from src.auth.password import hash_password, verify_password
from src.config import get_settings
from src.database.connection import get_session
from src.database.models import User

# How long a password-reset token stays valid.
PASSWORD_RESET_TTL = timedelta(hours=1)

load_dotenv()
logger = structlog.get_logger(__name__)

_settings = get_settings()
DEV_MODE = _settings.dev_mode and not _settings.is_production

REFERRAL_BONUS_ANALYSES = 5


def generate_referral_code(length: int = 8) -> str:
    """Generate a random uppercase alphanumeric referral code."""
    chars = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


def _build_user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "plan": user.plan,
        "avatar_url": user.avatar_url,
        "is_verified": getattr(user, "is_verified", False),
        "totp_enabled": getattr(user, "totp_enabled", False),
        "referral_code": getattr(user, "referral_code", None),
        # Surface admin status so the frontend can show/hide the
        # operator-only UI (DLQ admin, etc.) without an extra round-trip.
        "is_admin": is_admin(user),
    }


router = APIRouter(prefix="/auth", tags=["Authentication"])


# ============================================================
# SCHEMAS
# ============================================================

class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128, description="Password 8-128 characters")
    name: Optional[str] = None
    referral_code: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    totp_code: Optional[str] = Field(default=None, description="6-digit TOTP code if 2FA is enabled")


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: int
    email: str
    name: Optional[str]
    plan: str
    avatar_url: Optional[str]
    created_at: datetime
    is_verified: bool = False
    totp_enabled: bool = False
    referral_code: Optional[str] = None
    referral_count: int = 0
    referral_bonus_analyses: int = 0
    is_admin: bool = False

    class Config:
        from_attributes = True


class ReferralStatsResponse(BaseModel):
    referral_code: str
    referral_link: str
    referral_count: int
    bonus_analyses_earned: int


class VerifyEmailRequest(BaseModel):
    token: str


class Setup2FAResponse(BaseModel):
    secret: str
    otpauth_url: str


class Enable2FARequest(BaseModel):
    code: str


# ============================================================
# SIGNUP / LOGIN / REFRESH
# ============================================================

@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(Tier.AUTH)
async def signup(request: Request, signup_data: SignupRequest):
    """Create a new user account and issue tokens."""
    with get_session() as session:
        existing = session.query(User).filter(User.email == signup_data.email).first()
        if existing:
            record_audit_event("signup_failed_duplicate", request=request, details={"email": signup_data.email})
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )
        
        referrer = None
        if signup_data.referral_code:
            referrer = session.query(User).filter(
                User.referral_code == signup_data.referral_code.upper()
            ).first()
        
        new_referral_code = generate_referral_code()
        while session.query(User).filter(User.referral_code == new_referral_code).first():
            new_referral_code = generate_referral_code()
        
        user = User(
            email=signup_data.email,
            password_hash=hash_password(signup_data.password),
            name=signup_data.name,
            plan="free",
            created_at=datetime.utcnow(),
            usage_period_start=datetime.utcnow(),
            referral_code=new_referral_code,
            referred_by_id=referrer.id if referrer else None,
            email_verification_token=secrets.token_urlsafe(32),
        )
        
        session.add(user)
        session.flush()
        
        if referrer:
            referrer.referral_bonus_analyses += REFERRAL_BONUS_ANALYSES
            referrer.referral_count += 1
        
        access_token = create_access_token(user.id, user.email, token_version=user.token_version)
        refresh_token = create_refresh_token(user.id, token_version=user.token_version)
        
        user_payload = _build_user_payload(user)

        # Capture primitives before the session closes so the email send
        # below can't trip on a detached-instance lazy load.
        verify_token_value = user.email_verification_token
        verify_email_addr = user.email
        verify_name = user.name
        new_user_id = user.id

        session.commit()
        
        record_audit_event("signup", user_id=new_user_id, request=request)
        logger.info("auth.signup", user_id=new_user_id, email=verify_email_addr)

    # Send the verification email outside the DB transaction (fail-open —
    # a mailer outage must not fail signup; the user can resend later).
    if verify_token_value:
        send_verification_email(verify_email_addr, verify_token_value, verify_name)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=user_payload,
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit(Tier.AUTH)
async def login(request: Request, login_data: LoginRequest):
    """Log in with email + password (and optional TOTP code)."""
    
    # DEV MODE: per-process mock token bypass
    if DEV_MODE and MOCK_TOKEN and login_data.email == "demo@viewmagnet.io" and login_data.password == "demo123":
        return TokenResponse(
            access_token=MOCK_TOKEN,
            refresh_token=MOCK_TOKEN,
            user={
                "id": 1,
                "email": "demo@viewmagnet.io",
                "name": "Demo User",
                "plan": "pro",
                "avatar_url": None,
            },
        )
    
    with get_session() as session:
        user = session.query(User).filter(User.email == login_data.email).first()
        
        if not user or not user.password_hash:
            record_audit_event("login_failed", request=request, details={"email": login_data.email, "reason": "no_user"})
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )
        
        if not verify_password(login_data.password, user.password_hash):
            record_audit_event("login_failed", user_id=user.id, request=request, details={"reason": "bad_password"})
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )
        
        if getattr(user, "totp_enabled", False):
            if not login_data.totp_code:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="TOTP code required",
                )
            totp = pyotp.TOTP(user.totp_secret)
            if not totp.verify(login_data.totp_code, valid_window=1):
                record_audit_event("login_failed_2fa", user_id=user.id, request=request)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid TOTP code",
            )
        
        user.last_login = datetime.utcnow()
        
        access_token = create_access_token(user.id, user.email, token_version=user.token_version)
        refresh_token = create_refresh_token(user.id, token_version=user.token_version)
        
        user_payload = _build_user_payload(user)
        
        session.commit()
        
        record_audit_event("login_success", user_id=user.id, request=request)
        
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user=user_payload,
        )


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit(Tier.AUTH)
async def refresh_tokens(request: Request, body: RefreshRequest):
    """Exchange a refresh token for a fresh access + refresh pair."""
    payload = verify_token(body.refresh_token, token_type="refresh")
    
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    
    user_id = int(payload.get("sub"))
    token_ver = payload.get("ver")
    
    with get_session() as session:
        user = session.query(User).filter(User.id == user_id).first()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )
        
        if token_ver is not None and token_ver != user.token_version:
            record_audit_event("token_refresh_revoked", user_id=user.id, request=request)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
            )
        
        access_token = create_access_token(user.id, user.email, token_version=user.token_version)
        refresh_token = create_refresh_token(user.id, token_version=user.token_version)
        
        user_payload = _build_user_payload(user)
        
        record_audit_event("token_refresh", user_id=user.id, request=request)
        
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user=user_payload,
        )


@router.post("/logout")
async def logout(request: Request, current_user: User = Depends(get_current_user)):
    """Revoke all outstanding tokens by bumping the user's ``token_version``."""
    with get_session() as session:
        user = session.query(User).filter(User.id == current_user.id).first()
        if user:
            user.token_version = (user.token_version or 0) + 1
            session.commit()
    
    record_audit_event("logout", user_id=current_user.id, request=request)
    return {"success": True, "message": "All tokens revoked"}


# ============================================================
# EMAIL VERIFICATION
# ============================================================

@router.post("/verify-email")
async def verify_email(request: Request, body: VerifyEmailRequest):
    """Confirm an email address using the token sent on signup."""
    with get_session() as session:
        user = session.query(User).filter(
            User.email_verification_token == body.token
        ).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired verification token",
            )
        user.is_verified = True
        user.email_verification_token = None
        session.commit()
    
    record_audit_event("email_verified", user_id=user.id, request=request)
    return {"success": True, "message": "Email verified"}


@router.post("/resend-verification")
@limiter.limit("3/hour")
async def resend_verification(request: Request, current_user: User = Depends(get_current_user)):
    """Issue a fresh verification token and email it."""
    with get_session() as session:
        user = session.query(User).filter(User.id == current_user.id).first()
        if user.is_verified:
            return {"success": True, "message": "Already verified"}
        token = secrets.token_urlsafe(32)
        user.email_verification_token = token
        email_addr = user.email
        name = user.name
        session.commit()

    send_verification_email(email_addr, token, name)
    return {"success": True, "message": "Verification email sent"}


# ============================================================
# PASSWORD RESET
# ============================================================

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128, description="New password 8-128 characters")


@router.post("/forgot-password")
@limiter.limit(Tier.AUTH)
async def forgot_password(request: Request, body: ForgotPasswordRequest):
    """Begin a password reset: email a single-use, time-limited reset link.

    Always returns the same generic success response whether or not the
    email exists, so the endpoint can't be used to enumerate accounts.
    """
    token: Optional[str] = None
    email_addr: Optional[str] = None
    name: Optional[str] = None
    with get_session() as session:
        user = session.query(User).filter(User.email == body.email).first()
        if user and user.password_hash:
            token = secrets.token_urlsafe(32)
            user.password_reset_token = token
            user.password_reset_expires = datetime.utcnow() + PASSWORD_RESET_TTL
            email_addr = user.email
            name = user.name
            session.commit()
            record_audit_event("password_reset_requested", user_id=user.id, request=request)

    if token and email_addr:
        send_password_reset_email(email_addr, token, name)

    return {
        "success": True,
        "message": "If an account exists for that email, a reset link has been sent.",
    }


@router.post("/reset-password")
@limiter.limit(Tier.AUTH)
async def reset_password(request: Request, body: ResetPasswordRequest):
    """Complete a password reset using the emailed token.

    On success the new password is set and ALL outstanding tokens are
    revoked (``token_version`` bump) so any session opened with the old
    password is invalidated.
    """
    with get_session() as session:
        user = session.query(User).filter(
            User.password_reset_token == body.token
        ).first()
        if (
            not user
            or not user.password_reset_expires
            or user.password_reset_expires < datetime.utcnow()
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired reset token",
            )
        user.password_hash = hash_password(body.new_password)
        user.password_reset_token = None
        user.password_reset_expires = None
        user.token_version = (user.token_version or 0) + 1
        user_id = user.id
        session.commit()

    record_audit_event("password_reset_completed", user_id=user_id, request=request)
    return {"success": True, "message": "Password updated. Please log in again."}


# ============================================================
# TOTP 2FA
# ============================================================

@router.post("/2fa/setup", response_model=Setup2FAResponse)
async def setup_2fa(current_user: User = Depends(get_current_user)):
    """Generate a TOTP secret + provisioning URL. Call ``/2fa/enable`` next."""
    if current_user.plan == "free":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="2FA is available on Pro and Enterprise plans",
        )
    secret = pyotp.random_base32()
    with get_session() as session:
        user = session.query(User).filter(User.id == current_user.id).first()
        user.totp_secret = secret
        user.totp_enabled = False
        session.commit()
    otpauth_url = pyotp.totp.TOTP(secret).provisioning_uri(
        name=current_user.email,
        issuer_name="ViewMagnet",
    )
    return Setup2FAResponse(secret=secret, otpauth_url=otpauth_url)


@router.post("/2fa/enable")
async def enable_2fa(request: Request, body: Enable2FARequest, current_user: User = Depends(get_current_user)):
    """Confirm the TOTP secret with a valid code; turns 2FA on."""
    with get_session() as session:
        user = session.query(User).filter(User.id == current_user.id).first()
        if not user.totp_secret:
            raise HTTPException(status_code=400, detail="Run /2fa/setup first")
        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(body.code, valid_window=1):
            raise HTTPException(status_code=400, detail="Invalid TOTP code")
        user.totp_enabled = True
        session.commit()
    record_audit_event("2fa_enabled", user_id=current_user.id, request=request)
    return {"success": True}


@router.post("/2fa/disable")
async def disable_2fa(request: Request, body: Enable2FARequest, current_user: User = Depends(get_current_user)):
    """Disable 2FA (still requires a valid current code)."""
    with get_session() as session:
        user = session.query(User).filter(User.id == current_user.id).first()
        if not user.totp_enabled:
            return {"success": True, "message": "2FA already disabled"}
        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(body.code, valid_window=1):
            raise HTTPException(status_code=400, detail="Invalid TOTP code")
        user.totp_enabled = False
        user.totp_secret = None
        session.commit()
    record_audit_event("2fa_disabled", user_id=current_user.id, request=request)
    return {"success": True}


# ============================================================
# PROFILE
# ============================================================

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Return the current user profile."""
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        name=current_user.name,
        plan=current_user.plan,
        avatar_url=current_user.avatar_url,
        created_at=current_user.created_at,
        is_verified=getattr(current_user, "is_verified", False),
        totp_enabled=getattr(current_user, "totp_enabled", False),
        referral_code=getattr(current_user, "referral_code", None),
        referral_count=getattr(current_user, "referral_count", 0),
        referral_bonus_analyses=getattr(current_user, "referral_bonus_analyses", 0),
        is_admin=is_admin(current_user),
    )


@router.put("/me", response_model=UserResponse)
async def update_me(
    name: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """Update editable profile fields."""
    with get_session() as session:
        user = session.query(User).filter(User.id == current_user.id).first()
        
        if name is not None:
            user.name = name
        
        session.commit()
        
        return UserResponse(
            id=user.id,
            email=user.email,
            name=user.name,
            plan=user.plan,
            avatar_url=user.avatar_url,
            created_at=user.created_at,
            is_verified=user.is_verified,
            totp_enabled=user.totp_enabled,
            referral_code=user.referral_code,
            referral_count=user.referral_count,
            referral_bonus_analyses=user.referral_bonus_analyses,
            is_admin=is_admin(user),
        )


class DeleteAccountRequest(BaseModel):
    # Password confirmation for accounts that have one. OAuth-only users
    # (no password_hash) can delete without it.
    password: Optional[str] = None


@router.delete("/me")
async def delete_account(
    request: Request,
    body: DeleteAccountRequest,
    current_user: User = Depends(get_current_user),
):
    """Permanently delete the current user's account (GDPR right to erasure).

    Hard-deletes the ``users`` row. All user-owned rows are removed or
    detached automatically via the database's ON DELETE CASCADE / SET NULL
    foreign keys (PATs, sessions, projects cascade; payment + referral rows
    are nulled for accounting integrity).

    Password-backed accounts must confirm with their current password.
    """
    with get_session() as session:
        user = session.query(User).filter(User.id == current_user.id).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        if user.password_hash:
            if not body.password or not verify_password(body.password, user.password_hash):
                record_audit_event(
                    "account_delete_failed", user_id=user.id, request=request,
                    details={"reason": "bad_password"},
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Password confirmation required to delete your account",
                )

        deleted_id = user.id
        session.delete(user)
        session.commit()

    record_audit_event("account_deleted", user_id=deleted_id, request=request)
    logger.info("auth.account_deleted", user_id=deleted_id)
    return {"success": True, "message": "Your account has been permanently deleted."}


# ============================================================
# REFERRALS
# ============================================================

def _ensure_referral_code(session, user: User) -> str:
    if not user.referral_code:
        new_code = generate_referral_code()
        while session.query(User).filter(User.referral_code == new_code).first():
            new_code = generate_referral_code()
        user.referral_code = new_code
        session.commit()
    return user.referral_code


@router.get("/referral-code")
async def get_referral_code(current_user: User = Depends(get_current_user)):
    """Return (and lazily generate) the user's referral code + link."""
    with get_session() as session:
        user = session.query(User).filter(User.id == current_user.id).first()
        code = _ensure_referral_code(session, user)
        return {
            "referral_code": code,
            "referral_link": f"{_settings.frontend_url}/?ref={code}",
        }


@router.get("/referral-stats", response_model=ReferralStatsResponse)
async def get_referral_stats(current_user: User = Depends(get_current_user)):
    """Return signup count + bonus analyses earned."""
    with get_session() as session:
        user = session.query(User).filter(User.id == current_user.id).first()
        code = _ensure_referral_code(session, user)
        return ReferralStatsResponse(
            referral_code=code,
            referral_link=f"{_settings.frontend_url}/?ref={code}",
            referral_count=user.referral_count,
            bonus_analyses_earned=user.referral_bonus_analyses,
        )
