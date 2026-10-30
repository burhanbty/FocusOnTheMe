"""macOS menü çubuğu tarzı Liquid Glass Üst Çubuk (TopBarWindow).

Düzen ve Özellikler:
- Konum ve Boyut: x=8, y=8, genişlik=ekran_genişliği-16, yükseklik=44 px.
- Köşe yuvarlaklığı: 14 px, ince açık kenarlık (rgba 255,255,255,0.18), her zaman üstte.
- Sol: İzinli uygulama ikonları (tıklanınca açılır) + TEST_MODE=True ise "TEST MODU" rozeti.
- Orta: Aktif görev ("CENG201: 20 soru çöz • 1/3", tıklanınca TaskPopover açılır) +
        Aktif Ders Seçici ve Çalışma Sayacı ("📚 CENG201 • ⏱ 00:14:25", tıklanınca CourseAndActivityPopover açılır).
- Sağ: Saat, "Düşünce Park Et" butonu, "Ders Klasörü" butonu, "Acil Çıkış" butonu.
"""

from __future__ import annotations

from datetime import datetime
import os
from typing import Any

from PySide6.QtCore import QFileInfo, QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QGuiApplication,
    QIcon,
    QKeyEvent,
    QPainter,
    QPaintEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QFileIconProvider,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyle,
    QWidget,
)

from app import config
from app.core.activity_tracker import format_duration_hms
from app.ui.styles import (
    ACCENT_HEX,
    GLOBAL_STYLESHEET,
    apply_window_liquid_glass_effect,
    paint_liquid_glass_surface,
)
from app.ui.task_popover import CourseAndActivityPopover, StudyFolderPopover, TaskPopover


class TopBarWindow(QWidget):
    """Ekranın üst kısmında her zaman üstte duran Liquid Glass kontrol çubuğu."""

    app_launch_requested = Signal(str)          # exe_path
    task_toggled = Signal(int, bool)            # (task_id, completed)
    course_changed = Signal(str)                # course_code
    course_popover_opening = Signal()
    thought_parking_requested = Signal()
    study_file_open_requested = Signal(str)     # file_path
    emergency_exit_requested = Signal()

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowTitle("Ders Kilidi Üst Çubuk")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(GLOBAL_STYLESHEET)

        self._allow_close = False
        self._tasks: list[dict[str, Any]] = []
        self._study_folder: str = ""
        self._active_course_code: str = "CENG101"
        self._courses: list[dict[str, Any]] = []
        self._course_stats: list[dict[str, Any]] = []
        self._app_stats: list[dict[str, Any]] = []
        self._icon_provider = QFileIconProvider()

        self._position_bar()
        self.glass_mode = apply_window_liquid_glass_effect(self)

        # Popover panelleri
        self.task_popover = TaskPopover(self)
        self.task_popover.task_toggled.connect(self.task_toggled.emit)

        self.folder_popover = StudyFolderPopover(self)
        self.folder_popover.file_clicked.connect(self.study_file_open_requested.emit)

        self.course_popover = CourseAndActivityPopover(self)
        self.course_popover.course_selected.connect(self.course_changed.emit)

        self._build_ui()

        # Saat güncelleyici
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)
        self._update_clock()

    def _position_bar(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            sgeom = screen.geometry()
            sw = sgeom.width()
            sx = sgeom.x()
            sy = sgeom.y()
        else:
            sw = 1920
            sx = 0
            sy = 0

        bar_x = sx + config.TOP_BAR_MARGIN
        bar_y = sy + config.TOP_BAR_MARGIN
        bar_w = max(640, sw - (config.TOP_BAR_MARGIN * 2))
        bar_h = config.TOP_BAR_HEIGHT
        self.setGeometry(bar_x, bar_y, bar_w, bar_h)
        self.setFixedHeight(bar_h)

    def _build_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(12, 4, 12, 4)
        main_layout.setSpacing(8)

        # ------------------------------------------------------------------
        # SOL BÖLÜM: TEST MODU etiketi (TEST_MODE=True ise) + İzinli Uygulama İkonları
        # ------------------------------------------------------------------
        self.left_container = QWidget()
        self.left_container.setStyleSheet("background: transparent;")
        self.left_layout = QHBoxLayout(self.left_container)
        self.left_layout.setContentsMargins(0, 0, 0, 0)
        self.left_layout.setSpacing(6)

        self.test_mode_badge = QLabel("TEST MODU")
        self.test_mode_badge.setStyleSheet(
            "QLabel {"
            "  background-color: rgba(245, 158, 11, 45);"
            "  border: 1px solid rgba(245, 158, 11, 140);"
            "  border-radius: 7px;"
            "  padding: 2px 8px;"
            "  color: #FDE68A;"
            "  font-size: 11px;"
            "  font-weight: 700;"
            "  letter-spacing: 0.4px;"
            "}"
        )
        self.test_mode_badge.setVisible(bool(config.TEST_MODE))
        self.left_layout.addWidget(self.test_mode_badge)

        self.apps_container = QWidget()
        self.apps_container.setStyleSheet("background: transparent;")
        self.apps_layout = QHBoxLayout(self.apps_container)
        self.apps_layout.setContentsMargins(0, 0, 0, 0)
        self.apps_layout.setSpacing(5)
        self.left_layout.addWidget(self.apps_container)

        main_layout.addWidget(self.left_container, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        main_layout.addStretch(1)

        # ------------------------------------------------------------------
        # ORTA BÖLÜM: Şu Anki Görev ("2/5") + Aktif Ders Seçici & Canlı Çalışma Sayacı
        # ------------------------------------------------------------------
        center_container = QWidget()
        center_container.setStyleSheet("background: transparent;")
        center_layout = QHBoxLayout(center_container)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(8)

        self.center_task_btn = QPushButton("Görev yükleniyor...  0/0")
        self.center_task_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.center_task_btn.setFixedHeight(32)
        self.center_task_btn.setMinimumWidth(240)
        self.center_task_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: rgba(255, 255, 255, 14);"
            f"  border: 1px solid rgba(255, 255, 255, 38);"
            f"  border-radius: 10px;"
            f"  padding: 4px 14px;"
            f"  color: #F8FAFC;"
            f"  font-size: 13px;"
            f"  font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background-color: rgba(56, 189, 248, 30);"
            f"  border: 1px solid {ACCENT_HEX};"
            f"}}"
        )
        self.center_task_btn.clicked.connect(self.toggle_task_popover)
        center_layout.addWidget(self.center_task_btn)

        self.course_timer_btn = QPushButton("📚 CENG101  •  ⏱ 00:00:00")
        self.course_timer_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.course_timer_btn.setFixedHeight(32)
        self.course_timer_btn.setToolTip(
            "Şu an çalıştığınız dersi seçmek ve uygulama sürelerini görmek için tıklayın.\n"
            "2 dakika hareketsizlikte sayaç otomatik duraklatılır."
        )
        self._apply_course_timer_style(is_active=True)
        self.course_timer_btn.clicked.connect(self.toggle_course_popover)
        center_layout.addWidget(self.course_timer_btn)

        main_layout.addWidget(center_container, 0, Qt.AlignmentFlag.AlignCenter)
        main_layout.addStretch(1)

        # ------------------------------------------------------------------
        # SAĞ BÖLÜM: Saat, "Düşünce Park Et", "Ders Klasörü", "Acil Çıkış"
        # ------------------------------------------------------------------
        self.right_container = QWidget()
        self.right_container.setStyleSheet("background: transparent;")
        right_layout = QHBoxLayout(self.right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        self.clock_lbl = QLabel("00:00")
        self.clock_lbl.setStyleSheet(
            "font-size: 13px; font-weight: 600; color: #E2E8F0; padding: 0 6px;"
        )
        right_layout.addWidget(self.clock_lbl)

        self.thought_btn = QPushButton("Düşünce Park Et")
        self.thought_btn.setToolTip("Düşünce Park Alanı (Ctrl+Alt+P)")
        self.thought_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.thought_btn.setFixedHeight(30)
        self.thought_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: rgba(255, 255, 255, 14);"
            "  border: 1px solid rgba(255, 255, 255, 36);"
            "  border-radius: 8px;"
            "  padding: 3px 10px;"
            "  font-size: 12px;"
            "}"
            "QPushButton:hover {"
            "  background-color: rgba(255, 255, 255, 26);"
            "}"
        )
        self.thought_btn.clicked.connect(self.thought_parking_requested.emit)
        right_layout.addWidget(self.thought_btn)

        self.study_folder_btn = QPushButton("Ders Klasörü")
        self.study_folder_btn.setToolTip("Seçili ders klasöründeki alt klasörleri ve dosyaları listele")
        self.study_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.study_folder_btn.setFixedHeight(30)
        self.study_folder_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: rgba(255, 255, 255, 14);"
            "  border: 1px solid rgba(255, 255, 255, 36);"
            "  border-radius: 8px;"
            "  padding: 3px 10px;"
            "  font-size: 12px;"
            "}"
            "QPushButton:hover {"
            "  background-color: rgba(255, 255, 255, 26);"
            "}"
        )
        self.study_folder_btn.clicked.connect(self.toggle_study_folder_popover)
        right_layout.addWidget(self.study_folder_btn)

        self.emergency_btn = QPushButton("Acil Çıkış")
        self.emergency_btn.setObjectName("DangerButton")
        self.emergency_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.emergency_btn.setFixedHeight(30)
        self.emergency_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: rgba(248, 113, 113, 24);"
            "  border: 1px solid rgba(248, 113, 113, 85);"
            "  border-radius: 8px;"
            "  padding: 3px 10px;"
            "  color: #FECACA;"
            "  font-size: 12px;"
            "  font-weight: 600;"
            "}"
            "QPushButton:hover {"
            "  background-color: rgba(248, 113, 113, 45);"
            "}"
        )
        self.emergency_btn.clicked.connect(self.emergency_exit_requested.emit)
        right_layout.addWidget(self.emergency_btn)

        main_layout.addWidget(self.right_container, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def _apply_course_timer_style(self, is_active: bool) -> None:
        if is_active:
            self.course_timer_btn.setStyleSheet(
                f"QPushButton {{"
                f"  background-color: rgba(56, 189, 248, 22);"
                f"  border: 1px solid rgba(56, 189, 248, 115);"
                f"  border-radius: 10px;"
                f"  padding: 4px 12px;"
                f"  color: #E0F2FE;"
                f"  font-size: 12px;"
                f"  font-weight: 600;"
                f"}}"
                f"QPushButton:hover {{"
                f"  background-color: rgba(56, 189, 248, 38);"
                f"  border: 1px solid {ACCENT_HEX};"
                f"}}"
            )
        else:
            self.course_timer_btn.setStyleSheet(
                "QPushButton {"
                "  background-color: rgba(245, 158, 11, 20);"
                "  border: 1px solid rgba(245, 158, 11, 95);"
                "  border-radius: 10px;"
                "  padding: 4px 12px;"
                "  color: #FDE68A;"
                "  font-size: 12px;"
                "  font-weight: 600;"
                "}"
                "QPushButton:hover {"
                "  background-color: rgba(245, 158, 11, 35);"
                "}"
            )

    def update_course_timer_display(
        self,
        course_code: str,
        active_seconds: int,
        is_actively_working: bool,
        courses: list[dict[str, Any]] | None = None,
        course_stats: list[dict[str, Any]] | None = None,
        app_stats: list[dict[str, Any]] | None = None,
    ) -> None:
        """Üst çubuktaki aktif ders ve çalışma sayacını günceller."""
        self._active_course_code = (course_code or "CENG101").strip()
        if courses is not None:
            self._courses = courses
        if course_stats is not None:
            self._course_stats = course_stats
        if app_stats is not None:
            self._app_stats = app_stats

        hms = format_duration_hms(active_seconds)
        if is_actively_working:
            self.course_timer_btn.setText(f"📚 {self._active_course_code} ▾  •  ⏱ {hms}")
        else:
            self.course_timer_btn.setText(f"📚 {self._active_course_code} ▾  •  ⏸ {hms} (Boşta)")

        self._apply_course_timer_style(is_active=is_actively_working)
        self._update_clock()

        if self.course_popover.isVisible():
            self.course_popover.refresh_data(
                courses=self._courses,
                active_course_code=self._active_course_code,
                course_stats=self._course_stats,
                app_stats=self._app_stats,
            )
        self.update()

    def refresh_test_mode_badge(self) -> None:
        self.test_mode_badge.setVisible(bool(config.TEST_MODE))

    def set_allowed_apps(self, apps: list[dict[str, Any]]) -> None:
        """Sol bölümdeki izinli uygulama ikon butonlarını günceller."""
        while self.apps_layout.count():
            item = self.apps_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        for app in apps:
            if not app.get("enabled", 1):
                continue
            name = str(app.get("name") or "Uygulama").strip()
            exe_path = str(app.get("exe_path") or "").strip()
            if not exe_path:
                continue

            btn = QPushButton()
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(f"{name}\n({exe_path})")
            btn.setFixedHeight(30)

            icon = QIcon()
            if os.path.exists(exe_path):
                icon = self._icon_provider.icon(QFileInfo(exe_path))
            if icon.isNull():
                icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DesktopIcon)

            btn.setIcon(icon)
            btn.setIconSize(QSize(18, 18))
            short_label = name if len(name) <= 14 else name[:12] + "…"
            btn.setText(f" {short_label}")
            btn.setStyleSheet(
                "QPushButton {"
                "  background-color: rgba(255, 255, 255, 13);"
                "  border: 1px solid rgba(255, 255, 255, 32);"
                "  border-radius: 8px;"
                "  padding: 2px 9px;"
                "  font-size: 12px;"
                "  color: #F1F5F9;"
                "}"
                "QPushButton:hover {"
                f"  background-color: rgba(56, 189, 248, 28);"
                f"  border: 1px solid {ACCENT_HEX};"
                "}"
            )
            btn.clicked.connect(lambda _=False, path=exe_path: self.app_launch_requested.emit(path))
            self.apps_layout.addWidget(btn)

    def set_tasks(self, tasks: list[dict[str, Any]]) -> None:
        """Orta bölümdeki aktif görev metnini, ilerleme sayacını ve açılır paneli günceller."""
        self._tasks = list(tasks)
        self.task_popover.set_tasks(self._tasks)

        total = len(self._tasks)
        completed = sum(1 for t in self._tasks if t.get("completed"))
        active_task = next((t for t in self._tasks if not t.get("completed")), None)

        if total == 0:
            self.center_task_btn.setText("Görev yok  0/0")
            return

        if active_task is not None:
            subj = str(active_task.get("subject") or "").strip()
            title = str(active_task.get("title") or "").strip()
            full_text = f"{subj}: {title}" if subj else title
            if len(full_text) > 36:
                full_text = full_text[:33] + "..."
            self.center_task_btn.setText(f"{full_text}   •   {completed}/{total}")
        else:
            self.center_task_btn.setText(f"Tüm görevler tamamlandı   •   {completed}/{total}")

    def set_study_folder(self, folder_path: str) -> None:
        self._study_folder = (folder_path or "").strip()

    def toggle_task_popover(self) -> None:
        if self.task_popover.isVisible():
            self.task_popover.close_with_fade()
            return
        self.task_popover.set_tasks(self._tasks)
        btn_global = self.center_task_btn.mapToGlobal(QPoint(0, self.center_task_btn.height() + 8))
        pop_x = btn_global.x() + (self.center_task_btn.width() - self.task_popover.width()) // 2
        pop_y = self.y() + self.height() + 6
        self.task_popover.show_at(QPoint(max(8, pop_x), pop_y))

    def toggle_course_popover(self) -> None:
        if self.course_popover.isVisible():
            self.course_popover.close_with_fade()
            return
        self.course_popover_opening.emit()
        self.course_popover.refresh_data(
            courses=self._courses,
            active_course_code=self._active_course_code,
            course_stats=self._course_stats,
            app_stats=self._app_stats,
        )
        btn_global = self.course_timer_btn.mapToGlobal(QPoint(0, self.course_timer_btn.height() + 8))
        pop_x = btn_global.x() + (self.course_timer_btn.width() - self.course_popover.width()) // 2
        pop_y = self.y() + self.height() + 6
        self.course_popover.show_at(QPoint(max(8, pop_x), pop_y))

    def toggle_study_folder_popover(self) -> None:
        if self.folder_popover.isVisible():
            self.folder_popover.close_with_fade()
            return
        self.folder_popover.load_folder(self._study_folder)
        btn_global = self.study_folder_btn.mapToGlobal(QPoint(0, self.study_folder_btn.height() + 8))
        screen = QGuiApplication.primaryScreen()
        max_x = (screen.geometry().width() - self.folder_popover.width() - 8) if screen else 1500
        pop_x = min(max_x, max(8, btn_global.x() - self.folder_popover.width() // 2))
        pop_y = self.y() + self.height() + 6
        self.folder_popover.show_at(QPoint(pop_x, pop_y))

    def _update_clock(self) -> None:
        new_time = datetime.now().strftime("%H:%M")
        if self.clock_lbl.text() != new_time:
            self.clock_lbl.setText(new_time)
            self.clock_lbl.update()
            self.update()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._update_clock()
        if not self._clock_timer.isActive():
            self._clock_timer.start(1000)

    def allow_closing(self, allow: bool = True) -> None:
        self._allow_close = allow

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        paint_liquid_glass_surface(
            painter,
            QRectF(self.rect()),
            radius=float(config.TOP_BAR_RADIUS),
            bg_alpha_top=208,
            bg_alpha_bottom=190,
        )

    def keyPressEvent(self, event: QKeyEvent) -> None:
        event.ignore()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._allow_close:
            self._clock_timer.stop()
            event.accept()
        else:
            event.ignore()
