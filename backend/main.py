"""MLS operator HTTP/WebSocket API."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .objects import BITRATES, VARIANTS, VARIANT_TPDO1, catalog
from .sdo import SdoError
from .session import MlsSession

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

app = FastAPI(title="SICK MLS Operator", version="1.0.0")
session = MlsSession()


class ConnectBody(BaseModel):
    mode: str = "simulation"
    variant: str = "MLSE-0400"
    node_id: int = Field(10, ge=1, le=127)
    bitrate: int = 125000
    interface: str = "pcan"
    channel: str = "PCAN_USBBUS1"


class SdoReadBody(BaseModel):
    index: int
    sub: int = 0


class SdoWriteBody(BaseModel):
    index: int
    sub: int = 0
    value: Any


class NmtBody(BaseModel):
    command: int


class ScenarioBody(BaseModel):
    name: str = "single"


class SimTracksBody(BaseModel):
    tracks: list[dict[str, Any]]
    marker_code: int = 0


@app.get("/api/meta")
def meta() -> dict[str, Any]:
    return {
        "variants": VARIANTS,
        "bitrates": BITRATES,
        "variant_tpdo1": VARIANT_TPDO1,
        "objects": catalog(),
        "interfaces": ["pcan", "kvaser", "ixxat", "slcan", "socketcan", "usb2can", "vector", "virtual"],
        "nmt": {
            "start": 0x01,
            "stop": 0x02,
            "preop": 0x80,
            "reset_node": 0x81,
            "reset_communication": 0x82,
        },
    }


@app.get("/api/status")
def status() -> dict[str, Any]:
    return session.status()


@app.get("/api/process")
def process() -> dict[str, Any]:
    return session.process


@app.post("/api/connect")
def connect(body: ConnectBody) -> dict[str, Any]:
    try:
        if body.mode == "simulation":
            session.connect_sim(body.variant, body.node_id)
        else:
            session.connect_can(body.interface, body.channel, body.bitrate, body.node_id, body.variant)
        return session.status()
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/disconnect")
def disconnect() -> dict[str, Any]:
    session.disconnect()
    return session.status()


@app.post("/api/sdo/read")
def sdo_read(body: SdoReadBody) -> dict[str, Any]:
    try:
        return session.read_object(body.index, body.sub)
    except SdoError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/sdo/write")
def sdo_write(body: SdoWriteBody) -> dict[str, Any]:
    try:
        return session.write_object(body.index, body.sub, body.value)
    except SdoError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/nmt")
def nmt(body: NmtBody) -> dict[str, Any]:
    try:
        session.nmt(body.command)
        return session.status()
    except SdoError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/sim/scenario")
def sim_scenario(body: ScenarioBody) -> dict[str, Any]:
    try:
        session.set_scenario(body.name)
        return {"ok": True, "name": body.name}
    except SdoError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/hall")
def pull_hall() -> dict[str, Any]:
    try:
        session._pull_aux_hw(light=False)
        return {"ok": True, "count": len(session.process.get("hall") or [])}
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/sim/tracks")
def sim_tracks(body: SimTracksBody) -> dict[str, Any]:
    try:
        session.set_sim_tracks(body.tracks, body.marker_code)
        return {"ok": True}
    except SdoError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.websocket("/ws/process")
async def ws_process(ws: WebSocket) -> None:
    await ws.accept()
    queue: asyncio.Queue = asyncio.Queue(maxsize=8)
    loop = asyncio.get_event_loop()

    def on_frame(snap: dict[str, Any]) -> None:
        def push() -> None:
            if queue.full():
                try:
                    queue.get_nowait()
                except Exception:
                    pass
            try:
                queue.put_nowait(snap)
            except Exception:
                pass

        loop.call_soon_threadsafe(push)

    session.subscribe(on_frame)
    try:
        await ws.send_json(session.process)
        while True:
            try:
                snap = await asyncio.wait_for(queue.get(), timeout=1.0)
                await ws.send_json(snap)
            except asyncio.TimeoutError:
                await ws.send_json(session.process)
    except WebSocketDisconnect:
        pass
    finally:
        session.unsubscribe(on_frame)


if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")
