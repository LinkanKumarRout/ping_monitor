# Ping Monitor

Simple continuous ICMP monitor with a saf_edge-style UI.

- Add IPs / hostnames one by one (writes `data/ips.json` immediately)
- Add/remove only while **Stopped** (API returns 409 if running)
- **Start** pings every target every **1 second**
- Every failed ping is appended to `logs/ping_errors.log` with a timestamp
- **Stop** ends all ping loops
- Live per-IP status (OK / FAIL) in the UI

## Run

```bash
cd ping_monitor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8090
```

Open http://127.0.0.1:8090

## Notes

- Uses system `ping`:
  - Linux/macOS: `ping -c 1 -W 1 <host>`
  - Windows: `ping -n 1 -w 1000 <host>`
- Monitoring always starts **Stopped** after a process restart; the IP list is kept.
- Add/remove IPs only while Stopped.
