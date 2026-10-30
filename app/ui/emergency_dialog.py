"""Acil Çıkış Şifre Doğrulama Diyaloğu (EmergencyExitDialog)."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeyEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.config import TOP_BAR_RADIUS
from app.core.auth import EmergencyAuthManager
from app.ui.styles import (
    DANGER_HEX,
    GLOBAL_STYLESHEET,
    TEXT_SECONDARY,
    apply_window_liquid_glass_effect,
    paint_liquid_glass_surface,
)


class EmergencyExitDialog(QWidget):
    """PBKDF2 doğrulamalı ve artan bekleme sayaçlı Liquid Glass acil çıkış ekranı."""

    emergency_unlocked = Signal()

    def __init__(self, auth_mgr: EmergencyAuthManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.auth_mgr = auth_mgr
        self.setWindowTitle("Acil Çıkış")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(GLOBAL_STYLESHEET)
        self.setFixedSize(440, 220)

        apply_window_liquid_glass_effect(self)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(20, 18, 20, 18)
        root_layout.setSpacing(10)

        title_lbl = QLabel("Acil Çıkış Doğrulaması")
        title_lbl.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {DANGER_HEX};")
        root_layout.addWidget(title_lbl)

        desc_lbl = QLabel(
            "Ders kilidini görevler bitmeden açmak için yakınınızın belirlediği acil çıkış şifresini girin. "
            "Hatalı denemelerde bekleme süresi katlanarak artar."
        )
        desc_lbl.setStyleSheet(f"font-size: 12px; color: {TEXT_SECONDARY};")
        desc_lbl.setWordWrap(True)
        root_layout.addWidget(desc_lbl)

        self.pwd_edit = QLineEdit()
        self.pwd_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pwd_edit.setPlaceholderText("Acil çıkış şifresi...")
        self.pwd_edit.returnPressed.connect(self._attempt_unlock)
        root_layout.addWidget(self.pwd_edit)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("font-size: 12px; color: #FCA5A5; font-weight: 600;")
        self.status_lbl.setWordWrap(True)
        root_layout.addWidget(self.status_lbl)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.cancel_btn = QPushButton("Vazgeç")
        self.cancel_btn.clicked.connect(self.hide)
        btn_row.addWidget(self.cancel_btn)

        self.unlock_btn = QPushButton("Kilidi Aç")
        self.unlock_btn.setObjectName("DangerButton")
        self.unlock_btn.clicked.connect(self._attempt_unlock)
        btn_row.addWidget(self.unlock_btn)
        root_layout.addLayout(btn_row)

        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._refresh_lockout_state)
        self._countdown_timer.start(1000)

    def open_dialog(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            sgeom = screen.geometry()
            x = sgeom.x() + (sgeom.width() - self.width()) // 2
            y = sgeom.y() + int(sgeom.height() * 0.25)
            self.move(x, y)

        self.pwd_edit.clear()
        self.status_lbl.clear()
        self._refresh_lockout_state()
        self.show()
        self.raise_()
        self.activateWindow()
        self.pwd_edit.setFocus()

    def _refresh_lockout_state(self) -> None:
        rem = self.auth_mgr.get_remaining_lockout_seconds()
        if rem > 0:
            self.pwd_edit.setEnabled(False)
            self.unlock_btn.setEnabled(False)
            self.status_lbl.setText(f"Çok fazla hatalı deneme yapıldı. Kalan bekleme süresi: {rem} sn")
        else:
            self.pwd_edit.setEnabled(True)
            self.unlock_btn.setEnabled(True)
            if "Kalan bekleme süresi" in self.status_lbl.text():
                self.status_lbl.clear()

    def _attempt_unlock(self) -> None:
        pwd = self.pwd_edit.text()
        if not pwd:
            self.status_lbl.setText("Lütfen şifreyi girin.")
            return

        ok, rem, msg = self.auth_mgr.verify_password(pwd)
        if ok:
            self.pwd_edit.clear()
            self.hide()
            self.emergency_unlocked.emit()
        else:
            self.pwd_edit.clear()
            self.status_lbl.setText(msg)
            self._refresh_lockout_state()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        paint_liquid_glass_surface(
            painter,
            QRectF(self.rect()),
            radius=float(TOP_BAR_RADIUS),
            bg_alpha_top=232,
            bg_alpha_bottom=218,
        )
