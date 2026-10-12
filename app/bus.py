"""CAN adapter: python-can hardware or the built-in MLS simulator."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable

from .objects import OD_BY_KEY
from .protocol import (
    decode_value,
    encode_value,
    parse_sdo_response,
    parse_tpdo1,
    parse_tpdo2,
    parse_tpdo3,
    parse_tpdo4,
    sdo_download_request,
    sdo_rx_id,
    sdo_tx_id,
    sdo_upload_request,
    type_size,
)
from .simulator import MlsSimulator


class MlsSession:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.connected = False
        self.mode = "idle"
        self.node_id = 10
        self.bitrate = 125000
        self.interface = "simulator"
        self.channel = ""
        self.variant_tpdo1 = 3
        self.bus = None
        self.sim: MlsSimulator | None = None
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.listeners: list[Callable[[dict], None]] = []
        self.last_process: dict[str, Any] = {}
        self.tpdo_map: dict[int, int] = {}
        self.sdo_events: dict[int, threading.Event] = {}
        self.sdo_replies: dict[int, bytes] = {}
        self.sdo_seq = 0
        self.log: deque[dict] = deque(maxlen=200)
        self.combi = False
        self.hall: list[int] = []
        self.range_mm = 300
        self.elements = 54
        self.variant = "MLSE-0300"

    def emit(self, event: dict) -> None:
        event.setdefault("ts", time.time())
        for cb in list(self.listeners):
            try:
                cb(event)
            except Exception:
                pass

    def connect(self, cfg: dict) -> dict:
        self.disconnect()
        self.node_id = int(cfg.get("nodeId", 10))
        self.bitrate = int(cfg.get("bitrate", 125000))
        self.interface = cfg.get("interface", "simulator")
        self.channel = cfg.get("channel") or ""
        self.variant = cfg.get("variant", "MLSE-0300")
        self.stop_event.clear()
        if self.interface == "simulator":
            self.sim = MlsSimulator(self.variant, self.node_id)
            self.mode = "simulator"
            self.connected = True
            self.range_mm = self.sim.spec()["range_mm"]
            self.elements = self.sim.spec()["elements"]
        else:
            import can

            kwargs: dict[str, Any] = {"interface": self.interface, "bitrate": self.bitrate}
            if self.channel:
                kwargs["channel"] = self.channel
            self.bus = can.Bus(**kwargs)
            self.mode = "hardware"
            self.connected = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        self.emit({"type": "connection", "connected": True, "mode": self.mode})
        return {"ok": True, "mode": self.mode, "nodeId": self.node_id}

    def disconnect(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        if self.bus is not None:
            try:
                self.bus.shutdown()
            except Exception:
                pass
        self.bus = None
        self.sim = None
        self.connected = False
        self.mode = "idle"
        self.emit({"type": "connection", "connected": False, "mode": self.mode})

    def send(self, can_id: int, data: bytes) -> None:
        if self.sim is not None:
            if can_id == 0:
                self.sim.handle_nmt(data)
            elif can_id == sdo_rx_id(self.node_id):
                reply = self.sim.handle_sdo(data)
                self._on_sdo(bytes(reply))
            return
        if self.bus is None:
            raise RuntimeError("Nicht verbunden")
        import can

        self.bus.send(can.Message(arbitration_id=can_id, data=data, is_extended_id=False))

    def nmt(self, command: int, target: int | None = None) -> None:
        nid = self.node_id if target is None else target
        self.send(0x000, bytes([command & 0xFF, nid & 0xFF]))

    def sdo_read(self, index: int, sub: int, timeout: float = 0.4) -> dict:
        entry = OD_BY_KEY.get((index, sub))
        token = self._next_sdo()
        event = threading.Event()
        with self.lock:
            self.sdo_events[token] = event
        self.send(sdo_rx_id(self.node_id), sdo_upload_request(index, sub))
        if not event.wait(timeout):
            return {"ok": False, "error": "SDO-Timeout", "index": index, "sub": sub}
        raw = self.sdo_replies.pop(token, b"")
        parsed = parse_sdo_response(raw)
        if not parsed.get("ok"):
            return parsed
        if entry and parsed.get("raw") is not None:
            value = decode_value(entry, bytes(parsed["raw"]))
            parsed["value"] = value
            parsed["dataType"] = entry.data_type
            parsed["name"] = entry.name
        return parsed

    def sdo_write(self, index: int, sub: int, value: Any, timeout: float = 0.4) -> dict:
        entry = OD_BY_KEY.get((index, sub))
        if entry is None:
            return {"ok": False, "error": "Unbekanntes Objekt"}
        if entry.access == "RO":
            return {"ok": False, "error": "Objekt ist nur lesbar"}
        data = encode_value(entry, value)
        token = self._next_sdo()
        event = threading.Event()
        with self.lock:
            self.sdo_events[token] = event
        self.send(sdo_rx_id(self.node_id), sdo_download_request(index, sub, data[: type_size(entry)]))
        if not event.wait(timeout):
            return {"ok": False, "error": "SDO-Timeout", "index": index, "sub": sub}
        raw = self.sdo_replies.pop(token, b"")
        parsed = parse_sdo_response(raw)
        if parsed.get("ok") and (index, sub) == (0x2006, 1):
            self.variant_tpdo1 = int(value)
            self.combi = int(value) in (1, 5, 6, 7)
        return parsed

    def _next_sdo(self) -> int:
        with self.lock:
            self.sdo_seq += 1
            return self.sdo_seq

    def _on_sdo(self, data: bytes) -> None:
        with self.lock:
            if not self.sdo_events:
                return
            token = min(self.sdo_events)
            event = self.sdo_events.pop(token)
            self.sdo_replies[token] = data
        event.set()

    def configure_sim(self, body: dict) -> None:
        if not self.sim:
            return
        if "variant" in body:
            self.sim.set_variant(body["variant"])
            self.variant = self.sim.variant
            self.range_mm = self.sim.spec()["range_mm"]
            self.elements = self.sim.spec()["elements"]
        if "autoMove" in body:
            self.sim.auto_move = bool(body["autoMove"])
        if "trackCount" in body:
            from .simulator import SimTrack

            n = max(0, min(3, int(body["trackCount"])))
            while len(self.sim.tracks) < n:
                self.sim.tracks.append(SimTrack(position_mm=40.0 * len(self.sim.tracks)))
            self.sim.tracks = self.sim.tracks[:n]
        if "tracks" in body:
            from .simulator import SimTrack

            self.sim.tracks = [
                SimTrack(
                    position_mm=float(t.get("positionMm", 0)),
                    width_mm=float(t.get("widthMm", 25)),
                    polarity=int(t.get("polarity", 1)),
                )
                for t in body["tracks"][:3]
            ]
        if "marker" in body:
            m = body["marker"]
            self.sim.marker.visible = bool(m.get("visible", False))
            self.sim.marker.offset_mm = float(m.get("offsetMm", 30))
        if "useMarkers" in body:
            self.sim.params[(0x2028, 1)] = 1 if body["useMarkers"] else 0

    def _run(self) -> None:
        last_pdo = 0.0
        while not self.stop_event.is_set():
            if self.sim is not None:
                now = time.time()
                dt = max(0.01, now - last_pdo) if last_pdo else 0.02
                snapshot = self.sim.step(dt)
                last_pdo = now
                self.hall = snapshot["hall"]
                self._publish_process(snapshot)
                time.sleep(0.04)
                continue
            if self.bus is None:
                time.sleep(0.05)
                continue
            msg = self.bus.recv(timeout=0.05)
            if msg is None:
                continue
            self._handle_hw(msg.arbitration_id, bytes(msg.data))

    def _handle_hw(self, can_id: int, data: bytes) -> None:
        if can_id == sdo_tx_id(self.node_id):
            self._on_sdo(data)
            return
        pdo_slot = None
        if can_id == 0x180 + self.node_id:
            pdo_slot = 1
        elif can_id == 0x280 + self.node_id:
            pdo_slot = 2
        elif can_id == 0x380 + self.node_id:
            pdo_slot = 3
        elif can_id == 0x480 + self.node_id:
            pdo_slot = 4
        if pdo_slot == 1:
            parsed = parse_tpdo1(data, combi=self.combi)
            self.last_process.update(parsed)
            self.emit({"type": "process", "process": self._process_view()})
        elif pdo_slot == 2:
            self.last_process["tpdo2"] = parse_tpdo2(data)
            self.emit({"type": "process", "process": self._process_view()})
        elif pdo_slot == 3:
            self.last_process["tpdo3"] = parse_tpdo3(data)
        elif pdo_slot == 4:
            mapped = None
            if len(data) >= 8:
                mapped = parse_tpdo4(data)
            self.last_process["imu"] = mapped
        elif can_id == 0x700 + self.node_id:
            self.emit({"type": "heartbeat", "state": data[0] if data else None})

    def _publish_process(self, snapshot: dict) -> None:
        tpdo1 = parse_tpdo1(self.sim.build_tpdo1() if self.sim else b"", combi=int(self.sim.params.get((0x2006, 1), 3)) in (1, 5, 6, 7) if self.sim else False)
        tpdo2 = parse_tpdo2(self.sim.build_tpdo2() if self.sim else b"")
        self.last_process = {
            **tpdo1,
            "tpdo2": tpdo2,
            "imu": parse_tpdo4(self.sim.build_tpdo4()) if self.sim else None,
            "hall": snapshot["hall"],
            "positionsMm": snapshot["positionsMm"],
            "variant": snapshot["variant"],
            "rangeMm": snapshot["rangeMm"],
            "elements": snapshot["elements"],
            "fieldLevel": snapshot["fieldLevel"],
            "marker": snapshot["marker"],
            "nmt": self.sim.nmt_state if self.sim else "unknown",
        }
        self.emit({"type": "process", "process": self._process_view()})

    def _process_view(self) -> dict:
        p = self.last_process
        return {
            "connected": self.connected,
            "mode": self.mode,
            "variant": p.get("variant", self.variant),
            "rangeMm": p.get("rangeMm", self.range_mm),
            "elements": p.get("elements", self.elements),
            "lcp1": p.get("lcp1"),
            "lcp2": p.get("lcp2"),
            "lcp3": p.get("lcp3"),
            "width1": p.get("width1") or (p.get("tpdo2") or {}).get("width1"),
            "width2": p.get("width2") or (p.get("tpdo2") or {}).get("width2"),
            "width3": p.get("width3") or (p.get("tpdo2") or {}).get("width3"),
            "level1": (p.get("tpdo2") or {}).get("level1"),
            "level2": (p.get("tpdo2") or {}).get("level2"),
            "level3": (p.get("tpdo2") or {}).get("level3"),
            "tracks": p.get("tracks", []),
            "nlcp": p.get("nlcp"),
            "status": p.get("status"),
            "hall": p.get("hall", self.hall),
            "positionsMm": p.get("positionsMm", []),
            "fieldLevel": p.get("fieldLevel"),
            "marker": p.get("marker"),
            "imu": p.get("imu"),
            "nmt": p.get("nmt", "operational" if self.connected else "offline"),
            "raw": p.get("raw"),
            "combi": p.get("combi", self.combi),
        }


SESSION = MlsSession()
