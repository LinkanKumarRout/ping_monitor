from __future__ import annotations

import platform
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.store import ROOT, load_ips

LOGS_DIR = ROOT / "logs"
ERROR_LOG = LOGS_DIR / "ping_errors.log"
PING_INTERVAL_SEC = 1.0
PING_TIMEOUT_SEC = 1
IS_WINDOWS = platform.system().lower() == "windows"


@dataclass
class TargetState:
    ip: str
    state: str = "idle"  # idle | ok | fail
    last_ok_at: str | None = None
    last_fail_at: str | None = None
    fail_count: int = 0
    last_message: str | None = None


@dataclass
class Monitor:
    running: bool = False
    targets: dict[str, TargetState] = field(default_factory=dict)
    _threads: dict[str, threading.Thread] = field(default_factory=dict)
    _stop: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def status(self) -> dict[str, Any]:
        with self._lock:
            targets = [
                {
                    "ip": t.ip,
                    "state": t.state,
                    "last_ok_at": t.last_ok_at,
                    "last_fail_at": t.last_fail_at,
                    "fail_count": t.fail_count,
                    "last_message": t.last_message,
                }
                for t in sorted(self.targets.values(), key=lambda x: x.ip)
            ]
            return {"running": self.running, "targets": targets}

    def sync_targets_from_store(self) -> None:
        ips = load_ips()
        with self._lock:
            for ip in ips:
                if ip not in self.targets:
                    self.targets[ip] = TargetState(ip=ip)
            for ip in list(self.targets):
                if ip not in ips:
                    del self.targets[ip]

    def start(self) -> dict[str, Any]:
        self.sync_targets_from_store()
        with self._lock:
            if not self.targets:
                raise ValueError("add at least one IP before starting")
            if self.running:
                return self.status()
            self._stop.clear()
            self.running = True
            for ip, target in self.targets.items():
                target.state = "idle"
                target.last_message = "starting"
                thread = threading.Thread(
                    target=self._loop,
                    args=(ip,),
                    name=f"ping-{ip}",
                    daemon=True,
                )
                self._threads[ip] = thread
                thread.start()
        return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._stop.set()
            self.running = False
            threads = list(self._threads.values())
            self._threads.clear()
            for target in self.targets.values():
                if target.state in ("ok", "fail"):
                    target.state = "idle"
                    target.last_message = "stopped"
        for thread in threads:
            thread.join(timeout=2.0)
        return self.status()

    def on_ip_added(self, ip: str) -> None:
        """Update in-memory list only while stopped (API enforces stopped)."""
        with self._lock:
            if ip not in self.targets:
                self.targets[ip] = TargetState(ip=ip, state="idle", last_message="added")

    def on_ip_removed(self, ip: str) -> None:
        """Drop in-memory target only while stopped (API enforces stopped)."""
        with self._lock:
            self.targets.pop(ip, None)
            self._threads.pop(ip, None)

    def _loop(self, ip: str) -> None:
        while not self._stop.is_set():
            if ip not in load_ips():
                break
            ok, message = _ping_once(ip)
            now = _now()
            with self._lock:
                target = self.targets.get(ip)
                if target is None:
                    break
                if ok:
                    target.state = "ok"
                    target.last_ok_at = now
                    target.last_message = message
                else:
                    target.state = "fail"
                    target.last_fail_at = now
                    target.fail_count += 1
                    target.last_message = message
                    _append_error(ip, message, now)
            # Sleep in small slices so Stop responds quickly.
            deadline = time.monotonic() + PING_INTERVAL_SEC
            while time.monotonic() < deadline:
                if self._stop.is_set():
                    return
                time.sleep(0.05)
        with self._lock:
            self._threads.pop(ip, None)


monitor = Monitor()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _append_error(ip: str, message: str, timestamp: str) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{timestamp} ERROR ping failed ip={ip} detail={message}\n"
    with open(ERROR_LOG, "a", encoding="utf-8") as fh:
        fh.write(line)


def _ping_cmd(ip: str) -> list[str]:
    # Linux/macOS: -c count, -W timeout seconds
    # Windows: -n count, -w timeout milliseconds (-c is "compartment" and needs admin)
    if IS_WINDOWS:
        return ["ping", "-n", "1", "-w", str(PING_TIMEOUT_SEC * 1000), ip]
    return ["ping", "-c", "1", "-W", str(PING_TIMEOUT_SEC), ip]


def _ping_once(ip: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            _ping_cmd(ip),
            capture_output=True,
            text=True,
            timeout=PING_TIMEOUT_SEC + 2,
        )
    except FileNotFoundError:
        return False, "ping command not found"
    except subprocess.TimeoutExpired:
        return False, "ping subprocess timeout"
    except OSError as exc:
        return False, f"os error: {exc}"

    if result.returncode == 0:
        return True, "ok"
    err = (result.stderr or result.stdout or "no reply").strip().splitlines()
    detail = err[-1] if err else f"exit={result.returncode}"
    return False, detail[:200]


def read_error_log(limit: int = 200) -> list[str]:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    if not ERROR_LOG.exists():
        return []
    try:
        lines = ERROR_LOG.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    if limit <= 0:
        return lines
    return lines[-limit:]


def clear_error_log() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ERROR_LOG.write_text("", encoding="utf-8")
