"""CANopen object dictionary for SICK MLS (operating instructions 8021642.1OC7)."""

from __future__ import annotations

VARIANTS = {
    "MLSE-0200": {"length_mm": 217, "range_mm": 200, "elements": 36},
    "MLSE-0300": {"length_mm": 325, "range_mm": 300, "elements": 54},
    "MLSE-0400": {"length_mm": 397, "range_mm": 400, "elements": 66},
    "MLSE-0500": {"length_mm": 505, "range_mm": 500, "elements": 84},
    "MLSE-0600": {"length_mm": 613, "range_mm": 600, "elements": 102},
}

BITRATES = [10000, 20000, 50000, 100000, 125000, 250000, 500000, 800000, 1000000]

TPDO_COB = {
    1: 0x180,
    2: 0x280,
    3: 0x380,
    4: 0x480,
}

VARIANT_TPDO1 = {
    0: "Standard",
    1: "Combi",
    2: "Standard compensated",
    3: "Standard enhanced",
    4: "Standard enhanced compensated",
    5: "Combi compensated",
    6: "Combi enhanced",
    7: "Combi enhanced compensated",
}

SAVE_MAGIC = 0x65766173  # ASCII "save" little-endian

# Access: ro / rw / wo
OBJECTS: list[dict] = [
    # Communication profile
    {"index": 0x1000, "sub": 0, "access": "ro", "dtype": "UINT32", "name": "Device type", "group": "Kommunikation", "process": False},
    {"index": 0x1001, "sub": 0, "access": "ro", "dtype": "UINT8", "name": "Error register", "group": "Kommunikation", "process": False},
    {"index": 0x1008, "sub": 0, "access": "ro", "dtype": "STRING", "name": "Manufacturer device name", "group": "Kommunikation", "process": False},
    {"index": 0x1009, "sub": 0, "access": "ro", "dtype": "STRING", "name": "Manufacturer hardware version", "group": "Kommunikation", "process": False},
    {"index": 0x100A, "sub": 0, "access": "ro", "dtype": "STRING", "name": "Manufacturer software version", "group": "Kommunikation", "process": False},
    {"index": 0x100C, "sub": 0, "access": "rw", "dtype": "UINT16", "name": "Guard time", "default": 0, "group": "Kommunikation", "fw5": True, "process": False},
    {"index": 0x100D, "sub": 0, "access": "rw", "dtype": "UINT8", "name": "Life time factor", "default": 0, "group": "Kommunikation", "fw5": True, "process": False},
    {"index": 0x1010, "sub": 1, "access": "rw", "dtype": "UINT32", "name": "Save all parameters", "hint": "0x65766173 ('save') schreibt Parameter nichtflüchtig", "group": "Kommunikation", "fw5": True, "process": False},
    {"index": 0x1010, "sub": 2, "access": "rw", "dtype": "UINT32", "name": "CANopen save behaviour", "group": "Kommunikation", "fw5": True, "process": False},
    {"index": 0x1017, "sub": 0, "access": "rw", "dtype": "UINT16", "name": "Heartbeat time [ms]", "default": 0, "group": "Kommunikation", "fw5": True, "process": False},
    {"index": 0x1018, "sub": 1, "access": "ro", "dtype": "UINT32", "name": "Vendor-ID", "group": "Identität", "process": False},
    {"index": 0x1018, "sub": 2, "access": "ro", "dtype": "UINT32", "name": "Product code", "group": "Identität", "process": False},
    {"index": 0x1018, "sub": 3, "access": "ro", "dtype": "UINT32", "name": "Revision number", "group": "Identität", "process": False},
    {"index": 0x1018, "sub": 4, "access": "ro", "dtype": "UINT32", "name": "Serial number", "group": "Identität", "process": False},
    {"index": 0x1F80, "sub": 0, "access": "rw", "dtype": "UINT32", "name": "NMT startup", "default": 8, "group": "Kommunikation", "fw5": True, "process": False},
    # TPDO communication
    *[
        item
        for n, idx, cob_default, timer_default in [
            (1, 0x1800, 0x0000018A, 0x000A),
            (2, 0x1801, 0x8000028A, 0x0000),
            (3, 0x1802, 0x8000038A, 0x0000),
            (4, 0x1803, 0x8000048A, 0x0000),
            (5, 0x1804, 0x80000000, 0x0000),
            (6, 0x1805, 0x80000000, 0x0000),
            (7, 0x1806, 0x80000000, 0x0000),
        ]
        for item in [
            {"index": idx, "sub": 1, "access": "rw", "dtype": "UINT32", "name": f"TPDO{n} COB-ID", "default": cob_default, "group": "TPDO", "fw5": n >= 2, "process": False},
            {"index": idx, "sub": 2, "access": "rw", "dtype": "UINT8", "name": f"TPDO{n} Transmission type", "default": 0xFF, "group": "TPDO", "fw5": n >= 2, "process": False},
            {"index": idx, "sub": 5, "access": "rw", "dtype": "UINT16", "name": f"TPDO{n} Event timer [ms]", "default": timer_default, "group": "TPDO", "fw5": n >= 2, "process": False},
        ]
    ],
    {"index": 0x2006, "sub": 1, "access": "rw", "dtype": "UINT8", "name": "Variant TPDO1", "default": 3, "group": "Konfiguration", "hint": "0–7: Standard/Combi ± compensated ± enhanced. Neustart nötig.", "process": False},
    {"index": 0x2006, "sub": 2, "access": "rw", "dtype": "UINT8", "name": "Variant MEMS (IMU)", "default": 1, "group": "Konfiguration", "hint": "0 = IMU+Temp aus, 1 = ein. Neustart nötig.", "process": False},
    {"index": 0x2019, "sub": 0, "access": "ro", "dtype": "UINT32", "name": "Order number", "group": "Identität", "process": False},
    # Process LCPs
    {"index": 0x2021, "sub": 1, "access": "ro", "dtype": "INT16", "name": "LCP1 [mm]", "group": "Prozessdaten", "process": True, "unit": "mm"},
    {"index": 0x2021, "sub": 2, "access": "ro", "dtype": "INT16", "name": "LCP2 [mm]", "group": "Prozessdaten", "process": True, "unit": "mm"},
    {"index": 0x2021, "sub": 3, "access": "ro", "dtype": "INT16", "name": "LCP3 [mm]", "group": "Prozessdaten", "process": True, "unit": "mm"},
    {"index": 0x2021, "sub": 4, "access": "ro", "dtype": "UINT8", "name": "#LCP", "group": "Prozessdaten", "process": True},
    {"index": 0x2021, "sub": 5, "access": "ro", "dtype": "UINT8", "name": "LCP1 width [mm]", "group": "Prozessdaten", "fw5": True, "process": True, "unit": "mm"},
    {"index": 0x2021, "sub": 6, "access": "ro", "dtype": "UINT8", "name": "LCP2 width [mm]", "group": "Prozessdaten", "fw5": True, "process": True, "unit": "mm"},
    {"index": 0x2021, "sub": 7, "access": "ro", "dtype": "UINT8", "name": "LCP3 width [mm]", "group": "Prozessdaten", "fw5": True, "process": True, "unit": "mm"},
    {"index": 0x2021, "sub": 8, "access": "ro", "dtype": "UINT16", "name": "LCP1 Combi", "group": "Prozessdaten", "fw5": True, "process": True},
    {"index": 0x2021, "sub": 9, "access": "ro", "dtype": "UINT16", "name": "LCP2 Combi", "group": "Prozessdaten", "fw5": True, "process": True},
    {"index": 0x2021, "sub": 0x0A, "access": "ro", "dtype": "UINT16", "name": "LCP3 Combi", "group": "Prozessdaten", "fw5": True, "process": True},
    {"index": 0x2021, "sub": 0x0B, "access": "ro", "dtype": "INT8", "name": "Line Level 1", "group": "Prozessdaten", "fw5": True, "process": True, "hint": "LSB = 0.048 mT"},
    {"index": 0x2021, "sub": 0x0C, "access": "ro", "dtype": "INT8", "name": "Line Level 2", "group": "Prozessdaten", "fw5": True, "process": True},
    {"index": 0x2021, "sub": 0x0D, "access": "ro", "dtype": "INT8", "name": "Line Level 3", "group": "Prozessdaten", "fw5": True, "process": True},
    {"index": 0x2022, "sub": 0, "access": "ro", "dtype": "UINT8", "name": "Status", "group": "Prozessdaten", "process": True},
    {"index": 0x2023, "sub": 0, "access": "ro", "dtype": "UINT16", "name": "Track Level", "group": "Prozessdaten", "process": True},
    {"index": 0x2024, "sub": 0, "access": "ro", "dtype": "UINT16", "name": "Field level", "group": "Prozessdaten", "process": True, "hint": "LSB ≈ 0.00076 mT"},
    {"index": 0x2025, "sub": 0, "access": "rw", "dtype": "UINT16", "name": "Min. level", "default": 200, "group": "Spur-Erkennung", "process": False},
    {"index": 0x2026, "sub": 0, "access": "rw", "dtype": "INT16", "name": "Offset [mm]", "default": 0, "group": "Spur-Erkennung", "process": False, "unit": "mm"},
    {"index": 0x2027, "sub": 0, "access": "rw", "dtype": "BOOL", "name": "Sensor flipped", "default": 0, "group": "Spur-Erkennung", "process": False},
    {"index": 0x2028, "sub": 1, "access": "rw", "dtype": "BOOL", "name": "Use markers", "default": 0, "group": "Marker", "process": False},
    {"index": 0x2028, "sub": 2, "access": "rw", "dtype": "UINT8", "name": "Marker style", "default": 0, "group": "Marker", "hint": "0 aus, 1 Standard, 2 Extended", "process": False},
    {"index": 0x2028, "sub": 3, "access": "rw", "dtype": "BOOL", "name": "Failsafe mode", "default": 0, "group": "Marker", "process": False},
    {"index": 0x2029, "sub": 0, "access": "rw", "dtype": "BOOL", "name": "Lock teach", "default": 0, "group": "Teach", "process": False},
    {"index": 0x202A, "sub": 0, "access": "wo", "dtype": "BOOL", "name": "Set param. to default", "group": "Teach", "process": False},
    {"index": 0x202B, "sub": 0, "access": "wo", "dtype": "BOOL", "name": "Trigger user offset calibration", "group": "Teach", "process": False},
    {"index": 0x202C, "sub": 0, "access": "wo", "dtype": "BOOL", "name": "Trigger zero position teach", "group": "Teach", "process": False},
    {"index": 0x202D, "sub": 1, "access": "rw", "dtype": "UINT8", "name": "First Level [%]", "default": 30, "group": "Spur-Erkennung", "fw5": True, "process": False},
    {"index": 0x202D, "sub": 2, "access": "rw", "dtype": "UINT8", "name": "Last Level [%]", "default": 30, "group": "Spur-Erkennung", "fw5": True, "process": False},
    {"index": 0x202D, "sub": 3, "access": "rw", "dtype": "UINT8", "name": "Averaging magnetic", "default": 1, "group": "Spur-Erkennung", "fw5": True, "process": False},
    {"index": 0x202D, "sub": 4, "access": "rw", "dtype": "UINT8", "name": "Averaging inertial", "default": 0, "group": "IMU", "fw5": True, "process": False},
    {"index": 0x202D, "sub": 5, "access": "rw", "dtype": "UINT8", "name": "Tape polarity", "default": 0, "group": "Spur-Erkennung", "fw5": True, "hint": "0 beide, 1 Nord, 2 Süd", "process": False},
    {"index": 0x202E, "sub": 1, "access": "ro", "dtype": "UINT32", "name": "Bitmap bytes 1-4", "group": "Bitmap", "fw5": True, "process": True},
    {"index": 0x202E, "sub": 2, "access": "ro", "dtype": "UINT32", "name": "Bitmap bytes 5-8", "group": "Bitmap", "fw5": True, "process": True},
    {"index": 0x202E, "sub": 3, "access": "ro", "dtype": "UINT32", "name": "Bitmap bytes 9-12", "group": "Bitmap", "fw5": True, "process": True},
    {"index": 0x202E, "sub": 4, "access": "ro", "dtype": "UINT32", "name": "Bitmap bytes 13-16", "group": "Bitmap", "fw5": True, "process": True},
    {"index": 0x202F, "sub": 1, "access": "rw", "dtype": "UINT16", "name": "Bitmap threshold", "default": 500, "group": "Bitmap", "fw5": True, "process": False},
    {"index": 0x202F, "sub": 2, "access": "rw", "dtype": "UINT8", "name": "Bitmap mode", "default": 0, "group": "Bitmap", "fw5": True, "hint": "0 aus, 1 beide, 2 Süd, 3 Nord", "process": False},
    {"index": 0x2030, "sub": 1, "access": "ro", "dtype": "INT16", "name": "Roll (1/10000 rad)", "group": "IMU", "fw5": True, "process": True},
    {"index": 0x2030, "sub": 2, "access": "ro", "dtype": "INT16", "name": "Pitch (1/10000 rad)", "group": "IMU", "fw5": True, "process": True},
    {"index": 0x2030, "sub": 3, "access": "ro", "dtype": "INT16", "name": "Yaw (1/10000 rad)", "group": "IMU", "fw5": True, "process": True},
    {"index": 0x2031, "sub": 1, "access": "ro", "dtype": "INT16", "name": "Quaternion w", "group": "IMU", "fw5": True, "process": True},
    {"index": 0x2031, "sub": 2, "access": "ro", "dtype": "INT16", "name": "Quaternion x", "group": "IMU", "fw5": True, "process": True},
    {"index": 0x2031, "sub": 3, "access": "ro", "dtype": "INT16", "name": "Quaternion y", "group": "IMU", "fw5": True, "process": True},
    {"index": 0x2031, "sub": 4, "access": "ro", "dtype": "INT16", "name": "Quaternion z", "group": "IMU", "fw5": True, "process": True},
    {"index": 0x2032, "sub": 1, "access": "wo", "dtype": "UINT8", "name": "Reset yaw", "group": "IMU", "fw5": True, "process": False},
    {"index": 0x2032, "sub": 2, "access": "wo", "dtype": "UINT8", "name": "Reset acceleration peaks", "group": "IMU", "fw5": True, "process": False},
    {"index": 0x2033, "sub": 1, "access": "ro", "dtype": "INT16", "name": "Accel X", "group": "IMU", "fw5": True, "process": True},
    {"index": 0x2033, "sub": 2, "access": "ro", "dtype": "INT16", "name": "Accel Y", "group": "IMU", "fw5": True, "process": True},
    {"index": 0x2033, "sub": 3, "access": "ro", "dtype": "INT16", "name": "Accel Z", "group": "IMU", "fw5": True, "process": True},
    {"index": 0x2034, "sub": 1, "access": "ro", "dtype": "INT16", "name": "Gyro X", "group": "IMU", "fw5": True, "process": True},
    {"index": 0x2034, "sub": 2, "access": "ro", "dtype": "INT16", "name": "Gyro Y", "group": "IMU", "fw5": True, "process": True},
    {"index": 0x2034, "sub": 3, "access": "ro", "dtype": "INT16", "name": "Gyro Z", "group": "IMU", "fw5": True, "process": True},
    {"index": 0x2035, "sub": 0, "access": "ro", "dtype": "UINT16", "name": "Sample timestamp [ms]", "group": "IMU", "fw5": True, "process": True},
    {"index": 0x2070, "sub": 1, "access": "ro", "dtype": "INT8", "name": "Current temperature [°C]", "group": "Temperatur", "fw5": True, "process": True, "unit": "°C"},
    {"index": 0x2070, "sub": 2, "access": "ro", "dtype": "INT8", "name": "Max. temperature all time", "group": "Temperatur", "fw5": True, "process": True, "unit": "°C"},
    {"index": 0x2070, "sub": 3, "access": "ro", "dtype": "INT8", "name": "Min. temperature all time", "group": "Temperatur", "fw5": True, "process": True, "unit": "°C"},
    {"index": 0x2070, "sub": 4, "access": "rw", "dtype": "INT8", "name": "Max. temperature since reset", "group": "Temperatur", "fw5": True, "process": False, "unit": "°C"},
    {"index": 0x2070, "sub": 5, "access": "rw", "dtype": "INT8", "name": "Min. temperature since reset", "group": "Temperatur", "fw5": True, "process": False, "unit": "°C"},
    {"index": 0x2070, "sub": 6, "access": "rw", "dtype": "INT8", "name": "Upper temperature threshold", "default": 80, "group": "Temperatur", "fw5": True, "process": False, "unit": "°C"},
    {"index": 0x2070, "sub": 7, "access": "rw", "dtype": "INT8", "name": "Lower temperature threshold", "default": -30, "group": "Temperatur", "fw5": True, "process": False, "unit": "°C"},
    {"index": 0x2080, "sub": 1, "access": "wo", "dtype": "UINT8", "name": "Reset event flag", "group": "Events", "fw5": True, "process": False},
    {"index": 0x2080, "sub": 2, "access": "ro", "dtype": "UINT8", "name": "Event source", "group": "Events", "fw5": True, "process": True, "hint": "0 kein, 2 Magnet, 4 Temp, 6 beides"},
    {"index": 0x2080, "sub": 4, "access": "ro", "dtype": "UINT8", "name": "Magnetic field event code", "group": "Events", "fw5": True, "process": True},
    {"index": 0x2080, "sub": 5, "access": "ro", "dtype": "UINT8", "name": "Temperature event code", "group": "Events", "fw5": True, "process": True},
]


def hall_objects(max_elements: int = 102) -> list[dict]:
    return [
        {
            "index": 0x2000,
            "sub": i,
            "access": "ro",
            "dtype": "INT16",
            "name": f"Hall element {i}",
            "group": "Hall-Rohdaten",
            "process": True,
        }
        for i in range(1, max_elements + 1)
    ]


def object_by_key(index: int, sub: int) -> dict | None:
    for obj in OBJECTS:
        if obj["index"] == index and obj["sub"] == sub:
            return obj
    if index == 0x2000 and 1 <= sub <= 168:
        return {
            "index": 0x2000,
            "sub": sub,
            "access": "ro",
            "dtype": "INT16",
            "name": f"Hall element {sub}",
            "group": "Hall-Rohdaten",
            "process": True,
        }
    return None


def catalog() -> list[dict]:
    out = []
    for obj in OBJECTS:
        item = dict(obj)
        item["index_hex"] = f"0x{obj['index']:04X}"
        item["sub_hex"] = f"0x{obj['sub']:02X}"
        out.append(item)
    return out
