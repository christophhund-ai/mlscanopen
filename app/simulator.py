"""Software MLS that speaks CANopen on a virtual bus."""

from __future__ import annotations

import math
import struct
import time
from dataclasses import dataclass, field

from .objects import OD_BY_KEY, VARIANTS, OdEntry
from .protocol import (
    CMD_TO_SIZE,
    SIZE_TO_CMD,
    decode_value,
    encode_value,
    nmt_frame,
    pack_combi,
    parse_nlcp,
    parse_status,
    sdo_tx_id,
    type_size,
)


@dataclass
class SimTrack:
    position_mm: float
    width_mm: float = 25.0
    polarity: int = 1  # +1 north, -1 south
    amplitude: float = 2200.0


@dataclass
class SimMarker:
    offset_mm: float
    code_side: int = 1
    polarity: int = -1
    amplitude: float = 1400.0
    width_mm: float = 12.0
    visible: bool = False


class MlsSimulator:
    def __init__(self, variant: str = "MLSE-0300", node_id: int = 10) -> None:
        self.variant = variant if variant in VARIANTS else "MLSE-0300"
        self.node_id = node_id
        self.nmt_state = "operational"
        self.boot_ms = int(time.time() * 1000)
        self.params: dict[tuple[int, int], int | str] = {}
        self._init_params()
        self.tracks: list[SimTrack] = [SimTrack(8.0)]
        self.marker = SimMarker(offset_mm=30.0)
        self.auto_move = True
        self.phase = 0.0
        self.hall: list[int] = []
        self.last_process: dict = {}
        self.hall_poll = True

    def _init_params(self) -> None:
        for key, entry in OD_BY_KEY.items():
            if entry.default is not None:
                self.params[key] = entry.default
        spec = VARIANTS[self.variant]
        self.params[(0x1008, 0)] = "Magnetic line guidance sensor"
        self.params[(0x1009, 0)] = "HW 1.0"
        self.params[(0x100A, 0)] = "FW 5.0"
        self.params[(0x2019, 0)] = 1094078
        self.params[(0x1800, 1)] = 0x180 + self.node_id
        self.params[(0x1801, 1)] = 0x80000000 | (0x280 + self.node_id)
        self.params[(0x1802, 1)] = 0x80000000 | (0x380 + self.node_id)
        self.params[(0x1803, 1)] = 0x80000000 | (0x480 + self.node_id)
        self.params[(0x1800, 5)] = 10
        self.params[(0x2006, 1)] = 3
        self.params[(0x2025, 0)] = 200
        self.params[(0x2070, 1)] = 28
        self.params[(0x2070, 2)] = 41
        self.params[(0x2070, 3)] = 12
        self.params[(0x2070, 4)] = 31
        self.params[(0x2070, 5)] = 21
        n = spec["elements"]
        for i in range(1, n + 1):
            self.params[(0x2000, i)] = 0

    def set_variant(self, variant: str) -> None:
        if variant in VARIANTS:
            self.variant = variant
            self._init_params()

    def spec(self) -> dict:
        return VARIANTS[self.variant]

    def element_positions(self) -> list[float]:
        spec = self.spec()
        n = spec["elements"]
        half = spec["range_mm"] / 2.0
        if n <= 1:
            return [0.0]
        return [(-half + i * (spec["range_mm"] / (n - 1))) for i in range(n)]

    def _gaussian(self, x: float, mu: float, sigma: float, amp: float) -> float:
        return amp * math.exp(-0.5 * ((x - mu) / max(sigma, 1.0)) ** 2)

    def compute_hall(self) -> list[int]:
        flipped = bool(self.params.get((0x2027, 0), 0))
        sign = -1 if flipped else 1
        values = []
        for x in self.element_positions():
            field = 8.0 * math.sin(self.phase * 0.15 + x * 0.02)
            for track in self.tracks:
                sigma = max(4.0, track.width_mm * 0.35)
                field += self._gaussian(x, sign * track.position_mm, sigma, track.polarity * track.amplitude)
            if self.marker.visible and self.tracks:
                main = self.tracks[0]
                mx = sign * (main.position_mm + self.marker.offset_mm)
                field += self._gaussian(x, mx, 4.5, self.marker.polarity * self.marker.amplitude)
            values.append(int(max(-32768, min(32767, round(field)))))
        self.hall = values
        for i, v in enumerate(values, start=1):
            self.params[(0x2000, i)] = v
        return values

    def _detect_tracks(self) -> list[dict]:
        min_level = int(self.params.get((0x2025, 0), 200))
        xs = self.element_positions()
        hall = self.hall or self.compute_hall()
        peaks: list[dict] = []
        for i in range(1, len(hall) - 1):
            v = hall[i]
            if abs(v) < min_level:
                continue
            if abs(v) >= abs(hall[i - 1]) and abs(v) >= abs(hall[i + 1]):
                if peaks and abs(xs[i] - peaks[-1]["positionMm"]) < 12:
                    if abs(v) > abs(peaks[-1]["raw"]):
                        peaks[-1] = {"positionMm": xs[i], "raw": v}
                else:
                    peaks.append({"positionMm": xs[i], "raw": v})
        peaks.sort(key=lambda p: p["positionMm"])
        offset = int(self.params.get((0x2026, 0), 0))
        flipped = bool(self.params.get((0x2027, 0), 0))
        out = []
        for p in peaks[:3]:
            pos = p["positionMm"] + offset
            if flipped:
                pos = -pos
            width = 25
            for t in self.tracks:
                if abs(t.position_mm - (p["positionMm"] if not flipped else -p["positionMm"])) < 20:
                    width = int(t.width_mm)
            level = int(max(-127, min(127, round(p["raw"] / 64))))
            out.append({"positionMm": int(round(pos)), "widthMm": width, "level": level, "raw": p["raw"]})
        return out

    def _nlcp_and_assign(self, detected: list[dict]) -> tuple[int, dict]:
        assigned = {"lcp1": 0, "lcp2": 0, "lcp3": 0, "w1": 0, "w2": 0, "w3": 0, "lv1": 0, "lv2": 0, "lv3": 0}
        n = len(detected)
        if n == 0:
            code = 0
        elif n == 1:
            code = 2
            assigned.update(lcp2=detected[0]["positionMm"], w2=detected[0]["widthMm"], lv2=detected[0]["level"])
        elif n == 2:
            left, right = detected
            mid = (left["positionMm"] + right["positionMm"]) / 2
            if abs(mid) < 8:
                code = 3 if abs(left["positionMm"]) > abs(right["positionMm"]) else 6
            else:
                code = 3 if mid < 0 else 6
            if code == 3:
                assigned.update(
                    lcp1=left["positionMm"],
                    w1=left["widthMm"],
                    lv1=left["level"],
                    lcp2=right["positionMm"],
                    w2=right["widthMm"],
                    lv2=right["level"],
                )
            else:
                assigned.update(
                    lcp2=left["positionMm"],
                    w2=left["widthMm"],
                    lv2=left["level"],
                    lcp3=right["positionMm"],
                    w3=right["widthMm"],
                    lv3=right["level"],
                )
        else:
            code = 7
            assigned.update(
                lcp1=detected[0]["positionMm"],
                w1=detected[0]["widthMm"],
                lv1=detected[0]["level"],
                lcp2=detected[1]["positionMm"],
                w2=detected[1]["widthMm"],
                lv2=detected[1]["level"],
                lcp3=detected[2]["positionMm"],
                w3=detected[2]["widthMm"],
                lv3=detected[2]["level"],
            )
        marker_bits = 0
        if self.params.get((0x2028, 1), 0) and self.marker.visible:
            intro = 1
            code_m = max(1, min(15, int(round(abs(self.marker.offset_mm) / 30))))
            marker_bits = intro | (code_m << 1)
        nlcp = code | (marker_bits << 3)
        return nlcp, assigned

    def _status_byte(self, field_level: int, detected: list[dict]) -> int:
        line_good = 1 if field_level >= 500 or (detected and field_level >= 400) else 0
        if field_level >= 1750:
            track_level = 6 if field_level < 2000 else 7
        elif field_level >= 1500:
            track_level = 5
        elif field_level >= 1250:
            track_level = 4
        elif field_level >= 1000:
            track_level = 3
        elif field_level >= 750:
            track_level = 2
        elif field_level >= 500:
            track_level = 1
        else:
            track_level = 0
        flipped = 1 if self.params.get((0x2027, 0), 0) else 0
        polarity = 0
        if detected:
            polarity = 1 if detected[0]["raw"] < 0 else 0
        reading = 1 if self.marker.visible and self.params.get((0x2028, 1), 0) else 0
        temp = int(self.params.get((0x2070, 1), 28))
        hi = int(self.params.get((0x2070, 6), 80))
        lo = int(self.params.get((0x2070, 7), -30))
        mag_event = 1 if 0 < field_level < 350 else 0
        temp_event = 1 if temp < lo else (2 if temp > hi else 0)
        event = 1 if mag_event or temp_event else 0
        src = (2 if mag_event else 0) + (4 if temp_event else 0)
        self.params[(0x2080, 2)] = src
        self.params[(0x2080, 4)] = mag_event
        self.params[(0x2080, 5)] = temp_event
        self.params[(0x2023, 0)] = track_level
        self.params[(0x2024, 0)] = min(65535, field_level)
        return line_good | (track_level << 1) | (flipped << 4) | (polarity << 5) | (reading << 6) | (event << 7)

    def step(self, dt: float = 0.02) -> dict:
        if self.auto_move and self.tracks:
            self.phase += dt
            span = self.spec()["range_mm"] * 0.32
            self.tracks[0].position_mm = math.sin(self.phase * 0.6) * span
            if len(self.tracks) > 1:
                self.tracks[1].position_mm = self.tracks[0].position_mm - 55
            if len(self.tracks) > 2:
                self.tracks[2].position_mm = self.tracks[0].position_mm + 55
            self.marker.visible = (math.sin(self.phase * 0.25) > 0.65) and bool(self.params.get((0x2028, 1), 0) or True)
        hall = self.compute_hall()
        detected = self._detect_tracks()
        field_level = max((abs(v) for v in hall), default=0)
        nlcp, assigned = self._nlcp_and_assign(detected)
        status = self._status_byte(field_level, detected)
        for key, val in (
            ((0x2021, 1), assigned["lcp1"] & 0xFFFF),
            ((0x2021, 2), assigned["lcp2"] & 0xFFFF),
            ((0x2021, 3), assigned["lcp3"] & 0xFFFF),
            ((0x2021, 4), nlcp),
            ((0x2021, 5), assigned["w1"]),
            ((0x2021, 6), assigned["w2"]),
            ((0x2021, 7), assigned["w3"]),
            ((0x2021, 0xB), assigned["lv1"]),
            ((0x2021, 0xC), assigned["lv2"]),
            ((0x2021, 0xD), assigned["lv3"]),
            ((0x2022, 0), status),
        ):
            self.params[key] = val
        ts = int(time.time() * 1000) & 0xFFFF
        self.params[(0x2035, 0)] = ts
        self.params[(0x2030, 1)] = int(80 * math.sin(self.phase * 0.2))
        self.params[(0x2030, 2)] = int(40 * math.cos(self.phase * 0.13))
        self.params[(0x2030, 3)] = int((self.phase * 200) % 62832 - 31416)
        self.params[(0x2033, 1)] = int(20 * math.sin(self.phase))
        self.params[(0x2033, 3)] = 2048
        bits = 0
        thr = int(self.params.get((0x202F, 1), 500))
        mode = int(self.params.get((0x202F, 2), 0))
        for i, v in enumerate(hall[:128]):
            on = False
            if mode == 1:
                on = abs(v) > thr
            elif mode == 2:
                on = v > thr
            elif mode == 3:
                on = v < -thr
            if on:
                bits |= 1 << i
        self.params[(0x202E, 1)] = bits & 0xFFFFFFFF
        self.params[(0x202E, 2)] = (bits >> 32) & 0xFFFFFFFF
        self.params[(0x202E, 3)] = (bits >> 64) & 0xFFFFFFFF
        self.params[(0x202E, 4)] = (bits >> 96) & 0xFFFFFFFF
        self.last_process = {
            "variant": self.variant,
            "rangeMm": self.spec()["range_mm"],
            "elements": self.spec()["elements"],
            "hall": hall,
            "positionsMm": self.element_positions(),
            "detected": detected,
            "nlcp": parse_nlcp(nlcp),
            "status": parse_status(status),
            "assigned": assigned,
            "fieldLevel": field_level,
            "timestampMs": ts,
            "marker": {
                "visible": self.marker.visible,
                "offsetMm": self.marker.offset_mm,
                "code": parse_nlcp(nlcp)["markerCode"],
            },
        }
        return self.last_process

    def pdo_enabled(self, pdo: int) -> bool:
        cob = int(self.params.get((0x1800 + pdo - 1, 1), 0x80000000))
        return (cob & 0x80000000) == 0

    def cob_id(self, pdo: int) -> int:
        return int(self.params.get((0x1800 + pdo - 1, 1), 0)) & 0x7FF

    def build_tpdo1(self) -> bytes:
        a = self.last_process.get("assigned", {})
        variant = int(self.params.get((0x2006, 1), 3))
        combi = variant in (1, 5, 6, 7)
        if combi:
            raw = b""
            for pos_key, w_key in (("lcp1", "w1"), ("lcp2", "w2"), ("lcp3", "w3")):
                raw += struct.pack("<H", pack_combi(a.get(pos_key, 0), a.get(w_key, 0)))
        else:
            raw = struct.pack("<hhh", a.get("lcp1", 0), a.get("lcp2", 0), a.get("lcp3", 0))
        return raw + bytes([int(self.params.get((0x2021, 4), 0)), int(self.params.get((0x2022, 0), 0))])

    def build_tpdo2(self) -> bytes:
        a = self.last_process.get("assigned", {})
        return bytes(
            [
                a.get("w1", 0) & 0xFF,
                a.get("w2", 0) & 0xFF,
                a.get("w3", 0) & 0xFF,
                a.get("lv1", 0) & 0xFF,
                a.get("lv2", 0) & 0xFF,
                a.get("lv3", 0) & 0xFF,
                0,
                0,
            ]
        )

    def build_tpdo3(self) -> bytes:
        bits = int(self.params.get((0x202E, 1), 0)) | (int(self.params.get((0x202E, 2), 0)) << 32)
        return struct.pack("<Q", bits & 0xFFFFFFFFFFFFFFFF)

    def build_tpdo4(self) -> bytes:
        return struct.pack(
            "<hhhH",
            int(self.params.get((0x2030, 1), 0)),
            int(self.params.get((0x2030, 2), 0)),
            int(self.params.get((0x2030, 3), 0)),
            int(self.params.get((0x2035, 0), 0)),
        )

    def handle_sdo(self, data: bytes) -> bytes:
        if len(data) < 4:
            return bytes(8)
        cmd, index_lo, index_hi, sub = data[0], data[1], data[2], data[3]
        index = index_lo | (index_hi << 8)
        key = (index, sub)
        entry = OD_BY_KEY.get(key)
        if cmd == 0x40:
            if key not in self.params and entry is None:
                return bytes([0x80, index_lo, index_hi, sub, 0x00, 0x00, 0x02, 0x06])
            value = self.params.get(key, 0 if not entry or entry.data_type != "STRING" else "")
            if entry and entry.data_type == "STRING":
                encoded = str(value).encode("ascii")[:4]
                n = len(encoded)
                cmd_out = {1: 0x4F, 2: 0x4B, 3: 0x47, 4: 0x43}.get(max(n, 1), 0x43)
                return bytes([cmd_out, index_lo, index_hi, sub]) + (encoded + b"\x00" * 4)[:4]
            raw = encode_value(entry or OdEntry(index, sub, "RO", "UINT32", "", 0, ""), value)
            n = type_size(entry) if entry else 4
            cmd_out = {1: 0x4F, 2: 0x4B, 3: 0x47, 4: 0x43}[n]
            return bytes([cmd_out, index_lo, index_hi, sub]) + (raw + b"\x00" * 4)[:4]
        if cmd in SIZE_TO_CMD.values() or cmd in (0x23, 0x27, 0x2B, 0x2F):
            if entry and entry.access == "RO":
                return bytes([0x80, index_lo, index_hi, sub, 0x01, 0x00, 0x03, 0x06])
            n = CMD_TO_SIZE.get(cmd, 4)
            raw = data[4 : 4 + n]
            if entry:
                self.params[key] = decode_value(entry, raw)
            else:
                self.params[key] = int.from_bytes(raw + b"\x00" * 4, "little")
            if key == (0x202A, 0) and self.params[key]:
                self._init_params()
            if key == (0x202B, 0):
                pass
            if key == (0x2080, 1):
                self.params[(0x2080, 2)] = 0
                self.params[(0x2080, 4)] = 0
                self.params[(0x2080, 5)] = 0
            return bytes([0x60, index_lo, index_hi, sub, 0, 0, 0, 0])
        return bytes([0x80, index_lo, index_hi, sub, 0x00, 0x00, 0x04, 0x05])

    def handle_nmt(self, data: bytes) -> None:
        if len(data) < 2:
            return
        cmd, target = data[0], data[1]
        if target not in (0, self.node_id):
            return
        if cmd == 0x01:
            self.nmt_state = "operational"
        elif cmd == 0x02:
            self.nmt_state = "stopped"
        elif cmd == 0x80:
            self.nmt_state = "pre-operational"
        elif cmd in (0x81, 0x82):
            self.nmt_state = "pre-operational"

    def outgoing_frames(self) -> list[tuple[int, bytes]]:
        frames: list[tuple[int, bytes]] = []
        if self.nmt_state != "operational":
            return frames
        builders = {1: self.build_tpdo1, 2: self.build_tpdo2, 3: self.build_tpdo3, 4: self.build_tpdo4}
        for pdo, builder in builders.items():
            if self.pdo_enabled(pdo):
                frames.append((self.cob_id(pdo), builder()))
        hb = int(self.params.get((0x1017, 0), 0))
        if hb:
            frames.append((0x700 + self.node_id, bytes([0x05])))
        return frames
