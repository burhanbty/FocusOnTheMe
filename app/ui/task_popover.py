"""Üst çubuktan açılan Liquid Glass Görev Listesi (TaskPopover), Ders Klasörü Gezgini (StudyFolderPopover)
ve Aktif Ders / Uygulama Süre Takibi (CourseAndActivityPopover) panelleri.

Özellikler:
- Dışına tıklanınca otomatik kapanır (Qt.Popup).
- Açılış ve kapanışta en fazla 120 ms'lik solma (opacity fade) animasyonu kullanır.
- StudyFolderPopover sınırsız derinlikte alt klasör gezintisi (`📁` klasöre gir, `⬅️ ..` üst klasöre dön) sunar.
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
from PySide6.QtGui import QPainter, QPaintEvent
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
from app.core.activity_tracker import format_duration_human
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
    """'Ders Klasörü' butonuna tıklanınca alt klasörler ve dosyalar arasında gezinmeyi sağlayan cam panel."""

    file_clicked = Signal(str)  # tam dosya yolu

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent, width=410, max_height=450)
        self._root_folder: Path | None = None
        self._current_folder: Path | None = None

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(16, 14, 16, 14)
        root_layout.setSpacing(8)

        self.header_lbl = QLabel("Ders Klasörü")
        self.header_lbl.setStyleSheet("font-size: 14px; font-weight: 600; color: #F8FAFC;")
        root_layout.addWidget(self.header_lbl)

        self.path_lbl = QLabel("")
        self.path_lbl.setStyleSheet(f"font-size: 11px; color: {ACCENT_HEX}; font-weight: 500;")
        self.path_lbl.setWordWrap(True)
        root_layout.addWidget(self.path_lbl)

        self.file_list = QListWidget()
        self.file_list.itemClicked.connect(self._on_item_clicked)
        root_layout.addWidget(self.file_list, 1)

        hint_lbl = QLabel("Klasörlere tıklayarak içine girebilir, dosyalara tıklayarak açabilirsiniz.")
        hint_lbl.setStyleSheet(f"font-size: 11px; color: {TEXT_SECONDARY};")
        hint_lbl.setWordWrap(True)
        root_layout.addWidget(hint_lbl)

    def load_folder(self, folder_path: str) -> None:
        """Ana Ders Klasörünü yükler; daha önce bir alt klasörde kalındıysa aynı kök altındaysa korur."""
        cleaned = (folder_path or "").strip()
        if not cleaned or not os.path.isdir(cleaned):
            self._root_folder = None
            self._current_folder = None
            self.file_list.clear()
            self.path_lbl.setText("Sabah ayarlarından bir Ders Klasörü seçilmemiş.")
            empty_item = QListWidgetItem("Klasör tanımlanmamış veya bulunamadı.")
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.file_list.addItem(empty_item)
            self.setFixedHeight(200)
            return

        new_root = Path(cleaned).resolve()
        if self._root_folder != new_root or self._current_folder is None:
            self._root_folder = new_root
            self._current_folder = new_root
        elif not self._is_within_root(self._current_folder):
            self._current_folder = new_root

        self._render_current_directory()

    def navigate_to_subfolder(self, target_dir: str | Path) -> None:
        """Alt klasöre (veya üst klasöre) geçiş yapar."""
        target = Path(target_dir).resolve()
        if self._is_within_root(target) and target.is_dir():
            self._current_folder = target
            self._render_current_directory()

    def _is_within_root(self, candidate: Path) -> bool:
        if self._root_folder is None:
            return False
        try:
            candidate.resolve().relative_to(self._root_folder.resolve())
            return True
        except ValueError:
            return False

    def _render_current_directory(self) -> None:
        self.file_list.clear()
        if self._root_folder is None or self._current_folder is None:
            return

        try:
            rel = self._current_folder.relative_to(self._root_folder)
            rel_str = "" if str(rel) == "." else f" / {str(rel).replace(os.sep, ' / ')}"
        except ValueError:
            rel_str = ""

        self.path_lbl.setText(f"📂 {self._root_folder.name}{rel_str}")

        row_count = 0
        # Eğer alt klasördeysek en üste "Üst Klasöre Dön (..)" öğesi ekle
        if self._current_folder != self._root_folder:
            parent_dir = self._current_folder.parent
            if self._is_within_root(parent_dir):
                up_item = QListWidgetItem("⬅️  .. (Üst Klasöre Dön)")
                up_item.setData(Qt.ItemDataRole.UserRole, ("dir", str(parent_dir)))
                up_item.setToolTip(str(parent_dir))
                self.file_list.addItem(up_item)
                row_count += 1

        dirs: list[Path] = []
        files: list[Path] = []
        try:
            for entry in sorted(self._current_folder.iterdir(), key=lambda p: p.name.lower()):
                if entry.name.startswith("."):
                    continue
                if entry.is_dir():
                    dirs.append(entry)
                elif entry.is_file():
                    files.append(entry)
        except OSError:
            pass

        for dpath in dirs:
            item = QListWidgetItem(f"📁  {dpath.name}")
            item.setData(Qt.ItemDataRole.UserRole, ("dir", str(dpath)))
            item.setToolTip(f"Klasör: {dpath}")
            self.file_list.addItem(item)
            row_count += 1

        for fpath in files:
            item = QListWidgetItem(f"📄  {fpath.name}")
            item.setData(Qt.ItemDataRole.UserRole, ("file", str(fpath)))
            item.setToolTip(str(fpath))
            self.file_list.addItem(item)
            row_count += 1

        if row_count == 0 or (len(dirs) == 0 and len(files) == 0):
            empty_item = QListWidgetItem("Bu klasörde alt klasör veya dosya yok.")
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.file_list.addItem(empty_item)
            row_count += 1

        self.setFixedHeight(min(440, max(230, 130 + row_count * 32)))

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, tuple) or len(payload) != 2:
            return
        kind, target_path = payload
        if kind == "dir":
            self.navigate_to_subfolder(target_path)
        elif kind == "file" and os.path.isfile(str(target_path)):
            self.close_with_fade()
            self.file_clicked.emit(str(target_path))


class CourseAndActivityPopover(BaseGlassPopover):
    """Üst çubuktaki Ders / Aktif Sayaç butonuna tıklanınca açılan ders seçimi ve uygulama süreleri paneli."""

    course_selected = Signal(str)  # course_code

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent, width=450, max_height=480)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(16, 14, 16, 14)
        root_layout.setSpacing(8)

        course_hdr = QLabel("Şu An Çalıştığınız Dersi Seçin")
        course_hdr.setStyleSheet("font-size: 14px; font-weight: 600; color: #F8FAFC;")
        root_layout.addWidget(course_hdr)

        course_sub = QLabel(
            "Sayaç yalnızca aktif etkileşim (fare, kaydırma, dokunma, klavye) varken ilerler; "
            "2 dakika hareketsizlikte otomatik duraklatılır."
        )
        course_sub.setStyleSheet(f"font-size: 11px; color: {TEXT_SECONDARY};")
        course_sub.setWordWrap(True)
        root_layout.addWidget(course_sub)

        self.course_list = QListWidget()
        self.course_list.setMinimumHeight(180)
        self.course_list.itemClicked.connect(self._on_course_item_clicked)
        root_layout.addWidget(self.course_list, 3)

        app_hdr = QLabel("Bugün Uygulamalarda Geçirilen Aktif Süre")
        app_hdr.setStyleSheet("font-size: 13px; font-weight: 600; color: #F8FAFC; margin-top: 4px;")
        root_layout.addWidget(app_hdr)

        self.app_usage_list = QListWidget()
        self.app_usage_list.setMinimumHeight(105)
        root_layout.addWidget(self.app_usage_list, 2)

        self.setFixedHeight(450)

    def refresh_data(
        self,
        courses: list[dict[str, Any]],
        active_course_code: str,
        course_stats: list[dict[str, Any]],
        app_stats: list[dict[str, Any]],
    ) -> None:
        seconds_by_course = {
            str(r["course_code"]): int(r.get("active_seconds") or 0) for r in course_stats
        }

        self.course_list.clear()
        for c in courses:
            code = str(c["code"])
            name = str(c["name"])
            sec = seconds_by_course.get(code, 0)
            dur_str = format_duration_human(sec) if sec > 0 else "0 sn"
            prefix = "● " if code == active_course_code else "○ "
            item_text = f"{prefix}{code} — {name}   ({dur_str})"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, code)
            if code == active_course_code:
                item.setSelected(True)
            self.course_list.addItem(item)

        self.app_usage_list.clear()
        if not app_stats:
            empty_item = QListWidgetItem("Henüz uygulama kullanım süresi kaydedilmedi.")
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.app_usage_list.addItem(empty_item)
        else:
            for a in app_stats:
                disp = str(a.get("display_name") or a.get("exe_name") or "Uygulama")
                sec = int(a.get("active_seconds") or 0)
                item = QListWidgetItem(f"🖥️  {disp}   •   {format_duration_human(sec)}")
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.app_usage_list.addItem(item)

    def _on_course_item_clicked(self, item: QListWidgetItem) -> None:
        code = item.data(Qt.ItemDataRole.UserRole)
        if code:
            self.close_with_fade()
            self.course_selected.emit(str(code))
