#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
safe_json_io — קריאה/כתיבה בטוחה של קבצי JSON.

התוכנה שומרת כמה קבצי מצב (יומן שיחות, מכשירים מוכרים, הגדרות תא קולי
ועוד) בקבצי JSON תחת תיקיית המשתמש. כתיבה "רגילה" (open().write) יכולה
להשאיר קובץ חצי-כתוב/פגום אם התוכנה קורסת או נסגרת באמצע הכתיבה —
מה שגורם לאובדן נתונים בהפעלה הבאה. המודול הזה פותר זאת:

* atomic_write_json  — כותב לקובץ זמני באותה תיקייה ואז מחליף (os.replace)
  את הקובץ המקורי באופן אטומי, כך שלעולם לא נשאר קובץ חצי-כתוב.
* load_json           — טוען JSON בבטחה; אם הקובץ פגום/חסר, שומר גיבוי
  של הקובץ הפגום (כדי לא לאבד מידע לצמיתות) ומחזיר ברירת מחדל.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from typing import Any


def atomic_write_json(path: str, data: Any, *, indent: int = 2) -> bool:
    """כותב JSON לקובץ באופן אטומי. מחזיר True בהצלחה, False בכישלון (לא זורק)."""
    try:
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(
            prefix=".tmp_", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=indent)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        finally:
            # If replace succeeded tmp_path no longer exists; if it failed,
            # make sure we don't leave a stray temp file behind.
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        return True
    except Exception:
        return False


def load_json(path: str, default: Any = None) -> Any:
    """טוען JSON בבטחה. אם הקובץ חסר/פגום, מגבה אותו (אם אפשר) ומחזיר default."""
    if default is None:
        default = {}
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        _backup_corrupt_file(path)
        return default


def _backup_corrupt_file(path: str) -> None:
    """שומר עותק של קובץ פגום עם סיומת .corrupt, כדי לאפשר שחזור ידני."""
    try:
        backup_path = path + ".corrupt"
        shutil.copyfile(path, backup_path)
    except Exception:
        pass
