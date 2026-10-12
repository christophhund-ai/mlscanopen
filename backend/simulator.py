"""In-process MLS sensor simulator (CANopen SDO/PDO behaviour)."""

from __future__ import annotations

import math
import struct
import time
from dataclasses import dataclass, field
from typing import Any

from .decode import pack_combi
from .objects import SAVE_MAGIC, VARIANTS, object_by_key
from .sdo import decode_value, encode_value


def _signed_clamp(value: int, bits: int) -> int:
    max_u = 1 << bits
    value %= max_u
    sign = 1 << (bits - 1)
    return value - max_u if value & sign else value


@dataclass
class SimTrack:
    position_mm: float
    width_mm: float = 25.0
    level: float = 1800.0  # field digits at peak
    polarity: int = 1  # +1 north-up convention for peak sign


@dataclass
class MlsSimulator:
    variant: str = "MLSE-0400"
    node_id: int = 10
    nmt_state: str = "operational"  # stopped / preoperational / operational
    params: dict[tuple[int, int], Any] = field(default_factory=dict)
    tracks: list[SimTrack] = field(default_factory=list)
    marker_code: int = 0
    marker_intro: bool = False
    yaw_offset: float = 0.0
    t0: float = field(default_factory=time.monotonic)
    last_pdo: dict[int, float] = field(default_factory=dict)
    scenario: str = "single"

    def __post_init__(self) -> None:
        self._init_params()
        self.set_scenario("single")

    def _init_params(self) -> None:
        spec = VARIANTS[self.variant]
        self.params.clear()
        self.params[(0x1000, 0)] = 0
        self.params[(0x1001, 0)] = 0
        self.params[(0x1008, 0)] = "Magnetic line guidance sensor"
        self.params[(0x1009, 0)] = "1.0"
        self.params[(0x100A, 0)] = "V5.0 sim"
        self.params[(0x100C, 0)] = 0
        self.params[(0x100D, 0)] = 0
        self.params[(0x1010, 1)] = 1
        self.params[(0x1010, 2)] = 0
        self.params[(0x1017, 0)] = 0
        self.params[(0x1018, 1)] = 0x01000056
        self.params[(0x1018, 2)] = 0x00001100
        self.params[(0x1018, 3)] = 0x00000005
        self.params[(0x1018, 4)] = 0x24100001
        self.params[(0x1F80, 0)] = 8
        cob = {
            0x1800: 0x180 + self.node_id,
            0x1801: 0x80000000 | (0x280 + self.node_id),
            0x1802: 0x80000000 | (0x380 + self.node_id),
            0x1803: 0x80000000 | (0x480 + self.node_id),
            0x1804: 0x80000000,
            0x1805: 0x80000000,
            0x1806: 0x80000000,
        }
        for idx, default_cob in cob.items():
            self.params[(idx, 1)] = default_cob
            self.params[(idx, 2)] = 0xFF
            self.params[(idx, 5)] = 10 if idx == 0x1800 else 0
        self.params[(0x2006, 1)] = 3
        self.params[(0x2006, 2)] = 1
        self.params[(0x2019, 0)] = 1107594
        self.params[(0x2025, 0)] = 200
        self.params[(0x2026, 0)] = 0
        self.params[(0x2027, 0)] = 0
        self.params[(0x2028, 1)] = 1
        self.params[(0x2028, 2)] = 1
        self.params[(0x2028, 3)] = 0
        self.params[(0x2029, 0)] = 0
        self.params[(0x202D, 1)] = 30
        self.params[(0x202D, 2)] = 30
        self.params[(0x202D, 3)] = 1
        self.params[(0x202D, 4)] = 0
        self.params[(0x202D, 5)] = 0
        self.params[(0x202F, 1)] = 500
        self.params[(0x202F, 2)] = 1
        self.params[(0x2070, 4)] = 28
        self.params[(0x2070, 5)] = 21
        self.params[(0x2070, 6)] = 80
        self.params[(0x2070, 7)] = -30
        self.params["_elements"] = spec["elements"]
        self.params["_range"] = spec["range_mm"]

    def set_scenario(self, name: str) -> None:
        self.scenario = name
        self.marker_code = 0
        self.marker_intro = False
        if name == "none":
            self.tracks = []
        elif name == "diverter_left":
            self.tracks = [
                SimTrack(-40, 25, 1600),
                SimTrack(15, 30, 1900),
            ]
        elif name == "diverter_right":
            self.tracks = [
                SimTrack(-10, 28, 1850),
                SimTrack(55, 25, 1500),
            ]
        elif name == "three":
            self.tracks = [
                SimTrack(-70, 25, 1400),
                SimTrack(0, 25, 2000),
                SimTrack(80, 25, 1350),
            ]
        elif name == "marker":
            self.tracks = [SimTrack(8, 25, 2100)]
            self.marker_code = 4
            self.marker_intro = True
        elif name == "weak":
            self.tracks = [SimTrack(-20, 25, 420)]
        else:
            self.tracks = [SimTrack(12, 25, 1950)]

    def nmt(self, cmd: int) -> None:
        if cmd == 0x01:
            self.nmt_state = "operational"
        elif cmd == 0x02:
            self.nmt_state = "stopped"
        elif cmd == 0x80:
            self.nmt_state = "preoperational"
        elif cmd == 0x81:
            self._init_params()
            self.nmt_state = "preoperational"
        elif cmd == 0x82:
            self.nmt_state = "preoperational"

    def read(self, index: int, sub: int) -> bytes:
        self._refresh_process()
        key = (index, sub)
        if index == 0x2000:
            hall = self.hall_profile()
            if 1 <= sub <= len(hall):
                return encode_value("INT16", hall[sub - 1])
            raise KeyError("hall sub")
        obj = object_by_key(index, sub)
        if obj is None:
            raise KeyError("unknown object")
        if obj["access"] == "wo":
            raise PermissionError("write-only")
        if key not in self.params:
            raise KeyError("no value")
        return encode_value(obj["dtype"], self.params[key])

    def write(self, index: int, sub: int, data: bytes) -> None:
        obj = object_by_key(index, sub)
        if obj is None:
            raise KeyError("unknown object")
        if obj["access"] == "ro":
            raise PermissionError("read-only")
        value = decode_value(obj["dtype"], data)
        if index == 0x202A and value:
            self._init_params()
            return
        if index == 0x202B and value:
            return
        if index == 0x202C and value:
            if len(self.tracks) == 1:
                self.params[(0x2026, 0)] = int(round(self.tracks[0].position_mm))
            return
        if index == 0x2032 and sub == 1 and value:
            self.yaw_offset = time.monotonic()
            return
        if index == 0x2080 and sub == 1:
            self.params[(0x2080, 2)] = 0
            self.params[(0x2080, 4)] = 0
            self.params[(0x2080, 5)] = 0
            return
        if index == 0x1010 and sub == 1 and value == SAVE_MAGIC:
            self.params[key] = 1
            return
        self.params[(index, sub)] = value

    def _nlcp(self) -> int:
        n = len(self.tracks)
        if n == 0:
            return 0
        if n == 1:
            return 2
        if n == 2:
            if self.tracks[0].position_mm < 0:
                return 3
            return 6
        return 7

    def hall_profile(self) -> list[int]:
        n = int(self.params["_elements"])
        span = float(self.params["_range"])
        xs = [(-span / 2.0) + i * (span / max(n - 1, 1)) for i in range(n)]
        values = [0.0] * n
        for tr in self.tracks:
            sigma = max(tr.width_mm / 2.2, 6.0)
            for i, x in enumerate(xs):
                values[i] += tr.polarity * tr.level * math.exp(-0.5 * ((x - tr.position_mm) / sigma) ** 2)
        if self.marker_code and self.params.get((0x2028, 1)):
            main = self.tracks[0].position_mm if self.tracks else 0.0
            side = 1 if self.marker_code else 1
            dist = {1: 30, 2: 60, 3: 90, 4: 120, 5: 90, 6: 120, 7: 120}.get(self.marker_code, 60)
            mx = main + dist * side
            for i, x in enumerate(xs):
                values[i] -= 900 * math.exp(-0.5 * ((x - mx) / 8.0) ** 2)
        return [int(max(-32000, min(32000, v))) for v in values]

    def _refresh_process(self) -> None:
        offset = int(self.params.get((0x2026, 0), 0) or 0)
        flipped = bool(self.params.get((0x2027, 0), 0))
        ordered = sorted(self.tracks, key=lambda t: t.position_mm)
        positions = []
        widths = []
        levels = []
        for tr in ordered:
            pos = tr.position_mm - offset
            if flipped:
                pos = -pos
            positions.append(int(round(pos)))
            widths.append(int(round(tr.width_mm)))
            levels.append(int(max(-127, min(127, round(tr.level * 0.016)))))
        while len(positions) < 3:
            positions.append(0)
            widths.append(0)
            levels.append(0)
        # mapping: 1 track -> LCP2; 2 tracks left -> LCP1+LCP2; 2 right -> LCP2+LCP3
        lcp = [0, 0, 0]
        w = [0, 0, 0]
        lv = [0, 0, 0]
        n = len(ordered)
        if n == 1:
            lcp[1], w[1], lv[1] = positions[0], widths[0], levels[0]
        elif n == 2:
            if ordered[0].position_mm < 0:
                lcp[0], w[0], lv[0] = positions[0], widths[0], levels[0]
                lcp[1], w[1], lv[1] = positions[1], widths[1], levels[1]
            else:
                lcp[1], w[1], lv[1] = positions[0], widths[0], levels[0]
                lcp[2], w[2], lv[2] = positions[1], widths[1], levels[1]
        elif n >= 3:
            for i in range(3):
                lcp[i], w[i], lv[i] = positions[i], widths[i], levels[i]

        nlcp = self._nlcp()
        self.params[(0x2021, 1)] = lcp[0]
        self.params[(0x2021, 2)] = lcp[1]
        self.params[(0x2021, 3)] = lcp[2]
        self.params[(0x2021, 4)] = nlcp
        self.params[(0x2021, 5)] = w[0]
        self.params[(0x2021, 6)] = w[1]
        self.params[(0x2021, 7)] = w[2]
        self.params[(0x2021, 8)] = pack_combi(lcp[0], w[0])
        self.params[(0x2021, 9)] = pack_combi(lcp[1], w[1])
        self.params[(0x2021, 0x0A)] = pack_combi(lcp[2], w[2])
        self.params[(0x2021, 0x0B)] = lv[0]
        self.params[(0x2021, 0x0C)] = lv[1]
        self.params[(0x2021, 0x0D)] = lv[2]

        field = int(max((abs(t.level) for t in ordered), default=0))
        self.params[(0x2024, 0)] = field
        track_level = 0
        for fl, tl in (
            (4500, 7),
            (2250, 7),
            (2000, 7),
            (1750, 6),
            (1500, 5),
            (1250, 4),
            (1000, 3),
            (750, 2),
            (500, 1),
        ):
            if field >= fl:
                track_level = tl
                break
        self.params[(0x2023, 0)] = track_level
        line_good = 1 if field > 500 else 0
        polarity_south = 0
        reading = 1 if self.marker_intro or self.marker_code else 0
        event = 1 if field and field < 500 else 0
        status = line_good | (track_level << 1) | (int(flipped) << 4) | (polarity_south << 5) | (reading << 6) | (event << 7)
        self.params[(0x2022, 0)] = status
        self.params[(0x2080, 2)] = 2 if event else 0
        self.params[(0x2080, 4)] = 1 if event else 0
        self.params[(0x2080, 5)] = 0

        hall = self.hall_profile()
        thr = int(self.params.get((0x202F, 1), 500))
        mode = int(self.params.get((0x202F, 2), 0))
        bits = 0
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

        t = time.monotonic() - self.t0
        stamp = int((t * 1000) % 65536)
        self.params[(0x2035, 0)] = stamp
        roll = int(800 * math.sin(t * 0.3))
        pitch = int(500 * math.cos(t * 0.21))
        yaw = int(((t - self.yaw_offset) * 200) % 30000)
        self.params[(0x2030, 1)] = roll
        self.params[(0x2030, 2)] = pitch
        self.params[(0x2030, 3)] = yaw
        self.params[(0x2031, 1)] = 10000
        self.params[(0x2031, 2)] = roll
        self.params[(0x2031, 3)] = pitch
        self.params[(0x2031, 4)] = yaw
        self.params[(0x2033, 1)] = 0
        self.params[(0x2033, 2)] = 0
        self.params[(0x2033, 3)] = 2048  # ~1 g
        self.params[(0x2034, 1)] = 0
        self.params[(0x2034, 2)] = 0
        self.params[(0x2034, 3)] = 12
        self.params[(0x2070, 1)] = 27
        self.params[(0x2070, 2)] = 41
        self.params[(0x2070, 3)] = 12

        marker_byte = nlcp
        if self.params.get((0x2028, 1)):
            marker_byte |= (int(self.marker_intro) | (self.marker_code << 1)) << 3
        self.params["_tpdo1_b7"] = marker_byte
        self.params["_tpdo1_b8"] = status

    def _pdo_enabled(self, pdo_index: int) -> bool:
        cob = int(self.params.get((pdo_index, 1), 0x80000000))
        timer = int(self.params.get((pdo_index, 5), 0))
        return (cob & 0x80000000) == 0 and timer > 0 and self.nmt_state == "operational"

    def poll_pdos(self) -> list[tuple[int, bytes]]:
        self._refresh_process()
        now = time.monotonic()
        out: list[tuple[int, bytes]] = []
        mapping = [
            (0x1800, 1, self._pack_tpdo1),
            (0x1801, 2, self._pack_tpdo2),
            (0x1802, 3, self._pack_tpdo3),
            (0x1803, 4, self._pack_tpdo4),
            (0x1804, 5, self._pack_tpdo5),
            (0x1805, 6, self._pack_tpdo6),
            (0x1806, 7, self._pack_tpdo7),
        ]
        for idx, num, packer in mapping:
            if not self._pdo_enabled(idx):
                continue
            timer_s = int(self.params[(idx, 5)]) / 1000.0
            last = self.last_pdo.get(num, 0.0)
            if now - last >= timer_s:
                self.last_pdo[num] = now
                cob = int(self.params[(idx, 1)]) & 0x7FF
                out.append((cob, packer()))
        return out

    def _pack_tpdo1(self) -> bytes:
        combi = int(self.params.get((0x2006, 1), 0)) in (1, 5, 6, 7)
        if combi:
            raw = struct.pack(
                "<HHH",
                self.params[(0x2021, 8)],
                self.params[(0x2021, 9)],
                self.params[(0x2021, 0x0A)],
            )
        else:
            raw = struct.pack(
                "<hhh",
                _signed_clamp(self.params[(0x2021, 1)], 16),
                _signed_clamp(self.params[(0x2021, 2)], 16),
                _signed_clamp(self.params[(0x2021, 3)], 16),
            )
        return raw + bytes([self.params["_tpdo1_b7"], self.params["_tpdo1_b8"]])

    def _pack_tpdo2(self) -> bytes:
        return bytes(
            [
                self.params[(0x2021, 5)],
                self.params[(0x2021, 6)],
                self.params[(0x2021, 7)],
                0,
                self.params[(0x2021, 0x0B)] & 0xFF,
                self.params[(0x2021, 0x0C)] & 0xFF,
                self.params[(0x2021, 0x0D)] & 0xFF,
                0,
            ]
        )

    def _pack_tpdo3(self) -> bytes:
        w1 = self.params[(0x202E, 1)]
        w2 = self.params[(0x202E, 2)]
        return struct.pack("<I", w1)[:4] + struct.pack("<I", w2)[:4]

    def _pack_tpdo4(self) -> bytes:
        return struct.pack(
            "<hhhH",
            self.params[(0x2030, 1)],
            self.params[(0x2030, 2)],
            self.params[(0x2030, 3)],
            self.params[(0x2035, 0)],
        )

    def _pack_tpdo5(self) -> bytes:
        return struct.pack(
            "<hhhH",
            self.params[(0x2031, 2)],
            self.params[(0x2031, 3)],
            self.params[(0x2031, 4)],
            self.params[(0x2035, 0)],
        )

    def _pack_tpdo6(self) -> bytes:
        return struct.pack(
            "<hhhH",
            self.params[(0x2033, 1)],
            self.params[(0x2033, 2)],
            self.params[(0x2033, 3)],
            self.params[(0x2035, 0)],
        )

    def _pack_tpdo7(self) -> bytes:
        return struct.pack(
            "<hhhH",
            self.params[(0x2034, 1)],
            self.params[(0x2034, 2)],
            self.params[(0x2034, 3)],
            self.params[(0x2035, 0)],
        )

    def snapshot(self) -> dict[str, Any]:
        self._refresh_process()
        spec = VARIANTS[self.variant]
        return {
            "variant": self.variant,
            "range_mm": spec["range_mm"],
            "elements": spec["elements"],
            "nmt": self.nmt_state,
            "hall": self.hall_profile(),
            "params_hint": {
                "variant_tpdo1": self.params[(0x2006, 1)],
                "use_markers": self.params[(0x2028, 1)],
                "marker_style": self.params[(0x2028, 2)],
            },
        }
