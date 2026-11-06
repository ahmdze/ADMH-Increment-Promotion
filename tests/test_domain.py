"""اختبارات المجال: الموظفون، القواعد، الاحتساب، كتب الشكر، الأوامر، الوثائق، Excel."""

from __future__ import annotations

import base64
import sqlite3
from pathlib import Path

from amdh_hr.exporters import excel as X
from tests.conftest import ADMIN_PASSWORD, call, fails

HIRE = "2015-01-01"


def _setup_unit(service, token, code="H1", editors=2):
    return call(service, "units.create", token,
                data={"name": f"مستشفى {code}", "code": code, "kind": "مستشفى"},
                editor_count=editors, create_manager=True)


def _users(service, token):
    return call(service, "users.list", token)["users"]


def _title(service, token):
    return call(service, "titles.create", token,
                data={"code": "DOC", "name": "طبيب", "grade": "3"})["title"]


def _employee(service, token, unit_id, title_id, assigned="", emp_no="1001"):
    return call(service, "employees.create", token, data={
        "emp_no": emp_no, "full_name": "أحمد علي", "unit_id": unit_id,
        "job_title_id": title_id, "grade": "3", "stage": "1", "category": "طبية",
        "hire_date": HIRE, "gender": "male", "status": "active",
        "assigned_user_id": assigned,
    })["employee"]


def _login(service, username, password):
    return call(service, "auth.login", username=username, password=password)


def _rules(service, token):
    package = call(service, "rules.create_package", token,
                   data={"code": "HR-2020", "effective_from": "2020-01-01",
                         "note": "حزمة اختبار"})["package"]
    call(service, "rules.save_row", token, package_id=package["package_id"], data={
        "rule_type": "promotion", "name": "ترفيع بعد 36 شهراً",
        "scope": {"grade": "3", "stage": "1"},
        "params": {"required_months": 36, "to_grade": "4", "to_stage": "1"},
        "priority": 10})
    call(service, "rules.save_row", token, package_id=package["package_id"], data={
        "rule_type": "increment", "name": "علاوة سنوية",
        "scope": {}, "params": {"required_months": 12}, "priority": 10})
    call(service, "rules.save_row", token, package_id=package["package_id"], data={
        "rule_type": "letter_effect", "name": "كتاب دائرة 30 يوماً",
        "scope": {"issuer_type": "director_general"},
        "params": {"days": 30, "cap_days": 60}, "priority": 10})
    return call(service, "rules.publish", token,
                package_id=package["package_id"])["package"]


def test_employee_scope_and_update_conflict(service, admin):
    token = admin["token"]
    created = _setup_unit(service, token, code="H2", editors=1)
    unit_id = created["unit"]["unit_id"]
    title = _title(service, token)
    editor = next(u for u in _users(service, token)
                  if u["unit_id"] == unit_id and u["role"] == "unit_editor")
    manager = next(u for u in _users(service, token)
                   if u["unit_id"] == unit_id and u["role"] == "unit_manager")
    employee = _employee(service, token, unit_id, title["title_id"],
                         assigned=editor["user_id"])

    editor_login = call(service, "auth.login", username=editor["username"],
                        password=created["credentials"][1]["password"])
    visible = call(service, "employees.list", editor_login["token"])["employees"]
    assert [row["employee_id"] for row in visible] == [employee["employee_id"]]

    updated = call(service, "employees.update", admin["token"],
                   employee_id=employee["employee_id"],
                   data={**employee, "grade": "4", "version": employee["version"]})
    assert updated["employee"]["grade"] == "4"
    error = fails(service, "employees.update", admin["token"],
                  employee_id=employee["employee_id"],
                  data={**updated["employee"], "grade": "5",
                        "version": employee["version"]})
    assert error["code"] == "conflict"
    assert manager["role"] == "unit_manager"


def test_rules_and_calculation(service, admin):
    token = admin["token"]
    created = _setup_unit(service, token, code="H3", editors=1)
    unit_id = created["unit"]["unit_id"]
    title = _title(service, token)
    employee = _employee(service, token, unit_id, title["title_id"])
    _rules(service, token)

    result = call(service, "calc.employee", token,
                  employee_id=employee["employee_id"], as_of="2020-01-01")
    assert result["package"]["code"] == "HR-2020"
    assert result["service"]["years"] == 5
    assert result["promotion"]["state"] == "computed"
    assert result["promotion"]["eligible"] is True
    assert result["increment"]["state"] == "computed"
    assert result["state"] == "estimated"


def test_letter_targeting_and_effect(service, admin):
    token = admin["token"]
    created = _setup_unit(service, token, code="H4", editors=1)
    unit_id = created["unit"]["unit_id"]
    title = _title(service, token)
    male = _employee(service, token, unit_id, title["title_id"], emp_no="2001")
    female = call(service, "employees.create", token, data={
        "emp_no": "2002", "full_name": "سارة محمد", "unit_id": unit_id,
        "job_title_id": title["title_id"], "grade": "3", "stage": "1",
        "hire_date": HIRE, "gender": "female"})["employee"]
    manager = next(u for u in _users(service, token)
                   if u["unit_id"] == unit_id and u["role"] == "unit_manager")
    manager_login = call(service, "auth.login", username=manager["username"],
                         password=created["credentials"][0]["password"])
    manager_token = manager_login["token"]
    _rules(service, token)

    preview = call(service, "letters.preview", manager_token, data={
        "target_mode": "females", "letter_date": "2020-01-01",
        "reference_date": "2020-01-01"})
    assert preview["count"] == 1
    assert preview["employees"][0]["employee_id"] == female["employee_id"]

    specific = call(service, "letters.preview", manager_token, data={
        "target_mode": "specific", "letter_date": "2020-01-01",
        "reference_date": "2020-01-01",
        "target_params": {"employee_ids": [male["employee_id"], female["employee_id"]]}})
    assert specific["count"] == 2

    letter = call(service, "letters.create", manager_token, data={
        "issuer": "دائرة الصحة", "issuer_type": "director_general", "letter_no": "L-1",
        "letter_date": "2020-01-01", "subject": "شكر",
        "target_mode": "specific", "reference_date": "2020-01-01",
        "target_params": {"employee_ids": [male["employee_id"]]}})
    assert letter["count"] == 1
    approved = call(service, "letters.approve", manager_token,
                    letter_id=letter["letter_id"])["letter"]
    assert approved["status"] == "approved"
    assert approved["recipients"][0]["effect_days"] == 30

    result = call(service, "calc.employee", manager_token,
                  employee_id=male["employee_id"], as_of="2020-06-01")
    assert int(result["letters"]["days"]) == 30


def test_orders(service, admin):
    token = admin["token"]
    created = _setup_unit(service, token, code="H5", editors=1)
    unit_id = created["unit"]["unit_id"]
    title = _title(service, token)
    employee = _employee(service, token, unit_id, title["title_id"])
    order = call(service, "orders.create", token, data={
        "order_type": "promotion", "order_no": "O-1", "order_date": "2020-01-01",
        "effective_date": "2020-02-01", "employee_ids": [employee["employee_id"]]})["order"]
    assert len(order["recipients"]) == 1
    approved = call(service, "orders.approve", token, order_id=order["order_id"])["order"]
    assert approved["status"] == "approved"


def test_documents(service, admin):
    token = admin["token"]
    created = _setup_unit(service, token, code="H6", editors=1)
    unit_id = created["unit"]["unit_id"]
    title = _title(service, token)
    employee = _employee(service, token, unit_id, title["title_id"])
    content = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    document = call(service, "documents.upload", token,
                    entity_type="employee", entity_id=employee["employee_id"],
                    filename="scan.png",
                    content_b64=base64.b64encode(content).decode())
    assert len(document["sha256"]) == 64
    again = call(service, "documents.upload", token,
                 entity_type="employee", entity_id=employee["employee_id"],
                 filename="scan-copy.png",
                 content_b64=base64.b64encode(content).decode())
    assert again["document_id"] == document["document_id"]
    listed = call(service, "documents.list", token, entity_type="employee",
                  entity_id=employee["employee_id"])["documents"]
    assert len(listed) == 1


def test_excel_import_export(service, admin, tmp_path):
    token = admin["token"]
    created = _setup_unit(service, token, code="H7", editors=1)
    unit_id = created["unit"]["unit_id"]
    title = _title(service, token)
    _employee(service, token, unit_id, title["title_id"], emp_no="3001")
    exported = call(service, "employees.export", token)["path"]
    assert exported.endswith(".xlsx")

    headers = [label for _key, label, _syn in X.EMPLOYEE_COLUMNS]
    path = tmp_path / "import.xlsx"
    X.write_rows(path, "الموظفون", headers, [[
        "3002", "موظف جديد", "طبيب", "2", "1", "", HIRE, HIRE, HIRE, "", "أنثى",
        "على الملاك", "مستشفى H7", "", "",
    ]])
    content = path.read_bytes()
    result = call(service, "employees.import", token,
                  content_b64=base64.b64encode(content).decode(), update_existing=True)
    assert result["added"] == 1
    rows = call(service, "employees.list", token, search="موظف جديد")["employees"]
    assert len(rows) == 1
    assert rows[0]["gender"] == "female"


def test_provision_filters_institution_data(service, admin, tmp_path):
    token = admin["token"]
    first = _setup_unit(service, token, code="H8", editors=1)
    second = _setup_unit(service, token, code="H9", editors=1)
    title = _title(service, token)
    employee_a = _employee(service, token, first["unit"]["unit_id"],
                           title["title_id"], emp_no="4001")
    _employee(service, token, second["unit"]["unit_id"], title["title_id"], emp_no="4002")
    _rules(service, token)
    call(service, "letters.create", token, data={
        "issuer": "دائرة", "issuer_type": "director_general", "letter_no": "L-8",
        "letter_date": "2020-01-01", "target_mode": "specific",
        "reference_date": "2020-01-01",
        "target_params": {"employee_ids": [employee_a["employee_id"]]}})
    call(service, "orders.create", token, data={
        "order_type": "promotion", "order_no": "O-8", "order_date": "2020-01-01",
        "effective_date": "2020-02-01",
        "employee_ids": [employee_a["employee_id"]]})
    call(service, "documents.upload", token, entity_type="employee",
         entity_id=employee_a["employee_id"], filename="scan.png",
         content_b64=base64.b64encode(b"pngdata" * 10).decode())

    bundled = call(service, "units.provision", token,
                   unit_id=first["unit"]["unit_id"], admin_password="Maint#2026",
                   dest_dir=str(tmp_path / "exports"), include_program=False, make_zip=True)
    folder = Path(bundled["folder"])
    connection = sqlite3.connect(str(folder / "data" / "amdh_hr.db"))
    try:
        assert connection.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == 1
        assert connection.execute("SELECT emp_no FROM employees").fetchone()[0] == "4001"
        assert connection.execute("SELECT COUNT(*) FROM appreciation_letters").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM hr_orders").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM rule_packages").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM rule_rows").fetchone()[0] >= 1
    finally:
        connection.close()
    files = list((folder / "data" / "attachments").iterdir())
    assert len(files) == 1
