from __future__ import annotations

import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # pragma: no cover - exercised on machines without pyserial
    serial = None
    list_ports = None


POSITION_RE = re.compile(r"\b([XYZ])(-?\d+(?:\.\d+)?)", re.IGNORECASE)
SPINDLE_RE = re.compile(r"\bS\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)


@dataclass
class ControllerStatus:
    mode: str
    connected: bool
    state: str
    port: str | None
    baud: int | None
    mpos: tuple[float, float, float]
    feed: int
    spindle: int
    last_response: str
    active_pins: tuple[str, ...]

    def to_dict(self) -> dict:
        active = set(self.active_pins)
        return {
            "mode": self.mode,
            "connected": self.connected,
            "state": self.state,
            "port": self.port,
            "baud": self.baud,
            "mpos": {"x": self.mpos[0], "y": self.mpos[1], "z": self.mpos[2]},
            "feed": self.feed,
            "spindle": self.spindle,
            "last_response": self.last_response,
            "active_pins": list(self.active_pins),
            "limit_switches": {
                "x": "X" in active,
                "y": "Y" in active,
                "z": "Z" in active,
            },
        }


class BaseController:
    mode = "base"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._log: Deque[str] = deque(maxlen=400)
        self.connected = False
        self.port: str | None = None
        self.baud: int | None = None
        self.state = "Disconnected"
        self.mpos = (0.0, 0.0, 0.0)
        self.feed = 0
        self.spindle = 0
        self.last_response = ""
        self.active_pins: tuple[str, ...] = ()

    def log(self, entry: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self._log.append(f"[{stamp}] {entry}")

    def log_tail(self, limit: int = 80) -> list[str]:
        return list(self._log)[-limit:]

    def connect(self, port: str | None = None, baud: int = 115200) -> None:
        raise NotImplementedError

    def disconnect(self) -> None:
        self.connected = False
        self.state = "Disconnected"
        self.feed = 0
        self.spindle = 0
        self.active_pins = ()
        self.log("Disconnected")

    def send_line(self, line: str, timeout: float = 15.0) -> str:
        raise NotImplementedError

    def status(self) -> ControllerStatus:
        return ControllerStatus(
            mode=self.mode,
            connected=self.connected,
            state=self.state,
            port=self.port,
            baud=self.baud,
            mpos=self.mpos,
            feed=self.feed,
            spindle=self.spindle,
            last_response=self.last_response,
            active_pins=self.active_pins,
        )

    def feed_hold(self) -> None:
        self.send_line("!")

    def cycle_start(self) -> None:
        self.send_line("~")

    def soft_reset(self) -> None:
        self.send_line("\x18")


class SimulatorController(BaseController):
    mode = "simulator"

    def connect(self, port: str | None = None, baud: int = 115200) -> None:
        with self._lock:
            self.connected = True
            self.port = port or "SIMULATOR"
            self.baud = baud
            self.state = "Idle"
            self.last_response = "ok"
            self.log("Simulator connected")

    def _apply_motion(self, line: str) -> None:
        x, y, z = self.mpos
        for axis, value in POSITION_RE.findall(line):
            if axis.upper() == "X":
                x = float(value)
            elif axis.upper() == "Y":
                y = float(value)
            elif axis.upper() == "Z":
                z = float(value)
        spindle = SPINDLE_RE.search(line)
        if spindle:
            self.spindle = max(0, int(float(spindle.group(1))))
        if re.search(r"\bM0?5\b", line, re.IGNORECASE):
            self.spindle = 0
        if "$H" in line:
            self.mpos = (0.0, 0.0, 0.0)
        else:
            self.mpos = (x, y, z)

    def send_line(self, line: str, timeout: float = 15.0) -> str:
        with self._lock:
            if not self.connected:
                raise RuntimeError("Simulator is not connected.")
            clean = line.strip()
            self.log(f"> {clean.encode('unicode_escape').decode()}")
            if clean == "?":
                response = f"<{self.state}|MPos:{self.mpos[0]:.3f},{self.mpos[1]:.3f},{self.mpos[2]:.3f}|FS:{self.feed},{self.spindle}>"
            elif clean == "!":
                self.state = "Hold"
                response = "ok"
            elif clean == "~":
                self.state = "Idle"
                response = "ok"
            elif clean == "\x18":
                self.state = "Idle"
                self.spindle = 0
                response = "Grbl 1.1h ['$' for help]"
            else:
                self.state = "Run" if clean.startswith(("G0", "G1", "$J")) else self.state
                self._apply_motion(clean)
                time.sleep(0.004)
                self.state = "Idle"
                response = "ok"
            self.last_response = response
            self.log(f"< {response}")
            return response


class GrblSerialController(BaseController):
    mode = "serial"

    def __init__(self) -> None:
        super().__init__()
        self._serial = None

    def _mark_serial_fault(self, exc: Exception) -> None:
        self.last_response = str(exc)
        self.connected = False
        self.state = "Disconnected"
        self.feed = 0
        self.spindle = 0
        self.active_pins = ()
        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
        self.log(f"! serial connection lost: {exc}")

    def connect(self, port: str | None = None, baud: int = 115200) -> None:
        if serial is None:
            raise RuntimeError("pyserial is not installed.")
        if not port:
            raise RuntimeError("A serial port is required.")
        with self._lock:
            self._serial = serial.Serial(port, baud, timeout=0.2, write_timeout=2)
            self.connected = True
            self.port = port
            self.baud = baud
            self.state = "Connecting"
            time.sleep(1.8)
            self._serial.reset_input_buffer()
            self._serial.write(b"\r\n\r\n")
            self._serial.flush()
            time.sleep(0.3)
            self._drain()
            self.state = "Idle"
            self.last_response = "connected"
            self.log(f"Serial connected on {port} at {baud}")

    def disconnect(self) -> None:
        with self._lock:
            if self._serial:
                try:
                    self._serial.close()
                finally:
                    self._serial = None
            super().disconnect()

    def _readline(self) -> str:
        if not self._serial:
            return ""
        raw = self._serial.readline()
        if not raw:
            return ""
        return raw.decode("utf-8", errors="replace").strip()

    def _drain(self) -> None:
        deadline = time.monotonic() + 0.8
        while time.monotonic() < deadline:
            line = self._readline()
            if line:
                self.log(f"< {line}")
            else:
                break

    def send_line(self, line: str, timeout: float = 15.0) -> str:
        with self._lock:
            if not self.connected or not self._serial:
                raise RuntimeError("Controller is not connected.")
            try:
                clean = line.strip()
                if clean == "\x18":
                    self._serial.write(b"\x18")
                    self._serial.flush()
                    self.log("> soft reset")
                    time.sleep(0.5)
                    self._drain()
                    self.state = "Idle"
                    self.spindle = 0
                    self.last_response = "soft reset"
                    return self.last_response
                if clean in {"!", "~"}:
                    self._serial.write(clean.encode("ascii"))
                    self._serial.flush()
                    self.log(f"> {clean}")
                    self.last_response = "realtime command sent"
                    return self.last_response
                if clean == "?":
                    payload = clean.encode("ascii")
                else:
                    payload = (clean + "\n").encode("ascii", errors="ignore")
                self._serial.write(payload)
                self._serial.flush()
                self.log(f"> {clean}")
                deadline = time.monotonic() + timeout
                responses: list[str] = []
                while time.monotonic() < deadline:
                    response = self._readline()
                    if not response:
                        continue
                    responses.append(response)
                    self.log(f"< {response}")
                    if response.startswith("<"):
                        self._parse_status_line(response)
                        if clean == "?":
                            self.last_response = response
                            return response
                    low = response.lower()
                    if low.startswith(("ok", "error", "alarm")):
                        self.last_response = response
                        return response
                joined = " | ".join(responses[-4:]) if responses else "no response"
                raise TimeoutError(f"Timed out waiting for controller response: {joined}")
            except Exception as exc:
                self._mark_serial_fault(exc)
                raise

    def _poll_status(self, timeout: float = 1.0) -> None:
        if not self._serial:
            return
        self._serial.write(b"?")
        self._serial.flush()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            response = self._readline()
            if not response:
                continue
            if response.startswith("<"):
                self._parse_status_line(response)
                self.last_response = response
                return

    def status(self) -> ControllerStatus:
        if self.connected:
            try:
                self._poll_status(timeout=1.0)
            except Exception as exc:  # status polling should not break the UI
                self._mark_serial_fault(exc)
        return super().status()

    def _parse_status_line(self, line: str) -> None:
        body = line.strip("<>")
        parts = body.split("|")
        saw_pins = False
        if parts:
            self.state = parts[0]
        for part in parts[1:]:
            if part.startswith(("MPos:", "WPos:")):
                values = part.split(":", 1)[1].split(",")
                if len(values) >= 3:
                    self.mpos = (float(values[0]), float(values[1]), float(values[2]))
            elif part.startswith("FS:"):
                values = part.split(":", 1)[1].split(",")
                if values:
                    self.feed = int(float(values[0]))
                if len(values) > 1:
                    self.spindle = int(float(values[1]))
            elif part.startswith("Pn:"):
                saw_pins = True
                pins = part.split(":", 1)[1].upper()
                self.active_pins = tuple(pin for pin in pins if pin.isalpha())
        if not saw_pins:
            self.active_pins = ()


def available_ports() -> list[dict]:
    if list_ports is None:
        return []
    ports = []
    for port in list_ports.comports():
        ports.append(
            {
                "device": port.device,
                "description": port.description,
                "hwid": port.hwid,
            }
        )
    return ports
