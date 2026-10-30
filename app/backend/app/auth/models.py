"""Pydantic V2 request/response shapes for /api/auth/* and /api/admin/users/*."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=512)


class LoginResponse(BaseModel):
    ok: bool


class MeResponse(BaseModel):
    signed_in: bool
    id: int | None = None
    email: str | None = None
    role: str | None = None
    first_name: str | None = None
    last_name: str | None = None


class UserNameUpdate(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=512)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=512)


class OkResponse(BaseModel):
    ok: bool = True
    # Soft-fail payload: when an email send fails, routers set email_failed=True
    # and return the underlying URL so the admin can copy-paste it manually.
    email_failed: bool = False
    fallback_url: str | None = None
    fallback_message: str | None = None


class AdminUserRow(BaseModel):
    id: int
    email: str
    first_name: str | None = None
    last_name: str | None = None
    role: str
    pending: bool
    created_at: str


class InviteUserPayload(BaseModel):
    email: str
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    role: str


class RoleUpdatePayload(BaseModel):
    role: str


class ActivatePayload(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=512)
