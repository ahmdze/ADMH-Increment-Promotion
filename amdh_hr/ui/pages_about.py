"""صفحة حول النظام."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QLabel, QVBoxLayout

from ..config import (
    APP_DEVELOPER, APP_EMAIL, APP_NAME, APP_PHONE, APP_RELEASE, APP_VERSION,
    asset_path,
)
from . import widgets as W
from .pages_base import BasePage


class AboutPage(BasePage):
    def build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)
        root.addWidget(W.page_header("حول النظام", "معلومات الإصدار والمطوّر ونطاق المرحلة"))

        top = W.card()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(22, 18, 22, 18)
        top_layout.setSpacing(4)
        logo = asset_path("logo_badge.png")
        if logo.exists():
            mark = QLabel()
            mark.setPixmap(QPixmap(str(logo)).scaled(
                110, 110, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
            mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
            top_layout.addWidget(mark)
        name = QLabel(APP_NAME)
        name.setStyleSheet("font-size: 17pt; font-weight: 800;")
        top_layout.addWidget(name)
        top_layout.addWidget(W.muted(
            "سجل وظيفي موحّد، واحتساب استرشادي للعلاوات والترفيعات، وكتب شكر بمستفيدين "
            "متعددين، وأوامر رسمية ومرفقات مشتركة."))
        top_layout.addWidget(W.muted(
            f"الإصدار {APP_VERSION} — {APP_RELEASE} · المواصفة المرجعية v1.1"))
        root.addWidget(top)

        info = W.card()
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(22, 16, 22, 16)
        info_layout.setSpacing(6)
        rows = [
            ("المطوّر", APP_DEVELOPER),
            ("الهاتف", APP_PHONE),
            ("البريد", APP_EMAIL),
            ("الجهة", "مركز الدائرة والمؤسسات الصحية التابعة له"),
            ("طريقة العمل", "خدمة محلية + عملاء على الشبكة الداخلية، وتبادل عبر USB"),
        ]
        for key, value in rows:
            line = QLabel(f"<b>{key}:</b> {value}")
            line.setTextFormat(Qt.TextFormat.RichText)
            info_layout.addWidget(line)
        root.addWidget(info)

        phase = W.card()
        phase_layout = QVBoxLayout(phase)
        phase_layout.setContentsMargins(22, 16, 22, 16)
        phase_layout.setSpacing(6)
        phase_layout.addWidget(QLabel("<b>المرحلة 1 — منفّذة</b>"))
        phase_layout.addWidget(W.muted(
            "خدمة محلية، دخول إلزامي، أربعة أدوار ونطاق، مؤسسات بحسابات تلقائية، "
            "بطاقة دخول HTML، تصفير كلمات المرور، نسخ احتياطي وفحص، تجهيز نسخة مؤسسة."))
        phase_layout.addWidget(QLabel("<b>المرحلة 2 — التالية</b>"))
        phase_layout.addWidget(W.muted(
            "ملف الموظف، العنوان الوظيفي التاريخي، السجل الوظيفي، مخزن الوثائق، "
            "عارض المرفقات والطباعة، وتوزيع الموظفين على المستخدمين."))
        root.addWidget(phase)

        root.addWidget(W.muted(
            "تنبيه: نتائج الاحتساب استرشادية، ولا تمنح صفة قانونية قبل اعتماد مصفوفة "
            "القواعد القانونية من الجهة المختصة."))
        root.addStretch()
