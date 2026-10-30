"""Üst çubuktan açılan Liquid Glass Görev Listesi (TaskPopover) ve Ders Klasörü (StudyFolderPopover) panelleri.

Özellikler:
- Dışına tıklanınca otomatik kapanır (Qt.Popup).
- Açılış ve kapanışta en fazla 120 ms'lik solma (opacity fade) animasyonu kullanır.
- 14 px köşe yuvarlaklığı, rgba(255,255,255,0.18) kenarlık ve DWM Acrylic/Liquid Glass arka plan.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.config import POPOVER_FADE_MS, TOP_BAR_RADIUS
from app.ui.styles import (
    ACCENT_HEX,
    GLOBAL_STYLESHEET,
    TEXT_SECONDARY,
    apply_window_liquid_glass_effect,
    paint_liquid_glass_surface,
)


class BaseGlassPopover(QWidget):
    """Liquid Glass efektli ve <=120 ms solma animasyonlu temel açılır panel."""

    def __init__(self, parent: QWidget | None = None, width: int = 400, max_height: int = 420) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(width)
        self.setMaximumHeight(max_height)
        self.setStyleSheet(GLOBAL_STYLESHEET)

        self._fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_anim.setDuration(min(120, POPOVER_FADE_MS))
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_anim.finished.connect(self._on_anim_finished)
        self._closing_via_anim = False
        self.glass_mode = apply_window_liquid_glass_effect(self)

    def show_at(self, global_pos: QPoint) -> None:
        self._closing_via_anim = False
        self._fade_anim.stop()
        self.move(global_pos)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self.activateWindow()
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

    def close_with_fade(self) -> None:
        if not self.isVisible():
            return
        if self._closing_via_anim:
            self._fade_anim.stop()
            self._closing_via_anim = False
            self.hide()
            return
        self._closing_via_anim = True
        self._fade_anim.stop()
        self._fade_anim.setStartValue(max(0.1, self.windowOpacity()))
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.start()

    def _on_anim_finished(self) -> None:
        if self._closing_via_anim:
            self._closing_via_anim = False
            self.hide()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        paint_liquid_glass_surface(
            painter,
            QRectF(self.rect()),
            radius=float(TOP_BAR_RADIUS),
            bg_alpha_top=226,
            bg_alpha_bottom=212,
        )


class TaskPopover(BaseGlassPopover):
    """Üst çubuğun ortasına tıklanınca açılan görev listesi cam paneli."""

    task_toggled = Signal(int, bool)  # (task_id, completed)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent, width=430, max_height=440)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(16, 14, 16, 14)
        root_layout.setSpacing(10)

        header_row = QHBoxLayout()
        self.title_lbl = QLabel("Günün Görevleri")
        self.title_lbl.setStyleSheet("font-size: 14px; font-weight: 600; color: #F8FAFC;")
        self.progress_lbl = QLabel("0/0 tamamlandı")
        self.progress_lbl.setStyleSheet(f"font-size: 12px; color: {ACCENT_HEX}; font-weight: 600;")
        header_row.addWidget(self.title_lbl)
        header_row.addStretch()
        header_row.addWidget(self.progress_lbl)
        root_layout.addLayout(header_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: rgba(255, 255, 255, 32); max-height: 1px; border: none;")
        root_layout.addWidget(sep)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setStyleSheet("background: transparent;")

        self.tasks_container = QWidget()
        self.tasks_container.setStyleSheet("background: transparent;")
        self.tasks_layout = QVBoxLayout(self.tasks_container)
        self.tasks_layout.setContentsMargins(2, 2, 2, 2)
        self.tasks_layout.setSpacing(8)
        self.scroll_area.setWidget(self.tasks_container)
        root_layout.addWidget(self.scroll_area)

        hint_lbl = QLabel("Tüm görevleri işaretlediğinizde ders kilidi otomatik olarak kalkar.")
        hint_lbl.setStyleSheet(f"font-size: 11px; color: {TEXT_SECONDARY};")
        hint_lbl.setWordWrap(True)
        root_layout.addWidget(hint_lbl)

    def set_tasks(self, tasks: list[dict[str, Any]]) -> None:
        while self.tasks_layout.count():
            item = self.tasks_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        completed_count = sum(1 for t in tasks if t.get("completed"))
        total_count = len(tasks)
        self.progress_lbl.setText(f"{completed_count}/{total_count} tamamlandı")

        if not tasks:
            empty_lbl = QLabel("Bugün için kayıtlı görev yok.")
            empty_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; padding: 12px 0;")
            self.tasks_layout.addWidget(empty_lbl)
            self.adjustSize()
            return

        for task in tasks:
            tid = int(task["id"])
            is_done = bool(task.get("completed"))
            subject = str(task.get("subject") or "").strip()
            title = str(task.get("title") or "").strip()
            est = task.get("estimated_minutes")

            row_frame = QFrame()
            row_frame.setStyleSheet(
                "QFrame {"
                "  background-color: rgba(255, 255, 255, 10);"
                "  border: 1px solid rgba(255, 255, 255, 24);"
                "  border-radius: 9px;"
                "}"
                "QFrame:hover {"
                "  background-color: rgba(255, 255, 255, 18);"
                "}"
            )
            row_layout = QHBoxLayout(row_frame)
            row_layout.setContentsMargins(10, 8, 10, 8)
            row_layout.setSpacing(10)

            label_text = f"{subject}: {title}" if subject else title
            if est:
                label_text += f"  ({est} dk)"

            cb = QCheckBox(label_text)
            cb.setChecked(is_done)
            if is_done:
                cb.setStyleSheet("color: #94A3B8; text-decoration: line-through;")
            else:
                cb.setStyleSheet("color: #F1F5F9; font-weight: 500;")

            cb.toggled.connect(lambda checked, task_id=tid: self.task_toggled.emit(task_id, checked))
            row_layout.addWidget(cb, 1)
            self.tasks_layout.addWidget(row_frame)

        self.tasks_layout.addStretch(1)
        target_h = min(420, max(165, 115 + len(tasks) * 46))
        self.setFixedHeight(target_h)


class StudyFolderPopover(BaseGlassPopover):
    """'Ders Klasörü' butonuna tıklanınca seçili klasörün dosyalarını listeleyen cam panel."""

    file_clicked = Signal(str)  # tam dosya yolu

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent, width=380, max_height=420)
        self._folder_path: str = ""

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(16, 14, 16, 14)
        root_layout.setSpacing(8)

        self.header_lbl = QLabel("Ders Klasörü")
        self.header_lbl.setStyleSheet("font-size: 14px; font-weight: 600; color: #F8FAFC;")
        root_layout.addWidget(self.header_lbl)

        self.path_lbl = QLabel("")
        self.path_lbl.setStyleSheet(f"font-size: 11px; color: {TEXT_SECONDARY};")
        self.path_lbl.setWordWrap(True)
        root_layout.addWidget(self.path_lbl)

        self.file_list = QListWidget()
        self.file_list.itemClicked.connect(self._on_item_clicked)
        root_layout.addWidget(self.file_list, 1)

        hint_lbl = QLabel("Dosyaya tıkladığınızda varsayılan uygulamayla açılır.")
        hint_lbl.setStyleSheet(f"font-size: 11px; color: {TEXT_SECONDARY};")
        root_layout.addWidget(hint_lbl)

    def load_folder(self, folder_path: str) -> None:
        self._folder_path = (folder_path or "").strip()
        self.file_list.clear()

        if not self._folder_path or not os.path.isdir(self._folder_path):
            self.path_lbl.setText("Sabah ayarlarından bir Ders Klasörü seçilmemiş.")
            empty_item = QListWidgetItem("Klasör tanımlanmamış veya bulunamadı.")
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.file_list.addItem(empty_item)
            self.setFixedHeight(200)
            return

        folder = Path(self._folder_path)
        self.path_lbl.setText(str(folder))

        entries: list[Path] = []
        try:
            for entry in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
                if entry.name.startswith("."):
                    continue
                if entry.is_file():
                    entries.append(entry)
                elif entry.is_dir():
                    # Bir alt seviyedeki dosyaları da "AltKlasör / dosya" olarak listele
                    try:
                        for sub in sorted(entry.iterdir(), key=lambda sp: sp.name.lower()):
                            if sub.is_file() and not sub.name.startswith("."):
                                entries.append(sub)
                    except OSError:
                        pass
        except OSError:
            pass

        if not entries:
            empty_item = QListWidgetItem("Bu klasörde gösterilecek dosya yok.")
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.file_list.addItem(empty_item)
            self.setFixedHeight(210)
            return

        for fpath in entries[:200]:
            rel_name = str(fpath.relative_to(folder))
            item = QListWidgetItem(f"📄  {rel_name}")
            item.setData(Qt.ItemDataRole.UserRole, str(fpath))
            item.setToolTip(str(fpath))
            self.file_list.addItem(item)

        self.setFixedHeight(min(400, max(230, 130 + len(entries) * 32)))

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        full_path = item.data(Qt.ItemDataRole.UserRole)
        if full_path and os.path.isfile(str(full_path)):
            self.close_with_fade()
            self.file_clicked.emit(str(full_path))
