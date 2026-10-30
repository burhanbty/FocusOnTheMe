"""Gün Sonu Tebrik, Ders/Uygulama Süre Dağılımı, Park Edilen Düşünceler ve İstatistik Ekranı."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.activity_tracker import format_duration_human
from app.ui.styles import (
    ACCENT_HEX,
    GLOBAL_STYLESHEET,
    TEXT_SECONDARY,
    apply_window_liquid_glass_effect,
    paint_liquid_glass_surface,
)


class SummaryScreenWindow(QWidget):
    """Tüm görevler tamamlandığında kısıtlar kalktıktan sonra gösterilen tebrik ve özet ekranı."""

    new_session_requested = Signal()

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowTitle("Ders Kilidi — Gün Tamamlandı")
        self.resize(820, 620)
        self.setMinimumSize(720, 520)
        self.setStyleSheet(GLOBAL_STYLESHEET)

        apply_window_liquid_glass_effect(self)
        self._build_ui()

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(28, 22, 28, 22)
        root_layout.setSpacing(14)

        title_lbl = QLabel("Tebrikler! Bugünün Tüm Görevleri Tamamlandı")
        title_lbl.setStyleSheet("font-size: 21px; font-weight: 700; color: #F8FAFC;")
        root_layout.addWidget(title_lbl)

        sub_lbl = QLabel("Tüm masaüstü, görev çubuğu ve Microsoft Edge kısıtları kaldırıldı.")
        sub_lbl.setStyleSheet(f"font-size: 13px; color: {ACCENT_HEX}; font-weight: 600;")
        root_layout.addWidget(sub_lbl)

        # İstatistik Kartları Satırı
        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)

        self.tasks_card_val = self._create_stat_card(cards_row, "Tamamlanan Görev", "0/0")
        self.duration_card_val = self._create_stat_card(cards_row, "Aktif Çalışma Süresi", "0 dk")
        self.blocked_card_val = self._create_stat_card(cards_row, "Kapatılan İzinsiz Uygulama", "0")
        self.streak_card_val = self._create_stat_card(cards_row, "Üst Üste Gün Serisi", "1 gün")

        root_layout.addLayout(cards_row)

        # Orta Bölüm: Yan Yana Ders Süreleri ve Uygulama Süreleri
        breakdown_row = QHBoxLayout()
        breakdown_row.setSpacing(14)

        course_col = QVBoxLayout()
        course_hdr = QLabel("Derslere Göre Aktif Çalışma Süresi:")
        course_hdr.setStyleSheet("font-size: 13px; font-weight: 600; color: #F1F5F9;")
        course_col.addWidget(course_hdr)
        self.course_stats_list = QListWidget()
        course_col.addWidget(self.course_stats_list, 1)
        breakdown_row.addLayout(course_col, 1)

        app_col = QVBoxLayout()
        app_hdr = QLabel("Hangi Uygulamada Ne Kadar Süre Geçirildi:")
        app_hdr.setStyleSheet("font-size: 13px; font-weight: 600; color: #F1F5F9;")
        app_col.addWidget(app_hdr)
        self.app_stats_list = QListWidget()
        app_col.addWidget(self.app_stats_list, 1)
        breakdown_row.addLayout(app_col, 1)

        root_layout.addLayout(breakdown_row, 2)

        # Alt Bölüm: Düşünce Park Alanı Notları
        thoughts_hdr = QLabel("Ders Sırasında Park Ettiğiniz Düşünceler (Ctrl+Alt+P):")
        thoughts_hdr.setStyleSheet("font-size: 13px; font-weight: 600; color: #F1F5F9;")
        root_layout.addWidget(thoughts_hdr)

        self.thoughts_list = QListWidget()
        self.thoughts_list.setMaximumHeight(130)
        root_layout.addWidget(self.thoughts_list, 1)

        # Alt Butonlar
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        reopen_setup_btn = QPushButton("Görev Planlama Ekranına Dön")
        reopen_setup_btn.clicked.connect(self.new_session_requested.emit)
        btn_row.addWidget(reopen_setup_btn)

        close_btn = QPushButton("Uygulamadan Çık")
        close_btn.setObjectName("PrimaryAccentButton")
        close_btn.setFixedWidth(170)
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        root_layout.addLayout(btn_row)

    def _create_stat_card(self, parent_layout: QHBoxLayout, label_text: str, initial_val: str) -> QLabel:
        card = QFrame()
        card.setStyleSheet(
            "QFrame {"
            "  background-color: rgba(255, 255, 255, 12);"
            "  border: 1px solid rgba(255, 255, 255, 34);"
            "  border-radius: 12px;"
            "}"
        )
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(14, 10, 14, 10)
        c_layout.setSpacing(4)

        val_lbl = QLabel(initial_val)
        val_lbl.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {ACCENT_HEX}; border: none; background: transparent;")
        lbl = QLabel(label_text)
        lbl.setStyleSheet(f"font-size: 12px; color: {TEXT_SECONDARY}; border: none; background: transparent;")
        lbl.setWordWrap(True)

        c_layout.addWidget(val_lbl)
        c_layout.addWidget(lbl)
        parent_layout.addWidget(card, 1)
        return val_lbl

    def load_summary(
        self,
        stats: dict[str, Any],
        thoughts: list[dict[str, Any]],
        course_stats: list[dict[str, Any]] | None = None,
        app_stats: list[dict[str, Any]] | None = None,
    ) -> None:
        comp = stats.get("completed_tasks", 0)
        tot = stats.get("total_tasks", 0)
        secs = int(stats.get("focus_seconds", 0))
        blocked = stats.get("blocked_app_count", 0)
        streak = stats.get("streak_days", 0)

        self.tasks_card_val.setText(f"{comp}/{tot}")
        self.duration_card_val.setText(format_duration_human(secs))
        self.blocked_card_val.setText(str(blocked))
        self.streak_card_val.setText(f"{streak} gün")

        self.course_stats_list.clear()
        c_list = course_stats or []
        if not c_list:
            empty_c = QListWidgetItem("Bugün için kayıtlı ders çalışma süresi yok.")
            empty_c.setFlags(Qt.ItemFlag.NoItemFlags)
            self.course_stats_list.addItem(empty_c)
        else:
            for c in c_list:
                code = str(c.get("course_code") or "")
                name = str(c.get("course_name") or code)
                c_sec = int(c.get("active_seconds") or 0)
                self.course_stats_list.addItem(
                    f"📚  {code} ({name})   —   {format_duration_human(c_sec)}"
                )

        self.app_stats_list.clear()
        a_list = app_stats or []
        if not a_list:
            empty_a = QListWidgetItem("Bugün için kayıtlı uygulama kullanım süresi yok.")
            empty_a.setFlags(Qt.ItemFlag.NoItemFlags)
            self.app_stats_list.addItem(empty_a)
        else:
            for a in a_list:
                disp = str(a.get("display_name") or a.get("exe_name") or "Uygulama")
                a_sec = int(a.get("active_seconds") or 0)
                self.app_stats_list.addItem(
                    f"🖥️  {disp}   —   {format_duration_human(a_sec)}"
                )

        self.thoughts_list.clear()
        if not thoughts:
            item = QListWidgetItem("Bu oturumda park edilmiş düşünce kaydı yok.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.thoughts_list.addItem(item)
        else:
            for t in thoughts:
                ts = str(t.get("created_at") or "")[-8:]
                content = str(t.get("content") or "")
                self.thoughts_list.addItem(f"[{ts}]  {content}")

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        paint_liquid_glass_surface(
            painter,
            QRectF(self.rect()),
            radius=14.0,
            bg_alpha_top=240,
            bg_alpha_bottom=230,
        )
