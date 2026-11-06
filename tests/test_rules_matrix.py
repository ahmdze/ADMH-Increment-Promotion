"""حالات يدوية لمصفوفة القِدَم: السقف، الترحيل، الأقرب، وتاريخ الأثر."""

from __future__ import annotations

from tests.conftest import call


def _setup(service, admin, code="MX1", hire="2010-01-01", grade_date="2015-01-01",
           stage_date="2020-01-01"):
    token = admin["token"]
    created = call(service, "units.create", token,
                   data={"name": f"مؤسسة {code}", "code": code, "kind": "مستشفى"},
                   editor_count=1, create_manager=True)
    unit_id = created["unit"]["unit_id"]
    title = call(service, "titles.create", token,
                 data={"code": "T" + code, "name": "عنوان " + code})["title"]
    employee = call(service, "employees.create", token, data={
        "emp_no": "8" + code, "full_name": "موظف " + code, "unit_id": unit_id,
        "job_title_id": title["title_id"], "grade": "3", "stage": "1",
        "hire_date": hire, "last_grade_date": grade_date,
        "last_stage_date": stage_date, "gender": "male"})["employee"]
    package = call(service, "rules.seed_matrix", token)["package"]
    assert package["code"] == "LAW-MATRIX"
    return unit_id, employee


def _letter(service, admin, unit_id, employee, issuer, date, number):
    token = admin["token"]
    letter = call(service, "letters.create", token, data={
        "issuer": "جهة", "issuer_type": issuer, "letter_no": number,
        "letter_date": date, "target_mode": "specific", "reference_date": date,
        "target_params": {"employee_ids": [employee["employee_id"]]}, "unit_id": unit_id})
    call(service, "letters.approve", token, letter_id=letter["letter_id"])
    return letter


def _calc(service, admin, employee, as_of):
    return call(service, "calc.employee", admin["token"],
                employee_id=employee["employee_id"], as_of=as_of)


def test_matrix_defaults(service, admin):
    _unit, employee = _setup(service, admin)
    result = _calc(service, admin, employee, "2024-01-01")
    assert result["promotion"]["required_months"] == 48
    assert result["increment"]["required_months"] == 12
    assert result["promotion"]["eligible_date"] == "2019-01-01"
    assert result["increment"]["eligible_date"] == "2021-01-01"
    assert result["letters"]["months"] == 0


def test_prime_minister_six_months(service, admin):
    unit, employee = _setup(service, admin)
    _letter(service, admin, unit, employee, "prime_minister", "2020-01-01", "PM-1")
    result = _calc(service, admin, employee, "2024-06-01")
    assert result["letters"]["months"] == 6
    assert result["increment"]["eligible_date"] == "2020-07-01"
    assert result["increment"]["eligible"] is True


def test_two_prime_minister_letters_full_year(service, admin):
    unit, employee = _setup(service, admin)
    _letter(service, admin, unit, employee, "prime_minister", "2020-01-01", "PM-2")
    _letter(service, admin, unit, employee, "prime_minister", "2020-02-01", "PM-3")
    result = _calc(service, admin, employee, "2020-08-01")
    assert result["letters"]["months"] == 12
    assert result["increment"]["eligible"] is True
    assert result["increment"]["eligible_date"] <= "2020-08-01"


def test_minister_cap_three_months_calendar_year(service, admin):
    unit, employee = _setup(service, admin, grade_date="2022-01-01",
                            stage_date="2023-01-01")
    for month in ("01", "02", "03", "04"):
        _letter(service, admin, unit, employee, "minister",
                f"2020-{month}-01", f"MIN-{month}")
    result = _calc(service, admin, employee, "2023-06-01")
    assert result["letters"]["months"] == 3
    assert any("تجاوز سقف" in item for item in result["warnings"])
    assert result["increment"]["eligible_date"] == "2023-10-01"


def test_minister_cap_resets_across_years(service, admin):
    unit, employee = _setup(service, admin, stage_date="2023-01-01")
    for year in ("2020", "2021"):
        for month in ("01", "02", "03"):
            _letter(service, admin, unit, employee, "minister",
                    f"{year}-{month}-01", f"MIN-{year}-{month}")
    result = _calc(service, admin, employee, "2023-06-01")
    assert result["letters"]["months"] == 6
    assert not any("تجاوز سقف" in item for item in result["warnings"])


def test_governor_and_minister_share_cap(service, admin):
    unit, employee = _setup(service, admin, stage_date="2023-01-01")
    _letter(service, admin, unit, employee, "governor", "2020-01-01", "GOV-1")
    _letter(service, admin, unit, employee, "governor", "2020-02-01", "GOV-2")
    _letter(service, admin, unit, employee, "minister", "2020-03-01", "MIN-1")
    _letter(service, admin, unit, employee, "minister", "2020-04-01", "MIN-2")
    result = _calc(service, admin, employee, "2023-06-01")
    assert result["letters"]["months"] == 3
    assert any("تجاوز سقف" in item for item in result["warnings"])


def test_prime_minister_letters_are_not_capped(service, admin):
    unit, employee = _setup(service, admin, stage_date="2023-01-01")
    for month in ("01", "02", "03"):
        _letter(service, admin, unit, employee, "prime_minister",
                f"2020-{month}-01", f"PM-{month}")
    result = _calc(service, admin, employee, "2023-06-01")
    assert result["letters"]["months"] == 18
    assert not any("تجاوز سقف" in item for item in result["warnings"])


def test_unknown_issuer_has_no_effect(service, admin):
    unit, employee = _setup(service, admin)
    _letter(service, admin, unit, employee, "other", "2020-01-01", "OTH-1")
    result = _calc(service, admin, employee, "2024-01-01")
    assert result["letters"]["months"] == 0
    assert any("بلا قاعدة أثر" in item for item in result["warnings"])


def test_effect_never_precedes_letter_date(service, admin):
    unit, employee = _setup(service, admin)
    _letter(service, admin, unit, employee, "prime_minister", "2020-12-01", "PM-FLOOR")
    result = _calc(service, admin, employee, "2021-08-01")
    assert result["increment"]["eligible_date"] >= "2020-12-01"


def test_letter_after_due_rolls_to_next_cycle(service, admin):
    unit, employee = _setup(service, admin, grade_date="2015-01-01",
                            stage_date="2020-01-01")
    _letter(service, admin, unit, employee, "prime_minister", "2025-01-01", "PM-LATE")
    result = _calc(service, admin, employee, "2026-01-01")
    assert result["increment"]["next_date"] >= "2025-01-01"
    assert any(item["state"] == "rollover" for item in result["letters"]["allocations"])


def test_nearest_entitlement_gets_credit_first(service, admin):
    unit, employee = _setup(service, admin, grade_date="2015-01-01",
                            stage_date="2023-01-01")
    _letter(service, admin, unit, employee, "prime_minister", "2018-06-01", "PM-NEAR")
    result = _calc(service, admin, employee, "2019-01-01")
    assert result["promotion"]["eligible_date"] < "2019-01-01"
    assert result["increment"]["eligible_date"] == "2024-01-01"


def test_equal_due_dates_flag_tie(service, admin):
    _unit, employee = _setup(service, admin, hire="2008-01-01",
                             grade_date="2015-01-01", stage_date="2018-01-01")
    result = _calc(service, admin, employee, "2020-01-01")
    assert result["promotion"]["eligible_date"] == result["increment"]["eligible_date"]
    assert result["promotion"]["tie"] is True
    assert any("متساويان" in item for item in result["warnings"])


def test_tie_policy_can_give_credit_to_increment(service, admin):
    unit, employee = _setup(service, admin, hire="2008-01-01",
                            grade_date="2015-01-01", stage_date="2018-01-01")
    _letter(service, admin, unit, employee, "prime_minister", "2018-06-01", "PM-TIE")
    result = call(service, "calc.employee", admin["token"],
                  employee_id=employee["employee_id"], as_of="2020-01-01",
                  tie_policy="increment")
    assert result["increment"]["credit_months"] == 6
    assert result["promotion"]["credit_months"] == 0


def test_rule_diff_between_packages(service, admin):
    token = admin["token"]
    first = call(service, "rules.seed_matrix", token)["package"]
    second = call(service, "rules.create_package", token, data={
        "code": "LAW-MATRIX-2", "effective_from": "2026-01-01"})["package"]
    call(service, "rules.save_row", token, package_id=second["package_id"], data={
        "rule_type": "promotion", "name": "ترفيع 60 شهراً", "scope": {},
        "params": {"required_months": 60}, "priority": 10})
    call(service, "rules.publish", token, package_id=second["package_id"])
    result = call(service, "reports.run", token, report_type="rule_diff", filters={
        "old_package": first["package_id"], "new_package": second["package_id"]})
    assert result["rows"]
    assert any(row[3] in {"مضافة", "معدّلة", "محذوفة"} for row in result["rows"])
