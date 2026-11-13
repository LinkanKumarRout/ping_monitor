from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.pinger import clear_error_log, monitor, read_error_log
from app.store import add_ip, load_ips, remove_ip, validate_target

APP_DISPLAY_NAME = "Ping Monitor"
_PKG_DIR = Path(__file__).resolve().parent

app = FastAPI(title=APP_DISPLAY_NAME, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(_PKG_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(_PKG_DIR / "templates"))


class IpBody(BaseModel):
    ip: str = Field(..., min_length=1, max_length=253)


@app.on_event("startup")
def _startup() -> None:
    monitor.sync_targets_from_store()


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    # Starlette 1.x: TemplateResponse(request, name, context)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "title": APP_DISPLAY_NAME,
            "app_name": APP_DISPLAY_NAME,
        },
    )


@app.get("/api/status")
def api_status() -> dict:
    monitor.sync_targets_from_store()
    return monitor.status()


@app.get("/api/ips")
def api_list_ips() -> dict:
    return {"ips": load_ips()}


def _require_stopped() -> None:
    if monitor.running:
        raise HTTPException(
            status_code=409,
            detail="Stop monitoring before adding or removing IPs",
        )


@app.post("/api/ips")
def api_add_ip(body: IpBody) -> dict:
    _require_stopped()
    try:
        target = validate_target(body.ip)
        ips = add_ip(target)  # writes data/ips.json immediately
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    monitor.on_ip_added(target)
    return {"ips": ips, "status": monitor.status()}


@app.delete("/api/ips/{ip}")
def api_remove_ip(ip: str) -> dict:
    _require_stopped()
    try:
        target = validate_target(ip)
        ips = remove_ip(target)  # writes data/ips.json immediately
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    monitor.on_ip_removed(target)
    return {"ips": ips, "status": monitor.status()}


@app.post("/api/start")
def api_start() -> dict:
    try:
        return monitor.start()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/stop")
def api_stop() -> dict:
    return monitor.stop()


@app.get("/api/logs")
def api_logs(limit: int = 200) -> dict:
    limit = max(1, min(limit, 2000))
    return {"lines": read_error_log(limit)}


@app.post("/api/logs/clear")
def api_clear_logs() -> dict:
    clear_error_log()
    return {"ok": True, "lines": []}
