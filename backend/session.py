"""Connection session: hardware CAN or simulator."""

from __future__ import annotations

import asyncio
import queue
import threading
import time
from typing import Any, Callable

from .decode import bitmap_bits, decode_tpdo1, decode_tpdo2, i16, marker_offsets_mm, rad_to_deg, u16
from .objects import VARIANTS, object_by_key
from .sdo import SdoError, decode_value, encode_value, format_display
from .simulator import MlsSimulator

Listener = Callable[[dict[str, Any]], None]


class MlsSession:
    def __init__(self) -> None:
        self.mode = "disconnected"
        self.node_id = 10
        self.bitrate = 125000
        self.interface = "pcan"
        self.channel = "PCAN_USBBUS1"
        self.variant = "MLSE-0400"
        self.sim: MlsSimulator | None = None
        self.bus = None
        self.sdo = None
        self._sdo_q: queue.Queue | None = None
        self._lock = threading.Lock()
        self.process: dict[str, Any] = self._empty_process()
        self._listeners: list[Listener] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.combi = False
        self.last_error: str | None = None

    def _empty_process(self) -> dict[str, Any]:
        spec = VARIANTS[self.variant]
        return {
            "connected": False,
            "mode": self.mode,
            "nmt": "unknown",
            "variant": self.variant,
            "range_mm": spec["range_mm"],
            "elements": spec["elements"],
            "tracks": [
                {"index": i, "position_mm": 0, "width_mm": None, "detected": False, "line_level": 0}
                for i in range(1, 4)
            ],
            "nlcp": 0,
            "nlcp_label": "Keine Spur",
            "marker_code": 0,
            "marker_intro": False,
            "reading_marker": False,
            "markers": [],
            "status": {
                "line_good": False,
                "track_level": 0,
                "track_level_class": "bad",
                "sensor_flipped": False,
                "polarity": "Nord",
                "reading_code": False,
                "event_flag": False,
                "raw": 0,
            },
            "field_level": 0,
            "hall": [],
            "bitmap": [],
            "imu": {"roll_deg": 0, "pitch_deg": 0, "yaw_deg": 0, "timestamp_ms": 0},
            "temperature_c": None,
            "updated": 0,
        }

    def status(self) -> dict[str, Any]:
        return {
            "connected": self.mode != "disconnected",
            "mode": self.mode,
            "node_id": self.node_id,
            "bitrate": self.bitrate,
            "interface": self.interface,
            "channel": self.channel,
            "variant": self.variant,
            "nmt": self.process.get("nmt"),
            "last_error": self.last_error,
        }

    def connect_sim(self, variant: str, node_id: int) -> None:
        self.disconnect()
        self.variant = variant if variant in VARIANTS else "MLSE-0400"
        self.node_id = node_id
        self.sim = MlsSimulator(variant=self.variant, node_id=node_id)
        self.mode = "simulation"
        self.combi = int(self.sim.params.get((0x2006, 1), 0)) in (1, 5, 6, 7)
        self.process = self._empty_process()
        self.process["connected"] = True
        self.process["mode"] = self.mode
        self.process["nmt"] = self.sim.nmt_state
        self._start_thread()

    def connect_can(self, interface: str, channel: str, bitrate: int, node_id: int, variant: str) -> None:
        import can

        self.disconnect()
        self.interface = interface
        self.channel = channel
        self.bitrate = bitrate
        self.node_id = node_id
        self.variant = variant if variant in VARIANTS else "MLSE-0400"
        kwargs: dict[str, Any] = {"interface": interface, "channel": channel, "bitrate": bitrate}
        if interface in ("pcan",):
            kwargs["fd"] = False
        self.bus = can.Bus(**kwargs)
        from .sdo import CanSdoClient

        self._sdo_q = queue.Queue()
        self.sdo = CanSdoClient(self.bus, node_id, rx_queue=self._sdo_q)
        self.mode = "hardware"
        self.process = self._empty_process()
        self.process["connected"] = True
        self.process["mode"] = self.mode
        try:
            raw = self.sdo.read_raw(0x2006, 1)
            self.combi = decode_value("UINT8", raw) in (1, 5, 6, 7)
        except Exception:
            self.combi = False
        self._start_thread()

    def disconnect(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._thread = None
        self._stop = threading.Event()
        if self.bus is not None:
            try:
                self.bus.shutdown()
            except Exception:
                pass
        self.bus = None
        self.sdo = None
        self._sdo_q = None
        self.sim = None
        self.mode = "disconnected"
        self.process = self._empty_process()

    def _start_thread(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        hall_tick = 0.0
        while not self._stop.is_set():
            try:
                if self.mode == "simulation" and self.sim:
                    frames = self.sim.poll_pdos()
                    for cob, data in frames:
                        self._handle_pdo(cob, data)
                    now = time.monotonic()
                    if now - hall_tick > 0.15:
                        self._pull_aux_sim()
                        hall_tick = now
                    self.process["nmt"] = self.sim.nmt_state
                    self.process["updated"] = time.time()
                    self._emit()
                    time.sleep(0.02)
                elif self.mode == "hardware" and self.bus is not None:
                    msg = self.bus.recv(timeout=0.05)
                    if msg is not None:
                        if self.sdo and msg.arbitration_id == self.sdo.rx_id:
                            if self._sdo_q is not None:
                                self._sdo_q.put(msg)
                        else:
                            self._handle_pdo(msg.arbitration_id, bytes(msg.data))
                    self.process["updated"] = time.time()
                    self._emit()
                else:
                    time.sleep(0.05)
            except Exception as exc:
                self.last_error = str(exc)
                time.sleep(0.1)

    def _handle_pdo(self, cob: int, data: bytes) -> None:
        nid = self.node_id
        pdo_fn = cob - nid
        if pdo_fn == 0x180:
            dec = decode_tpdo1(data, self.combi)
            self.process.update({k: dec[k] for k in ("tracks", "nlcp", "nlcp_label", "marker_code", "marker_intro", "reading_marker", "status")})
            style = 1
            if self.sim:
                style = int(self.sim.params.get((0x2028, 2), 1) or 1)
            self.process["markers"] = marker_offsets_mm(dec["marker_code"], style) if dec["reading_marker"] else []
        elif pdo_fn == 0x280:
            d2 = decode_tpdo2(data)
            for i, tr in enumerate(self.process["tracks"]):
                tr["width_mm"] = d2["widths"][i]
                tr["line_level"] = d2["line_levels"][i]
        elif pdo_fn == 0x380:
            words = [int.from_bytes(data[0:4], "little"), int.from_bytes(data[4:8], "little")]
            self.process["bitmap"] = bitmap_bits(words + [0, 0], VARIANTS[self.variant]["elements"])
        elif pdo_fn == 0x480:
            self.process["imu"] = {
                "roll_deg": round(rad_to_deg(i16(data[0], data[1])), 2),
                "pitch_deg": round(rad_to_deg(i16(data[2], data[3])), 2),
                "yaw_deg": round(rad_to_deg(i16(data[4], data[5])), 2),
                "timestamp_ms": u16(data[6], data[7]) if len(data) >= 8 else 0,
            }

    def _pull_aux_sim(self) -> None:
        assert self.sim
        snap = self.sim.snapshot()
        self.process["hall"] = snap["hall"]
        self.process["field_level"] = int(self.sim.params.get((0x2024, 0), 0))
        self.process["temperature_c"] = int(self.sim.params.get((0x2070, 1), 0))
        bits = [
            int(self.sim.params.get((0x202E, 1), 0)),
            int(self.sim.params.get((0x202E, 2), 0)),
            int(self.sim.params.get((0x202E, 3), 0)),
            int(self.sim.params.get((0x202E, 4), 0)),
        ]
        self.process["bitmap"] = bitmap_bits(bits, snap["elements"])
        self.process["imu"] = {
            "roll_deg": round(rad_to_deg(int(self.sim.params[(0x2030, 1)])), 2),
            "pitch_deg": round(rad_to_deg(int(self.sim.params[(0x2030, 2)])), 2),
            "yaw_deg": round(rad_to_deg(int(self.sim.params[(0x2030, 3)])), 2),
            "timestamp_ms": int(self.sim.params[(0x2035, 0)]),
        }
        widths = [int(self.sim.params.get((0x2021, 5 + i), 0) or 0) for i in range(3)]
        levels = [int(self.sim.params.get((0x2021, 0x0B + i), 0) or 0) for i in range(3)]
        for i, tr in enumerate(self.process.get("tracks") or []):
            if tr.get("width_mm") is None:
                tr["width_mm"] = widths[i]
            tr["line_level"] = levels[i]
        self.combi = int(self.sim.params.get((0x2006, 1), 0)) in (1, 5, 6, 7)

    def _pull_aux_hw(self, light: bool = False) -> None:
        if not self.sdo:
            return
        try:
            self.process["field_level"] = decode_value("UINT16", self.sdo.read_raw(0x2024, 0))
        except Exception:
            pass
        try:
            self.process["temperature_c"] = decode_value("INT8", self.sdo.read_raw(0x2070, 1))
        except Exception:
            pass
        if light:
            return
        try:
            n = VARIANTS[self.variant]["elements"]
            hall = []
            for i in range(1, n + 1):
                hall.append(decode_value("INT16", self.sdo.read_raw(0x2000, i)))
            self.process["hall"] = hall
        except Exception:
            pass

    def read_object(self, index: int, sub: int) -> dict[str, Any]:
        obj = object_by_key(index, sub)
        if obj is None:
            raise SdoError("Objekt nicht im MLS-Verzeichnis")
        if self.mode == "simulation" and self.sim:
            raw = self.sim.read(index, sub)
        elif self.mode == "hardware" and self.sdo:
            raw = self.sdo.read_raw(index, sub)
        else:
            raise SdoError("Nicht verbunden")
        value = decode_value(obj["dtype"], raw)
        if index == 0x2006 and sub == 1:
            self.combi = int(value) in (1, 5, 6, 7)
        return {
            "index": index,
            "sub": sub,
            "dtype": obj["dtype"],
            "name": obj["name"],
            "access": obj["access"],
            "value": value,
            "display": format_display(obj["dtype"], value),
            "raw_hex": raw.hex(),
        }

    def write_object(self, index: int, sub: int, value: Any) -> dict[str, Any]:
        obj = object_by_key(index, sub)
        if obj is None:
            raise SdoError("Objekt nicht im MLS-Verzeichnis")
        if obj["access"] == "ro":
            raise SdoError("Objekt ist nur lesbar")
        raw = encode_value(obj["dtype"], value)
        if self.mode == "simulation" and self.sim:
            self.sim.write(index, sub, raw)
        elif self.mode == "hardware" and self.sdo:
            self.sdo.write_raw(index, sub, raw)
        else:
            raise SdoError("Nicht verbunden")
        if index == 0x2006 and sub == 1:
            self.combi = int(value) in (1, 5, 6, 7)
        if obj["access"] == "wo":
            return {"ok": True, "written": value, "name": obj["name"]}
        return self.read_object(index, sub)

    def nmt(self, command: int) -> None:
        if self.mode == "simulation" and self.sim:
            self.sim.nmt(command)
            self.process["nmt"] = self.sim.nmt_state
        elif self.mode == "hardware" and self.sdo:
            self.sdo.nmt(command)
        else:
            raise SdoError("Nicht verbunden")

    def set_scenario(self, name: str) -> None:
        if not self.sim:
            raise SdoError("Szenarien nur in der Simulation")
        self.sim.set_scenario(name)

    def set_sim_tracks(self, tracks: list[dict[str, Any]], marker_code: int = 0) -> None:
        from .simulator import SimTrack

        if not self.sim:
            raise SdoError("Nur in der Simulation")
        self.sim.tracks = [
            SimTrack(
                position_mm=float(t["position_mm"]),
                width_mm=float(t.get("width_mm", 25)),
                level=float(t.get("level", 1800)),
            )
            for t in tracks
        ]
        self.sim.marker_code = int(marker_code)
        self.sim.marker_intro = bool(marker_code)

    def subscribe(self, fn: Listener) -> None:
        self._listeners.append(fn)

    def unsubscribe(self, fn: Listener) -> None:
        if fn in self._listeners:
            self._listeners.remove(fn)

    def _emit(self) -> None:
        snap = dict(self.process)
        for fn in list(self._listeners):
            try:
                fn(snap)
            except Exception:
                pass
