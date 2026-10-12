"""Decode MLS TPDO / status bytes according to the operating instructions."""

from __future__ import annotations

import struct
from typing import Any

NLCP_LABELS = {
    0: "Keine Spur",
    2: "Eine Spur (LCP2)",
    3: "Weiche links (LCP1+LCP2)",
    6: "Weiche rechts (LCP2+LCP3)",
    7: "Drei Spuren / 90°-Kreuzung",
}

EVENT_SOURCE = {0: "Kein Event", 2: "Magnetfeld", 4: "Temperatur", 6: "Magnetfeld und Temperatur"}


def i16(lo: int, hi: int) -> int:
    return struct.unpack("<h", bytes((lo, hi)))[0]


def u16(lo: int, hi: int) -> int:
    return lo | (hi << 8)


def unpack_combi(value: int) -> tuple[int, int]:
    """LCP INT10 + width UINT6 packed as described in table 10 notes."""
    lsb = value & 0xFF
    msb = (value >> 8) & 0xFF
    lcp = lsb | ((msb & 0x01) << 8) | ((msb & 0x80) << 2)
    width = (msb >> 1) & 0x3F
    if lcp & 0x200:
        lcp -= 0x400
    return lcp, width


def pack_combi(lcp: int, width: int) -> int:
    lcp &= 0x3FF
    width &= 0x3F
    lsb = lcp & 0xFF
    msb = ((lcp >> 8) & 0x01) | ((width & 0x3F) << 1) | ((lcp >> 9) & 0x01) << 7
    return lsb | (msb << 8)


def decode_nlcp_marker(byte7: int) -> dict[str, Any]:
    nlcp = byte7 & 0x07
    marker_field = (byte7 >> 3) & 0x1F
    intro = bool(marker_field & 0x01)
    code = (marker_field >> 1) & 0x0F
    return {
        "nlcp": nlcp,
        "nlcp_label": NLCP_LABELS.get(nlcp, f"Unbekannt ({nlcp})"),
        "marker_intro": intro,
        "marker_code": code,
        "marker_raw": marker_field,
        "reading_marker": intro or code > 0,
    }


def decode_status(byte8: int) -> dict[str, Any]:
    track_level = (byte8 >> 1) & 0x07
    return {
        "raw": byte8,
        "line_good": bool(byte8 & 0x01),
        "track_level": track_level,
        "track_level_class": "good" if track_level >= 4 else "critical" if track_level >= 1 else "bad",
        "sensor_flipped": bool(byte8 & 0x10),
        "polarity_south": bool(byte8 & 0x20),
        "polarity": "Süd" if byte8 & 0x20 else "Nord",
        "reading_code": bool(byte8 & 0x40),
        "event_flag": bool(byte8 & 0x80),
    }


def decode_tpdo1(data: bytes, combi: bool) -> dict[str, Any]:
    data = data.ljust(8, b"\x00")
    tracks = []
    if combi:
        for i in range(3):
            raw = u16(data[i * 2], data[i * 2 + 1])
            pos, width = unpack_combi(raw)
            tracks.append({"index": i + 1, "position_mm": pos, "width_mm": width, "combi_raw": raw})
    else:
        for i in range(3):
            tracks.append(
                {
                    "index": i + 1,
                    "position_mm": i16(data[i * 2], data[i * 2 + 1]),
                    "width_mm": None,
                    "combi_raw": None,
                }
            )
    meta = decode_nlcp_marker(data[6])
    status = decode_status(data[7])
    present = {1: bool(meta["nlcp"] & 0x01), 2: bool(meta["nlcp"] & 0x02), 3: bool(meta["nlcp"] & 0x04)}
    for t in tracks:
        t["detected"] = present[t["index"]]
    return {"tracks": tracks, **meta, "status": status, "combi": combi}


def decode_tpdo2(data: bytes) -> dict[str, Any]:
    data = data.ljust(8, b"\x00")
    return {
        "widths": [data[0], data[1], data[2]],
        "line_levels": [
            struct.unpack("b", bytes([data[4]]))[0],
            struct.unpack("b", bytes([data[5]]))[0],
            struct.unpack("b", bytes([data[6]]))[0],
        ],
    }


def bitmap_bits(words: list[int], n_elements: int) -> list[int]:
    bits = []
    for word in words:
        for i in range(32):
            bits.append((word >> i) & 1)
    return bits[:n_elements]


def rad_to_deg(raw_int16: int) -> float:
    return (raw_int16 / 10000.0) * (180.0 / 3.141592653589793)


def marker_offsets_mm(code: int, style: int) -> list[dict[str, Any]]:
    """Approximate SICK marker geometry on a 30 mm raster (standard/extended tables)."""
    tables_std = {
        1: [(30, 1)],
        2: [(60, 1)],
        3: [(60, 1), (30, -1)],
        4: [(90, 1), (30, -1)],
        5: [(120, 1), (30, -1)],
        6: [(120, 1), (60, -1)],
        7: [(120, 1), (90, -1)],
    }
    tables_ext = {
        1: [(30, 1)],
        2: [(60, 1)],
        3: [(60, 1), (30, -1)],
        4: [(90, 1)],
        5: [(90, 1), (30, -1)],
        6: [(90, 1), (60, -1)],
        7: [(120, 1)],
        8: [(120, 1), (30, -1)],
        9: [(120, 1), (60, -1)],
        10: [(120, 1), (90, -1)],
    }
    table = tables_ext if style == 2 else tables_std
    out = []
    for dist, side in table.get(code, []):
        out.append({"offset_mm": dist * side, "side": "positiv" if side > 0 else "negativ"})
    return out
