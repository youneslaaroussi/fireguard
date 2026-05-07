from __future__ import annotations


def mask_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    normalized = phone.strip()
    if len(normalized) <= 5:
        return "***"
    return f"{normalized[:2]}***{normalized[-4:]}"
