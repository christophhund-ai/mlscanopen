"""CANopen object dictionary for SICK MLS (MLSE-0200 … MLSE-0600)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Access = Literal["RO", "RW", "WO"]
DataType = Literal[
    "BOOL",
    "UINT8",
    "INT8",
    "UINT16",
    "INT16",
    "UINT32",
    "INT32",
    "STRING",
]


@dataclass(frozen=True)
class OdEntry:
    index: int
    sub: int
    access: Access
    data_type: DataType
    name: str
    default: int | str | None
    description: str
    unit: str = ""
    fw5: bool = False
    choices: tuple[tuple[int, str], ...] = ()


def _u(index: int, sub: int, access: Access, dtype: DataType, name: str, default, desc: str, **kw) -> OdEntry:
    return OdEntry(index, sub, access, dtype, name, default, desc, **kw)


VARIANTS = {
    "MLSE-0200": {"length_mm": 217, "range_mm": 200, "elements": 36, "rate_hz": 100},
    "MLSE-0300": {"length_mm": 325, "range_mm": 300, "elements": 54, "rate_hz": 100},
    "MLSE-0400": {"length_mm": 397, "range_mm": 400, "elements": 66, "rate_hz": 80},
    "MLSE-0500": {"length_mm": 505, "range_mm": 500, "elements": 84, "rate_hz": 70},
    "MLSE-0600": {"length_mm": 613, "range_mm": 600, "elements": 102, "rate_hz": 60},
}

TPDO1_VARIANTS = (
    (0, "Standard"),
    (1, "Combi"),
    (2, "Standard compensated"),
    (3, "Standard enhanced"),
    (4, "Standard enhanced compensated"),
    (5, "Combi compensated"),
    (6, "Combi enhanced"),
    (7, "Combi enhanced compensated"),
)

MARKER_STYLES = (
    (0, "Keine Marker-Erkennung"),
    (1, "SICK Standard (Codes 1–7)"),
    (2, "SICK Extended (Codes 1–10)"),
)

BITMAP_MODES = (
    (0, "Deaktiviert"),
    (1, "Beide Polaritäten"),
    (2, "Nur Süd"),
    (3, "Nur Nord"),
)

TAPE_POLARITY = (
    (0, "Beide Polaritäten"),
    (1, "Nur Nord-Spur"),
    (2, "Nur Süd-Spur"),
)

BITRATES = (10000, 20000, 50000, 100000, 125000, 250000, 500000, 800000, 1000000)

NCP_LCP = {
    0: "Keine Spur",
    2: "Eine Spur (LCP2)",
    3: "Zwei Spuren, Weiche links (LCP1+LCP2)",
    6: "Zwei Spuren, Weiche rechts (LCP2+LCP3)",
    7: "Drei Spuren oder Kreuzung",
}

OBJECT_DICTIONARY: list[OdEntry] = [
    _u(0x1000, 0, "RO", "UINT32", "Device type", None, "Kein Geräteprofil"),
    _u(0x1001, 0, "RO", "UINT8", "Error register", None, "Fehlerregister"),
    _u(0x1008, 0, "RO", "STRING", "Manufacturer device name", "Magnetic line guidance sensor", "Gerätename"),
    _u(0x1009, 0, "RO", "STRING", "Manufacturer hardware version", "1.0", "Hardware-Version"),
    _u(0x100A, 0, "RO", "STRING", "Manufacturer software version", "5.0", "Firmware-Version"),
    _u(0x100C, 0, "RW", "UINT16", "Guard time", 0, "Node Guarding nicht unterstützt", fw5=True),
    _u(0x100D, 0, "RW", "UINT8", "Life time factor", 0, "Node Guarding nicht unterstützt", fw5=True),
    _u(0x1010, 1, "RW", "UINT32", "Save all parameters", None, "Alle Parameter speichern (Wert 0x65766173 = 'save')"),
    _u(0x1017, 0, "RW", "UINT16", "Heartbeat time", 0, "Heartbeat-Zeit", unit="ms", fw5=True),
    _u(0x1018, 1, "RO", "UINT32", "Vendor-ID", 0x01000056, "SICK AG"),
    _u(0x1018, 2, "RO", "UINT32", "Product code", 0x00001100, "MLS"),
    _u(0x1018, 3, "RO", "UINT32", "Revision number", 0x00000005, "Revision"),
    _u(0x1018, 4, "RO", "UINT32", "Serial number", 0x24120001, "Format YYWW-nnnn"),
    _u(0x1200, 1, "RO", "UINT32", "SDO COB-ID client→server", None, "Master zum Sensor", fw5=True),
    _u(0x1200, 2, "RO", "UINT32", "SDO COB-ID server→client", None, "Sensor zum Master", fw5=True),
    _u(0x1F80, 0, "RW", "UINT32", "NMT Startup", 8, "Startverhalten", fw5=True),
    _u(0x2006, 1, "RW", "UINT8", "Variant TPDO1", 3, "Datenausgabe in TPDO1, Neustart nötig", choices=TPDO1_VARIANTS),
    _u(0x2006, 2, "RW", "UINT8", "Variant MEMS", 1, "IMU und Temperatursensor, Neustart nötig", choices=((0, "Aus"), (1, "Ein"))),
    _u(0x2019, 0, "RO", "UINT32", "Order number", 1094078, "Artikelnummer"),
    _u(0x2021, 1, "RO", "UINT16", "LCP1", None, "Line Center Point 1", unit="mm"),
    _u(0x2021, 2, "RO", "UINT16", "LCP2", None, "Line Center Point 2", unit="mm"),
    _u(0x2021, 3, "RO", "UINT16", "LCP3", None, "Line Center Point 3", unit="mm"),
    _u(0x2021, 4, "RO", "UINT8", "#LCP", None, "Anzahl erkannter Spuren und Marker"),
    _u(0x2021, 5, "RO", "UINT8", "LCP1_width", None, "Spurbreite 1", unit="mm", fw5=True),
    _u(0x2021, 6, "RO", "UINT8", "LCP2_width", None, "Spurbreite 2", unit="mm", fw5=True),
    _u(0x2021, 7, "RO", "UINT8", "LCP3_width", None, "Spurbreite 3", unit="mm", fw5=True),
    _u(0x2021, 8, "RO", "UINT16", "LCP1_Combi", None, "LCP1 + Breite kombiniert", fw5=True),
    _u(0x2021, 9, "RO", "UINT16", "LCP2_Combi", None, "LCP2 + Breite kombiniert", fw5=True),
    _u(0x2021, 0xA, "RO", "UINT16", "LCP3_Combi", None, "LCP3 + Breite kombiniert", fw5=True),
    _u(0x2021, 0xB, "RO", "INT8", "Line Level 1", None, "Feldstärke Spur 1, LSB = 0,048 mT", fw5=True),
    _u(0x2021, 0xC, "RO", "INT8", "Line Level 2", None, "Feldstärke Spur 2", fw5=True),
    _u(0x2021, 0xD, "RO", "INT8", "Line Level 3", None, "Feldstärke Spur 3", fw5=True),
    _u(0x2022, 0, "RO", "UINT8", "Status", None, "Statusbyte wie in TPDO1"),
    _u(0x2023, 0, "RO", "UINT16", "Track Level", None, "Bewertung der Feldstärke"),
    _u(0x2024, 0, "RO", "UINT16", "Field level", None, "Feldstärke volle Auflösung (0,00076 mT)"),
    _u(0x2025, 0, "RW", "UINT16", "Min. level", 200, "Mindest-Feldstärke für Spurerkennung"),
    _u(0x2026, 0, "RW", "INT16", "Offset", 0, "Nullpunkt-Offset", unit="mm"),
    _u(0x2027, 0, "RW", "BOOL", "Sensor flipped", 0, "0 = negativer Bereich am Kabelabgang"),
    _u(0x2028, 1, "RW", "BOOL", "Use markers", 0, "Marker in TPDO1 ausgeben"),
    _u(0x2028, 2, "RW", "UINT8", "Marker style", 0, "Marker-Modus", choices=MARKER_STYLES),
    _u(0x2028, 3, "RW", "BOOL", "Failsafe mode", 0, "Code erst nach vollständigem Überfahren"),
    _u(0x2029, 0, "RW", "BOOL", "Lock teach", 0, "Teach-Taste sperren"),
    _u(0x202A, 0, "WO", "BOOL", "Set param. to default", None, "1 = Werkseinstellungen"),
    _u(0x202B, 0, "WO", "BOOL", "Trigger user offset calibration", None, "1 = Hall-Offset kalibrieren, danach Neustart"),
    _u(0x202C, 0, "WO", "BOOL", "Trigger zero position teach", None, "1 = aktuelle Position als Nullpunkt"),
    _u(0x202D, 1, "RW", "UINT8", "First Level", 30, "Detection Level in % des Hauptpeaks", fw5=True),
    _u(0x202D, 2, "RW", "UINT8", "Last level", 30, "Soll = First Level", fw5=True),
    _u(0x202D, 3, "RW", "UINT8", "Averaging magnetic", 1, "IIR-Filter Spurwerte 0–4", fw5=True),
    _u(0x202D, 4, "RW", "UINT8", "Averaging inertial", 0, "Tiefpass Orientierung 0–100", fw5=True),
    _u(0x202D, 5, "RW", "UINT8", "Tape polarity", 0, "Spurpolarität", choices=TAPE_POLARITY, fw5=True),
    _u(0x202F, 1, "RW", "UINT16", "Bitmap threshold", 500, "Bitmap-Schwelle", fw5=True),
    _u(0x202F, 2, "RW", "UINT8", "Bitmap mode", 0, "Bitmap-Modus", choices=BITMAP_MODES, fw5=True),
    _u(0x2030, 1, "RO", "INT16", "Roll", None, "Euler φ", unit="1/10000 rad", fw5=True),
    _u(0x2030, 2, "RO", "INT16", "Pitch", None, "Euler θ", unit="1/10000 rad", fw5=True),
    _u(0x2030, 3, "RO", "INT16", "Yaw", None, "Euler ψ", unit="1/10000 rad", fw5=True),
    _u(0x2031, 1, "RO", "INT16", "Quaternion w", None, "Realteil /10000", fw5=True),
    _u(0x2031, 2, "RO", "INT16", "Quaternion x", None, "Imaginärteil /10000", fw5=True),
    _u(0x2031, 3, "RO", "INT16", "Quaternion y", None, "Imaginärteil /10000", fw5=True),
    _u(0x2031, 4, "RO", "INT16", "Quaternion z", None, "Imaginärteil /10000", fw5=True),
    _u(0x2032, 1, "WO", "UINT8", "Reset yaw", None, "1 = Gierwinkel auf 0", fw5=True),
    _u(0x2032, 2, "WO", "UINT8", "Reset acceleration peaks", None, "1 = Beschleunigungspeaks zurücksetzen", fw5=True),
    _u(0x2033, 1, "RO", "INT16", "Accel X", None, "2^-11 g", fw5=True),
    _u(0x2033, 2, "RO", "INT16", "Accel Y", None, "2^-11 g", fw5=True),
    _u(0x2033, 3, "RO", "INT16", "Accel Z", None, "2^-11 g", fw5=True),
    _u(0x2034, 1, "RO", "INT16", "Gyro X", None, "125·2^-11 °/s", fw5=True),
    _u(0x2034, 2, "RO", "INT16", "Gyro Y", None, "125·2^-11 °/s", fw5=True),
    _u(0x2034, 3, "RO", "INT16", "Gyro Z", None, "125·2^-11 °/s", fw5=True),
    _u(0x2035, 0, "RO", "UINT16", "Sample time stamp", None, "Zeitstempel", unit="ms", fw5=True),
    _u(0x2070, 1, "RO", "INT8", "Current temperature", None, "Aktuelle Temperatur", unit="°C", fw5=True),
    _u(0x2070, 2, "RO", "INT8", "Max. temperature all time", None, "Max. über Lebensdauer", unit="°C", fw5=True),
    _u(0x2070, 3, "RO", "INT8", "Min. temperature all time", None, "Min. über Lebensdauer", unit="°C", fw5=True),
    _u(0x2070, 4, "RW", "INT8", "Max. temperature since last reset", None, "Max. seit Reset", unit="°C", fw5=True),
    _u(0x2070, 5, "RW", "INT8", "Min. temperature since last reset", None, "Min. seit Reset", unit="°C", fw5=True),
    _u(0x2070, 6, "RW", "INT8", "Upper temperature threshold", 80, "Ereignis oberhalb", unit="°C", fw5=True),
    _u(0x2070, 7, "RW", "INT8", "Lower temperature threshold", -30, "Ereignis unterhalb", unit="°C", fw5=True),
    _u(0x2080, 1, "WO", "UINT8", "Reset event flag", None, "Ereignis-Flag zurücksetzen", fw5=True),
    _u(0x2080, 2, "RO", "UINT8", "Event source", None, "0 keine, 2 Magnet, 4 Temp, 6 beide", fw5=True),
    _u(0x2080, 4, "RO", "UINT8", "Magnetic field event", None, "0 keine, 1 Feld zu schwach", fw5=True),
    _u(0x2080, 5, "RO", "UINT8", "Temperature event", None, "0 keine, 1 unter, 2 über Schwelle", fw5=True),
]

for pdo, idx, default_cob in (
    (1, 0x1800, 0x0000018A),
    (2, 0x1801, 0x8000028A),
    (3, 0x1802, 0x8000038A),
    (4, 0x1803, 0x8000048A),
    (5, 0x1804, 0x80000000),
    (6, 0x1805, 0x80000000),
    (7, 0x1806, 0x80000000),
):
    OBJECT_DICTIONARY.extend(
        [
            _u(idx, 1, "RW", "UINT32", f"TPDO{pdo} COB-ID", default_cob, "MSB gesetzt = deaktiviert", fw5=pdo >= 2),
            _u(idx, 2, "RW", "UINT8", f"TPDO{pdo} transmission type", 0xFF, "0xFE oder 0xFF event-driven", fw5=pdo >= 2),
            _u(idx, 5, "RW", "UINT16", f"TPDO{pdo} event timer", 0x000A if pdo == 1 else 0, "Zykluszeit", unit="ms", fw5=pdo >= 2),
        ]
    )

for sub in range(1, 0xA9):
    OBJECT_DICTIONARY.append(
        _u(0x2000, sub, "RO", "INT16", f"Hall element {sub}", None, "Rohwert Hall-Element")
    )

for sub in range(1, 5):
    OBJECT_DICTIONARY.append(
        _u(0x202E, sub, "RO", "UINT32", f"Bitmap bytes {(sub - 1) * 4 + 1}-{sub * 4}", None, "Digitale Feldkarte Elemente", fw5=True)
    )

OD_BY_KEY = {(e.index, e.sub): e for e in OBJECT_DICTIONARY}


def od_as_json() -> list[dict]:
    rows = []
    for e in OBJECT_DICTIONARY:
        if e.index == 0x2000:
            continue
        rows.append(
            {
                "index": e.index,
                "indexHex": f"0x{e.index:04X}",
                "sub": e.sub,
                "subHex": f"0x{e.sub:02X}",
                "access": e.access,
                "dataType": e.data_type,
                "name": e.name,
                "default": e.default,
                "description": e.description,
                "unit": e.unit,
                "fw5": e.fw5,
                "choices": [{"value": v, "label": l} for v, l in e.choices],
            }
        )
    return rows
