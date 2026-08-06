#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
winrt_rfcomm — חיבור RFCOMM אמיתי ב-Windows דרך Windows Runtime (WinRT).

רקע טכני חשוב:
מודול ה-socket המובנה של פייתון (AF_BLUETOOTH + BTPROTO_RFCOMM) נתמך
היטב ב-Linux, אבל כמעט אף פעם לא עובד ב-Windows — הקבועים האלה או
שלא קיימים בכלל בבנייה של פייתון ל-Windows, או שפעולת ה-connect נכשלת
תמיד. זו הסיבה המרכזית לכך שהתוכנה תמיד נפלה למצב הדגמה.

המודול הזה מחליף את שכבת ההובלה (transport) בלבד: הוא פותח ומנהל
חיבור RFCOMM אמיתי דרך Windows.Devices.Bluetooth.Rfcomm ו-
Windows.Networking.Sockets.StreamSocket — ה-API הרשמי של Windows
לבלוטוס Classic, בדיוק כפי שדיבורית בלוטוס אמיתית הייתה משתמשת בו.

תלות: החבילה 'winsdk' (pip install winsdk) — עטיפת WinRT רשמית ומתוחזקת
עבור Python, ללא צורך ב-PowerShell/subprocess לשכבת הנתונים עצמה.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Optional, Callable

try:
    from winsdk.windows.devices.bluetooth import BluetoothDevice
    from winsdk.windows.devices.bluetooth.rfcomm import (
        RfcommDeviceService, RfcommServiceId,
    )
    from winsdk.windows.networking.sockets import StreamSocket
    from winsdk.windows.networking import HostName
    from winsdk.windows.storage.streams import DataReader, DataWriter, InputStreamOptions
    WINRT_AVAILABLE = True
except Exception:
    # winsdk not installed, or running on a non-Windows platform (e.g.
    # during development on Linux/CI) — real WinRT connections are simply
    # unavailable, and the caller should fall back to simulation mode.
    WINRT_AVAILABLE = False


class WinRTConnectionError(Exception):
    """שגיאה במהלך חיבור/תקשורת RFCOMM דרך WinRT, עם שלב מזוהה לאבחון."""

    def __init__(self, stage: str, message: str):
        super().__init__(f"[{stage}] {message}")
        self.stage = stage
        self.message = message


class WinRTRfcommConnection:
    """
    חיבור RFCOMM יחיד דרך WinRT, פועל בצורה סינכרונית מנקודת המבט של
    הקוד הקורא (מריץ asyncio באופן פנימי ב-thread ייעודי), כך שהוא יכול
    לשמש כתחליף ישיר ל-socket.socket הרגיל בשאר הקוד.
    """

    def __init__(self, service_uuid: str = "0000111f-0000-1000-8000-00805f9b34fb"):
        # ברירת המחדל: HFP Audio Gateway (הצד שהפלאפון חושף לדיבורית)
        self._service_uuid = service_uuid
        self._socket: Optional["StreamSocket"] = None
        self._writer: Optional["DataWriter"] = None
        self._reader: Optional["DataReader"] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._connected = False

    # ── internal event loop management ──────────────────────

    def _ensure_loop(self):
        if self._loop is not None:
            return
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._run_loop, daemon=True, name="WinRTRfcommLoop")
        self._loop_thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run(self, coro, timeout: float = 12.0):
        """הרץ coroutine בלופ הייעודי וחכה לתוצאה מה-thread הקורא."""
        self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    # ── connection lifecycle ─────────────────────────────────

    def connect(self, address: str) -> None:
        """
        מתחבר בפועל למכשיר בלוטוס לפי כתובת MAC (בפורמט 'AA:BB:CC:DD:EE:FF').
        זורק WinRTConnectionError עם שלב מזוהה אם משהו נכשל, כדי לאפשר
        אבחון מדויק (מכשיר לא נמצא / שירות לא נתמך / חיבור נדחה וכו').
        """
        if not WINRT_AVAILABLE:
            raise WinRTConnectionError(
                "import", "winsdk אינו מותקן או שהמערכת אינה Windows")
        self._run(self._connect_async(address))
        self._connected = True

    async def _connect_async(self, address: str):
        try:
            mac_int = int(address.replace(":", "").replace("-", ""), 16)
        except ValueError as e:
            raise WinRTConnectionError("address_parse", str(e))

        try:
            bt_device = await BluetoothDevice.from_bluetooth_address_async(mac_int)
        except Exception as e:
            raise WinRTConnectionError("device_lookup", str(e))
        if bt_device is None:
            raise WinRTConnectionError(
                "device_lookup",
                "המכשיר לא נמצא — ודא שהוא מותאם (paired) ובטווח בלוטוס")

        try:
            service_id = RfcommServiceId.from_uuid(self._service_uuid)
            services_result = await bt_device.get_rfcomm_services_for_id_async(service_id)
        except Exception as e:
            raise WinRTConnectionError("service_lookup", str(e))

        services = list(services_result.services) if services_result else []
        if not services:
            raise WinRTConnectionError(
                "service_lookup",
                "הפלאפון לא חשף שירות Hands-Free Audio Gateway — "
                "ייתכן שהוא לא תומך ב-HFP או שההתאמה (pairing) לא הושלמה כראוי")

        service = services[0]

        try:
            sock = StreamSocket()
            await sock.connect_async(
                service.connection_host_name, service.connection_service_name)
        except Exception as e:
            raise WinRTConnectionError("socket_connect", str(e))

        self._socket = sock
        self._writer = DataWriter(sock.output_stream)
        self._reader = DataReader(sock.input_stream)
        self._reader.input_stream_options = InputStreamOptions.PARTIAL

    # ── I/O ───────────────────────────────────────────────────

    def send(self, data: bytes) -> None:
        """שלח בייטים לפלאפון. זורק WinRTConnectionError בכישלון."""
        if not self._connected or self._writer is None:
            raise WinRTConnectionError("send", "אין חיבור פעיל")
        try:
            self._run(self._send_async(data), timeout=8.0)
        except WinRTConnectionError:
            raise
        except Exception as e:
            raise WinRTConnectionError("send", str(e))

    async def _send_async(self, data: bytes):
        self._writer.write_bytes(data)
        await self._writer.store_async()

    def recv(self, max_bytes: int = 256, timeout: float = 1.0) -> bytes:
        """
        קורא עד max_bytes בייטים, עם timeout. מחזיר b'' אם אין נתונים
        זמינים בתוך הזמן שהוקצה (מקביל להתנהגות socket.timeout).
        """
        if not self._connected or self._reader is None:
            raise WinRTConnectionError("recv", "אין חיבור פעיל")
        try:
            return self._run(self._recv_async(max_bytes), timeout=timeout + 2.0)
        except asyncio.TimeoutError:
            return b""
        except WinRTConnectionError:
            raise
        except Exception as e:
            raise WinRTConnectionError("recv", str(e))

    async def _recv_async(self, max_bytes: int) -> bytes:
        try:
            loaded = await asyncio.wait_for(
                self._reader.load_async(max_bytes), timeout=1.0)
        except asyncio.TimeoutError:
            return b""
        if loaded == 0:
            return b""
        buf = bytearray(loaded)
        self._reader.read_bytes(buf)
        return bytes(buf)

    def close(self) -> None:
        self._connected = False
        try:
            if self._socket is not None:
                self._socket.close()
        except Exception:
            pass
        self._socket = None
        self._writer = None
        self._reader = None
        if self._loop is not None:
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception:
                pass

    @property
    def is_connected(self) -> bool:
        return self._connected
