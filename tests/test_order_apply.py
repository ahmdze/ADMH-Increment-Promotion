"""اختبار تطبيق نتيجة الأمر على الدرجة والمرحلة عند الاعتماد."""

from __future__ import annotations

from tests.conftest import call, fails


def _setup(service, token, code="OA1"):
    created = call(service, "units.create", token,
                   data={"name": f"مستشفى {code}", "code": code, "kind": "مستشفى"},
                   editor_count=1, create_manager=True)
    unit_id = created["unit"]["unit_id"]
    title = call(service, "titles.create", token,
                 data={"code": "T-" + code, "name": "عنوان " + code})["title"]
    return unit_id, title["title_id"]


def _employee(service, token, unit_id, title_id, emp_no, grade="3", stage="1"):
    return call(service, "employees.create", token, data={
        "emp_no": emp_no, "full_name": "موظف " + emp_no, "unit_id": unit_id,
        "job_title_id": title_id, "grade": grade, "stage": stage,
        "hire_date": "2015-01-01", "gender": "male"})["employee"]


def test_promotion_and_increment_apply_automatically(service, admin):
    token = admin["token"]
    unit_id, title_id = _setup(service, token)
    employee = _employee(service, token, unit_id, title_id, "9001")

    order = call(service, "orders.create", token, data={
        "order_type": "promotion", "order_no": "OA-1", "order_date": "2020-01-01",
        "effective_date": "2020-02-01", "apply_mode": "auto",
        "employee_ids": [employee["employee_id"]]})["order"]
    approved = call(service, "orders.approve", token, order_id=order["order_id"])["order"]
    assert approved["applied_at"]
    updated = call(service, "employees.get", token,
                   employee_id=employee["employee_id"])["employee"]
    assert (updated["grade"], updated["stage"]) == ("4", "1")
    history = call(service, "employees.history", token,
                   employee_id=employee["employee_id"])["history"]
    assert any(row["event_type"] == "promotion" for row in history)

    increment = call(service, "orders.create", token, data={
        "order_type": "increment", "order_no": "OA-2", "order_date": "2021-01-01",
        "effective_date": "2021-02-01", "apply_mode": "auto",
        "employee_ids": [employee["employee_id"]]})["order"]
    call(service, "orders.approve", token, order_id=increment["order_id"])
    updated = call(service, "employees.get", token,
                   employee_id=employee["employee_id"])["employee"]
    assert (updated["grade"], updated["stage"]) == ("4", "2")

    # إعادة الاعتماد لا تطبق مرة ثانية
    call(service, "orders.approve", token, order_id=increment["order_id"])
    again = call(service, "employees.get", token,
                 employee_id=employee["employee_id"])["employee"]
    assert again["stage"] == "2"


def test_fixed_target_and_invalid_auto(service, admin):
    token = admin["token"]
    unit_id, title_id = _setup(service, token, code="OA2")
    first = _employee(service, token, unit_id, title_id, "9101", grade="2", stage="1")
    second = _employee(service, token, unit_id, title_id, "9102", grade="3", stage="2")

    fixed = call(service, "orders.create", token, data={
        "order_type": "promotion", "order_no": "OA-3", "order_date": "2020-01-01",
        "effective_date": "2020-02-01", "apply_mode": "fixed",
        "to_grade": "5", "to_stage": "2",
        "employee_ids": [first["employee_id"], second["employee_id"]]})["order"]
    call(service, "orders.approve", token, order_id=fixed["order_id"])
    for employee in (first, second):
        updated = call(service, "employees.get", token,
                       employee_id=employee["employee_id"])["employee"]
        assert (updated["grade"], updated["stage"]) == ("5", "2")

    invalid = _employee(service, token, unit_id, title_id, "9103", grade="أولى", stage="1")
    order = call(service, "orders.create", token, data={
        "order_type": "promotion", "order_no": "OA-4", "order_date": "2020-01-01",
        "effective_date": "2020-02-01", "apply_mode": "auto",
        "employee_ids": [invalid["employee_id"]]})["order"]
    error = fails(service, "orders.approve", token, order_id=order["order_id"])
    assert error["code"] == "validation"
    unchanged = call(service, "employees.get", token,
                     employee_id=invalid["employee_id"])["employee"]
    assert unchanged["grade"] == "أولى"
    current = call(service, "orders.get", token, order_id=order["order_id"])["order"]
    assert current["status"] == "draft"
