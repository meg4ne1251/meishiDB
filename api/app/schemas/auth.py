from pydantic import BaseModel, EmailStr, Field

from app.schemas.text import DatabaseText, UnicodeText


class RegisterRequest(BaseModel):
    email: EmailStr
    display_name: DatabaseText = Field(min_length=1, max_length=100)
    password: UnicodeText = Field(min_length=8, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: UnicodeText = Field(max_length=200)


class CurrentUser(BaseModel):
    id: str
    email: EmailStr
    display_name: str
    role: str
