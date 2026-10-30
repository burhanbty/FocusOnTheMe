"""Tam ekran masaüstü arka plan örtüsü (DesktopBackdropWindow).

Özellikler:
- Düz siyah değil; çok koyu, sakin, animasyonsuz, yumuşak renk geçişli statik bir zemin sunar
  ki üstteki Liquid Glass çubuğun ve açılır cam panellerin yarı saydamlığı net biçimde hissedilsin.
- `WindowStaysOnTopHint` kullanılmaz; böylece izinli uygulamalar örtünün üstünde çalışırken
  Windows masaüstü ikonları ve duvar kağıdı örtünün altında gizli kalır.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QGuiApplication,
    QKeyEvent,
    QLinearGradient,
    QPainter,
    QPaintEvent,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget


class DesktopBackdropWindow(QWidget):
    """Windows masaüstünü örten statik, koyu yumuşak renk geçişli tam ekran pencere."""

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowTitle("Ders Kilidi Masaüstü")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._allow_close = False
        self._fit_to_primary_screen()

    def _fit_to_primary_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geom = screen.geometry()
            self.setGeometry(geom)

    def allow_closing(self, allow: bool = True) -> None:
        self._allow_close = allow

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()
        w = float(rect.width())
        h = float(rect.height())

        # Ana diyagonal koyu gece mavisi -> derin antrasit statik geçiş
        base_grad = QLinearGradient(0.0, 0.0, w, h)
        base_grad.setColorAt(0.0, QColor(11, 17, 30))   # #0B111E
        base_grad.setColorAt(0.45, QColor(15, 23, 38))  # #0F1726
        base_grad.setColorAt(1.0, QColor(9, 13, 22))    # #090D16
        painter.fillRect(rect, base_grad)

        # Üst çubuk bölgesinin arkasında cam efektini belirginleştiren sakin radyal ışık katmanı (statik)
        top_glow = QRadialGradient(QPointF(w * 0.5, h * 0.06), max(w, h) * 0.55)
        top_glow.setColorAt(0.0, QColor(36, 68, 108, 68))
        top_glow.setColorAt(0.45, QColor(24, 45, 76, 28))
        top_glow.setColorAt(1.0, QColor(10, 15, 26, 0))
        painter.fillRect(rect, top_glow)

        # Sol alt sakin derin ton katmanı
        bottom_glow = QRadialGradient(QPointF(w * 0.2, h * 0.85), max(w, h) * 0.45)
        bottom_glow.setColorAt(0.0, QColor(22, 48, 68, 42))
        bottom_glow.setColorAt(1.0, QColor(9, 13, 22, 0))
        painter.fillRect(rect, bottom_glow)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        # Alt+F4 veya Escape ile arka plan örtüsünün kapanmasını engelle
        event.ignore()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._allow_close:
            event.accept()
        else:
            event.ignore()
