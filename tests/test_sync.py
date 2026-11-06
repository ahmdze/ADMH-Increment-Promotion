"""اختبار دورة المزامنة: تصدير بيانات مؤسسة واستيرادها، وحزم القواعد."""

from __future__ import annotations

import base64
import sqlite3
import zipfile
from pathlib import Path

from amdh_hr.config import Paths
from amdh_hr import crypto
from amdh_hr.server.app import ServiceApp
from tests.conftest import call, fails

ADMIN = "Strong#2026"
MAINT = "Maint#2026"


def _icall(app: ServiceApp, method: str, token: str = "", **params):
    response = app.dispatch(method, params, token)
    assert response["ok"], response
    return response["result"]


def test_sync_roundtrip(service, admin, tmp_path):
    token = admin["token"]
    created = call(service, "units.create", token,
                   data={"name": "مستشفى المزامنة", "code": "H11", "kind": "مستشفى"},
                   editor_count=1, create_manager=True)
    unit = created["unit"]
    manager = created["credentials"][0]
    title = call(service, "titles.create", token,
                 data={"code": "DOC", "name": "طبيب", "grade": "3"})["title"]
    employee_a = call(service, "employees.create", token, data={
        "emp_no": "5001", "full_name": "موظف المركز", "unit_id": unit["unit_id"],
        "job_title_id": title["title_id"], "grade": "3", "stage": "1",
        "hire_date": "2015-01-01", "gender": "male"})["employee"]
    package = call(service, "rules.create_package", token, data={
        "code": "HR-SYNC-1", "effective_from": "2020-01-01"})["package"]
    call(service, "rules.save_row", token, package_id=package["package_id"], data={
        "rule_type": "promotion", "name": "ترفيع", "scope": {"grade": "3"},
        "params": {"required_months": 36}, "priority": 10})
    call(service, "rules.publish", token, package_id=package["package_id"])
    call(service, "letters.create", token, data={
        "issuer": "دائرة", "issuer_type": "director_general", "letter_no": "L-11",
        "letter_date": "2020-01-01", "target_mode": "specific",
        "reference_date": "2020-01-01",
        "target_params": {"employee_ids": [employee_a["employee_id"]]}})
    call(service, "orders.create", token, data={
        "order_type": "promotion", "order_no": "O-11", "order_date": "2020-01-01",
        "effective_date": "2020-02-01", "employee_ids": [employee_a["employee_id"]]})
    call(service, "documents.upload", token, entity_type="employee",
         entity_id=employee_a["employee_id"], filename="scan.png",
         content_b64=base64.b64encode(b"doc-a" * 10).decode())
    bundled = call(service, "units.provision", token, unit_id=unit["unit_id"],
                   admin_password=MAINT, dest_dir=str(tmp_path / "bundles"),
                   include_program=False, make_zip=True)

    institution = ServiceApp(Paths(Path(bundled["folder"]) / "data"))
    try:
        login = _icall(institution, "auth.login", username=manager["username"],
                       password=manager["password"])
        itoken = login["token"]
        employee_b = _icall(institution, "employees.create", itoken, data={
            "emp_no": "5002", "full_name": "موظف المؤسسة", "unit_id": unit["unit_id"],
            "job_title_id": title["title_id"], "grade": "3", "stage": "1",
            "hire_date": "2018-01-01", "gender": "female"})["employee"]
        _icall(institution, "documents.upload", itoken, entity_type="employee",
               entity_id=employee_b["employee_id"], filename="scan-b.png",
               content_b64=base64.b64encode(b"doc-b" * 10).decode())
        exported = _icall(institution, "sync.export_data", itoken)
        assert Path(exported["path"]).exists()
        assert exported["counts"]["employees"] == 2

        preview = call(service, "sync.preview", token, path=exported["path"])
        assert preview["duplicate"] is False
        assert preview["counts"]["new_employees"] == 1
        assert preview["counts"]["conflicts"] == 0

        imported = call(service, "sync.import", token, path=exported["path"])
        assert imported["employees_added"] == 1
        assert imported["documents"] == 1
        rows = call(service, "employees.list", token, search="5002")["employees"]
        assert len(rows) == 1

        again = call(service, "sync.import", token, path=exported["path"])
        assert again["already_imported"] is True
        assert call(service, "employees.list", token)["employees"].__len__() == 2

        # حزمة قواعد جديدة من المركز إلى المؤسسة
        second = call(service, "rules.create_package", token, data={
            "code": "HR-SYNC-2", "effective_from": "2021-01-01"})["package"]
        call(service, "rules.save_row", token, package_id=second["package_id"], data={
            "rule_type": "increment", "name": "علاوة", "scope": {},
            "params": {"required_months": 12}, "priority": 10})
        call(service, "rules.publish", token, package_id=second["package_id"])
        rules_package = call(service, "sync.export_rules", token)
        institution_preview = _icall(institution, "sync.preview", itoken,
                                     path=rules_package["path"])
        assert institution_preview["counts"]["new_packages"] >= 1
        imported_rules = _icall(institution, "sync.import_rules", itoken,
                                path=rules_package["path"])
        assert imported_rules["packages_added"] >= 1
    finally:
        institution.close()


def test_results_package_roundtrip(service, admin, tmp_path):
    token = admin["token"]
    created = call(service, "units.create", token,
                   data={"name": "مستشفى النتائج", "code": "H13", "kind": "مستشفى"},
                   editor_count=1, create_manager=True)
    unit = created["unit"]
    manager = created["credentials"][0]
    title = call(service, "titles.create", token,
                 data={"code": "TECH", "name": "فني", "grade": "2"})["title"]
    employee = call(service, "employees.create", token, data={
        "emp_no": "7001", "full_name": "موظف النتائج", "unit_id": unit["unit_id"],
        "job_title_id": title["title_id"], "grade": "2", "stage": "1",
        "hire_date": "2016-01-01", "gender": "male"})["employee"]
    bundled = call(service, "units.provision", token, unit_id=unit["unit_id"],
                   admin_password=MAINT, dest_dir=str(tmp_path / "bundles"),
                   include_program=False, make_zip=True)
    institution = ServiceApp(Paths(Path(bundled["folder"]) / "data"))
    try:
        login = _icall(institution, "auth.login", username=manager["username"],
                       password=manager["password"])
        itoken = login["token"]
        letter = call(service, "letters.create", token, data={
            "issuer": "دائرة", "issuer_type": "director_general", "letter_no": "L-13",
            "letter_date": "2020-01-01", "target_mode": "specific",
            "reference_date": "2020-01-01",
            "target_params": {"employee_ids": [employee["employee_id"]]}})
        call(service, "letters.approve", token, letter_id=letter["letter_id"])
        order = call(service, "orders.create", token, data={
            "order_type": "increment", "order_no": "O-13", "order_date": "2020-01-01",
            "effective_date": "2020-02-01", "apply_mode": "auto",
            "employee_ids": [employee["employee_id"]]})["order"]
        call(service, "orders.approve", token, order_id=order["order_id"])
        center_employee = call(service, "employees.get", token,
                               employee_id=employee["employee_id"])["employee"]
        assert (center_employee["grade"], center_employee["stage"]) == ("2", "2")
        exported = call(service, "sync.export_results", token, unit_id=unit["unit_id"])
        preview = _icall(institution, "sync.preview", itoken, path=exported["path"])
        assert preview["manifest"]["direction"] == "center_results"
        assert preview["counts"]["letters"] == 1
        result = _icall(institution, "sync.import_results", itoken, path=exported["path"])
        assert result["letters"] == 1 and result["orders"] == 1
        imported = _icall(institution, "letters.get", itoken, letter_id=letter["letter_id"])
        assert imported["letter"]["status"] == "approved"
        imported_order = _icall(institution, "orders.get", itoken, order_id=order["order_id"])
        assert imported_order["order"]["status"] == "approved"
        institution_employee = _icall(institution, "employees.get", itoken,
                                      employee_id=employee["employee_id"])["employee"]
        assert (institution_employee["grade"], institution_employee["stage"]) == ("2", "2")
        again = _icall(institution, "sync.import_results", itoken, path=exported["path"])
        assert again["already_imported"] is True
    finally:
        institution.close()


def test_sync_conflict_resolution(service, admin, tmp_path):
    token = admin["token"]
    for index, choice in enumerate(("source", "target")):
        code = f"H2{index}"
        emp_no = f"88{index}0"
        created = call(service, "units.create", token,
                       data={"name": f"مؤسسة تعارض {index}", "code": code, "kind": "مستشفى"},
                       editor_count=1, create_manager=True)
        unit = created["unit"]
        manager = created["credentials"][0]
        title = call(service, "titles.create", token,
                     data={"code": "C" + code, "name": "عنوان " + code})["title"]
        bundled = call(service, "units.provision", token, unit_id=unit["unit_id"],
                       admin_password=MAINT, dest_dir=str(tmp_path / f"b{index}"),
                       include_program=False, make_zip=True)
        institution = ServiceApp(Paths(Path(bundled["folder"]) / "data"))
        try:
            login = _icall(institution, "auth.login", username=manager["username"],
                           password=manager["password"])
            itoken = login["token"]
            center_employee = call(service, "employees.create", token, data={
                "emp_no": emp_no, "full_name": "اسم المركز", "unit_id": unit["unit_id"],
                "job_title_id": title["title_id"], "grade": "3", "stage": "1",
                "hire_date": "2015-01-01", "gender": "male"})["employee"]
            _icall(institution, "employees.create", itoken, data={
                "emp_no": emp_no, "full_name": "اسم المؤسسة", "unit_id": unit["unit_id"],
                "job_title_id": title["title_id"], "grade": "4", "stage": "2",
                "hire_date": "2015-01-01", "gender": "male"})
            exported = _icall(institution, "sync.export_data", itoken)
            preview = call(service, "sync.preview", token, path=exported["path"])
            assert preview["counts"]["conflicts"] == 1
            found = call(service, "sync.conflicts", token, path=exported["path"])["conflicts"]
            assert len(found) == 1
            result = call(service, "sync.import", token, path=exported["path"],
                          resolutions={found[0]["source_id"]: choice})
            assert result["conflicts_resolved"] == 1
            employee = call(service, "employees.get", token,
                            employee_id=center_employee["employee_id"])["employee"]
            expected = "اسم المؤسسة" if choice == "source" else "اسم المركز"
            assert employee["full_name"] == expected
            rows = call(service, "employees.list", token, search=emp_no)["employees"]
            assert len(rows) == 1
        finally:
            institution.close()


def test_encrypted_package_requires_password(service, admin):
    token = admin["token"]
    package = call(service, "rules.create_package", token, data={
        "code": "ENC-1", "effective_from": "2020-01-01"})["package"]
    call(service, "rules.save_row", token, package_id=package["package_id"], data={
        "rule_type": "increment", "name": "علاوة", "scope": {},
        "params": {"required_months": 12}, "priority": 10})
    call(service, "rules.publish", token, package_id=package["package_id"])
    password = "Pack#2026"
    exported = call(service, "sync.export_rules", token, password=password)
    path = Path(exported["path"])
    assert crypto.is_encrypted_package(path)
    assert not zipfile.is_zipfile(path)
    wrong = fails(service, "sync.preview", token, path=str(path), password="Wrong#2026")
    assert wrong["code"] == "validation"
    preview = call(service, "sync.preview", token, path=str(path), password=password)
    assert preview["manifest"]["direction"] == "center_rules"


def test_report_generation(service, admin, tmp_path):
    token = admin["token"]
    call(service, "units.create", token,
         data={"name": "مستشفى التقارير", "code": "H12", "kind": "مستشفى"},
         editor_count=1, create_manager=True)
    unit = call(service, "units.list", token)["units"][0]
    title = call(service, "titles.create", token,
                 data={"code": "NUR", "name": "ممرض", "grade": "2"})["title"]
    call(service, "employees.create", token, data={
        "emp_no": "6001", "full_name": "موظف تقرير", "unit_id": unit["unit_id"],
        "job_title_id": title["title_id"], "grade": "2", "stage": "1",
        "hire_date": "2015-01-01", "gender": "male"})
    employee = call(service, "employees.list", token, search="6001")["employees"][0]
    result = call(service, "reports.run", token, report_type="employees", filters={})
    assert result["rows"]
    export = call(service, "reports.export", token, report_type="employees", filters={},
                  format="xlsx")
    assert Path(export["path"]).exists()
    html = call(service, "reports.export", token, report_type="employees", filters={},
                format="html")
    assert Path(html["path"]).exists()
    pdf = call(service, "reports.export", token, report_type="employees", filters={},
               format="pdf")
    assert Path(pdf["path"]).exists()
    assert Path(pdf["path"]).read_bytes()[:4] == b"%PDF"
    csv_path = call(service, "reports.export", token, report_type="employees", filters={},
                    format="csv")["path"]
    assert Path(csv_path).read_bytes()[:3] == b"\xef\xbb\xbf"
    calc_pdf = call(service, "calc.export_pdf", token,
                    employee_id=employee["employee_id"], as_of="2024-01-01")
    assert Path(calc_pdf["path"]).read_bytes()[:4] == b"%PDF"
    for kind in ("employee_history", "letter_recipients", "letters_documents",
                 "orders_documents", "rule_changes", "rule_diff", "rule_usage", "sync",
                 "backups"):
        result = call(service, "reports.run", token, report_type=kind, filters={})
        assert result["title"]
