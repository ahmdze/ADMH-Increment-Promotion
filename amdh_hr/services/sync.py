"""حزم USB: تصدير بيانات المؤسسة، استيرادها في المركز، وحزم القواعد العكسية."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from pathlib import Path

from ..config import APP_VERSION
from ..db import SCHEMA_VERSION
from .. import crypto
from ..errors import conflict, not_found, validation
from ..util import as_date, jdump, jload, now_iso, stamp
from . import audit, backup, orders as orders_service

FORMAT = "amdh-hr-package-1"
DIRECTIONS = {"institution_data": "بيانات مؤسسة", "center_rules": "حزمة قواعد",
              "center_results": "نتائج اعتماد"}


# ---------------------------------------------------------------------------
# التصدير
# ---------------------------------------------------------------------------
def _export_unit(db, user: dict, unit_id: str) -> dict:
    unit_id = str(unit_id or "").strip()
    if user.get("role") in {"unit_manager", "unit_editor"}:
        unit_id = user.get("unit_id") or ""
    if not unit_id:
        raise validation("حدّد المؤسسة.")
    unit = db.one("SELECT * FROM health_units WHERE unit_id=? AND deleted_at IS NULL", (unit_id,))
    if not unit:
        raise not_found("المؤسسة غير موجودة.")
    if unit["is_center"]:
        raise validation("لا تُصدَّر بيانات مركز الدائرة كحزمة مؤسسة.")
    return unit


def export_data(db, paths, user: dict, unit_id: str = "", period: dict | None = None,
                ip: str = "", password: str = "") -> dict:
    if password and len(password) < 8:
        raise validation("كلمة مرور الحزمة يجب ألا تقل عن 8 أحرف.")
    unit = _export_unit(db, user, unit_id)
    work = Path(tempfile.mkdtemp(prefix="amdh_pkg_"))
    source = work / "data.db"
    try:
        db.export_plaintext(source)
        connection = sqlite3.connect(str(source))
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=OFF")
            counts, stored = _filter_unit(connection, unit, db)
            connection.commit()
            connection.execute("VACUUM")
        finally:
            connection.close()

        package_id = uuid.uuid4().hex
        manifest = {
            "format": FORMAT, "direction": "institution_data", "package_id": package_id,
            "created_at": now_iso(), "app_version": APP_VERSION, "schema_version": SCHEMA_VERSION,
            "unit_id": unit["unit_id"], "unit_name": unit["name"], "unit_code": unit["code"],
            "center": (db.one("SELECT name FROM health_units WHERE is_center=1 "
                              "AND deleted_at IS NULL") or {}).get("name", ""),
            "counts": counts, "period": period or {},
        }
        (work / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
        attachments = work / "attachments"
        attachments.mkdir(exist_ok=True)
        for name in stored:
            file = Path(paths.attachments_dir) / name
            if file.exists():
                shutil.copy2(file, attachments / name)

        target = Path(paths.exports_dir) / f"AMDH_{unit['code']}_{stamp()}.amdhpkg"
        _zip_folder(work, target)
        if password:
            try:
                crypto.encrypt_package(target, target, password)
            except Exception:
                target.unlink(missing_ok=True)
                raise
        _record(db, user, package_id, "institution_data", unit, manifest, "exported")
        audit.log(db, user, "تصدير حزمة مؤسسة", "sync_packages", package_id,
                  f"{unit['name']} — {counts.get('employees', 0)} موظف", ip=ip)
        return {"path": str(target), "manifest": manifest, "counts": counts}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _filter_unit(connection, unit: dict, center_db) -> tuple[dict, list[str]]:
    unit_id = unit["unit_id"]
    for table in ("users", "sessions", "audit_events", "backup_jobs", "calc_runs",
                  "sync_packages", "rule_rows", "rule_packages"):
        connection.execute(f"DELETE FROM {table}")
    connection.execute(
        "DELETE FROM employee_history WHERE employee_id NOT IN "
        "(SELECT employee_id FROM employees WHERE unit_id=?)", (unit_id,))
    connection.execute("DELETE FROM employees WHERE unit_id<>?", (unit_id,))
    connection.execute(
        "DELETE FROM appreciation_letter_recipients WHERE employee_id NOT IN "
        "(SELECT employee_id FROM employees)")
    connection.execute(
        "DELETE FROM appreciation_letters WHERE letter_id NOT IN "
        "(SELECT letter_id FROM appreciation_letter_recipients)")
    connection.execute(
        "DELETE FROM hr_order_recipients WHERE employee_id NOT IN "
        "(SELECT employee_id FROM employees)")
    connection.execute(
        "DELETE FROM hr_orders WHERE order_id NOT IN "
        "(SELECT order_id FROM hr_order_recipients)")
    connection.execute(
        "DELETE FROM document_links WHERE "
        "(entity_type='employee' AND entity_id NOT IN (SELECT employee_id FROM employees)) "
        "OR (entity_type='letter' AND entity_id NOT IN "
        "(SELECT letter_id FROM appreciation_letters)) "
        "OR (entity_type='order' AND entity_id NOT IN (SELECT order_id FROM hr_orders))")
    connection.execute("DELETE FROM documents WHERE document_id NOT IN "
                       "(SELECT document_id FROM document_links)")
    center = center_db.one("SELECT * FROM health_units WHERE is_center=1 AND deleted_at IS NULL")
    keep = [unit_id] + ([center["unit_id"]] if center else [])
    connection.execute("DELETE FROM health_units WHERE unit_id NOT IN (" +
                       ",".join("?" for _ in keep) + ")", keep)
    connection.execute("UPDATE health_units SET is_center=0 WHERE unit_id<>?", (unit_id,))
    connection.execute("INSERT OR REPLACE INTO app_meta(key, value) VALUES ('package_unit_id',?)",
                       (unit_id,))
    connection.execute("INSERT OR REPLACE INTO app_meta(key, value) VALUES ('package_unit_name',?)",
                       (unit["name"],))
    counts = {
        "employees": connection.execute("SELECT COUNT(*) FROM employees").fetchone()[0],
        "letters": connection.execute("SELECT COUNT(*) FROM appreciation_letters").fetchone()[0],
        "orders": connection.execute("SELECT COUNT(*) FROM hr_orders").fetchone()[0],
        "documents": connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
        "titles": connection.execute("SELECT COUNT(*) FROM job_titles").fetchone()[0],
    }
    stored = [row[0] for row in connection.execute(
        "SELECT DISTINCT stored_name FROM documents").fetchall() if row[0]]
    return counts, stored


def export_rules(db, paths, user: dict, ip: str = "", password: str = "") -> dict:
    if password and len(password) < 8:
        raise validation("كلمة مرور الحزمة يجب ألا تقل عن 8 أحرف.")
    work = Path(tempfile.mkdtemp(prefix="amdh_rules_"))
    source = work / "rules.db"
    try:
        connection = sqlite3.connect(str(source))
        try:
            connection.executescript(
                "CREATE TABLE rule_packages (package_id TEXT PRIMARY KEY, code TEXT, version INTEGER,"
                " status TEXT, effective_from TEXT, effective_to TEXT, note TEXT, legal_source TEXT,"
                " created_by TEXT, created_at TEXT, published_at TEXT, published_by TEXT);"
                "CREATE TABLE rule_rows (rule_id TEXT PRIMARY KEY, package_id TEXT, rule_type TEXT,"
                " name TEXT, scope TEXT, params TEXT, priority INTEGER, active INTEGER);")
            packages = db.query("SELECT * FROM rule_packages WHERE status='published'")
            rows = db.query("SELECT * FROM rule_rows WHERE package_id IN "
                            "(SELECT package_id FROM rule_packages WHERE status='published')")
            for row in packages:
                connection.execute(
                    "INSERT INTO rule_packages VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    tuple(row[key] for key in ("package_id", "code", "version", "status",
                                               "effective_from", "effective_to", "note",
                                               "legal_source", "created_by", "created_at",
                                               "published_at", "published_by")))
            for row in rows:
                connection.execute("INSERT INTO rule_rows VALUES (?,?,?,?,?,?,?,?)",
                                   tuple(row[key] for key in ("rule_id", "package_id", "rule_type",
                                                              "name", "scope", "params", "priority",
                                                              "active")))
            connection.commit()
        finally:
            connection.close()
        package_id = uuid.uuid4().hex
        manifest = {
            "format": FORMAT, "direction": "center_rules", "package_id": package_id,
            "created_at": now_iso(), "app_version": APP_VERSION, "schema_version": SCHEMA_VERSION,
            "counts": {"packages": len(packages), "rules": len(rows)},
        }
        (work / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
        target = Path(paths.exports_dir) / f"قواعد_{stamp()}.amdhpkg"
        _zip_folder(work, target)
        if password:
            try:
                crypto.encrypt_package(target, target, password)
            except Exception:
                target.unlink(missing_ok=True)
                raise
        _record(db, user, package_id, "center_rules", None, manifest, "exported")
        audit.log(db, user, "تصدير حزمة قواعد", "sync_packages", package_id,
                  f"{len(packages)} حزمة", ip=ip)
        return {"path": str(target), "manifest": manifest}
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------------------
# الاستيراد
# ---------------------------------------------------------------------------
def export_results(db, paths, user: dict, unit_id: str, ip: str = "",
                   password: str = "") -> dict:
    if password and len(password) < 8:
        raise validation("كلمة مرور الحزمة يجب ألا تقل عن 8 أحرف.")
    unit = _export_unit(db, user, unit_id)
    work = Path(tempfile.mkdtemp(prefix="amdh_results_"))
    source = work / "results.db"
    try:
        connection = sqlite3.connect(str(source))
        try:
            connection.executescript(
                "CREATE TABLE appreciation_letters (letter_id TEXT PRIMARY KEY, unit_id TEXT,"
                " issuer TEXT, issuer_type TEXT, letter_no TEXT, letter_date TEXT, received_date TEXT,"
                " subject TEXT, target_mode TEXT, target_params TEXT, reference_date TEXT, status TEXT,"
                " notes TEXT, created_by TEXT, created_at TEXT, updated_at TEXT, deleted_at TEXT);"
                "CREATE TABLE appreciation_letter_recipients (letter_id TEXT, employee_id TEXT,"
                " eligible INTEGER, effect_days REAL, effect_state TEXT, note TEXT,"
                " PRIMARY KEY (letter_id, employee_id));"
                "CREATE TABLE hr_orders (order_id TEXT PRIMARY KEY, unit_id TEXT, order_type TEXT,"
                " order_no TEXT, order_date TEXT, issuer TEXT, effective_date TEXT, status TEXT,"
                " notes TEXT, created_by TEXT, created_at TEXT, updated_at TEXT, deleted_at TEXT,"
                " apply_mode TEXT, to_grade TEXT, to_stage TEXT, applied_at TEXT);"
                "CREATE TABLE hr_order_recipients (order_id TEXT, employee_id TEXT, note TEXT,"
                " PRIMARY KEY (order_id, employee_id));")
            letters = db.query(
                "SELECT * FROM appreciation_letters WHERE unit_id=? AND status='approved' "
                "AND deleted_at IS NULL", (unit["unit_id"],))
            for row in letters:
                connection.execute(
                    "INSERT INTO appreciation_letters VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    tuple(row[key] for key in ("letter_id", "unit_id", "issuer", "issuer_type",
                                               "letter_no", "letter_date", "received_date",
                                               "subject", "target_mode", "target_params",
                                               "reference_date", "status", "notes", "created_by",
                                               "created_at", "updated_at", "deleted_at")))
                for recipient in db.query(
                        "SELECT * FROM appreciation_letter_recipients WHERE letter_id=?",
                        (row["letter_id"],)):
                    connection.execute(
                        "INSERT INTO appreciation_letter_recipients VALUES (?,?,?,?,?,?)",
                        tuple(recipient[key] for key in ("letter_id", "employee_id", "eligible",
                                                         "effect_days", "effect_state", "note")))
            orders = db.query(
                "SELECT * FROM hr_orders WHERE unit_id=? AND status='approved' AND deleted_at IS NULL",
                (unit["unit_id"],))
            for row in orders:
                connection.execute(
                    "INSERT INTO hr_orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (*tuple(row[key] for key in (
                        "order_id", "unit_id", "order_type", "order_no", "order_date", "issuer",
                        "effective_date", "status", "notes", "created_by", "created_at",
                        "updated_at", "deleted_at")),
                     row.get("apply_mode", "auto") if hasattr(row, "get") else "auto",
                     row.get("to_grade", "") if hasattr(row, "get") else "",
                     row.get("to_stage", "") if hasattr(row, "get") else "",
                     None))
                for recipient in db.query("SELECT * FROM hr_order_recipients WHERE order_id=?",
                                          (row["order_id"],)):
                    connection.execute("INSERT INTO hr_order_recipients VALUES (?,?,?)",
                                       (recipient["order_id"], recipient["employee_id"],
                                        recipient["note"]))
            connection.commit()
        finally:
            connection.close()
        package_id = uuid.uuid4().hex
        manifest = {
            "format": FORMAT, "direction": "center_results", "package_id": package_id,
            "created_at": now_iso(), "app_version": APP_VERSION, "schema_version": SCHEMA_VERSION,
            "unit_id": unit["unit_id"], "unit_name": unit["name"], "unit_code": unit["code"],
            "counts": {"letters": len(letters), "orders": len(orders)},
        }
        (work / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
        target = Path(paths.exports_dir) / f"نتائج_{unit['code']}_{stamp()}.amdhpkg"
        _zip_folder(work, target)
        if password:
            try:
                crypto.encrypt_package(target, target, password)
            except Exception:
                target.unlink(missing_ok=True)
                raise
        _record(db, user, package_id, "center_results", unit, manifest, "exported")
        audit.log(db, user, "تصدير نتائج اعتماد", "sync_packages", package_id,
                  f"{unit['name']} — {len(letters)} كتاب، {len(orders)} أمر", ip=ip)
        return {"path": str(target), "manifest": manifest}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def preview(db, path: str | Path, password: str = "") -> dict:
    manifest, work, source = _open_package(path, password)
    try:
        connection = sqlite3.connect(str(source))
        connection.row_factory = sqlite3.Row
        try:
            direction = manifest.get("direction")
            if direction == "institution_data":
                unit = _target_unit(db, manifest)
                existing = db.one("SELECT 1 FROM sync_packages WHERE package_id=? AND status='imported'",
                                  (manifest.get("package_id"),))
                counts = {"new_employees": 0, "updated_employees": 0, "conflicts": 0,
                          "new_letters": 0, "new_orders": 0, "new_documents": 0}
                for row in connection.execute("SELECT * FROM employees"):
                    target = db.one("SELECT employee_id, updated_at FROM employees "
                                    "WHERE employee_id=?", (row["employee_id"],))
                    if target:
                        counts["updated_employees"] += 1
                    else:
                        counts["new_employees"] += 1
                    clash = db.one("SELECT employee_id FROM employees WHERE lower(emp_no)=lower(?) "
                                   "AND unit_id=? AND deleted_at IS NULL", (row["emp_no"], unit))
                    if clash and clash["employee_id"] != row["employee_id"]:
                        counts["conflicts"] += 1
                counts["new_letters"] = sum(
                    1 for row in connection.execute("SELECT letter_id FROM appreciation_letters")
                    if not db.one("SELECT 1 FROM appreciation_letters WHERE letter_id=?",
                                  (row["letter_id"],)))
                counts["new_orders"] = sum(
                    1 for row in connection.execute("SELECT order_id FROM hr_orders")
                    if not db.one("SELECT 1 FROM hr_orders WHERE order_id=?", (row["order_id"],)))
                counts["new_documents"] = sum(
                    1 for row in connection.execute("SELECT sha256 FROM documents")
                    if not db.one("SELECT 1 FROM documents WHERE sha256=?", (row["sha256"],)))
                return {"manifest": manifest, "duplicate": bool(existing), "counts": counts,
                        "unit": unit, "can_import": True}
            if direction == "center_results":
                unit = _target_unit(db, manifest)
                duplicate = bool(db.one(
                    "SELECT 1 FROM sync_packages WHERE package_id=? AND status='imported'",
                    (manifest.get("package_id"),)))
                letters = connection.execute("SELECT letter_id FROM appreciation_letters").fetchall()
                orders = connection.execute("SELECT order_id FROM hr_orders").fetchall()
                return {"manifest": manifest, "duplicate": duplicate,
                        "counts": {"letters": len(letters), "orders": len(orders)},
                        "unit": unit, "can_import": True}
            packages = connection.execute("SELECT package_id, code, version FROM rule_packages").fetchall()
            new = sum(1 for row in packages if not db.one(
                "SELECT 1 FROM rule_packages WHERE package_id=?", (row["package_id"],)))
            return {"manifest": manifest, "duplicate": bool(db.one(
                "SELECT 1 FROM sync_packages WHERE package_id=? AND status='imported'",
                (manifest.get("package_id"),))),
                "counts": {"packages": len(packages), "new_packages": new},
                "unit": None, "can_import": True}
        finally:
            connection.close()
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _target_unit(db, manifest: dict) -> str:
    unit_id = str(manifest.get("unit_id") or "")
    unit = db.one("SELECT unit_id FROM health_units WHERE unit_id=? AND deleted_at IS NULL",
                  (unit_id,))
    if unit:
        return unit["unit_id"]
    unit = db.one("SELECT unit_id FROM health_units WHERE (code=? OR name=?) "
                  "AND deleted_at IS NULL", (manifest.get("unit_code"), manifest.get("unit_name")))
    if unit:
        return unit["unit_id"]
    raise validation(f"المؤسسة «{manifest.get('unit_name')}» غير موجودة في المركز. "
                     "أنشئها أولاً بنفس الرمز.")


def _open_package(path, password: str = ""):
    path = Path(path)
    if not path.exists():
        raise validation("ملف الحزمة غير موجود.")
    work = Path(tempfile.mkdtemp(prefix="amdh_import_"))
    try:
        archive_path = path
        if crypto.is_encrypted_package(path):
            if not password:
                raise validation("هذه حزمة مشفرة؛ أدخل كلمة مرور الحزمة.")
            archive_path = work / "package.zip"
            try:
                crypto.decrypt_package(path, archive_path, password)
            except crypto.CryptoError as exc:
                raise validation(str(exc)) from exc
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            if "manifest.json" not in names:
                raise validation("الملف ليس حزمة صالحة (لا يحوي بياناً).")
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            if manifest.get("format") != FORMAT:
                raise validation("صيغة الحزمة غير مدعومة.")
            archive.extractall(work)
        source = next((work / name for name in ("data.db", "rules.db", "results.db")
                       if (work / name).exists()), None)
        if source is None:
            raise validation("الحزمة لا تحوي قاعدة بيانات.")
        return manifest, work, source
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise


def import_package(db, paths, user: dict, path: str | Path, ip: str = "",
                   resolutions: dict | None = None, password: str = "") -> dict:
    manifest, work, source = _open_package(path, password)
    try:
        package_id = manifest.get("package_id")
        if db.one("SELECT 1 FROM sync_packages WHERE package_id=? AND status='imported'",
                  (package_id,)):
            return {"already_imported": True, "package_id": package_id}
        direction = manifest.get("direction")
        if direction == "institution_data":
            result = _import_data(db, paths, user, manifest, source, work, resolutions)
        elif direction == "center_results":
            result = _import_results(db, user, manifest, source)
        else:
            result = _import_rules(db, user, manifest, source)
        _mark_imported(db, user, manifest, result)
        audit.log(db, user, "استيراد حزمة", "sync_packages", package_id,
                  f"{DIRECTIONS.get(manifest.get('direction'), '')} — {result}", ip=ip)
        return {"already_imported": False, "package_id": package_id, **result}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def conflicts(db, path: str | Path, password: str = "") -> dict:
    """يعيد تعارضات أرقام الموظفين بين الحزمة والمركز (هوية مختلفة)."""
    manifest, work, source = _open_package(path, password)
    try:
        if manifest.get("direction") != "institution_data":
            return {"conflicts": [], "unit": ""}
        unit_id = _target_unit(db, manifest)
        connection = sqlite3.connect(str(source))
        connection.row_factory = sqlite3.Row
        rows = []
        try:
            for row in connection.execute("SELECT * FROM employees"):
                target = db.one(
                    "SELECT * FROM employees WHERE lower(emp_no)=lower(?) AND unit_id=? "
                    "AND deleted_at IS NULL", (row["emp_no"], unit_id))
                if target and target["employee_id"] != row["employee_id"]:
                    rows.append({
                        "source_id": row["employee_id"], "target_id": target["employee_id"],
                        "emp_no": row["emp_no"], "source_name": row["full_name"],
                        "target_name": target["full_name"],
                        "source_grade": row["grade"], "target_grade": target["grade"],
                        "source_stage": row["stage"], "target_stage": target["stage"],
                        "source_updated": row["updated_at"] or "",
                    })
        finally:
            connection.close()
        return {"conflicts": rows, "unit": unit_id}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _import_data(db, paths, user: dict, manifest: dict, source, work: Path,
                 resolutions: dict | None = None) -> dict:
    unit_id = _target_unit(db, manifest)
    backup_path = backup.run(db, paths, user, kind="pre_import", ip="")["path"]
    connection = sqlite3.connect(str(source))
    connection.row_factory = sqlite3.Row
    counts = {"employees_added": 0, "employees_updated": 0, "letters": 0, "orders": 0,
              "documents": 0, "links": 0, "conflicts_resolved": 0}
    resolutions = resolutions or {}
    mapping: dict[str, str] = {}
    try:
        title_map: dict[str, str] = {}
        for row in connection.execute("SELECT * FROM job_titles"):
            existing = db.one("SELECT title_id FROM job_titles WHERE code=?", (row["code"],))
            if existing:
                title_map[row["title_id"]] = existing["title_id"]
            else:
                title_map[row["title_id"]] = row["title_id"]
        with db.write() as conn:
            for row in connection.execute("SELECT * FROM job_titles"):
                conn.execute("INSERT OR IGNORE INTO job_titles(title_id, code, name, grade, active, "
                             "created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                             (row["title_id"], row["code"], row["name"], row["grade"],
                              row["active"], row["created_at"], row["updated_at"]))
            for row in connection.execute("SELECT * FROM employees"):
                target = db.one(
                    "SELECT * FROM employees WHERE lower(emp_no)=lower(?) AND unit_id=? "
                    "AND deleted_at IS NULL", (row["emp_no"], unit_id))
                if not target or target["employee_id"] == row["employee_id"]:
                    continue
                mapping[row["employee_id"]] = target["employee_id"]
                counts["conflicts_resolved"] += 1
                if resolutions.get(row["employee_id"], "target") == "source":
                    title_id = title_map.get(row["job_title_id"], row["job_title_id"])
                    conn.execute(
                        "UPDATE employees SET full_name=?, job_title_id=?, grade=?, stage=?, "
                        "category=?, hire_date=?, end_date=?, gender=?, status=?, notes=?, "
                        "last_grade_date=?, last_stage_date=?, version=version+1, updated_at=? "
                        "WHERE employee_id=?",
                        (row["full_name"], title_id, row["grade"], row["stage"],
                         row["category"], row["hire_date"], row["end_date"], row["gender"],
                         row["status"], row["notes"],
                         _row(row, "last_grade_date", row["hire_date"]),
                         _row(row, "last_stage_date", row["hire_date"]),
                         row["updated_at"], target["employee_id"]))
                    counts["employees_updated"] += 1
            for row in connection.execute("SELECT * FROM employees"):
                if row["employee_id"] in mapping:
                    continue
                existing = db.one("SELECT * FROM employees WHERE employee_id=?",
                                  (row["employee_id"],))
                title_id = title_map.get(row["job_title_id"], row["job_title_id"])
                if existing:
                    if str(row["updated_at"] or "") > str(existing["updated_at"] or ""):
                        conn.execute(
                            "UPDATE employees SET emp_no=?, full_name=?, job_title_id=?, grade=?, "
                            "stage=?, category=?, hire_date=?, end_date=?, gender=?, status=?, "
                            "notes=?, last_grade_date=?, last_stage_date=?, version=version+1, "
                            "updated_at=? WHERE employee_id=?",
                            (row["emp_no"], row["full_name"], title_id, row["grade"], row["stage"],
                             row["category"], row["hire_date"], row["end_date"], row["gender"],
                             row["status"], row["notes"], _row(row, "last_grade_date",
                                                               row["hire_date"]),
                             _row(row, "last_stage_date", row["hire_date"]), row["updated_at"],
                             row["employee_id"]))
                        counts["employees_updated"] += 1
                else:
                    conn.execute(
                        "INSERT INTO employees(employee_id, emp_no, full_name, unit_id, "
                        "job_title_id, grade, stage, category, hire_date, end_date, gender, "
                        "status, notes, assigned_user_id, last_grade_date, last_stage_date, "
                        "version, created_at, updated_at, deleted_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?,?,1,?,?,?)",
                        (row["employee_id"], row["emp_no"], row["full_name"], unit_id, title_id,
                         row["grade"], row["stage"], row["category"], row["hire_date"],
                         row["end_date"], row["gender"], row["status"], row["notes"],
                         _row(row, "last_grade_date", row["hire_date"]),
                         _row(row, "last_stage_date", row["hire_date"]),
                         row["created_at"], row["updated_at"], row["deleted_at"]))
                    counts["employees_added"] += 1
            for row in connection.execute("SELECT * FROM employee_history"):
                employee_id = mapping.get(row["employee_id"], row["employee_id"])
                if not db.one("SELECT 1 FROM employees WHERE employee_id=?", (employee_id,)):
                    continue
                conn.execute("INSERT OR IGNORE INTO employee_history(history_id, employee_id, "
                             "event_type, effective_date, old_value, new_value, order_no, note, "
                             "created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (row["history_id"], employee_id,
                              row["event_type"], row["effective_date"], row["old_value"],
                              row["new_value"], row["order_no"], row["note"], row["created_by"],
                              row["created_at"]))
            for row in connection.execute("SELECT * FROM appreciation_letters"):
                existing = db.one("SELECT status, updated_at FROM appreciation_letters "
                                  "WHERE letter_id=?", (row["letter_id"],))
                if existing is None:
                    conn.execute(
                        "INSERT INTO appreciation_letters(letter_id, unit_id, issuer, issuer_type, "
                        "letter_no, letter_date, received_date, subject, target_mode, target_params, "
                        "reference_date, status, notes, created_by, created_at, updated_at, "
                        "deleted_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (row["letter_id"], unit_id, row["issuer"], row["issuer_type"],
                         row["letter_no"], row["letter_date"], row["received_date"], row["subject"],
                         row["target_mode"], row["target_params"], row["reference_date"],
                         row["status"], row["notes"], row["created_by"], row["created_at"],
                         row["updated_at"], row["deleted_at"]))
                    counts["letters"] += 1
                elif row["status"] == "approved" and existing["status"] != "approved":
                    conn.execute("UPDATE appreciation_letters SET status='approved', updated_at=? "
                                 "WHERE letter_id=?", (row["updated_at"], row["letter_id"]))
                    counts["letters"] += 1
            for row in connection.execute("SELECT * FROM appreciation_letter_recipients"):
                employee_id = mapping.get(row["employee_id"], row["employee_id"])
                if not db.one("SELECT 1 FROM employees WHERE employee_id=?", (employee_id,)):
                    continue
                conn.execute("INSERT OR IGNORE INTO appreciation_letter_recipients(letter_id, "
                             "employee_id, eligible, effect_days, effect_state, note) "
                             "VALUES (?,?,?,?,?,?)",
                             (row["letter_id"], employee_id, row["eligible"],
                              row["effect_days"], row["effect_state"], row["note"]))
            for row in connection.execute("SELECT * FROM hr_orders"):
                existing = db.one("SELECT status FROM hr_orders WHERE order_id=?", (row["order_id"],))
                if existing is None:
                    conn.execute(
                        "INSERT INTO hr_orders(order_id, unit_id, order_type, order_no, order_date, "
                        "issuer, effective_date, status, notes, created_by, created_at, updated_at, "
                        "deleted_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (row["order_id"], unit_id, row["order_type"], row["order_no"],
                         row["order_date"], row["issuer"], row["effective_date"], row["status"],
                         row["notes"], row["created_by"], row["created_at"], row["updated_at"],
                         row["deleted_at"]))
                    counts["orders"] += 1
                elif row["status"] == "approved" and existing["status"] != "approved":
                    conn.execute("UPDATE hr_orders SET status='approved', updated_at=? "
                                 "WHERE order_id=?", (row["updated_at"], row["order_id"]))
                    counts["orders"] += 1
            for row in connection.execute("SELECT * FROM hr_order_recipients"):
                employee_id = mapping.get(row["employee_id"], row["employee_id"])
                if not db.one("SELECT 1 FROM employees WHERE employee_id=?", (employee_id,)):
                    continue
                conn.execute("INSERT OR IGNORE INTO hr_order_recipients(order_id, employee_id, note) "
                             "VALUES (?,?,?)", (row["order_id"], employee_id, row["note"]))
            document_map: dict[str, str] = {}
            for row in connection.execute("SELECT * FROM documents"):
                existing = db.one("SELECT document_id FROM documents WHERE sha256=?",
                                  (row["sha256"],))
                if existing:
                    document_map[row["document_id"]] = existing["document_id"]
                    continue
                document_map[row["document_id"]] = row["document_id"]
                conn.execute("INSERT INTO documents(document_id, sha256, filename, stored_name, mime, "
                             "size, uploaded_by, uploaded_at) VALUES (?,?,?,?,?,?,?,?)",
                             (row["document_id"], row["sha256"], row["filename"],
                              row["stored_name"], row["mime"], row["size"], row["uploaded_by"],
                              row["uploaded_at"]))
                counts["documents"] += 1
                source_file = work / "attachments" / row["stored_name"]
                target_file = Path(paths.attachments_dir) / row["stored_name"]
                if source_file.exists() and not target_file.exists():
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source_file, target_file)
            for row in connection.execute("SELECT * FROM document_links"):
                document_id = document_map.get(row["document_id"], row["document_id"])
                entity_id = row["entity_id"]
                if row["entity_type"] == "employee":
                    entity_id = mapping.get(entity_id, entity_id)
                    if not db.one("SELECT 1 FROM employees WHERE employee_id=?", (entity_id,)):
                        continue
                if db.one("SELECT 1 FROM document_links WHERE document_id=? AND entity_type=? "
                          "AND entity_id=? AND purpose=?",
                          (document_id, row["entity_type"], entity_id, row["purpose"])):
                    continue
                conn.execute("INSERT INTO document_links(link_id, document_id, entity_type, "
                             "entity_id, purpose, created_at) VALUES (?,?,?,?,?,?)",
                             (uuid.uuid4().hex, document_id, row["entity_type"], entity_id,
                              row["purpose"], now_iso()))
                counts["links"] += 1
    finally:
        connection.close()
    counts["backup"] = backup_path
    return counts


def _row(row, key: str, default: str = ""):
    try:
        value = row[key]
    except (IndexError, KeyError):
        return default
    return value if value is not None else default


def _import_results(db, user: dict, manifest: dict, source) -> dict:
    unit_id = _target_unit(db, manifest)
    connection = sqlite3.connect(str(source))
    connection.row_factory = sqlite3.Row
    counts = {"letters": 0, "orders": 0}
    try:
        with db.write() as conn:
            for row in connection.execute("SELECT * FROM appreciation_letters"):
                existing = db.one("SELECT status FROM appreciation_letters WHERE letter_id=?",
                                  (row["letter_id"],))
                if existing is None:
                    conn.execute(
                        "INSERT INTO appreciation_letters(letter_id, unit_id, issuer, issuer_type, "
                        "letter_no, letter_date, received_date, subject, target_mode, target_params, "
                        "reference_date, status, notes, created_by, created_at, updated_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (row["letter_id"], unit_id, row["issuer"], row["issuer_type"],
                         row["letter_no"], row["letter_date"], row["received_date"], row["subject"],
                         row["target_mode"], row["target_params"], row["reference_date"],
                         "approved", row["notes"], row["created_by"], row["created_at"],
                         row["updated_at"]))
                    counts["letters"] += 1
                elif existing["status"] != "approved":
                    conn.execute("UPDATE appreciation_letters SET status='approved', updated_at=? "
                                 "WHERE letter_id=?", (row["updated_at"], row["letter_id"]))
                    counts["letters"] += 1
                for recipient in connection.execute(
                        "SELECT * FROM appreciation_letter_recipients WHERE letter_id=?",
                        (row["letter_id"],)):
                    if not db.one("SELECT 1 FROM employees WHERE employee_id=?",
                                  (recipient["employee_id"],)):
                        continue
                    conn.execute("INSERT OR IGNORE INTO appreciation_letter_recipients(letter_id, "
                                 "employee_id, eligible, effect_days, effect_state, note) "
                                 "VALUES (?,?,?,?,?,?)",
                                 (recipient["letter_id"], recipient["employee_id"],
                                  recipient["eligible"], recipient["effect_days"],
                                  recipient["effect_state"], recipient["note"]))
            for row in connection.execute("SELECT * FROM hr_orders"):
                existing = db.one("SELECT status, applied_at FROM hr_orders WHERE order_id=?",
                                  (row["order_id"],))
                if existing is None:
                    conn.execute(
                        "INSERT INTO hr_orders(order_id, unit_id, order_type, order_no, order_date, "
                        "issuer, effective_date, status, notes, created_by, created_at, updated_at, "
                        "apply_mode, to_grade, to_stage) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (row["order_id"], unit_id, row["order_type"], row["order_no"],
                         row["order_date"], row["issuer"], row["effective_date"], "approved",
                         row["notes"], row["created_by"], row["created_at"], row["updated_at"],
                         _row(row, "apply_mode", "auto"), _row(row, "to_grade", ""),
                         _row(row, "to_stage", "")))
                    counts["orders"] += 1
                elif existing["status"] != "approved":
                    conn.execute("UPDATE hr_orders SET status='approved', updated_at=? "
                                 "WHERE order_id=?", (row["updated_at"], row["order_id"]))
                    counts["orders"] += 1
                for recipient in connection.execute(
                        "SELECT * FROM hr_order_recipients WHERE order_id=?", (row["order_id"],)):
                    if not db.one("SELECT 1 FROM employees WHERE employee_id=?",
                                  (recipient["employee_id"],)):
                        continue
                    conn.execute("INSERT OR IGNORE INTO hr_order_recipients(order_id, employee_id, "
                                 "note) VALUES (?,?,?)",
                                 (recipient["order_id"], recipient["employee_id"],
                                  recipient["note"]))
                order_row = db.one("SELECT * FROM hr_orders WHERE order_id=?", (row["order_id"],))
                if order_row and not order_row.get("applied_at"):
                    counts["applied"] = counts.get("applied", 0) + orders_service.apply_order_effects(
                        db, order_row, user, conn=conn)
    finally:
        connection.close()
    return counts


def _import_rules(db, user: dict, manifest: dict, source) -> dict:
    connection = sqlite3.connect(str(source))
    connection.row_factory = sqlite3.Row
    counts = {"packages_added": 0, "rules_added": 0, "packages_skipped": 0}
    try:
        with db.write() as conn:
            for row in connection.execute("SELECT * FROM rule_packages"):
                if db.one("SELECT 1 FROM rule_packages WHERE package_id=?", (row["package_id"],)):
                    counts["packages_skipped"] += 1
                    continue
                conn.execute(
                    "INSERT INTO rule_packages(package_id, code, version, status, effective_from, "
                    "effective_to, note, legal_source, created_by, created_at, published_at, "
                    "published_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    tuple(row[key] for key in ("package_id", "code", "version", "status",
                                               "effective_from", "effective_to", "note",
                                               "legal_source", "created_by", "created_at",
                                               "published_at", "published_by")))
                counts["packages_added"] += 1
            for row in connection.execute("SELECT * FROM rule_rows"):
                conn.execute("INSERT OR IGNORE INTO rule_rows(rule_id, package_id, rule_type, name, "
                             "scope, params, priority, active) VALUES (?,?,?,?,?,?,?,?)",
                             tuple(row[key] for key in ("rule_id", "package_id", "rule_type", "name",
                                                        "scope", "params", "priority", "active")))
                counts["rules_added"] += 1
    finally:
        connection.close()
    return counts


# ---------------------------------------------------------------------------
# السجل والمساعدات
# ---------------------------------------------------------------------------
def _record(db, user, package_id: str, direction: str, unit, manifest: dict, status: str) -> None:
    with db.write() as conn:
        conn.execute("INSERT OR REPLACE INTO sync_packages(package_id, direction, source_unit_id, "
                     "source_unit_name, created_at, status, manifest) VALUES (?,?,?,?,?,?,?)",
                     (package_id, direction, unit["unit_id"] if unit else "",
                      unit["name"] if unit else "", now_iso(), status,
                      jdump(manifest)))


def _mark_imported(db, user, manifest: dict, result: dict) -> None:
    package_id = manifest.get("package_id")
    with db.write() as conn:
        conn.execute("INSERT OR REPLACE INTO sync_packages(package_id, direction, source_unit_id, "
                     "source_unit_name, created_at, imported_at, status, manifest, note) "
                     "VALUES (?,?,?,?,?,?,?,?,?)",
                     (package_id, manifest.get("direction", ""), manifest.get("unit_id", ""),
                      manifest.get("unit_name", ""), manifest.get("created_at", now_iso()),
                      now_iso(), "imported", jdump(manifest), jdump(result)))


def log(db) -> list[dict]:
    rows = db.query("SELECT * FROM sync_packages ORDER BY created_at DESC LIMIT 200")
    for row in rows:
        row["direction_label"] = DIRECTIONS.get(row["direction"], row["direction"])
        row["manifest_data"] = jload(row["manifest"])
    return rows


def _zip_folder(folder: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in folder.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(folder).as_posix())


def packages_list(paths) -> list[dict]:
    folder = Path(paths.exports_dir)
    if not folder.exists():
        return []
    rows = []
    for path in sorted(folder.glob("*.amdhpkg"), key=lambda p: p.stat().st_mtime, reverse=True):
        rows.append({"name": path.name, "path": str(path),
                     "size_kb": round(path.stat().st_size / 1024, 1),
                     "encrypted": crypto.is_encrypted_package(path),
                     "modified": path.stat().st_mtime})
    return rows
