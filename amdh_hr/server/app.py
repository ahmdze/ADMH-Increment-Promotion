"""طبقة الخدمة: تجمع قاعدة البيانات والخدمات وتفرض الصلاحيات لكل عملية."""

from __future__ import annotations

import base64
import uuid
from pathlib import Path

from .. import permissions as P
from ..config import APP_NAME, APP_VERSION, Paths
from ..db import Database
from ..errors import AppError, forbidden, unauthenticated, validation
from ..logging_setup import get_logger
from ..util import now_iso, stamp
from ..services import (audit, auth, backup, calc, documents, employees, letters,
                        orders, provisioning, reports, rules, sync as sync_service,
                        units, users)
from ..exporters import csv as CSV
from ..exporters import excel as X
from ..exporters import html as H
from ..exporters import pdf as PDF

LOG = get_logger("service")


class ServiceApp:
    """كل المنطق هنا؛ العميل لا يصل إلى قاعدة البيانات مباشرة."""

    def __init__(self, paths: Paths, db_key: str = "") -> None:
        self.paths = paths.ensure()
        self.db = Database(paths.db_path, db_key)
        self._methods = {
            "ping": (self._ping, None),
            "bootstrap.status": (self._bootstrap_status, None),
            "bootstrap.create_admin": (self._bootstrap_create_admin, None),
            "auth.login": (self._login, None),
            "auth.logout": (self._logout, None),
            "auth.me": (self._me, None),
            "auth.change_password": (self._change_password, None),
            "meta.info": (self._meta_info, None),
            "units.list": (self._units_list, None),
            "units.get": (self._units_get, None),
            "units.create": (self._units_create, "manage_units"),
            "units.update": (self._units_update, "manage_units"),
            "units.delete": (self._units_delete, "manage_units"),
            "units.reset_users": (self._units_reset_users, "manage_users"),
            "units.provision": (self._units_provision, "provision_units"),
            "users.list": (self._users_list, "manage_users"),
            "users.create": (self._users_create, "manage_users"),
            "users.update": (self._users_update, "manage_users"),
            "users.reset_password": (self._users_reset, "manage_users"),
            "users.set_active": (self._users_set_active, "manage_users"),
            "backup.list": (self._backup_list, "backup_restore"),
            "backup.run": (self._backup_run, "backup_restore"),
            "backup.verify": (self._backup_verify, "backup_restore"),
            "audit.list": (self._audit_list, "view_audit"),
            "titles.list": (self._titles_list, "view_employees"),
            "titles.create": (self._titles_create, "edit_rules"),
            "titles.update": (self._titles_update, "edit_rules"),
            "employees.list": (self._employees_list, "view_employees"),
            "employees.get": (self._employees_get, "view_employees"),
            "employees.history": (self._employees_history, "view_employees"),
            "employees.create": (self._employees_create, "edit_employee"),
            "employees.update": (self._employees_update, "edit_employee"),
            "employees.archive": (self._employees_archive, "delete_employee"),
            "employees.assign": (self._employees_assign, "assign_employees"),
            "employees.import": (self._employees_import, "edit_employee"),
            "employees.export": (self._employees_export, "export_reports"),
            "employees.template": (self._employees_template, "edit_employee"),
            "employees.stats": (self._employees_stats, "view_employees"),
            "employees.assignment_summary": (self._employees_assignment, "assign_employees"),
            "employees.assignable_users": (self._employees_assignable, "assign_employees"),
            "letters.list": (self._letters_list, "view_letters"),
            "letters.get": (self._letters_get, "view_letters"),
            "letters.preview": (self._letters_preview, "view_letters"),
            "letters.create": (self._letters_create, "edit_letters"),
            "letters.approve": (self._letters_approve, "approve_letters"),
            "letters.delete": (self._letters_delete, "edit_letters"),
            "orders.list": (self._orders_list, "view_orders"),
            "orders.get": (self._orders_get, "view_orders"),
            "orders.create": (self._orders_create, "edit_orders"),
            "orders.approve": (self._orders_approve, "approve_orders"),
            "orders.delete": (self._orders_delete, "edit_orders"),
            "rules.packages": (self._rules_packages, "view_settings"),
            "rules.get": (self._rules_get, "view_settings"),
            "rules.create_package": (self._rules_create_package, "edit_rules"),
            "rules.update_package": (self._rules_update_package, "edit_rules"),
            "rules.save_row": (self._rules_save_row, "edit_rules"),
            "rules.delete_row": (self._rules_delete_row, "edit_rules"),
            "rules.publish": (self._rules_publish, "publish_rules"),
            "rules.new_version": (self._rules_new_version, "edit_rules"),
            "rules.seed_matrix": (self._rules_seed_matrix, "edit_rules"),
            "calc.employee": (self._calc_employee, "view_employees"),
            "calc.export_pdf": (self._calc_export_pdf, "view_employees"),
            "calc.runs": (self._calc_runs, "view_employees"),
            "documents.upload": (self._documents_upload, "edit_employee"),
            "documents.list": (self._documents_list, "view_employees"),
            "documents.fetch": (self._documents_fetch, "view_employees"),
            "documents.unlink": (self._documents_unlink, "edit_employee"),
            "reports.types": (self._reports_types, "export_reports"),
            "reports.run": (self._reports_run, "export_reports"),
            "reports.export": (self._reports_export, "export_reports"),
            "sync.export_data": (self._sync_export_data, "export_package"),
            "sync.export_rules": (self._sync_export_rules, "publish_rules"),
            "sync.export_results": (self._sync_export_results, "approve_final"),
            "sync.preview": (self._sync_preview, None),
            "sync.conflicts": (self._sync_conflicts, "import_package"),
            "sync.import": (self._sync_import, "import_package"),
            "sync.import_rules": (self._sync_import_rules, "import_rules"),
            "sync.import_results": (self._sync_import_results, "import_results"),
            "sync.log": (self._sync_log, "view_settings"),
            "sync.packages": (self._sync_packages, "view_settings"),
        }

    # ------------------------------------------------------------------
    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------------
    def dispatch(self, method: str, params: dict | None = None, token: str = "",
                 ip: str = "") -> dict:
        params = params or {}
        entry = self._methods.get(method)
        if entry is None:
            return {"ok": False, "error": {"code": "unknown_method",
                                           "message": f"عملية غير معروفة: {method}"}}
        handler, permission = entry
        try:
            user = None
            if permission is not None or method not in {
                    "ping", "bootstrap.status", "bootstrap.create_admin", "auth.login"}:
                user = auth.resolve(self.db, token, ip)
                if user is None:
                    raise unauthenticated()
            if permission and permission not in user["permissions"]:
                raise forbidden()
            result = handler(user, params, {"token": token, "ip": ip})
            return {"ok": True, "result": result}
        except AppError as exc:
            return {"ok": False, "error": exc.to_dict()}
        except Exception as exc:  # pragma: no cover - حماية من تسرّب الأخطاء
            LOG.exception("فشل تنفيذ %s", method)
            return {"ok": False, "error": {"code": "internal",
                                           "message": f"خطأ داخلي: {type(exc).__name__}"}}

    # ------------------------------------------------------------------
    # عام
    # ------------------------------------------------------------------
    def _ping(self, user, params, ctx):
        return {"app": APP_NAME, "version": APP_VERSION, "time": now_iso()}

    def _bootstrap_status(self, user, params, ctx):
        return auth.bootstrap_status(self.db)

    def _bootstrap_create_admin(self, user, params, ctx):
        created = auth.create_admin(self.db, params.get("username", "admin"),
                                    params.get("password", ""),
                                    params.get("display_name", ""))
        return {"user": created}

    def _login(self, user, params, ctx):
        result = auth.login(self.db, params.get("username", ""),
                            params.get("password", ""), ctx["ip"])
        return result

    def _logout(self, user, params, ctx):
        return auth.logout(self.db, ctx["token"], ctx["ip"])

    def _me(self, user, params, ctx):
        return {"user": user}

    def _change_password(self, user, params, ctx):
        return auth.change_password(self.db, ctx["token"], params.get("old_password", ""),
                                    params.get("new_password", ""))

    def _meta_info(self, user, params, ctx):
        center = units.center_unit(self.db)
        data = {
            "app_name": APP_NAME,
            "version": APP_VERSION,
            "data_dir": str(self.paths.data_dir),
            "db_path": str(self.paths.db_path),
            "center": center["name"] if center else "",
            "schema_version": self.db.get_meta("schema_version", "0"),
            "provisioned_unit": self.db.get_meta("provisioned_unit_name", ""),
            "server_time": now_iso(),
            "roles": [{"code": code, "name": name} for code, name, _d in P.ROLES],
        }
        return data

    # ------------------------------------------------------------------
    # المؤسسات
    # ------------------------------------------------------------------
    def _units_list(self, user, params, ctx):
        if "manage_units" in user["permissions"]:
            return {"units": units.list_units(self.db)}
        if user.get("unit_id"):
            unit = units.get_unit(self.db, user["unit_id"])
            return {"units": [unit] if unit else []}
        return {"units": []}

    def _units_get(self, user, params, ctx):
        unit = units.get_unit(self.db, params.get("unit_id", ""))
        if not unit:
            raise AppError("not_found", "المؤسسة غير موجودة.")
        if "manage_units" not in user["permissions"] and unit["unit_id"] != user.get("unit_id"):
            raise forbidden()
        return {"unit": unit}

    def _units_create(self, user, params, ctx):
        return units.create_unit(self.db, params.get("data") or {},
                                 int(params.get("editor_count", 1)),
                                 bool(params.get("create_manager", True)),
                                 user, ctx["ip"])

    def _units_update(self, user, params, ctx):
        return {"unit": units.update_unit(self.db, params.get("unit_id", ""),
                                          params.get("data") or {}, user, ctx["ip"])}

    def _units_delete(self, user, params, ctx):
        return units.delete_unit(self.db, params.get("unit_id", ""), user, ctx["ip"])

    def _units_reset_users(self, user, params, ctx):
        return units.reset_unit_users(self.db, params.get("unit_id", ""), user, ctx["ip"])

    def _units_provision(self, user, params, ctx):
        dest = params.get("dest_dir") or str(self.paths.exports_dir)
        return provisioning.build_bundle(
            self.db, self.paths, params.get("unit_id", ""),
            admin_password=params.get("admin_password", ""),
            dest_dir=dest,
            include_program=bool(params.get("include_program", False)),
            make_zip=bool(params.get("make_zip", True)),
            credentials=params.get("credentials") or [],
            operator=user, ip=ctx["ip"])

    # ------------------------------------------------------------------
    # المستخدمون
    # ------------------------------------------------------------------
    def _users_list(self, user, params, ctx):
        return {"users": users.list_users(self.db, params.get("unit_id") or None)}

    def _users_create(self, user, params, ctx):
        return users.create_user(self.db, params.get("data") or {}, user, ctx["ip"])

    def _users_update(self, user, params, ctx):
        return {"user": users.update_user(self.db, params.get("user_id", ""),
                                          params.get("data") or {}, user, ctx["ip"])}

    def _users_reset(self, user, params, ctx):
        return users.reset_password(self.db, params.get("user_id", ""), user, ctx["ip"])

    def _users_set_active(self, user, params, ctx):
        return users.set_active(self.db, params.get("user_id", ""),
                                bool(params.get("active")), user, ctx["ip"])

    # ------------------------------------------------------------------
    # النسخ والتدقيق
    # ------------------------------------------------------------------
    def _backup_list(self, user, params, ctx):
        return {"backups": backup.list_backups(self.db)}

    def _backup_run(self, user, params, ctx):
        return backup.run(self.db, self.paths, user, kind="manual", ip=ctx["ip"])

    def _backup_verify(self, user, params, ctx):
        return backup.verify(params.get("path", ""), self.db.key)

    def _audit_list(self, user, params, ctx):
        rows = audit.recent(self.db, int(params.get("limit", 200)))
        if "manage_units" not in user["permissions"]:
            usernames = {row["username"] for row in units.unit_users(self.db, user["unit_id"])} \
                if user.get("unit_id") else {user["username"]}
            rows = [row for row in rows if row["username"] in usernames]
        return {"events": rows}

    # ------------------------------------------------------------------
    # العناوين والموظفون
    # ------------------------------------------------------------------
    def _titles_list(self, user, params, ctx):
        return {"titles": employees.list_titles(self.db, bool(params.get("active_only")))}

    def _titles_create(self, user, params, ctx):
        return {"title": employees.create_title(self.db, params.get("data") or {},
                                                user, ctx["ip"])}

    def _titles_update(self, user, params, ctx):
        return {"title": employees.update_title(self.db, params.get("title_id", ""),
                                                params.get("data") or {}, user, ctx["ip"])}

    def _employees_list(self, user, params, ctx):
        return {"employees": employees.list_employees(
            self.db, user, params.get("search", ""), params.get("unit_id", ""),
            int(params.get("limit", 1000)))}

    def _employees_get(self, user, params, ctx):
        return {"employee": employees.get_employee(self.db, user,
                                                   params.get("employee_id", ""))}

    def _employees_history(self, user, params, ctx):
        return {"history": employees.history(self.db, user, params.get("employee_id", ""))}

    def _employees_create(self, user, params, ctx):
        return {"employee": employees.create_employee(self.db, user,
                                                      params.get("data") or {}, ctx["ip"])}

    def _employees_update(self, user, params, ctx):
        return {"employee": employees.update_employee(
            self.db, user, params.get("employee_id", ""), params.get("data") or {}, ctx["ip"])}

    def _employees_archive(self, user, params, ctx):
        return employees.archive_employee(self.db, user, params.get("employee_id", ""),
                                          params.get("reason", ""), ctx["ip"])

    def _employees_assign(self, user, params, ctx):
        return employees.assign_employees(self.db, user, params.get("employee_ids") or [],
                                          params.get("target_user_id", ""), ctx["ip"])

    def _employees_stats(self, user, params, ctx):
        return employees.stats(self.db, user)

    def _employees_assignment(self, user, params, ctx):
        unit_id = params.get("unit_id") or user.get("unit_id") or ""
        return {"users": employees.assignment_summary(self.db, unit_id)}

    def _employees_assignable(self, user, params, ctx):
        unit_id = params.get("unit_id") or user.get("unit_id") or ""
        rows = self.db.query(
            "SELECT user_id, username, display_name, role, unit_id FROM users "
            "WHERE active=1 AND role IN ('unit_editor','center_editor')"
            + (" AND unit_id=?" if unit_id else "") + " ORDER BY username",
            (unit_id,) if unit_id else ())
        return {"users": rows}

    def _employees_export(self, user, params, ctx):
        path = self.paths.exports_dir / f"الموظفون_{stamp()}.xlsx"
        employees.export_excel(self.db, user, path)
        return {"path": str(path)}

    def _employees_template(self, user, params, ctx):
        path = self.paths.exports_dir / "قالب_استيراد_الموظفين.xlsx"
        employees.template_excel(path)
        return {"path": str(path)}

    def _employees_import(self, user, params, ctx):
        content = self._decode(params.get("content_b64"))
        temp = self.paths.exports_dir / f"import_{uuid.uuid4().hex}.xlsx"
        temp.write_bytes(content)
        try:
            return employees.import_excel(
                self.db, user, temp,
                update_existing=bool(params.get("update_existing", True)),
                assigned_user_id=params.get("assigned_user_id", ""), ip=ctx["ip"])
        finally:
            temp.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # كتب الشكر والأوامر
    # ------------------------------------------------------------------
    def _letters_list(self, user, params, ctx):
        return {"letters": letters.list_letters(self.db, user)}

    def _letters_get(self, user, params, ctx):
        return {"letter": letters.get_letter(self.db, user, params.get("letter_id", ""))}

    def _letters_preview(self, user, params, ctx):
        return letters.preview(self.db, user, params.get("data") or {})

    def _letters_create(self, user, params, ctx):
        return letters.create(self.db, user, params.get("data") or {}, ctx["ip"])

    def _letters_approve(self, user, params, ctx):
        return {"letter": letters.approve(self.db, user, params.get("letter_id", ""), ctx["ip"])}

    def _letters_delete(self, user, params, ctx):
        return letters.delete_letter(self.db, user, params.get("letter_id", ""), ctx["ip"])

    def _orders_list(self, user, params, ctx):
        return {"orders": orders.list_orders(self.db, user)}

    def _orders_get(self, user, params, ctx):
        return {"order": orders.get_order(self.db, user, params.get("order_id", ""))}

    def _orders_create(self, user, params, ctx):
        return {"order": orders.create_order(self.db, user, params.get("data") or {}, ctx["ip"])}

    def _orders_approve(self, user, params, ctx):
        return {"order": orders.approve_order(self.db, user, params.get("order_id", ""),
                                               ctx["ip"])}

    def _orders_delete(self, user, params, ctx):
        return orders.delete_order(self.db, user, params.get("order_id", ""), ctx["ip"])

    # ------------------------------------------------------------------
    # القواعد والاحتساب
    # ------------------------------------------------------------------
    def _rules_packages(self, user, params, ctx):
        return {"packages": rules.list_packages(self.db)}

    def _rules_get(self, user, params, ctx):
        return {"package": rules.get_package(self.db, params.get("package_id", ""))}

    def _rules_create_package(self, user, params, ctx):
        return {"package": rules.create_package(self.db, user, params.get("data") or {},
                                                ctx["ip"])}

    def _rules_update_package(self, user, params, ctx):
        return {"package": rules.update_package(self.db, user, params.get("package_id", ""),
                                                params.get("data") or {}, ctx["ip"])}

    def _rules_save_row(self, user, params, ctx):
        return {"row": rules.save_row(self.db, user, params.get("package_id", ""),
                                      params.get("data") or {}, ctx["ip"])}

    def _rules_delete_row(self, user, params, ctx):
        return rules.delete_row(self.db, user, params.get("rule_id", ""), ctx["ip"])

    def _rules_publish(self, user, params, ctx):
        return {"package": rules.publish_package(self.db, user,
                                                 params.get("package_id", ""), ctx["ip"])}

    def _rules_new_version(self, user, params, ctx):
        return {"package": rules.new_version(self.db, user, params.get("package_id", ""),
                                             ctx["ip"])}

    def _rules_seed_matrix(self, user, params, ctx):
        return {"package": rules.seed_matrix(self.db, user, ctx["ip"])}

    def _calc_employee(self, user, params, ctx):
        return calc.calculate(self.db, user, params.get("employee_id", ""),
                              params.get("as_of", ""), ctx["ip"],
                              tie_policy=params.get("tie_policy", "promotion"))

    def _calc_export_pdf(self, user, params, ctx):
        return calc.export_pdf(self.db, user, params.get("employee_id", ""),
                               params.get("as_of", ""), self.paths,
                               params.get("tie_policy", "promotion"), ctx["ip"])

    def _calc_runs(self, user, params, ctx):
        return {"runs": calc.latest_runs(self.db, params.get("employee_id", ""))}

    # ------------------------------------------------------------------
    # الوثائق
    # ------------------------------------------------------------------
    def _documents_upload(self, user, params, ctx):
        entity_type = str(params.get("entity_type") or "")
        entity_id = str(params.get("entity_id") or "")
        table = {"employee": "employees", "letter": "appreciation_letters",
                 "order": "hr_orders"}.get(entity_type)
        if not table:
            raise validation("نوع الكيان غير معروف.")
        if not self.db.one(f"SELECT 1 FROM {table} WHERE "
                           f"{'employee_id' if table == 'employees' else ('letter_id' if table == 'appreciation_letters' else 'order_id')}=?",
                           (entity_id,)):
            raise validation("الكيان غير موجود.")
        content = self._decode(params.get("content_b64"))
        return documents.save(self.db, self.paths, user, params.get("filename", ""),
                              content, entity_type, entity_id,
                              str(params.get("purpose") or ""), ctx["ip"])

    def _documents_list(self, user, params, ctx):
        return {"documents": documents.list_for(self.db, params.get("entity_type", ""),
                                                params.get("entity_id", ""))}

    def _documents_fetch(self, user, params, ctx):
        return documents.fetch(self.db, self.paths, params.get("document_id", ""))

    def _documents_unlink(self, user, params, ctx):
        return documents.unlink(self.db, user, params.get("link_id", ""), ctx["ip"])

    @staticmethod
    def _decode(content_b64) -> bytes:
        try:
            return base64.b64decode(str(content_b64 or ""), validate=True)
        except Exception:  # noqa: BLE001
            raise validation("محتوى الملف غير صالح.") from None

    # ------------------------------------------------------------------
    # التقارير
    # ------------------------------------------------------------------
    def _reports_types(self, user, params, ctx):
        return {"types": [{"code": code, "name": name}
                          for code, name in reports.REPORT_TYPES.items()]}

    def _reports_run(self, user, params, ctx):
        return reports.run(self.db, user, params.get("report_type", ""),
                           params.get("filters") or {})

    def _reports_export(self, user, params, ctx):
        result = reports.run(self.db, user, params.get("report_type", ""),
                             params.get("filters") or {})
        fmt = params.get("format", "html")
        center = units.center_unit(self.db)
        center_name = center["name"] if center else ""
        if fmt == "xlsx":
            path = self.paths.exports_dir / f"{result['title']}_{stamp()}.xlsx"
            X.write_rows(path, result["title"], result["headers"], result["rows"])
        elif fmt == "pdf":
            path = self.paths.exports_dir / f"{result['title']}_{stamp()}.pdf"
            PDF.export_report(path, result["title"], result["headers"], result["rows"],
                              result["note"], center_name)
        elif fmt == "csv":
            path = self.paths.exports_dir / f"{result['title']}_{stamp()}.csv"
            CSV.export_rows(path, result["headers"], result["rows"])
        else:
            document = H.table_page(result["title"], result["headers"], result["rows"],
                                    subtitle=result["note"], center_name=center_name)
            path = H.save(document, self.paths.exports_dir,
                          f"{result['title']}_{stamp()}.html")
        return {"path": str(path)}

    # ------------------------------------------------------------------
    # المزامنة
    # ------------------------------------------------------------------
    def _sync_export_data(self, user, params, ctx):
        return sync_service.export_data(self.db, self.paths, user,
                                        params.get("unit_id", ""), params.get("period"),
                                        ctx["ip"], params.get("password", ""))

    def _sync_export_rules(self, user, params, ctx):
        return sync_service.export_rules(self.db, self.paths, user, ctx["ip"],
                                         params.get("password", ""))

    def _sync_export_results(self, user, params, ctx):
        return sync_service.export_results(self.db, self.paths, user,
                                           params.get("unit_id", ""), ctx["ip"],
                                           params.get("password", ""))

    def _sync_preview(self, user, params, ctx):
        return sync_service.preview(self.db, params.get("path", ""),
                                    params.get("password", ""))

    def _sync_conflicts(self, user, params, ctx):
        return sync_service.conflicts(self.db, params.get("path", ""),
                                      params.get("password", ""))

    def _sync_import(self, user, params, ctx):
        return sync_service.import_package(self.db, self.paths, user,
                                           params.get("path", ""), ctx["ip"],
                                           params.get("resolutions") or {},
                                           params.get("password", ""))

    def _sync_import_rules(self, user, params, ctx):
        return sync_service.import_package(self.db, self.paths, user,
                                           params.get("path", ""), ctx["ip"], {},
                                           params.get("password", ""))

    def _sync_import_results(self, user, params, ctx):
        return sync_service.import_package(self.db, self.paths, user,
                                           params.get("path", ""), ctx["ip"], {},
                                           params.get("password", ""))

    def _sync_log(self, user, params, ctx):
        return {"packages": sync_service.log(self.db)}

    def _sync_packages(self, user, params, ctx):
        return {"packages": sync_service.packages_list(self.paths)}
