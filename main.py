#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""פלאפון כשר חכם v1.0 — Smart Kosher Phone"""

import sys, os
import traceback
import datetime
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QIcon

from app.bluetooth_manager import BluetoothManager
from app.theme_manager import ThemeManager
from app.core.language_manager import LanguageManager
from app.pages.settings_page_main import SettingsPageMain

APP_VERSION = "1.0"
ICON_PATH = os.path.join(os.path.dirname(__file__), "app", "resources", "icon_256.png")

CRASH_LOG_DIR = os.path.join(os.path.expanduser("~"), "BluePhone")
CRASH_LOG_PATH = os.path.join(CRASH_LOG_DIR, "crash.log")


def _log_crash(exc_type, exc_value, exc_tb):
    """כאשר התוכנה רצה כ-EXE ללא חלון קונסולה, חריגה שלא נתפסת גורמת
    לתוכנה להיסגר בשקט לחלוטין ללא כל הודעה למשתמש או למפתח. הפונקציה
    הזו תופסת כל חריגה כזו, שומרת אותה לקובץ לוג קריא, ומנסה גם להציג
    הודעה למשתמש אם Qt עדיין זמין."""
    try:
        os.makedirs(CRASH_LOG_DIR, exist_ok=True)
        with open(CRASH_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n===== {datetime.datetime.now().isoformat()} =====\n")
            traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
    except Exception:
        pass

    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance() is not None:
            QMessageBox.critical(
                None, "Smart Kosher Phone — שגיאה קריטית",
                "אירעה שגיאה בלתי צפויה והתוכנה תיסגר.\n"
                f"פרטי השגיאה נשמרו לקובץ:\n{CRASH_LOG_PATH}\n\n"
                f"{exc_type.__name__}: {exc_value}")
    except Exception:
        pass

    # Also print to stderr in case a console is attached (dev runs).
    traceback.print_exception(exc_type, exc_value, exc_tb)


def main():
    sys.excepthook = _log_crash
    app = QApplication(sys.argv)
    app.setOrganizationName("SmartKosherPhone")
    app.setQuitOnLastWindowClosed(False)

    icon = QIcon(ICON_PATH)
    if not icon.isNull():
        app.setWindowIcon(icon)

    # ── Language — load saved, apply immediately ──
    lang_mgr = LanguageManager()
    lang = lang_mgr.lang

    app.setLayoutDirection(lang_mgr.direction)
    app.setApplicationName(lang_mgr.app_name)
    app.setApplicationVersion(APP_VERSION)
    app.setApplicationDisplayName(f"{lang_mgr.app_name} v{APP_VERSION}")

    font = QFont("Segoe UI", 10)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)

    # Theme — light by default
    theme_mgr = ThemeManager(app)
    theme_mgr.apply("light")

    # Password check
    if not SettingsPageMain.verify_password_at_startup():
        sys.exit(0)

    try:
        from app.main_window import MainWindow
        from app.tray_manager import TrayManager

        bt = BluetoothManager(language_manager=lang_mgr)
        win = MainWindow(bt, theme_mgr, lang_mgr)
        tray = TrayManager(win, bt, app, language_manager=lang_mgr)

        win.show()
    except Exception:
        _log_crash(*sys.exc_info())
        sys.exit(1)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
