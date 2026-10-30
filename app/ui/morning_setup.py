"""Sabah Görev Girişi ve Ders Modu Yapılandırma Ekranı (MorningSetupWindow).

Kurallar:
- Gün sınırı 04:00'tür.
- En az 1 görev eklenmeden "Ders Modunu Başlat" düğmesi etkinleşmez.
- Beyaz liste (.exe seçerek veya yolla), TEK Ders Klasörü, Edge izinli siteler ve
  Acil Çıkış şifresi bu ekrandan yapılandırılır.
"""

from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app import config
from app.core.auth import EmergencyAuthManager
from app.core.database import Database
from app.core.logical_date import get_logical_date
from app.ui.styles import (
    ACCENT_HEX,
    GLOBAL_STYLESHEET,
    TEXT_SECONDARY,
    apply_window_liquid_glass_effect,
    paint_liquid_glass_surface,
)


class MorningSetupWindow(QWidget):
    """Ders modu başlamadan önce görevlerin ve izinlerin girildiği Liquid Glass pencere."""

    start_study_mode_requested = Signal()

    def __init__(self, db: Database, auth_mgr: EmergencyAuthManager) -> None:
        super().__init__(None)
        self.db = db
        self.auth_mgr = auth_mgr
        self.logical_date = get_logical_date()

        self.setWindowTitle("Ders Kilidi — Sabah Görev Girişi ve Hazırlık")
        self.resize(840, 620)
        self.setMinimumSize(760, 560)
        self.setStyleSheet(
            GLOBAL_STYLESHEET
            + f"""
            QTabWidget::pane {{
                border: 1px solid rgba(255, 255, 255, 36);
                border-radius: 12px;
                background-color: rgba(13, 19, 31, 185);
                padding: 10px;
            }}
            QTabBar::tab {{
                background-color: rgba(255, 255, 255, 12);
                border: 1px solid rgba(255, 255, 255, 30);
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                padding: 8px 16px;
                margin-right: 4px;
                color: {TEXT_SECONDARY};
                font-weight: 600;
            }}
            QTabBar::tab:selected {{
                background-color: rgba(56, 189, 248, 36);
                border-color: {ACCENT_HEX};
                color: #F8FAFC;
            }}
            """
        )
        apply_window_liquid_glass_effect(self)
        self._build_ui()
        self.refresh_all()

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(24, 20, 24, 20)
        root_layout.setSpacing(14)

        # Üst Başlık
        header_row = QHBoxLayout()
        title_col = QVBoxLayout()
        title_lbl = QLabel("Ders Kilidi — Sabah Görev Planlama")
        title_lbl.setStyleSheet("font-size: 20px; font-weight: 700; color: #F8FAFC;")
        self.subtitle_lbl = QLabel("")
        self.subtitle_lbl.setStyleSheet(f"font-size: 12px; color: {TEXT_SECONDARY};")
        title_col.addWidget(title_lbl)
        title_col.addWidget(self.subtitle_lbl)
        header_row.addLayout(title_col)
        header_row.addStretch()

        if config.TEST_MODE:
            test_badge = QLabel("TEST MODU AKTİF (10 dk Dead-Man)")
            test_badge.setStyleSheet(
                "background-color: rgba(245, 158, 11, 40);"
                "border: 1px solid rgba(245, 158, 11, 140);"
                "border-radius: 8px; padding: 5px 10px;"
                "color: #FDE68A; font-weight: 700; font-size: 12px;"
            )
            header_row.addWidget(test_badge)

        root_layout.addLayout(header_row)

        # Sekmeler
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_tasks_tab(), "1. Bugünün Görevleri")
        self.tabs.addTab(self._build_apps_and_folder_tab(), "2. İzinli Uygulamalar & Ders Klasörü")
        self.tabs.addTab(self._build_urls_tab(), "3. Edge İzinli Siteler")
        self.tabs.addTab(self._build_security_tab(), "4. Acil Çıkış & Güvenlik")
        root_layout.addWidget(self.tabs, 1)

        # Alt Eylem Satırı
        footer_row = QHBoxLayout()
        self.requirement_lbl = QLabel("Ders modunu başlatmak için en az 1 görev ekleyin.")
        self.requirement_lbl.setStyleSheet(f"font-size: 12px; color: {TEXT_SECONDARY};")
        footer_row.addWidget(self.requirement_lbl)
        footer_row.addStretch()

        self.start_btn = QPushButton("Ders Modunu Başlat (Masaüstünü Kilitle)")
        self.start_btn.setObjectName("PrimaryAccentButton")
        self.start_btn.setFixedHeight(42)
        self.start_btn.setMinimumWidth(290)
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.clicked.connect(self._on_start_clicked)
        footer_row.addWidget(self.start_btn)
        root_layout.addLayout(footer_row)

    def _build_tasks_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)

        form_row = QHBoxLayout()
        form_row.setSpacing(8)

        self.subject_edit = QLineEdit()
        self.subject_edit.setPlaceholderText("Ders adı (örn. Matematik, Fizik)")
        self.subject_edit.setFixedWidth(180)
        form_row.addWidget(self.subject_edit)

        self.task_title_edit = QLineEdit()
        self.task_title_edit.setPlaceholderText("Görev başlığı (örn. Türevden 30 soru çöz)")
        self.task_title_edit.returnPressed.connect(self._add_task)
        form_row.addWidget(self.task_title_edit, 1)

        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(0, 480)
        self.duration_spin.setSpecialValueText("Süre (İsteğe bağlı)")
        self.duration_spin.setSuffix(" dk")
        self.duration_spin.setFixedWidth(145)
        form_row.addWidget(self.duration_spin)

        add_btn = QPushButton("Görev Ekle")
        add_btn.setObjectName("PrimaryAccentButton")
        add_btn.clicked.connect(self._add_task)
        form_row.addWidget(add_btn)
        layout.addLayout(form_row)

        self.tasks_list = QListWidget()
        layout.addWidget(self.tasks_list, 1)

        bottom_row = QHBoxLayout()
        self.proof_checkbox = QCheckBox("Görev tamamlandığında ekran görüntüsü kanıtı kaydet (İsteğe bağlı)")
        self.proof_checkbox.toggled.connect(self.db.set_screenshot_proof_required)
        bottom_row.addWidget(self.proof_checkbox)
        bottom_row.addStretch()

        del_task_btn = QPushButton("Seçili Görevi Sil")
        del_task_btn.clicked.connect(self._delete_selected_task)
        bottom_row.addWidget(del_task_btn)
        layout.addLayout(bottom_row)
        return page

    def _build_apps_and_folder_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        # Ders Klasörü Seçimi (TEK Klasör)
        folder_box = QFrame()
        folder_box.setStyleSheet(
            "QFrame { background-color: rgba(255,255,255,10); border: 1px solid rgba(255,255,255,28); border-radius: 10px; }"
        )
        folder_layout = QVBoxLayout(folder_box)
        folder_lbl = QLabel("Ders Klasörü (Üst çubuktan erişilecek TEK çalışma klasörü):")
        folder_lbl.setStyleSheet("font-weight: 600; border: none; background: transparent;")
        folder_layout.addWidget(folder_lbl)

        folder_row = QHBoxLayout()
        self.study_folder_edit = QLineEdit()
        self.study_folder_edit.setPlaceholderText(r"Örn: C:\Users\...\Desktop\DersNotlari")
        self.study_folder_edit.editingFinished.connect(
            lambda: self.db.set_study_folder(self.study_folder_edit.text())
        )
        folder_row.addWidget(self.study_folder_edit, 1)

        browse_folder_btn = QPushButton("Klasör Seç...")
        browse_folder_btn.clicked.connect(self._browse_study_folder)
        folder_row.addWidget(browse_folder_btn)
        folder_layout.addLayout(folder_row)
        layout.addWidget(folder_box)

        # İzinli Uygulamalar (Beyaz Liste)
        apps_lbl = QLabel("İzinli Uygulamalar (Beyaz Liste — dışındaki pencereler 5 sn uyarıyla kapatılır):")
        apps_lbl.setStyleSheet("font-weight: 600;")
        layout.addWidget(apps_lbl)

        app_add_row = QHBoxLayout()
        self.app_name_edit = QLineEdit()
        self.app_name_edit.setPlaceholderText("Uygulama adı (örn. SumatraPDF)")
        self.app_name_edit.setFixedWidth(180)
        app_add_row.addWidget(self.app_name_edit)

        self.app_path_edit = QLineEdit()
        self.app_path_edit.setPlaceholderText(r"Tam .exe yolu (örn. C:\Program Files\...\uygulama.exe)")
        app_add_row.addWidget(self.app_path_edit, 1)

        browse_exe_btn = QPushButton(".exe Seç...")
        browse_exe_btn.clicked.connect(self._browse_allowed_exe)
        app_add_row.addWidget(browse_exe_btn)

        add_app_btn = QPushButton("Listeye Ekle")
        add_app_btn.setObjectName("PrimaryAccentButton")
        add_app_btn.clicked.connect(self._add_allowed_app)
        app_add_row.addWidget(add_app_btn)
        layout.addLayout(app_add_row)

        self.apps_list = QListWidget()
        layout.addWidget(self.apps_list, 1)

        del_app_btn_row = QHBoxLayout()
        del_app_btn_row.addStretch()
        del_app_btn = QPushButton("Seçili Uygulamayı Kaldır")
        del_app_btn.clicked.connect(self._remove_selected_app)
        del_app_btn_row.addWidget(del_app_btn)
        layout.addLayout(del_app_btn_row)
        return page

    def _build_urls_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)

        info_lbl = QLabel(
            "Microsoft Edge ders modunda tüm siteleri engeller (URLBlocklist='*') ve yalnızca aşağıdaki "
            "izinli adreslere (URLAllowlist) izin verir. Politika hem HKCU hem HKLM altına uygulanır."
        )
        info_lbl.setStyleSheet(f"color: {TEXT_SECONDARY};")
        info_lbl.setWordWrap(True)
        layout.addWidget(info_lbl)

        url_row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Örn: gemini.google.com veya https://*.edu.tr")
        self.url_edit.returnPressed.connect(self._add_allowed_url)
        url_row.addWidget(self.url_edit, 1)

        add_url_btn = QPushButton("Site Ekle")
        add_url_btn.setObjectName("PrimaryAccentButton")
        add_url_btn.clicked.connect(self._add_allowed_url)
        url_row.addWidget(add_url_btn)
        layout.addLayout(url_row)

        self.urls_list = QListWidget()
        layout.addWidget(self.urls_list, 1)

        del_url_row = QHBoxLayout()
        del_url_row.addStretch()
        del_url_btn = QPushButton("Seçili Siteyi Kaldır")
        del_url_btn.clicked.connect(self._remove_selected_url)
        del_url_row.addWidget(del_url_btn)
        layout.addLayout(del_url_row)
        return page

    def _build_security_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        desc_lbl = QLabel(
            "Acil çıkış şifresi güvendiğiniz bir yakınınız tarafından belirlenmelidir. "
            "Şifre PBKDF2-HMAC-SHA256 (600.000 iterasyon) ile özetlenerek saklanır; düz metin olarak okunamaz."
        )
        desc_lbl.setStyleSheet(f"color: {TEXT_SECONDARY};")
        desc_lbl.setWordWrap(True)
        layout.addWidget(desc_lbl)

        self.pwd_status_lbl = QLabel("")
        self.pwd_status_lbl.setStyleSheet(f"font-weight: 600; color: {ACCENT_HEX};")
        layout.addWidget(self.pwd_status_lbl)

        pwd_row = QHBoxLayout()
        self.new_pwd_edit = QLineEdit()
        self.new_pwd_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_pwd_edit.setPlaceholderText("Yeni acil çıkış şifresi (en az 4 karakter)")
        pwd_row.addWidget(self.new_pwd_edit, 1)

        save_pwd_btn = QPushButton("Şifreyi Kaydet")
        save_pwd_btn.setObjectName("PrimaryAccentButton")
        save_pwd_btn.clicked.connect(self._save_emergency_password)
        pwd_row.addWidget(save_pwd_btn)
        layout.addLayout(pwd_row)

        layout.addStretch(1)
        return page

    def refresh_all(self) -> None:
        self.logical_date = get_logical_date()
        stats = self.db.get_session_stats(self.logical_date)
        self.subtitle_lbl.setText(
            f"Mantıksal Gün (04:00 sınırı): {self.logical_date}   •   "
            f"Üst Üste Gün Serisi: {stats['streak_days']} gün"
        )
        self.proof_checkbox.setChecked(self.db.is_screenshot_proof_required())
        self.study_folder_edit.setText(self.db.get_study_folder())
        self._refresh_tasks_list()
        self._refresh_apps_list()
        self._refresh_urls_list()
        self._refresh_security_status()

    def _refresh_tasks_list(self) -> None:
        self.tasks_list.clear()
        tasks = self.db.get_tasks_for_date(self.logical_date)
        for idx, t in enumerate(tasks, start=1):
            est = f" ({t['estimated_minutes']} dk)" if t.get("estimated_minutes") else ""
            status = "✓ " if t.get("completed") else "○ "
            text = f"{status}{idx}. [{t['subject']}] {t['title']}{est}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, int(t["id"]))
            self.tasks_list.addItem(item)

        has_tasks = len(tasks) > 0
        self.start_btn.setEnabled(has_tasks)
        if has_tasks:
            self.requirement_lbl.setText(f"Bugün için {len(tasks)} görev hazır. Ders modunu başlatabilirsiniz.")
            self.requirement_lbl.setStyleSheet(f"font-size: 12px; color: {ACCENT_HEX}; font-weight: 600;")
        else:
            self.requirement_lbl.setText("Ders modunu başlatmak için en az 1 görev ekleyin.")
            self.requirement_lbl.setStyleSheet(f"font-size: 12px; color: {TEXT_SECONDARY};")

    def _add_task(self) -> None:
        subj = self.subject_edit.text().strip() or "Genel"
        title = self.task_title_edit.text().strip()
        if not title:
            return
        est = self.duration_spin.value() if self.duration_spin.value() > 0 else None
        self.db.add_task(title=title, subject=subj, estimated_minutes=est, logical_date=self.logical_date)
        self.task_title_edit.clear()
        self.duration_spin.setValue(0)
        self._refresh_tasks_list()

    def _delete_selected_task(self) -> None:
        item = self.tasks_list.currentItem()
        if item is None:
            return
        tid = int(item.data(Qt.ItemDataRole.UserRole))
        self.db.delete_task(tid)
        self._refresh_tasks_list()

    def _browse_study_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Ders Klasörü Seçin")
        if folder:
            norm = os.path.normpath(folder)
            self.study_folder_edit.setText(norm)
            self.db.set_study_folder(norm)

    def _browse_allowed_exe(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "İzinli Uygulama Seçin",
            r"C:\Program Files",
            "Çalıştırılabilir Dosyalar (*.exe)",
        )
        if file_path:
            norm = os.path.normpath(file_path)
            self.app_path_edit.setText(norm)
            if not self.app_name_edit.text().strip():
                base = os.path.splitext(os.path.basename(norm))[0]
                self.app_name_edit.setText(base)

    def _add_allowed_app(self) -> None:
        path = self.app_path_edit.text().strip()
        if not path:
            return
        name = self.app_name_edit.text().strip() or os.path.splitext(os.path.basename(path))[0]
        self.db.add_allowed_app(name=name, exe_path=path)
        self.app_name_edit.clear()
        self.app_path_edit.clear()
        self._refresh_apps_list()

    def _remove_selected_app(self) -> None:
        item = self.apps_list.currentItem()
        if item is None:
            return
        app_id = int(item.data(Qt.ItemDataRole.UserRole))
        self.db.remove_allowed_app(app_id)
        self._refresh_apps_list()

    def _refresh_apps_list(self) -> None:
        self.apps_list.clear()
        for app in self.db.get_allowed_apps(only_enabled=False):
            item = QListWidgetItem(f"{app['name']}   —   {app['exe_path']}")
            item.setData(Qt.ItemDataRole.UserRole, int(app["id"]))
            self.apps_list.addItem(item)

    def _add_allowed_url(self) -> None:
        pattern = self.url_edit.text().strip()
        if not pattern:
            return
        self.db.add_allowed_url(pattern)
        self.url_edit.clear()
        self._refresh_urls_list()

    def _remove_selected_url(self) -> None:
        item = self.urls_list.currentItem()
        if item is None:
            return
        pattern = str(item.data(Qt.ItemDataRole.UserRole))
        self.db.remove_allowed_url(pattern)
        self._refresh_urls_list()

    def _refresh_urls_list(self) -> None:
        self.urls_list.clear()
        for url in self.db.get_allowed_urls(only_enabled=False):
            item = QListWidgetItem(url)
            item.setData(Qt.ItemDataRole.UserRole, url)
            self.urls_list.addItem(item)

    def _save_emergency_password(self) -> None:
        pwd = self.new_pwd_edit.text().strip()
        if len(pwd) < 4:
            QMessageBox.warning(self, "Uyarı", "Acil çıkış şifresi en az 4 karakter olmalıdır.")
            return
        self.auth_mgr.set_password(pwd)
        self.new_pwd_edit.clear()
        self._refresh_security_status()
        QMessageBox.information(self, "Kaydedildi", "Acil çıkış şifresi güvenli biçimde kaydedildi.")

    def _refresh_security_status(self) -> None:
        if self.auth_mgr.has_password():
            self.pwd_status_lbl.setText("Durum: Acil çıkış şifresi tanımlı (PBKDF2-SHA256).")
        else:
            self.pwd_status_lbl.setText("Durum: Acil çıkış şifresi henüz tanımlanmamış.")

    def _on_start_clicked(self) -> None:
        if self.study_folder_edit.text().strip():
            self.db.set_study_folder(self.study_folder_edit.text().strip())
        tasks = self.db.get_tasks_for_date(self.logical_date)
        if not tasks:
            return
        self.start_study_mode_requested.emit()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        paint_liquid_glass_surface(
            painter,
            QRectF(self.rect()),
            radius=14.0,
            bg_alpha_top=240,
            bg_alpha_bottom=230,
        )
