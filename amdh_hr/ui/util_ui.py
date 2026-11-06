"""أدوات مساعدة للواجهة."""

from __future__ import annotations


def copy_credentials(unit: dict, credentials: list[dict]) -> str:
    lines = [f"المؤسسة: {unit.get('name', '')}", f"الرمز: {unit.get('code', '')}", ""]
    for item in credentials:
        lines.append(f"{item.get('role_label', '')}: {item.get('username')} / "
                     f"{item.get('password')}")
    return "\n".join(lines)
