"""MLS Operator – FastAPI backend."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .bus import SESSION
from .objects import BITRATES, VARIANTS, od_as_json
from .protocol import NMT_PREOP, NMT_RESET_COMM, NMT_RESET_NODE, NMT_START, NMT_STOP

STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="MLS Operator", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class ConnectBody(BaseModel):
    interface: str = "simulator"
    channel: str = ""
    bitrate: int = 125000
    nodeId: int = 10
    variant: str = "MLSE-0300"


class SdoReadBody(BaseModel):
    index: int
    sub: int = 0


class SdoWriteBody(BaseModel):
    index: int
    sub: int = 0
    value: Any


class NmtBody(BaseModel):
    command: int
    target: int | None = None


class SimBody(BaseModel):
    variant: str | None = None
    autoMove: bool | None = None
    trackCount: int | None = None
    tracks: list[dict] | None = None
    marker: dict | None = None
    useMarkers: bool | None = None


class TpdoEnableBody(BaseModel):
    pdo: int = Field(ge=1, le=7)
    enabled: bool = True
    cobId: int | None = None
    eventTimerMs: int | None = None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/meta")
def meta() -> dict:
    return {
        "variants": VARIANTS,
        "bitrates": BITRATES,
        "objects": od_as_json(),
        "interfaces": [
            {"id": "simulator", "label": "Simulator (ohne Hardware)"},
            {"id": "pcan", "label": "PEAK PCAN-USB"},
            {"id": "kvaser", "label": "Kvaser"},
            {"id": "slcan", "label": "SLCAN / USB-CAN (COM-Port)"},
            {"id": "usb2can", "label": "USB2CAN"},
            {"id": "ixxat", "label": "IXXAT"},
            {"id": "canalystii", "label": "CANalyst-II"},
            {"id": "virtual", "label": "python-can virtual"},
        ],
        "nmt": {
            "start": NMT_START,
            "stop": NMT_STOP,
            "preop": NMT_PREOP,
            "resetNode": NMT_RESET_NODE,
            "resetComm": NMT_RESET_COMM,
        },
    }


@app.get("/api/ports")
def ports() -> dict:
    try:
        import serial.tools.list_ports

        items = [{"device": p.device, "description": p.description} for p in serial.tools.list_ports.comports()]
    except Exception:
        items = []
    return {"ports": items}


@app.get("/api/status")
def status() -> dict:
    return {
        "connected": SESSION.connected,
        "mode": SESSION.mode,
        "nodeId": SESSION.node_id,
        "bitrate": SESSION.bitrate,
        "interface": SESSION.interface,
        "variant": SESSION.variant,
        "process": SESSION._process_view() if SESSION.connected else None,
    }


@app.post("/api/connect")
def connect(body: ConnectBody) -> dict:
    return SESSION.connect(body.model_dump())


@app.post("/api/disconnect")
def disconnect() -> dict:
    SESSION.disconnect()
    return {"ok": True}


@app.post("/api/sdo/read")
def sdo_read(body: SdoReadBody) -> dict:
    if not SESSION.connected:
        return {"ok": False, "error": "Nicht verbunden"}
    return SESSION.sdo_read(body.index, body.sub)


@app.post("/api/sdo/write")
def sdo_write(body: SdoWriteBody) -> dict:
    if not SESSION.connected:
        return {"ok": False, "error": "Nicht verbunden"}
    return SESSION.sdo_write(body.index, body.sub, body.value)


@app.post("/api/sdo/read-many")
def sdo_read_many(keys: list[SdoReadBody]) -> dict:
    if not SESSION.connected:
        return {"ok": False, "error": "Nicht verbunden"}
    results = []
    for item in keys:
        results.append(SESSION.sdo_read(item.index, item.sub))
    return {"ok": True, "results": results}


@app.post("/api/nmt")
def nmt(body: NmtBody) -> dict:
    if not SESSION.connected:
        return {"ok": False, "error": "Nicht verbunden"}
    SESSION.nmt(body.command, body.target)
    return {"ok": True}


@app.post("/api/sim")
def sim(body: SimBody) -> dict:
    SESSION.configure_sim(body.model_dump(exclude_none=True))
    return {"ok": True, "mode": SESSION.mode}


@app.post("/api/tpdo")
def tpdo(body: TpdoEnableBody) -> dict:
    if not SESSION.connected:
        return {"ok": False, "error": "Nicht verbunden"}
    idx = 0x1800 + body.pdo - 1
    if body.cobId is not None:
        cob = body.cobId
    else:
        defaults = {1: 0x180, 2: 0x280, 3: 0x380, 4: 0x480}
        cob = defaults.get(body.pdo, 0x180) + SESSION.node_id
    if not body.enabled:
        cob = 0x80000000 | cob
    wr = SESSION.sdo_write(idx, 1, cob)
    if body.eventTimerMs is not None:
        SESSION.sdo_write(idx, 5, body.eventTimerMs)
        SESSION.sdo_write(idx, 2, 0xFF)
    return wr


@app.get("/api/hall")
def hall() -> dict:
    if not SESSION.connected:
        return {"ok": False, "error": "Nicht verbunden"}
    if SESSION.sim is not None:
        return {
            "ok": True,
            "hall": SESSION.hall,
            "positionsMm": SESSION.sim.element_positions(),
            "elements": SESSION.elements,
        }
    values = []
    for sub in range(1, SESSION.elements + 1):
        r = SESSION.sdo_read(0x2000, sub, timeout=0.15)
        if not r.get("ok"):
            break
        values.append(int(r.get("value", 0)))
    half = SESSION.range_mm / 2
    n = max(len(values), 1)
    positions = [(-half + i * (SESSION.range_mm / max(n - 1, 1))) for i in range(len(values))]
    SESSION.hall = values
    return {"ok": True, "hall": values, "positionsMm": positions, "elements": len(values)}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    queue: asyncio.Queue = asyncio.Queue(maxsize=8)
    loop = asyncio.get_running_loop()

    def on_event(event: dict) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, event)
        except Exception:
            pass

    SESSION.listeners.append(on_event)
    try:
        await ws.send_text(json.dumps({"type": "hello", "connected": SESSION.connected, "mode": SESSION.mode}))
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=20)
                await ws.send_text(json.dumps(event, default=str))
            except TimeoutError:
                await ws.send_text(json.dumps({"type": "ping"}))
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        if on_event in SESSION.listeners:
            SESSION.listeners.remove(on_event)


def run() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":
    run()
