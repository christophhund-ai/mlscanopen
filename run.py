"""Start the MLS operator UI."""

from __future__ import annotations

import socket
import sys
import webbrowser

import uvicorn

HOST = "127.0.0.1"
PORT = 8765
URL = f"http://{HOST}:{PORT}"


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


if __name__ == "__main__":
    if port_in_use(HOST, PORT):
        print(f"MLS Operator laeuft bereits: {URL}")
        print("Ein neuer Start ist nicht noetig. Browser wird geoeffnet.")
        webbrowser.open(URL)
        input("Enter zum Schliessen dieses Fensters...")
        sys.exit(0)

    print(f"MLS Operator: {URL}")
    webbrowser.open(URL)
    uvicorn.run("backend.main:app", host=HOST, port=PORT, reload=False)
