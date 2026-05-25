"""Routes for the auth flow (anonymous + authenticated)."""
from __future__ import annotations

from typing import Union

from fastapi import APIRouter, Depends, status

from app.controllers.auth_controller import AuthController
from app.dependencies import (
    get_auth_controller,
    get_caller_jti,
    get_current_user_id,
)
from app.schemas.auth import (
    IntrospectRequest,
    IntrospectResponse,
    LoginOtpRequired,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    RefreshRequest,
    RefreshResponse,
)
from app.schemas.otp import OtpSendRequest, OtpSendResponse, OtpVerifyRequest
from app.schemas.password import (
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
)
from app.schemas.user import UserResponse


router = APIRouter(prefix="/users", tags=["auth"])


@router.post(
    "/login",
    response_model=Union[LoginResponse, LoginOtpRequired],
    response_model_by_alias=True,
    summary="Login with username/email + password",
    description=(
        "Returns a token pair on success when 2FA is not required. If 2FA is "
        "required, the response is 200 with `{requires_otp: true, ephemeral_token, channels_available}` "
        "— the FE then calls /login/send-otp and /login/verify-otp."
    ),
    responses={401: {"description": "Invalid credentials"}},
)
def login(
    payload: LoginRequest,
    controller: Annotated[AuthController, Depends(get_auth_controller)] = Depends(get_auth_controller),
):
    return controller.login(payload)


@router.post(
    "/login/send-otp",
    response_model=OtpSendResponse,
    summary="Send a 2FA OTP code",
    description="Generates a 6-digit code, stores its hash, dispatches via notification-svc.",
)
def send_otp(
    payload: OtpSendRequest,
    controller: Annotated[AuthController, Depends(get_auth_controller)] = Depends(get_auth_controller),
):
    return controller.send_otp(payload)


@router.post(
    "/login/verify-otp",
    response_model=LoginResponse,
    response_model_by_alias=True,
    summary="Verify a 2FA OTP and finish login",
    description="On success returns the full LoginResponse (token pair + user summary).",
    responses={
        401: {"description": "OTP invalid / expired / max-attempts-exceeded"},
    },
)
def verify_otp(
    payload: OtpVerifyRequest,
    controller: Annotated[AuthController, Depends(get_auth_controller)] = Depends(get_auth_controller),
):
    return controller.verify_otp(payload)


@router.post(
    "/refresh",
    response_model=RefreshResponse,
    response_model_by_alias=True,
    summary="Rotate access + refresh tokens",
    description="Accepts current OR grace-window refresh_token_jti.",
)
def refresh(
    payload: RefreshRequest,
    controller: Annotated[AuthController, Depends(get_auth_controller)] = Depends(get_auth_controller),
):
    return controller.refresh_tokens(payload)


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="Logout — revoke access token + clear refresh state",
)
def logout(
    controller: Annotated[AuthController, Depends(get_auth_controller)] = Depends(get_auth_controller),
    user_id: Annotated[str, Depends(get_current_user_id)] = Depends(get_current_user_id),
    jti: Annotated[str, Depends(get_caller_jti)] = Depends(get_caller_jti),
):
    return controller.logout(user_id=user_id, jti=jti)


@router.post(
    "/introspect",
    response_model=IntrospectResponse,
    summary="RFC-7662 token introspection",
    description="Inspect a token's active/expired state without re-issuing.",
)
def introspect(
    payload: IntrospectRequest,
    controller: Annotated[AuthController, Depends(get_auth_controller)] = Depends(get_auth_controller),
):
    return controller.introspect(payload)


@router.post(
    "/forgot-password",
    response_model=ForgotPasswordResponse,
    summary="Initiate password reset — always returns success (anti-enumeration)",
)
def forgot_password(
    payload: ForgotPasswordRequest,
    controller: Annotated[AuthController, Depends(get_auth_controller)] = Depends(get_auth_controller),
):
    return controller.forgot_password(payload)


@router.post(
    "/reset-password",
    response_model=ResetPasswordResponse,
    summary="Consume a reset token + set new password",
    responses={401: {"description": "Token invalid or expired"}},
)
def reset_password(
    payload: ResetPasswordRequest,
    controller: Annotated[AuthController, Depends(get_auth_controller)] = Depends(get_auth_controller),
):
    return controller.reset_password(payload)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Current user details",
)
def get_me(
    controller: Annotated[AuthController, Depends(get_auth_controller)] = Depends(get_auth_controller),
    user_id: Annotated[str, Depends(get_current_user_id)] = Depends(get_current_user_id),
):
    return controller.get_me(user_id)
