"""Global kısayol (Ctrl+Alt+P) ve klavye engelleme (Win tuşu, Alt+F4 vb. best-effort) modülü."""

from __future__ import annotations

from typing import Any, Callable

import keyboard


class InputBlocker:
    """Ders modunda kaçış kısayollarını bastıran ve Ctrl+Alt+P kısayolunu dinleyen sınıf."""

    def __init__(self, on_thought_shortcut: Callable[[], None] | None = None) -> None:
        self.on_thought_shortcut = on_thought_shortcut
        self._active = False
        self._hooks: list[Any] = []

    def start(self) -> bool:
        if self._active:
            return True
        try:
            # Sol ve Sağ Windows tuşlarını bastır (Başlat menüsü açılmasını engeller)
            for key_name in ("left windows", "right windows"):
                try:
                    h = keyboard.block_key(key_name)
                    self._hooks.append(h)
                except Exception:
                    pass

            # Kaçış kombinasyonlarını bastır (best-effort)
            for combo in ("alt+f4", "ctrl+shift+esc", "win+r", "win+d", "win+e", "win+tab"):
                try:
                    h = keyboard.add_hotkey(combo, lambda: None, suppress=True)
                    self._hooks.append(h)
                except Exception:
                    pass

            # Düşünce Park Alanı global kısayolu: Ctrl+Alt+P
            if self.on_thought_shortcut is not None:
                try:
                    h = keyboard.add_hotkey(
                        "ctrl+alt+p",
                        self._trigger_thought_shortcut,
                        suppress=False,
                    )
                    self._hooks.append(h)
                except Exception:
                    pass

            self._active = True
            return True
        except Exception:
            return False

    def _trigger_thought_shortcut(self) -> None:
        if self.on_thought_shortcut is not None:
            try:
                self.on_thought_shortcut()
            except Exception:
                pass

    def stop(self) -> None:
        if not self._active and not self._hooks:
            return
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        self._hooks.clear()
        self._active = False
