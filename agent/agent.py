import os
import re
import socket
import subprocess
import time
from datetime import datetime, timezone

import psutil
import requests
from dotenv import load_dotenv

load_dotenv()

MONITOR_API_URL = os.getenv("MONITOR_API_URL", "http://127.0.0.1:8000/api/v1/ingest")
MONITOR_API_TOKEN = os.getenv("MONITOR_API_TOKEN", "")
MONITOR_ENVIRONMENT = os.getenv("MONITOR_ENVIRONMENT", "production")
MONITOR_TAGS = [tag.strip() for tag in os.getenv("MONITOR_TAGS", "").split(",") if tag.strip()]
MONITOR_INTERVAL_SECONDS = int(os.getenv("MONITOR_INTERVAL_SECONDS", "15"))
MONITOR_TIMEOUT_SECONDS = int(os.getenv("MONITOR_TIMEOUT_SECONDS", "20"))
MONITOR_SERVICES = [svc.strip() for svc in os.getenv("MONITOR_SERVICES", "").split(",") if svc.strip()]
MONITOR_NGINX_ENABLED = os.getenv("MONITOR_NGINX_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
MONITOR_NGINX_STATUS_URL = os.getenv("MONITOR_NGINX_STATUS_URL", "http://127.0.0.1:8080/nginx_status")
MONITOR_NGINX_VERIFY_TLS = os.getenv("MONITOR_NGINX_VERIFY_TLS", "true").strip().lower() in {"1", "true", "yes", "on"}


def resolve_ip() -> str:
    try:
        host = socket.gethostname()
        return socket.gethostbyname(host)
    except OSError:
        return ""


def read_load() -> tuple[float, float, float]:
    try:
        return os.getloadavg()
    except (AttributeError, OSError):
        return (0.0, 0.0, 0.0)


def service_status(name: str) -> str:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", name],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except FileNotFoundError:
        return "unknown"
    except subprocess.SubprocessError:
        return "unknown"

    status = result.stdout.strip() or result.stderr.strip() or "unknown"
    if status == "active":
        return "running"
    if status in {"inactive", "failed", "deactivating"}:
        return "down"
    return status


def _parse_nginx_stub_status(text: str) -> dict | None:
    """
    Example expected format:
    Active connections: 291
    server accepts handled requests
     16630948 16630948 31070465
    Reading: 6 Writing: 179 Waiting: 106
    """
    active_match = re.search(r"Active connections:\\s*(\\d+)", text)
    counts_match = re.search(r"\\n\\s*(\\d+)\\s+(\\d+)\\s+(\\d+)\\s*\\n", text)
    rw_match = re.search(r"Reading:\\s*(\\d+)\\s+Writing:\\s*(\\d+)\\s+Waiting:\\s*(\\d+)", text)
    if not (active_match and counts_match and rw_match):
        return None

    return {
        "active_connections": int(active_match.group(1)),
        "accepts_total": int(counts_match.group(1)),
        "handled_total": int(counts_match.group(2)),
        "requests_total": int(counts_match.group(3)),
        "reading": int(rw_match.group(1)),
        "writing": int(rw_match.group(2)),
        "waiting": int(rw_match.group(3)),
    }


def collect_nginx_metrics() -> dict | None:
    if not MONITOR_NGINX_ENABLED:
        return None
    try:
        response = requests.get(
            MONITOR_NGINX_STATUS_URL,
            timeout=MONITOR_TIMEOUT_SECONDS,
            verify=MONITOR_NGINX_VERIFY_TLS,
        )
        response.raise_for_status()
        return _parse_nginx_stub_status(response.text)
    except requests.RequestException:
        return None


def collect_payload() -> dict:
    load_1m, load_5m, load_15m = read_load()

    services = [{"name": name, "status": service_status(name)} for name in MONITOR_SERVICES]

    payload = {
        "server": {
            "hostname": socket.gethostname(),
            "ip_address": resolve_ip(),
            "environment": MONITOR_ENVIRONMENT,
            "tags": MONITOR_TAGS,
        },
        "metrics": {
            "cpu_percent": psutil.cpu_percent(interval=0.5),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage("/").percent,
            "load_1m": load_1m,
            "load_5m": load_5m,
            "load_15m": load_15m,
            "uptime_seconds": int(time.time() - psutil.boot_time()),
        },
        "services": services,
        "nginx": collect_nginx_metrics(),
    }

    return payload


def main() -> None:
    headers = {"Content-Type": "application/json"}
    if MONITOR_API_TOKEN:
        headers["Authorization"] = f"Bearer {MONITOR_API_TOKEN}"

    print(
        (
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"starting monitor agent; target={MONITOR_API_URL} interval={MONITOR_INTERVAL_SECONDS}s"
        )
    )

    while True:
        payload = collect_payload()
        try:
            response = requests.post(
                MONITOR_API_URL,
                json=payload,
                headers=headers,
                timeout=MONITOR_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            print(f"[{datetime.now(timezone.utc).isoformat()}] sent metrics OK: {response.json()}")
        except requests.RequestException as exc:
            print(f"[{datetime.now(timezone.utc).isoformat()}] failed to send metrics: {exc}")

        time.sleep(MONITOR_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
