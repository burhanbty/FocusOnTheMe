"""Görev Tamamlama Ekran Görüntüsü Kanıtı Önizleme ve Onay Penceresi (ScreenshotProofDialog).

Özellikler:
- Görev tamamlandığında çalışma ekranının görüntüsünü yakalar ve canlı önizlemesini gösterir.
- Kullanıcı yanlış penceredeyse "3 Sn Sonra Yeniden Çek" ile doğru pencereyi öne getirip tekrar çekebilir.
- "Kanıtı Kaydet ve Görevi Tamamla" tıklandığında görseli `data/proofs/<tarih>/task_<id>.png` olarak kaydeder.
- "Vazgeç" tıklandığında görev tamamlanmamış (işaretsiz) duruma geri döner.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QGuiApplication,
    QKeyEvent,
    QPainter,
    QPaintEvent,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app import config
from app.core.logical_date import get_logical_date
from app.ui.styles import (
    ACCENT_HEX,
    GLOBAL_STYLESHEET,
    TEXT_SECONDARY,
    apply_window_liquid_glass_effect,
    paint_liquid_glass_surface,
)


class ScreenshotProofDialog(QWidget):
    """Ekran görüntüsü kanıtını önizleyen, yeniden çekmeye izin veren ve onaylayan Liquid Glass pencere."""

    proof_confirmed = Signal(int, str)  # (task_id, saved_file_path)
    proof_cancelled = Signal(int)       # (task_id)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Görev Tamamlama — Ekran Görüntüsü Kanıtı")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(GLOBAL_STYLESHEET)
        self.setFixedSize(660, 490)

        apply_window_liquid_glass_effect(self)

        self._task_id: int = 0
        self._task_label: str = ""
        self._logical_date: str = get_logical_date()
        self._current_pixmap: QPixmap | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(22, 18, 22, 18)
        root_layout.setSpacing(12)

        header_lbl = QLabel("Ekran Görüntüsü Kanıtı Onayı")
        header_lbl.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {ACCENT_HEX};")
        root_layout.addWidget(header_lbl)

        self.task_info_lbl = QLabel("")
        self.task_info_lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: #F8FAFC;")
        self.task_info_lbl.setWordWrap(True)
        root_layout.addWidget(self.task_info_lbl)

        # Önizleme çerçevesi
        preview_frame = QFrame()
        preview_frame.setStyleSheet(
            "QFrame {"
            "  background-color: rgba(8, 12, 20, 210);"
            "  border: 1px solid rgba(255, 255, 255, 45);"
            "  border-radius: 10px;"
            "}"
        )
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(8, 8, 8, 8)

        self.preview_lbl = QLabel("Ekran görüntüsü hazırlanıyor...")
        self.preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_lbl.setMinimumSize(600, 310)
        self.preview_lbl.setStyleSheet("border: none; background: transparent; color: #94A3B8;")
        preview_layout.addWidget(self.preview_lbl)
        root_layout.addWidget(preview_frame, 1)

        self.path_hint_lbl = QLabel("")
        self.path_hint_lbl.setStyleSheet(f"font-size: 11px; color: {TEXT_SECONDARY};")
        root_layout.addWidget(self.path_hint_lbl)

        # Alt buton satırı
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.retake_btn = QPushButton("🔄 3 Sn Sonra Yeniden Çek")
        self.retake_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.retake_btn.setToolTip("Pencereyi 3 saniyeliğine gizler, doğru ekranı açıp kanıtı yeniden yakalar")
        self.retake_btn.clicked.connect(self._on_retake_clicked)
        btn_row.addWidget(self.retake_btn)

        btn_row.addStretch()

        self.cancel_btn = QPushButton("Vazgeç")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        btn_row.addWidget(self.cancel_btn)

        self.confirm_btn = QPushButton("✓ Kanıtı Kaydet ve Görevi Tamamla")
        self.confirm_btn.setObjectName("PrimaryAccentButton")
        self.confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_btn.setFixedHeight(36)
        self.confirm_btn.clicked.connect(self._on_confirm_clicked)
        btn_row.addWidget(self.confirm_btn)

        root_layout.addLayout(btn_row)

    def start_capture_for_task(self, task: dict[str, Any], logical_date: str | None = None) -> None:
        """Verilen görev için ekran görüntüsü yakalar ve onay penceresini açar."""
        self._task_id = int(task["id"])
        subj = str(task.get("subject") or "").strip()
        title = str(task.get("title") or "").strip()
        self._task_label = f"[{subj}] {title}" if subj else title
        self._logical_date = logical_date or get_logical_date()

        self.task_info_lbl.setText(f"Tamamlanan Görev: {self._task_label}")
        out_path = self._get_target_file_path()
        self.path_hint_lbl.setText(f"Kaydedilecek konum: {out_path}")

        self._capture_screen_and_show()

    def _get_target_file_path(self) -> Path:
        day_dir = config.PROOFS_DIR / self._logical_date
        day_dir.mkdir(parents=True, exist_ok=True)
        return day_dir / f"task_{self._task_id}.png"

    def _capture_screen_and_show(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self._current_pixmap = screen.grabWindow(0)
            scaled = self._current_pixmap.scaled(
                596,
                306,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.preview_lbl.setPixmap(scaled)
            sgeom = screen.geometry()
            x = sgeom.x() + (sgeom.width() - self.width()) // 2
            y = sgeom.y() + (sgeom.height() - self.height()) // 2
            self.move(x, y)
        else:
            self._current_pixmap = None
            self.preview_lbl.setText("Ekran görüntüsü alınamadı.")

        self.show()
        self.raise_()
        self.activateWindow()

    def _on_retake_clicked(self) -> None:
        self.hide()
        QTimer.singleShot(3000, self._capture_screen_and_show)

    def _on_confirm_clicked(self) -> None:
        out_path = self._get_target_file_path()
        saved_str = ""
        if self._current_pixmap is not None and not self._current_pixmap.isNull():
            out_path.parent.mkdir(parents=True, exist_ok=True)
            self._current_pixmap.save(str(out_path), "PNG")
            saved_str = str(out_path)
        self.hide()
        self.proof_confirmed.emit(self._task_id, saved_str)

    def _on_cancel_clicked(self) -> None:
        tid = self._task_id
        self.hide()
        self.proof_cancelled.emit(tid)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._on_cancel_clicked()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        paint_liquid_glass_surface(
            painter,
            QRectF(self.rect()),
            radius=float(config.TOP_BAR_RADIUS),
            bg_alpha_top=236,
            bg_alpha_bottom=224,
        )
