#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CallLog - יומן שיחות
שמירה והצגת היסטוריית שיחות
"""

import csv
import time
import datetime
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional
from PyQt6.QtCore import QObject, pyqtSignal as Signal

from app.core.safe_json_io import atomic_write_json, load_json


@dataclass
class CallLogEntry:
    number:    str
    name:      str
    direction: str          # incoming / outgoing / missed / rejected / blacklist
    start_time: float
    duration:  float = 0.0
    answered:  bool  = False

    @property
    def start_dt(self) -> datetime.datetime:
        return datetime.datetime.fromtimestamp(self.start_time)

    @property
    def display_date(self) -> str:
        return self.display_date_for(is_rtl=True)

    def display_date_for(self, is_rtl: bool) -> str:
        dt = self.start_dt
        today = datetime.date.today()
        if dt.date() == today:
            label = "היום" if is_rtl else "Today"
            return f"{label} {dt.strftime('%H:%M')}"
        if dt.date() == today - datetime.timedelta(days=1):
            label = "אתמול" if is_rtl else "Yesterday"
            return f"{label} {dt.strftime('%H:%M')}"
        return dt.strftime("%d/%m/%Y %H:%M")

    @property
    def display_duration(self) -> str:
        s = int(self.duration)
        if s == 0:
            return ""
        return f"{s//60:02d}:{s%60:02d}"

    @property
    def direction_icon(self) -> str:
        return {
            "incoming":  "📲",
            "outgoing":  "📞",
            "missed":    "📵",
            "rejected":  "🚫",
            "blacklist": "⛔",
        }.get(self.direction, "📞")

    @property
    def direction_label(self) -> str:
        return self.direction_label_for(is_rtl=True)

    def direction_label_for(self, is_rtl: bool) -> str:
        if is_rtl:
            return {
                "incoming":  "נכנסת",
                "outgoing":  "יוצאת",
                "missed":    "לא נענתה",
                "rejected":  "נדחתה",
                "blacklist": "רשימה שחורה",
            }.get(self.direction, self.direction)
        return {
            "incoming":  "Incoming",
            "outgoing":  "Outgoing",
            "missed":    "Missed",
            "rejected":  "Declined",
            "blacklist": "Blacklisted",
        }.get(self.direction, self.direction)


class CallLog(QObject):
    log_updated = Signal()

    def __init__(self, base_dir: str = None, parent=None):
        super().__init__(parent)
        import os
        self._path = Path(base_dir or os.path.join(
            os.path.expanduser("~"), "BluePhone")) / "call_log.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: list[CallLogEntry] = []
        self._blacklist: set[str] = set()
        self._load()

    def _load(self):
        data = load_json(str(self._path), {})
        entries = []
        for e in data.get("entries", []):
            try:
                entries.append(CallLogEntry(**e))
            except Exception:
                # רשומה בודדת פגומה (למשל משדה חסר בגרסה ישנה) לא
                # תגרום לאיבוד כל יומן השיחות — פשוט מדלגים עליה
                continue
        self._entries = entries
        self._blacklist = set(data.get("blacklist", []))

    def _save(self):
        atomic_write_json(str(self._path), {
            "entries":   [asdict(e) for e in self._entries],
            "blacklist": list(self._blacklist),
        })

    # ── API ──────────────────────────────────────────────

    def add(self, number: str, name: str, direction: str,
            duration: float = 0.0, answered: bool = False):
        if number in self._blacklist:
            direction = "blacklist"
        entry = CallLogEntry(
            number=number, name=name, direction=direction,
            start_time=time.time(), duration=duration, answered=answered)
        self._entries.insert(0, entry)
        # Keep last 500
        self._entries = self._entries[:500]
        self._save()
        self.log_updated.emit()

    def get_all(self) -> list:
        return list(self._entries)

    def get_filtered(self, direction: str = "") -> list:
        if not direction:
            return self.get_all()
        return [e for e in self._entries if e.direction == direction]

    def clear(self):
        self._entries.clear()
        self._save()
        self.log_updated.emit()

    # ── Blacklist ─────────────────────────────────────────

    def add_to_blacklist(self, number: str):
        self._blacklist.add(number)
        self._save()

    def remove_from_blacklist(self, number: str):
        self._blacklist.discard(number)
        self._save()

    def get_blacklist(self) -> list:
        return sorted(self._blacklist)

    def is_blacklisted(self, number: str) -> bool:
        return number in self._blacklist

    # ── Export ───────────────────────────────────────────

    def export_csv(self, file_path: str, direction: str = "",
                    is_rtl: bool = True) -> bool:
        """מייצא את יומן השיחות (מסונן לפי direction אם צויין) לקובץ CSV.
        מחזיר True בהצלחה, False בכישלון (לא זורק חריגה)."""
        entries = self.get_filtered(direction)
        headers = (
            ["שם", "מספר", "כיוון", "תאריך ושעה", "משך (שניות)", "נענתה"]
            if is_rtl else
            ["Name", "Number", "Direction", "Date & Time", "Duration (s)", "Answered"]
        )
        try:
            with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                for e in entries:
                    writer.writerow([
                        e.name,
                        e.number,
                        e.direction_label_for(is_rtl),
                        e.start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                        int(e.duration),
                        "כן" if is_rtl and e.answered else
                        ("Yes" if e.answered else ("לא" if is_rtl else "No")),
                    ])
            return True
        except Exception:
            return False
