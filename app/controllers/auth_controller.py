"""AuthController — HTTP adapter for all login / OTP / refresh / password-reset routes."""
from __future__ import annotations

from typing import Union

from app.schemas.auth import (
    IntrospectRequest,
    IntrospectResponse,
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
from app.services.auth_service import AuthService
from app.services.password_reset_service import PasswordResetService
from app.services.refresh_service import RefreshService
from app.services.two_factor_service import TwoFactorService


class AuthController:
    def __init__(
        self,
        auth_service: AuthService,
        two_factor_service: TwoFactorService,
        refresh_service: RefreshService,
        password_reset_service: PasswordResetService,
    ):
        self.auth = auth_service
        self.otp = two_factor_service
        self.refresh = refresh_service
        self.password_reset = password_reset_service

    # ------------------------------------------------------------------ login flow

    def login(self, payload: LoginRequest) -> LoginResponse:
        return self.auth.authenticate(payload.login, payload.password)

    def send_otp(self, payload: OtpSendRequest) -> OtpSendResponse:
        return self.otp.send_otp(payload.ephemeral_token, payload.channel)

    def verify_otp(self, payload: OtpVerifyRequest) -> LoginResponse:
        return self.otp.verify_otp(payload.ephemeral_token, payload.code)

    # ------------------------------------------------------------------ refresh / logout

    def refresh_tokens(self, payload: RefreshRequest) -> RefreshResponse:
        return self.refresh.refresh(payload.refresh_token)

    def logout(self, *, user_id: str, jti: str) -> LogoutResponse:
        return self.auth.logout(user_id=user_id, jti=jti)

    # ------------------------------------------------------------------ introspect / me

    def introspect(self, payload: IntrospectRequest) -> IntrospectResponse:
        return self.auth.introspect(payload)

    def get_me(self, user_id: str) -> UserResponse:
        user = self.auth.get_me(user_id)
        return UserResponse.model_validate(user)

    # ------------------------------------------------------------------ password reset

    def forgot_password(self, payload: ForgotPasswordRequest) -> ForgotPasswordResponse:
        return self.password_reset.request_reset(payload.login_or_email, payload.channel)

    def reset_password(self, payload: ResetPasswordRequest) -> ResetPasswordResponse:
        return self.password_reset.perform_reset(payload.token_or_code, payload.new_password)
