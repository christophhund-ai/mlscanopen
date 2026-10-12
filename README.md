# SICK MLS Operator

Bedienoberfläche für den SICK MLS-Linienführungssensor (MLSE-0200 … MLSE-0600) nach Betriebsanleitung 8021642.

Die App spricht CANopen: **TPDOs** für Live-Prozessdaten, **SDOs** für Service- und Konfigurationsobjekte, **NMT** für den Gerätezustand. Ohne Hardware startet eine Simulation.

## Start

```bat
run.bat
```

Oder:

```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe run.py
```

Im Browser: [http://127.0.0.1:8765](http://127.0.0.1:8765)

## Funktionen

- Live-Draufsicht: bis zu drei Spuren (LCP1–3), Spurbreite, Marker-Code auf 30-mm-Raster
- Hall-Profil und Bitmap (Firmware V5)
- Prozessdaten lesen; beschreibbare Prozessparameter schreiben
- Vollständiges Objektverzeichnis (Servicedaten) lesen/schreiben
- NMT, TPDO COB-ID / Event-Timer
- Simulation mit Weichen, Kreuzung, Marker, schwachem Feld

## Hardware

Werkseitig: **Node-ID 10**, **125 kbit/s**, TPDO1 alle 10 ms.

Windows-Interfaces über `python-can`, z. B.:

| Interface | Kanal-Beispiel |
|-----------|----------------|
| pcan | `PCAN_USBBUS1` |
| kvaser | `0` |
| slcan | `COM3` |
| ixxat | `0` |

Adapter-Treiber müssen installiert sein. Maximal vier TPDOs gleichzeitig; gültige COB-IDs `0x180/280/380/480 + Node-ID`.
