"""لقطات شاشة آلية (بلا عرض) للتحقق البصري."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("AMDH_HR_SETTINGS", "HR_SMOKE")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QDate, Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from amdh_hr.config import Paths  # noqa: E402
from amdh_hr.exporters import html as H  # noqa: E402
from amdh_hr.exporters import pdf as PDF  # noqa: E402
from amdh_hr.server.app import ServiceApp  # noqa: E402
from amdh_hr.server.client import ApiClient  # noqa: E402
from amdh_hr.server.http_api import ApiServer  # noqa: E402
from amdh_hr.ui import theme  # noqa: E402
from amdh_hr.ui.app_settings import AppSettings  # noqa: E402
from amdh_hr.ui.dialogs_credentials import CredentialsDialog  # noqa: E402
from amdh_hr.ui.dialogs_login import LoginDialog  # noqa: E402
from amdh_hr.ui.dialogs_units import ProvisionDialog, UnitDialog  # noqa: E402
from amdh_hr.ui.pdf_viewer import PdfViewerDialog  # noqa: E402
from amdh_hr.ui.main_window import MainWindow  # noqa: E402

SHOTS = ROOT / "screenshots"
PASSWORD = "Strong#2026"


def _payload(service, method, token, **params):
    response = service.dispatch(method, params, token)
    assert response["ok"], response
    return response["result"]


def main() -> int:
    SHOTS.mkdir(exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix="amdh_shots_"))
    service = ServiceApp(Paths(temp / "data"))
    _payload(service, "bootstrap.create_admin", "",
             username="admin", password=PASSWORD, display_name="مدير المركز")
    token = _payload(service, "auth.login", "", username="admin", password=PASSWORD)["token"]

    _payload(service, "units.create", token,
             data={"name": "مركز الدائرة", "code": "CTR", "kind": "مركز الدائرة",
                   "is_center": True, "manager": "د. سعد الجابري",
                   "phone": "07701234567"}, editor_count=2, create_manager=False)
    hosp = _payload(service, "units.create", token,
                    data={"name": "مستشفى الكرامة", "code": "H1", "kind": "مستشفى",
                          "manager": "د. علي حسين", "phone": "07711223344",
                          "address": "مركز المدينة"}, editor_count=3, create_manager=True)
    _payload(service, "units.create", token,
             data={"name": "مركز صحي النور", "code": "PH2", "kind": "مركز صحي",
                   "manager": "د. سارة كريم"}, editor_count=1, create_manager=True)
    _payload(service, "backup.run", token)

    title = _payload(service, "titles.create", token,
                     data={"code": "DOC", "name": "طبيب", "grade": "3"})["title"]
    unit_id = hosp["unit"]["unit_id"]
    emp1 = _payload(service, "employees.create", token, data={
        "emp_no": "1001", "full_name": "أحمد علي حسين", "unit_id": unit_id,
        "job_title_id": title["title_id"], "grade": "3", "stage": "1", "category": "طبية",
        "hire_date": "2015-01-01", "gender": "male", "status": "active"})["employee"]
    emp2 = _payload(service, "employees.create", token, data={
        "emp_no": "1002", "full_name": "سارة محمد كريم", "unit_id": unit_id,
        "job_title_id": title["title_id"], "grade": "3", "stage": "1", "category": "طبية",
        "hire_date": "2018-06-01", "gender": "female", "status": "active"})["employee"]
    package = _payload(service, "rules.create_package", token, data={
        "code": "HR-2026-001", "effective_from": "2020-01-01",
        "note": "حزمة تجريبية للعرض", "legal_source": "نموذج — غير معتمد"})["package"]
    for row in (
        {"rule_type": "promotion", "name": "ترفيع بعد 36 شهراً",
         "scope": {"grade": "3", "stage": "1"},
         "params": {"required_months": 36, "to_grade": "4", "to_stage": "1"}, "priority": 10},
        {"rule_type": "increment", "name": "علاوة سنوية", "scope": {},
         "params": {"required_months": 12}, "priority": 10},
        {"rule_type": "letter_effect", "name": "كتاب دائرة 30 يوماً",
         "scope": {"issuer_type": "directorate"},
         "params": {"days": 30, "cap_days": 60}, "priority": 10},
    ):
        _payload(service, "rules.save_row", token, package_id=package["package_id"], data=row)
    _payload(service, "rules.publish", token, package_id=package["package_id"])
    letter = _payload(service, "letters.create", token, data={
        "issuer": "دائرة صحة المحافظة", "issuer_type": "directorate", "letter_no": "L-2020-15",
        "letter_date": "2020-01-01", "subject": "شكر وتقدير",
        "target_mode": "specific", "reference_date": "2020-01-01",
        "target_params": {"employee_ids": [emp1["employee_id"], emp2["employee_id"]]}})
    _payload(service, "letters.approve", token, letter_id=letter["letter_id"])
    order = _payload(service, "orders.create", token, data={
        "order_type": "promotion", "order_no": "O-2020-3", "order_date": "2020-02-01",
        "effective_date": "2020-03-01", "issuer": "دائرة الصحة",
        "employee_ids": [emp1["employee_id"]]})["order"]
    _payload(service, "orders.approve", token, order_id=order["order_id"])

    server = ApiServer(service, "127.0.0.1", 0).start(background=True)
    client = ApiClient(server.url)
    login = client.login("admin", PASSWORD)
    meta = client.call("meta.info")
    user = login["user"]

    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    settings = AppSettings()
    settings.theme = "dark"
    app.setStyleSheet(theme.stylesheet("dark"))

    def shot(widget, name: str, width: int = 1280, height: int = 820) -> None:
        widget.resize(width, height)
        widget.show()
        QTest.qWait(120)
        widget.grab().save(str(SHOTS / name))
        widget.hide()
        print("saved", name)

    login_dialog = LoginDialog(client, settings)
    login_dialog.server.setText(server.url)
    login_dialog._probe()
    shot(login_dialog, "01_login.png", 560, 700)

    window = MainWindow(client, user, settings, meta)
    shot(window, "02_dashboard_dark.png")
    window.show_page("units")
    shot(window, "03_units_dark.png")
    window.pages["units"].table.selectRow(1)
    QTest.qWait(60)

    credentials_page = H.credentials_page(
        hosp["unit"], hosp["credentials"], center_name="مركز الدائرة")
    credentials = CredentialsDialog(
        None, credentials_page, reports_dir=temp / "reports",
        filename="بيانات_دخول_H1",
        preview_html=H.credentials_preview(hosp["unit"], hosp["credentials"],
                                           center_name="مركز الدائرة"))
    shot(credentials, "04_credentials.png", 820, 700)

    window.show_page("users")
    shot(window, "05_users.png")
    window.show_page("settings")
    shot(window, "06_settings.png")
    window.show_page("about")
    shot(window, "07_about.png")

    window.show_page("employees")
    shot(window, "11_employees.png")
    window.show_page("letters")
    shot(window, "12_letters.png")
    window.show_page("rules")
    shot(window, "13_rules.png")
    window.show_page("orders")
    shot(window, "14_orders.png")
    window.show_page("calc")
    calc_page = window.pages["calc"]
    calc_page.employee.setCurrentIndex(0)
    calc_page.as_of.setDate(QDate(2020, 6, 1))
    calc_page._run()
    shot(window, "15_calc.png")

    window.show_page("reports")
    reports_page = window.pages["reports"]
    reports_page._run()
    shot(window, "16_reports.png")
    sample_pdf = temp / "sample_report.pdf"
    PDF.export_report(sample_pdf, "سجل الموظفين",
                      ["الرقم", "الاسم", "العنوان", "الدرجة/المرحلة"],
                      [["1001", "أحمد علي حسين", "طبيب", "3 / 1"],
                       ["1002", "سارة محمد كريم", "ممرض", "2 / 1"]],
                      "2 موظف", "مركز الدائرة")
    viewer = PdfViewerDialog(window, sample_pdf, "عارض PDF الداخلي")
    viewer.resize(1000, 760)
    viewer.show()
    QTest.qWait(900)
    shot(viewer, "18_pdf_viewer.png", 1000, 760)
    viewer.close()
    client.call("sync.export_rules", password="Smoke#2026")
    window.show_page("sync")
    shot(window, "17_sync.png")

    unit_dialog = UnitDialog(window, client, center_exists=True)
    shot(unit_dialog, "09_unit_dialog.png", 640, 760)
    provision = ProvisionDialog(window, client, hosp["unit"], meta)
    shot(provision, "10_provision.png", 660, 560)

    app.setStyleSheet(theme.stylesheet("light"))
    window.sync_theme_button()
    window.show_page("dashboard")
    shot(window, "08_dashboard_light.png")

    server.stop()
    service.close()
    shutil.rmtree(temp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
