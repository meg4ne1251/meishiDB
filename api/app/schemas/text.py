"""Text accepted by PostgreSQL UTF-8 string columns and query parameters."""

from typing import Annotated

from pydantic import AfterValidator


def validate_unicode_text(value: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("text must contain valid Unicode characters") from None
    return value


def validate_database_text(value: str) -> str:
    if "\x00" in value:
        raise ValueError("text must not contain NUL characters")
    return validate_unicode_text(value)


UnicodeText = Annotated[str, AfterValidator(validate_unicode_text)]
DatabaseText = Annotated[str, AfterValidator(validate_database_text)]
