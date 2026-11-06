"""الصلاحيات والأدوار: التعريف، التهيئة، والاشتقاق."""

from __future__ import annotations

# (الرمز، الاسم العربي، التصنيف)
PERMISSIONS: tuple[tuple[str, str, str], ...] = (
    ("manage_units", "إدارة المؤسسات", "إدارة"),
    ("manage_users", "إدارة المستخدمين", "إدارة"),
    ("provision_units", "تجهيز نسخ المؤسسات", "إدارة"),
    ("edit_rules", "تحرير القواعد", "القواعد"),
    ("publish_rules", "نشر القواعد", "القواعد"),
    ("view_employees", "عرض الموظفين", "الموظفون"),
    ("edit_employee", "إضافة وتعديل الموظفين", "الموظفون"),
    ("delete_employee", "حذف/أرشفة الموظفين", "الموظفون"),
    ("assign_employees", "توزيع الموظفين على المستخدمين", "الموظفون"),
    ("view_letters", "عرض كتب الشكر", "كتب الشكر"),
    ("edit_letters", "إضافة وتعديل كتب الشكر", "كتب الشكر"),
    ("approve_letters", "اعتماد كتب الشكر محلياً", "كتب الشكر"),
    ("view_orders", "عرض الأوامر", "الأوامر"),
    ("edit_orders", "إضافة وتعديل الأوامر", "الأوامر"),
    ("approve_orders", "اعتماد الأوامر محلياً", "الأوامر"),
    ("approve_final", "الاعتماد النهائي في المركز", "الاعتماد"),
    ("export_package", "تصدير حزمة للمركز", "الحزم"),
    ("import_package", "استيراد حزمة من مؤسسة", "الحزم"),
    ("import_rules", "استيراد حزم القواعد", "الحزم"),
    ("import_results", "استيراد نتائج الاعتماد", "الحزم"),
    ("backup_restore", "النسخ الاحتياطي والاستعادة", "النظام"),
    ("view_audit", "سجل التدقيق", "النظام"),
    ("export_reports", "تصدير التقارير", "التقارير"),
    ("view_settings", "عرض الإعدادات", "النظام"),
    ("edit_settings", "تعديل الإعدادات", "النظام"),
)

ALL_PERMISSIONS = tuple(code for code, _name, _cat in PERMISSIONS)

ROLES: tuple[tuple[str, str, str], ...] = (
    ("center_admin", "مدير المركز", "الاعتماد النهائي وإدارة القواعد والمستخدمين"),
    ("center_editor", "مدخل المركز", "إدخال موظفي المركز المخصصين له"),
    ("unit_manager", "مدير المؤسسة", "إدارة موظفي مؤسسته والتدقيق والاعتماد المحلي"),
    ("unit_editor", "مدخل بيانات المؤسسة", "إدخال الموظفين المخصصين له"),
)

ROLE_LABELS = {code: name for code, name, _desc in ROLES}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "center_admin": set(ALL_PERMISSIONS),
    "center_editor": {
        "view_employees", "edit_employee", "view_letters", "edit_letters",
        "view_orders", "edit_orders", "export_reports", "view_settings",
    },
    "unit_manager": {
        "view_employees", "edit_employee", "delete_employee", "assign_employees",
        "view_letters", "edit_letters", "approve_letters",
        "view_orders", "edit_orders", "approve_orders",
        "export_package", "import_rules", "import_results", "backup_restore", "view_audit",
        "export_reports", "view_settings",
    },
    "unit_editor": {
        "view_employees", "edit_employee", "view_letters", "edit_letters",
        "view_orders", "edit_orders", "export_reports", "view_settings",
    },
}


def permissions_for(role: str) -> set[str]:
    """صلاحيات الدور من قاعدة البيانات إن وُجدت، وإلا من التعريف الثابت."""
    return set(ROLE_PERMISSIONS.get(role, set()))


def role_order(role: str) -> int:
    order = ("center_admin", "unit_manager", "center_editor", "unit_editor")
    return order.index(role) if role in order else len(order)


def is_center_role(role: str) -> bool:
    return role in {"center_admin", "center_editor"}


def is_unit_role(role: str) -> bool:
    return role in {"unit_manager", "unit_editor"}
