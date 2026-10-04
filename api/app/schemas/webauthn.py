"""Validate outer WebAuthn payloads before using them in DB/challenge lookups."""

from pydantic import BaseModel, EmailStr, Field


class LoginBeginRequest(BaseModel):
    email: EmailStr | None = None


class FinishRequest(BaseModel):
    # Optional defaults preserve the endpoint's existing 400 response for missing fields.
    challenge_id: str | None = Field(default=None, max_length=200)
    credential: dict | None = None


class RegisterFinishRequest(FinishRequest):
    nickname: str | None = Field(default=None, max_length=100)
