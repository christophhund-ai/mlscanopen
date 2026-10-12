"""Minimal CANopen SDO client (expedited + segmented upload)."""

from __future__ import annotations

import struct
import threading
import time
from typing import Any

import can

ABORT = {
    0x05040000: "SDO protocol timed out",
    0x05040001: "Client/server command specifier invalid",
    0x06010000: "Unsupported access",
    0x06010001: "Attempt to read a write-only object",
    0x06010002: "Attempt to write a read-only object",
    0x06020000: "Object does not exist",
    0x06090011: "Sub-index does not exist",
    0x08000000: "General error",
}


class SdoError(RuntimeError):
    pass


def encode_value(dtype: str, value: Any) -> bytes:
    if dtype == "STRING":
        return str(value).encode("ascii", errors="replace") + b"\x00"
    ival = int(float(value)) if not isinstance(value, int) else int(value)
    if dtype == "BOOL":
        return bytes([1 if ival else 0])
    fmts = {
        "UINT8": "<B",
        "INT8": "<b",
        "UINT16": "<H",
        "INT16": "<h",
        "UINT32": "<I",
        "INT32": "<i",
    }
    if dtype not in fmts:
        raise SdoError(f"Unbekannter Datentyp {dtype}")
    return struct.pack(fmts[dtype], ival)


def decode_value(dtype: str, data: bytes) -> Any:
    if dtype == "STRING":
        return data.split(b"\x00", 1)[0].decode("ascii", errors="replace")
    need = {"BOOL": 1, "UINT8": 1, "INT8": 1, "UINT16": 2, "INT16": 2, "UINT32": 4, "INT32": 4}[dtype]
    data = (data + b"\x00" * need)[:need]
    if dtype == "BOOL":
        return 1 if data[0] else 0
    fmts = {
        "UINT8": "<B",
        "INT8": "<b",
        "UINT16": "<H",
        "INT16": "<h",
        "UINT32": "<I",
        "INT32": "<i",
    }
    return struct.unpack(fmts[dtype], data)[0]


def format_display(dtype: str, value: Any) -> str:
    if dtype == "STRING":
        return str(value)
    if dtype in ("UINT32", "UINT16", "UINT8") and isinstance(value, int):
        return f"{value} (0x{value:X})"
    return str(value)


class CanSdoClient:
    def __init__(self, bus: can.BusABC, node_id: int, timeout: float = 0.4, rx_queue: Any | None = None) -> None:
        self.bus = bus
        self.node_id = node_id
        self.timeout = timeout
        self._lock = threading.Lock()
        self.tx_id = 0x600 + node_id
        self.rx_id = 0x580 + node_id
        self.rx_queue = rx_queue

    def nmt(self, command: int, target: int | None = None) -> None:
        node = self.node_id if target is None else target
        self.bus.send(can.Message(arbitration_id=0, data=bytes([command & 0xFF, node & 0xFF]), is_extended_id=False))

    def read_raw(self, index: int, sub: int) -> bytes:
        with self._lock:
            req = bytes([0x40, index & 0xFF, (index >> 8) & 0xFF, sub & 0xFF, 0, 0, 0, 0])
            self._flush()
            self.bus.send(can.Message(arbitration_id=self.tx_id, data=req, is_extended_id=False))
            msg = self._recv()
            cs = msg.data[0]
            if cs == 0x80:
                abort = struct.unpack("<I", bytes(msg.data[4:8]))[0]
                raise SdoError(ABORT.get(abort, f"SDO abort 0x{abort:08X}"))
            if (cs & 0xE0) != 0x40:
                raise SdoError(f"Unerwartete SDO-Antwort 0x{cs:02X}")
            if cs & 0x02:  # expedited
                n = (cs >> 2) & 0x03
                size = 4 - n if cs & 0x01 else 4
                return bytes(msg.data[4 : 4 + size])
            # segmented
            size = struct.unpack("<I", bytes(msg.data[4:8]))[0] if cs & 0x01 else 0
            toggle = 0
            chunks = bytearray()
            while True:
                ack = bytes([0x60 | (toggle << 4), index & 0xFF, (index >> 8) & 0xFF, sub, 0, 0, 0, 0])
                self.bus.send(can.Message(arbitration_id=self.tx_id, data=ack, is_extended_id=False))
                seg = self._recv()
                scs = seg.data[0]
                if scs == 0x80:
                    abort = struct.unpack("<I", bytes(seg.data[4:8]))[0]
                    raise SdoError(ABORT.get(abort, f"SDO abort 0x{abort:08X}"))
                n = (scs >> 1) & 0x07
                payload = bytes(seg.data[1 : 8 - n]) if n else bytes(seg.data[1:8])
                chunks.extend(payload)
                last = bool(scs & 0x01)
                toggle ^= 1
                if last:
                    break
                if size and len(chunks) >= size:
                    break
            return bytes(chunks[:size] if size else chunks)

    def write_raw(self, index: int, sub: int, data: bytes) -> None:
        if len(data) > 4:
            raise SdoError("Segmentiertes SDO-Schreiben >4 Byte ist nicht implementiert")
        n = 4 - len(data)
        cs = 0x23 | (n << 2)  # expedited, size indicated
        payload = data.ljust(4, b"\x00")
        req = bytes([cs, index & 0xFF, (index >> 8) & 0xFF, sub & 0xFF]) + payload
        with self._lock:
            self._flush()
            self.bus.send(can.Message(arbitration_id=self.tx_id, data=req, is_extended_id=False))
            msg = self._recv()
            if msg.data[0] == 0x80:
                abort = struct.unpack("<I", bytes(msg.data[4:8]))[0]
                raise SdoError(ABORT.get(abort, f"SDO abort 0x{abort:08X}"))
            if msg.data[0] != 0x60:
                raise SdoError(f"Unerwartete SDO-Schreibantwort 0x{msg.data[0]:02X}")

    def _flush(self) -> None:
        if self.rx_queue is not None:
            while True:
                try:
                    self.rx_queue.get_nowait()
                except Exception:
                    break
            return
        deadline = time.time() + 0.02
        while time.time() < deadline:
            msg = self.bus.recv(timeout=0.001)
            if msg is None:
                break

    def _recv(self) -> can.Message:
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            if self.rx_queue is not None:
                remaining = max(0.0, deadline - time.time())
                try:
                    msg = self.rx_queue.get(timeout=min(0.05, remaining or 0.01))
                except Exception:
                    continue
            else:
                msg = self.bus.recv(timeout=0.05)
            if msg is None:
                continue
            if msg.arbitration_id == self.rx_id and msg.data:
                return msg
        raise SdoError("SDO-Timeout – Node-ID, Bitrate und Bus prüfen")
