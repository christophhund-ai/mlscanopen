"""CANopen SDO/PDO/NMT helpers for the MLS."""

from __future__ import annotations

import struct
from typing import Any

from .objects import NCP_LCP, OdEntry


NMT_START = 0x01
NMT_STOP = 0x02
NMT_PREOP = 0x80
NMT_RESET_NODE = 0x81
NMT_RESET_COMM = 0x82

CCS_DOWNLOAD = 1
CCS_UPLOAD = 2
CCS_ABORT = 4

SIZE_TO_CMD = {1: 0x2F, 2: 0x2B, 3: 0x27, 4: 0x23}
CMD_TO_SIZE = {0x4F: 1, 0x4B: 2, 0x47: 3, 0x43: 4, 0x2F: 1, 0x2B: 2, 0x27: 3, 0x23: 4}


def nmt_frame(command: int, node_id: int) -> tuple[int, bytes]:
    return 0x000, bytes([command & 0xFF, node_id & 0xFF])


def sdo_rx_id(node_id: int) -> int:
    return 0x600 + node_id


def sdo_tx_id(node_id: int) -> int:
    return 0x580 + node_id


def tpdo_ids(node_id: int) -> dict[int, int]:
    return {n: cob + node_id for n, cob in enumerate((0x180, 0x280, 0x380, 0x480), start=1)}


def encode_value(entry: OdEntry, value: Any) -> bytes:
    if entry.data_type == "STRING":
        data = str(value).encode("ascii", errors="replace")
        return data[:4] if len(data) <= 4 else data
    ival = int(value, 0) if isinstance(value, str) else int(value)
    if entry.data_type == "BOOL":
        return bytes([1 if ival else 0, 0, 0, 0])
    if entry.data_type == "UINT8":
        return struct.pack("<Bxxx", ival & 0xFF)
    if entry.data_type == "INT8":
        return struct.pack("<bxxx", ival)
    if entry.data_type == "UINT16":
        return struct.pack("<Hxx", ival & 0xFFFF)
    if entry.data_type == "INT16":
        return struct.pack("<hxx", ival)
    if entry.data_type == "UINT32":
        return struct.pack("<I", ival & 0xFFFFFFFF)
    if entry.data_type == "INT32":
        return struct.pack("<i", ival)
    raise ValueError(entry.data_type)


def type_size(entry: OdEntry) -> int:
    return {"BOOL": 1, "UINT8": 1, "INT8": 1, "UINT16": 2, "INT16": 2, "UINT32": 4, "INT32": 4, "STRING": 4}[
        entry.data_type
    ]


def decode_value(entry: OdEntry, data: bytes) -> int | str:
    payload = data + b"\x00" * 4
    if entry.data_type == "STRING":
        return data.split(b"\x00", 1)[0].decode("ascii", errors="replace")
    if entry.data_type in ("BOOL", "UINT8"):
        return payload[0]
    if entry.data_type == "INT8":
        return struct.unpack_from("<b", payload)[0]
    if entry.data_type == "UINT16":
        return struct.unpack_from("<H", payload)[0]
    if entry.data_type == "INT16":
        return struct.unpack_from("<h", payload)[0]
    if entry.data_type == "UINT32":
        return struct.unpack_from("<I", payload)[0]
    if entry.data_type == "INT32":
        return struct.unpack_from("<i", payload)[0]
    raise ValueError(entry.data_type)


def sdo_upload_request(index: int, sub: int) -> bytes:
    return bytes([0x40, index & 0xFF, (index >> 8) & 0xFF, sub & 0xFF, 0, 0, 0, 0])


def sdo_download_request(index: int, sub: int, data: bytes) -> bytes:
    n = min(len(data), 4)
    cmd = SIZE_TO_CMD[n]
    padded = (data[:4] + b"\x00" * 4)[:4]
    return bytes([cmd, index & 0xFF, (index >> 8) & 0xFF, sub & 0xFF]) + padded


def parse_sdo_response(data: bytes) -> dict[str, Any]:
    if len(data) < 8:
        raise ValueError("SDO-Antwort zu kurz")
    cmd = data[0]
    index = data[1] | (data[2] << 8)
    sub = data[3]
    if cmd == 0x80:
        abort = struct.unpack_from("<I", data, 4)[0]
        return {"ok": False, "index": index, "sub": sub, "abort": abort, "abortHex": f"0x{abort:08X}"}
    if cmd in CMD_TO_SIZE:
        n = CMD_TO_SIZE[cmd]
        return {"ok": True, "index": index, "sub": sub, "raw": list(data[4 : 4 + n]), "expedited": True}
    if cmd == 0x60:
        return {"ok": True, "index": index, "sub": sub, "written": True}
    if (cmd & 0xE0) == 0x40 and (cmd & 0x02):
        size = struct.unpack_from("<I", data, 4)[0] if cmd & 0x01 else None
        return {"ok": True, "index": index, "sub": sub, "segmented": True, "size": size}
    return {"ok": True, "index": index, "sub": sub, "raw": list(data[4:]), "cmd": cmd}


def decode_int16_le(b0: int, b1: int) -> int:
    v = b0 | (b1 << 8)
    return v - 0x10000 if v & 0x8000 else v


def decode_uint16_le(b0: int, b1: int) -> int:
    return b0 | (b1 << 8)


def unpack_combi(word: int) -> tuple[int, int]:
    # LSB: LCP 0..7, MSB: LCP8 | width0..5 | LCP9
    lcp = (word & 0x1FF) | ((word & 0x8000) >> 6)
    if lcp & 0x200:
        lcp -= 1024
    width = (word >> 9) & 0x3F
    return lcp, width


def pack_combi(lcp: int, width: int) -> int:
    lcp = max(-511, min(511, int(lcp)))
    width = max(0, min(63, int(width)))
    raw = lcp & 0x3FF
    return (raw & 0x1FF) | ((width & 0x3F) << 9) | ((raw & 0x200) << 6)


def parse_status(byte: int) -> dict[str, Any]:
    track_level = (byte >> 1) & 0x07
    return {
        "raw": byte,
        "lineGood": bool(byte & 0x01),
        "trackLevel": track_level,
        "trackQuality": "gut" if track_level >= 4 else ("kritisch" if track_level >= 1 else "schlecht"),
        "sensorFlipped": bool(byte & 0x10),
        "polarity": "Süd" if byte & 0x20 else "Nord",
        "readingCode": bool(byte & 0x40),
        "eventFlag": bool(byte & 0x80),
    }


def parse_nlcp(byte: int) -> dict[str, Any]:
    tracks = byte & 0x07
    marker = (byte >> 3) & 0x1F
    intro = bool(marker & 0x01)
    code = (marker >> 1) & 0x0F
    return {
        "raw": byte,
        "trackCode": tracks,
        "trackLabel": NCP_LCP.get(tracks, f"Unbekannt ({tracks})"),
        "lcp1": tracks in (3, 7),
        "lcp2": tracks in (2, 3, 6, 7),
        "lcp3": tracks in (6, 7),
        "markerIntro": intro,
        "markerCode": code if intro or code else 0,
        "markerBits": marker,
    }


def parse_tpdo1(data: bytes, combi: bool = False) -> dict[str, Any]:
    payload = (data + bytes(8))[:8]
    if combi:
        tracks = []
        for i in range(3):
            word = decode_uint16_le(payload[i * 2], payload[i * 2 + 1])
            pos, width = unpack_combi(word)
            tracks.append({"positionMm": pos, "widthMm": width})
        lcp1, lcp2, lcp3 = (t["positionMm"] for t in tracks)
        w1, w2, w3 = (t["widthMm"] for t in tracks)
    else:
        lcp1 = decode_int16_le(payload[0], payload[1])
        lcp2 = decode_int16_le(payload[2], payload[3])
        lcp3 = decode_int16_le(payload[4], payload[5])
        w1 = w2 = w3 = None
    nlcp = parse_nlcp(payload[6])
    status = parse_status(payload[7])
    present = []
    if nlcp["lcp1"]:
        present.append({"id": 1, "positionMm": lcp1, "widthMm": w1})
    if nlcp["lcp2"]:
        present.append({"id": 2, "positionMm": lcp2, "widthMm": w2})
    if nlcp["lcp3"]:
        present.append({"id": 3, "positionMm": lcp3, "widthMm": w3})
    return {
        "pdo": 1,
        "lcp1": lcp1,
        "lcp2": lcp2,
        "lcp3": lcp3,
        "width1": w1,
        "width2": w2,
        "width3": w3,
        "nlcp": nlcp,
        "status": status,
        "tracks": present,
        "raw": list(payload),
        "combi": combi,
    }


def parse_tpdo2(data: bytes) -> dict[str, Any]:
    payload = (data + bytes(8))[:8]
    return {
        "pdo": 2,
        "width1": payload[0],
        "width2": payload[1],
        "width3": payload[2],
        "level1": struct.unpack_from("<b", payload, 3)[0] if len(payload) > 3 else 0,
        "level2": struct.unpack_from("<b", payload, 4)[0] if len(payload) > 4 else 0,
        "level3": struct.unpack_from("<b", payload, 5)[0] if len(payload) > 5 else 0,
        "raw": list(payload),
    }


def parse_tpdo3(data: bytes) -> dict[str, Any]:
    payload = (data + bytes(8))[:8]
    return {"pdo": 3, "bitmap": list(payload), "raw": list(payload)}


def parse_tpdo4(data: bytes) -> dict[str, Any]:
    payload = (data + bytes(8))[:8]
    roll = decode_int16_le(payload[0], payload[1])
    pitch = decode_int16_le(payload[2], payload[3])
    yaw = decode_int16_le(payload[4], payload[5])
    ts = decode_uint16_le(payload[6], payload[7])
    return {
        "pdo": 4,
        "roll": roll,
        "pitch": pitch,
        "yaw": yaw,
        "rollRad": roll / 10000,
        "pitchRad": pitch / 10000,
        "yawRad": yaw / 10000,
        "timestampMs": ts,
        "raw": list(payload),
    }


def parse_tpdo5(data: bytes) -> dict[str, Any]:
    payload = (data + bytes(8))[:8]
    x = decode_int16_le(payload[0], payload[1]) / 10000
    y = decode_int16_le(payload[2], payload[3]) / 10000
    z = decode_int16_le(payload[4], payload[5]) / 10000
    w2 = max(0.0, 1.0 - (x * x + y * y + z * z))
    return {
        "pdo": 5,
        "x": x,
        "y": y,
        "z": z,
        "w": w2**0.5,
        "timestampMs": decode_uint16_le(payload[6], payload[7]),
        "raw": list(payload),
    }


def parse_xyz_ts(data: bytes, pdo: int, scale: float, unit: str) -> dict[str, Any]:
    payload = (data + bytes(8))[:8]
    x = decode_int16_le(payload[0], payload[1])
    y = decode_int16_le(payload[2], payload[3])
    z = decode_int16_le(payload[4], payload[5])
    return {
        "pdo": pdo,
        "x": x,
        "y": y,
        "z": z,
        "xScaled": x * scale,
        "yScaled": y * scale,
        "zScaled": z * scale,
        "unit": unit,
        "timestampMs": decode_uint16_le(payload[6], payload[7]),
        "raw": list(payload),
    }


def classify_can_id(can_id: int, node_id: int) -> str | None:
    if can_id == 0x000:
        return "nmt"
    if can_id == 0x080:
        return "sync"
    if can_id == 0x080 + node_id:
        return "emcy"
    if can_id == 0x580 + node_id:
        return "sdo_tx"
    if can_id == 0x600 + node_id:
        return "sdo_rx"
    if can_id == 0x700 + node_id:
        return "heartbeat"
    mapping = {0x180 + node_id: "tpdo1", 0x280 + node_id: "tpdo2", 0x380 + node_id: "tpdo3", 0x480 + node_id: "tpdo4"}
    return mapping.get(can_id)
