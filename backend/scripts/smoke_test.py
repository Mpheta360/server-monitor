import json
import os
import subprocess
import sys
import time
from base64 import b64encode
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from urllib import error, request


API_PORT = 8001
AUTH_PORT = 9010
API_BASE = f"http://127.0.0.1:{API_PORT}"


class SupabaseAuthMockHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/auth/v1/user":
            self.send_response(404)
            self.end_headers()
            return

        auth_header = self.headers.get("Authorization", "")
        if auth_header == "Bearer mobile-valid-token":
            payload = {
                "id": "test-user-1",
                "email": "tester@example.com",
                "app_metadata": {"role": "authenticated"},
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        body = json.dumps({"message": "invalid token"}).encode("utf-8")
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def http_json(method: str, url: str, data: dict | None = None, headers: dict | None = None) -> tuple[int, dict | str]:
    req_headers = headers or {}
    payload = None
    if data is not None:
        payload = json.dumps(data).encode("utf-8")
        req_headers = {**req_headers, "Content-Type": "application/json"}

    req = request.Request(url=url, method=method, data=payload, headers=req_headers)
    try:
        with request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            if raw:
                try:
                    return resp.status, json.loads(raw)
                except json.JSONDecodeError:
                    return resp.status, raw
            return resp.status, {}
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8") if exc.fp else ""
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def wait_for_health(timeout_seconds: int = 25) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            status, body = http_json("GET", f"{API_BASE}/health")
            if status == 200 and isinstance(body, dict) and body.get("status") == "ok":
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError("API did not become healthy in time")


def assert_status(actual: int, expected: int, context: str) -> None:
    if actual != expected:
        raise AssertionError(f"{context} expected {expected}, got {actual}")


def basic_auth_header(username: str, password: str) -> dict[str, str]:
    token = b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def main() -> None:
    workspace_root = Path(__file__).resolve().parents[2]
    backend_dir = workspace_root / "backend"
    smoke_db = backend_dir / "monitor_smoke.db"

    if smoke_db.exists():
        smoke_db.unlink()

    auth_server = HTTPServer(("127.0.0.1", AUTH_PORT), SupabaseAuthMockHandler)
    auth_thread = Thread(target=auth_server.serve_forever, daemon=True)
    auth_thread.start()

    env = os.environ.copy()
    env.update(
        {
            "SUPABASE_URL": f"http://127.0.0.1:{AUTH_PORT}",
            "SUPABASE_ANON_KEY": "test-anon-key",
            "DATABASE_URL": f"sqlite:///{smoke_db}",
            "SUPABASE_DB_URL": "",
            "INGEST_API_TOKEN": "ingest-test-token",
            "CORS_ALLOW_ORIGINS": "http://127.0.0.1:3000",
            "REQUIRE_ADMIN_AUTH": "true",
            "ADMIN_USERNAME": "admin",
            "ADMIN_PASSWORD": "adminpass",
            "ALLOWED_HOSTS": "127.0.0.1,localhost",
        }
    )

    admin_headers = basic_auth_header("admin", "adminpass")

    uvicorn_cmd = [
        str(backend_dir / ".venv" / "bin" / "python"),
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(API_PORT),
    ]

    api_proc = subprocess.Popen(
        uvicorn_cmd,
        cwd=str(backend_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        wait_for_health()

        status, _ = http_json("GET", f"{API_BASE}/")
        assert_status(status, 401, "GET / without admin auth")

        status, _ = http_json("GET", f"{API_BASE}/", headers=admin_headers)
        assert_status(status, 200, "GET /")

        status, _ = http_json("GET", f"{API_BASE}/api/v1/overview", headers=admin_headers)
        assert_status(status, 200, "GET /api/v1/overview")

        ingest_payload = {
            "server": {
                "hostname": "smoke-web-01",
                "ip_address": "10.10.0.12",
                "environment": "staging",
                "tags": ["web", "smoke"],
            },
            "metrics": {
                "cpu_percent": 12.0,
                "memory_percent": 34.0,
                "disk_percent": 56.0,
                "load_1m": 0.4,
                "load_5m": 0.2,
                "load_15m": 0.1,
                "uptime_seconds": 1024,
            },
            "services": [
                {"name": "nginx", "status": "running"},
                {"name": "postgresql", "status": "running"},
            ],
        }

        status, _ = http_json(
            "POST",
            f"{API_BASE}/api/v1/ingest",
            data=ingest_payload,
            headers={"Authorization": "Bearer ingest-test-token"},
        )
        assert_status(status, 200, "POST /api/v1/ingest")

        status, servers = http_json("GET", f"{API_BASE}/api/v1/servers", headers=admin_headers)
        assert_status(status, 200, "GET /api/v1/servers")
        if not isinstance(servers, list) or not servers:
            raise AssertionError("GET /api/v1/servers returned no data after ingest")
        server_id = servers[0]["id"]

        status, metrics = http_json(
            "GET",
            f"{API_BASE}/api/v1/servers/{server_id}/metrics?minutes=60",
            headers=admin_headers,
        )
        assert_status(status, 200, "GET /api/v1/servers/{id}/metrics")
        if not isinstance(metrics, list) or not metrics:
            raise AssertionError("GET /api/v1/servers/{id}/metrics returned no metrics")

        # Mobile endpoints: unauthorized
        status, _ = http_json("GET", f"{API_BASE}/api/v1/mobile/me")
        assert_status(status, 401, "GET /api/v1/mobile/me without token")

        mobile_headers = {"Authorization": "Bearer mobile-valid-token"}

        status, me = http_json("GET", f"{API_BASE}/api/v1/mobile/me", headers=mobile_headers)
        assert_status(status, 200, "GET /api/v1/mobile/me")
        if not isinstance(me, dict) or me.get("id") != "test-user-1":
            raise AssertionError("GET /api/v1/mobile/me returned unexpected user")

        status, _ = http_json("GET", f"{API_BASE}/api/v1/mobile/bootstrap", headers=mobile_headers)
        assert_status(status, 200, "GET /api/v1/mobile/bootstrap")

        status, _ = http_json("GET", f"{API_BASE}/api/v1/mobile/servers?limit=10&offset=0", headers=mobile_headers)
        assert_status(status, 200, "GET /api/v1/mobile/servers")

        status, _ = http_json("GET", f"{API_BASE}/api/v1/mobile/servers/{server_id}", headers=mobile_headers)
        assert_status(status, 200, "GET /api/v1/mobile/servers/{id}")

        status, _ = http_json(
            "GET",
            f"{API_BASE}/api/v1/mobile/servers/{server_id}/metrics?minutes=60",
            headers=mobile_headers,
        )
        assert_status(status, 200, "GET /api/v1/mobile/servers/{id}/metrics")

        status, _ = http_json("GET", f"{API_BASE}/api/v1/mobile/alerts?limit=20", headers=mobile_headers)
        assert_status(status, 200, "GET /api/v1/mobile/alerts")

        print("SMOKE TEST PASSED: all key endpoints are reachable and behaving as expected.")
    finally:
        api_proc.terminate()
        try:
            api_proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            api_proc.kill()

        auth_server.shutdown()
        auth_server.server_close()

        if smoke_db.exists():
            smoke_db.unlink()


if __name__ == "__main__":
    main()
