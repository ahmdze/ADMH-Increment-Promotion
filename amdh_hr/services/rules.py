"""حزم القواعد ومحرك مطابقة القواعد (بيانات فقط، بلا كود قابل للتنفيذ)."""

from __future__ import annotations

import json
import uuid

from ..errors import conflict, not_found, validation
from ..util import add_months, as_date, jdump, jload, now_iso, today_iso
from . import audit

RULE_TYPES = {"promotion": "ترفيع", "increment": "علاوة", "letter_effect": "أثر كتاب شكر"}
PACKAGE_STATUS = {"draft": "مسودة", "published": "منشورة", "retired": "مسحوبة"}
ENGINE_VERSION = "1.0"


# ---------------------------------------------------------------------------
# القراءة
# ---------------------------------------------------------------------------
def list_packages(db) -> list[dict]:
    rows = db.query(
        "SELECT p.*, (SELECT COUNT(*) FROM rule_rows r WHERE r.package_id=p.package_id) "
        "AS rows_count FROM rule_packages p ORDER BY p.created_at DESC, p.version DESC")
    for row in rows:
        row["status_label"] = PACKAGE_STATUS.get(row["status"], row["status"])
    return rows


def get_package(db, package_id: str) -> dict:
    package = db.one("SELECT * FROM rule_packages WHERE package_id=?", (package_id,))
    if not package:
        raise not_found("حزمة القواعد غير موجودة.")
    package["status_label"] = PACKAGE_STATUS.get(package["status"], package["status"])
    package["rows"] = [
        _decode_row(row) for row in
        db.query("SELECT * FROM rule_rows WHERE package_id=? ORDER BY rule_type, priority",
                 (package_id,))]
    return package


def _decode_row(row: dict) -> dict:
    row["scope_data"] = jload(row.get("scope"))
    row["params_data"] = jload(row.get("params"))
    row["type_label"] = RULE_TYPES.get(row["rule_type"], row["rule_type"])
    row["active"] = bool(row["active"])
    return row


def active_package(db, as_of: str) -> dict | None:
    row = db.one(
        "SELECT * FROM rule_packages WHERE status='published' AND effective_from<=? "
        "AND (effective_to IS NULL OR effective_to='' OR effective_to>=?) "
        "ORDER BY effective_from DESC, version DESC LIMIT 1", (as_of, as_of))
    return row


# ---------------------------------------------------------------------------
# الكتابة
# ---------------------------------------------------------------------------
def _clean_date(value, label: str, required: bool = True) -> str:
    text = str(value or "").strip()[:10]
    if not text:
        if required:
            raise validation(f"{label} مطلوب.")
        return ""
    if as_date(text) is None:
        raise validation(f"{label} غير صالح ({text}).")
    return text


def create_package(db, user: dict, data: dict, ip: str = "") -> dict:
    code = str(data.get("code") or "").strip().upper()
    if not code:
        raise validation("رمز الحزمة مطلوب.")
    effective_from = _clean_date(data.get("effective_from") or today_iso(), "تاريخ النفاذ")
    effective_to = _clean_date(data.get("effective_to"), "تاريخ الانتهاء", required=False)
    if effective_to and effective_to < effective_from:
        raise validation("تاريخ الانتهاء قبل النفاذ.")
    version = int(db.scalar("SELECT MAX(version) FROM rule_packages WHERE code=?", (code,), 0)) + 1
    package_id = uuid.uuid4().hex
    with db.write() as conn:
        conn.execute(
            "INSERT INTO rule_packages(package_id, code, version, status, effective_from, "
            "effective_to, note, legal_source, created_by, created_at) "
            "VALUES (?,?,?,'draft',?,?,?,?,?,?)",
            (package_id, code, version, effective_from, effective_to or None,
             str(data.get("note") or "").strip(), str(data.get("legal_source") or "").strip(),
             user.get("username", ""), now_iso()))
        audit.log(db, user, "إنشاء حزمة قواعد", "rule_packages", package_id,
                  f"{code} إصدار {version}", ip=ip, conn=conn)
    return get_package(db, package_id)


def update_package(db, user: dict, package_id: str, data: dict, ip: str = "") -> dict:
    package = db.one("SELECT * FROM rule_packages WHERE package_id=?", (package_id,))
    if not package:
        raise not_found("حزمة القواعد غير موجودة.")
    if package["status"] != "draft":
        raise conflict("لا تُعدّل حزمة منشورة؛ أنشئ إصداراً جديداً.")
    effective_from = _clean_date(data.get("effective_from", package["effective_from"]),
                                 "تاريخ النفاذ")
    effective_to = _clean_date(data.get("effective_to", package["effective_to"] or ""),
                               "تاريخ الانتهاء", required=False)
    with db.write() as conn:
        conn.execute("UPDATE rule_packages SET effective_from=?, effective_to=?, note=?, "
                     "legal_source=? WHERE package_id=?",
                     (effective_from, effective_to or None,
                      str(data.get("note", package["note"]) or "").strip(),
                      str(data.get("legal_source", package["legal_source"]) or "").strip(),
                      package_id))
        audit.log(db, user, "تعديل حزمة قواعد", "rule_packages", package_id,
                  package["code"], ip=ip, conn=conn)
    return get_package(db, package_id)


def save_row(db, user: dict, package_id: str, data: dict, ip: str = "") -> dict:
    package = db.one("SELECT * FROM rule_packages WHERE package_id=?", (package_id,))
    if not package:
        raise not_found("حزمة القواعد غير موجودة.")
    if package["status"] != "draft":
        raise conflict("لا تُعدّل قواعد حزمة منشورة؛ أنشئ إصداراً جديداً.")
    rule_type = str(data.get("rule_type") or "")
    if rule_type not in RULE_TYPES:
        raise validation("نوع القاعدة غير معروف.")
    scope = data.get("scope") or {}
    params = data.get("params") or {}
    if isinstance(scope, str):
        scope = jload(scope)
    if isinstance(params, str):
        params = jload(params)
    _validate_rule(rule_type, scope, params)
    rule_id = str(data.get("rule_id") or "") or uuid.uuid4().hex
    existing = db.one("SELECT * FROM rule_rows WHERE rule_id=? AND package_id=?",
                      (rule_id, package_id))
    with db.write() as conn:
        if existing:
            conn.execute("UPDATE rule_rows SET rule_type=?, name=?, scope=?, params=?, "
                         "priority=?, active=? WHERE rule_id=?",
                         (rule_type, str(data.get("name") or existing["name"]),
                          jdump(scope), jdump(params), int(data.get("priority") or 100),
                          1 if data.get("active", True) else 0, rule_id))
        else:
            conn.execute("INSERT INTO rule_rows(rule_id, package_id, rule_type, name, scope, "
                         "params, priority, active) VALUES (?,?,?,?,?,?,?,?)",
                         (rule_id, package_id, rule_type,
                          str(data.get("name") or RULE_TYPES[rule_type]), jdump(scope),
                          jdump(params), int(data.get("priority") or 100),
                          1 if data.get("active", True) else 0))
        audit.log(db, user, "حفظ قاعدة", "rule_rows", rule_id,
                  f"{RULE_TYPES[rule_type]} في {package['code']}", ip=ip, conn=conn)
    return _decode_row(db.one("SELECT * FROM rule_rows WHERE rule_id=?", (rule_id,)))  # type: ignore


def delete_row(db, user: dict, rule_id: str, ip: str = "") -> dict:
    row = db.one("SELECT r.*, p.status FROM rule_rows r JOIN rule_packages p "
                 "ON p.package_id=r.package_id WHERE r.rule_id=?", (rule_id,))
    if not row:
        raise not_found("القاعدة غير موجودة.")
    if row["status"] != "draft":
        raise conflict("لا تُحذف قاعدة من حزمة منشورة.")
    with db.write() as conn:
        conn.execute("DELETE FROM rule_rows WHERE rule_id=?", (rule_id,))
        audit.log(db, user, "حذف قاعدة", "rule_rows", rule_id, row["name"], ip=ip, conn=conn)
    return {"deleted": rule_id}


def _validate_rule(rule_type: str, scope: dict, params: dict) -> None:
    if rule_type == "promotion":
        if int(params.get("required_months") or 0) <= 0:
            raise validation("مدة القدم المطلوبة (بالأشهر) مطلوبة.")
    elif rule_type == "increment":
        if int(params.get("required_months") or 0) <= 0:
            raise validation("مدة العلاوة (بالأشهر) مطلوبة.")
    elif rule_type == "letter_effect":
        if int(params.get("days") or 0) <= 0 and int(params.get("months") or 0) <= 0:
            raise validation("أثر الكتاب (أيام أو أشهر) مطلوب.")
        source = str(scope.get("issuer_type") or "")
        if not source:
            raise validation("حدّد نوع الجهة المانحة لنطاق أثر الكتاب.")
        if int(params.get("cap_months") or 0) < 0:
            raise validation("سقف الأشهر لا يكون سالباً.")
        if params.get("cap_period") not in (None, "", "calendar_year", "service_year"):
            raise validation("دورة السقف غير معروفة.")


def publish_package(db, user: dict, package_id: str, ip: str = "") -> dict:
    package = get_package(db, package_id)
    if package["status"] != "draft":
        raise conflict("الحزمة منشورة مسبقاً.")
    if not package["rows"]:
        raise validation("لا تُنشر حزمة بلا قواعد.")
    stamp = now_iso()
    with db.write() as conn:
        conn.execute("UPDATE rule_packages SET status='published', published_at=?, "
                     "published_by=? WHERE package_id=?",
                     (stamp, user.get("username", ""), package_id))
        audit.log(db, user, "نشر حزمة قواعد", "rule_packages", package_id,
                  f"{package['code']} إصدار {package['version']}", ip=ip, conn=conn)
    return get_package(db, package_id)


def new_version(db, user: dict, package_id: str, ip: str = "") -> dict:
    source = get_package(db, package_id)
    created = create_package(db, user, {
        "code": source["code"],
        "effective_from": today_iso(),
        "note": f"إصدار جديد من {source['code']} إصدار {source['version']}",
        "legal_source": source["legal_source"],
    }, ip)
    for row in source["rows"]:
        save_row(db, user, created["package_id"], {
            "rule_type": row["rule_type"], "name": row["name"], "scope": row["scope_data"],
            "params": row["params_data"], "priority": row["priority"],
        }, ip)
    return get_package(db, created["package_id"])


# ---------------------------------------------------------------------------
# المطابقة
# ---------------------------------------------------------------------------
def _matches(scope: dict, employee: dict, issuer_type: str = "") -> bool:
    for key, value in (scope or {}).items():
        if value in (None, "", [], {}):
            continue
        if key == "issuer_type":
            actual = issuer_type
        elif key == "job_title":
            actual = employee.get("title_code") or employee.get("job_title_id")
        else:
            actual = employee.get(key)
        if isinstance(value, list):
            if actual not in value and str(actual) not in [str(item) for item in value]:
                return False
        elif str(actual or "") != str(value):
            return False
    return True


def _rows(db, package_id: str, rule_type: str) -> list[dict]:
    if not package_id:
        return []
    rows = db.query("SELECT * FROM rule_rows WHERE package_id=? AND rule_type=? AND active=1 "
                    "ORDER BY priority, rowid", (package_id, rule_type))
    return [_decode_row(row) for row in rows]


def letter_effect(db, package: dict | None, employee: dict, issuer_type: str,
                  letter_date: str) -> dict | None:
    if not package:
        return None
    for row in _rows(db, package["package_id"], "letter_effect"):
        if not _matches(row["scope_data"], employee, issuer_type):
            continue
        params = row["params_data"]
        days = int(params.get("days") or 0)
        months = int(params.get("months") or 0)
        if months:
            start = as_date(letter_date)
            end = add_months(letter_date, months)
            days = max(0, (end - start).days) if start and end else 0
        return {"days": days, "months": months,
                "cap_days": int(params.get("cap_days") or 0),
                "cap_months": int(params.get("cap_months") or 0),
                "cap_period": params.get("cap_period") or "calendar_year",
                "rule_id": row["rule_id"], "rule_name": row["name"]}
    return None


def promotion_rule(db, package: dict | None, employee: dict) -> dict | None:
    if not package:
        return None
    for row in _rows(db, package["package_id"], "promotion"):
        if _matches(row["scope_data"], employee):
            return {"rule_id": row["rule_id"], "rule_name": row["name"],
                    "required_months": int(row["params_data"].get("required_months") or 0),
                    "to_grade": row["params_data"].get("to_grade", ""),
                    "to_stage": row["params_data"].get("to_stage", "")}
    return None


def increment_rule(db, package: dict | None, employee: dict) -> dict | None:
    if not package:
        return None
    for row in _rows(db, package["package_id"], "increment"):
        if _matches(row["scope_data"], employee):
            return {"rule_id": row["rule_id"], "rule_name": row["name"],
                    "required_months": int(row["params_data"].get("required_months") or 0),
                    "max_stage": row["params_data"].get("max_stage", "")}
    return None


def package_json(package: dict | None) -> dict:
    if not package:
        return {}
    return {"package_id": package["package_id"], "code": package["code"],
            "version": package["version"], "effective_from": package["effective_from"]}


MATRIX_CODE = "LAW-MATRIX"
MATRIX_SOURCE = (
    "قرار مجلس قيادة الثورة (المنحل) رقم 155 لسنة 2000؛ "
    "قانون انضباط موظفي الدولة رقم 14 لسنة 1991 المادة 21/أولاً؛ "
    "قانون رواتب موظفي الدولة رقم 22 لسنة 2008")


def seed_matrix(db, user: dict, ip: str = "") -> dict:
    """ينشئ حزمة المصفوفة القانونية المعتمدة (إن لم تكن موجودة) وينشرها."""
    existing = db.one("SELECT * FROM rule_packages WHERE code=?", (MATRIX_CODE,))
    if existing:
        return get_package(db, existing["package_id"])
    package = create_package(db, user, {
        "code": MATRIX_CODE, "effective_from": "1991-01-01",
        "note": "مصفوفة القِدَم والعلاوة والترفيع المعتمدة",
        "legal_source": MATRIX_SOURCE,
    }, ip)
    save_row(db, user, package["package_id"], {
        "rule_type": "promotion", "name": "الترفيع الاعتيادي (48 شهراً)",
        "scope": {}, "params": {"required_months": 48}, "priority": 10}, ip)
    save_row(db, user, package["package_id"], {
        "rule_type": "increment", "name": "العلاوة السنوية (12 شهراً)",
        "scope": {}, "params": {"required_months": 12}, "priority": 10}, ip)
    issuers = [
        ("president", "رئيس الجمهورية", 6, 0),
        ("prime_minister", "رئيس الوزراء", 6, 0),
        ("minister", "الوزير المختص", 1, 3),
        ("authority_head", "رئيس جهة غير مرتبطة بوزارة", 1, 3),
        ("undersecretary", "الوكيل", 1, 3),
        ("governor", "المحافظ", 1, 3),
        ("director_general", "المدير العام", 1, 3),
    ]
    for code, label, months, cap in issuers:
        save_row(db, user, package["package_id"], {
            "rule_type": "letter_effect", "name": f"كتاب شكر — {label}",
            "scope": {"issuer_type": code},
            "params": {"months": months, "cap_months": cap, "cap_period": "calendar_year"},
            "priority": 10}, ip)
    publish_package(db, user, package["package_id"], ip)
    return get_package(db, package["package_id"])
