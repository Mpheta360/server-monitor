import json
import os
import subprocess
import time
from base64 import b64encode
from pathlib import Path
from urllib import error, request

from dotenv import dotenv_values


API_HOST = "127.0.0.1"
API_PORT = 8002
API_BASE = f"http://{API_HOST}:{API_PORT}"


def fail(message: str) -> None:
    raise RuntimeError(message)


def http_json(method: str, url: str, data: dict | None = None, headers: dict | None = None) -> tuple[int, dict | str]:
    req_headers = headers or {}
    payload = None
    if data is not None:
        payload = json.dumps(data).encode("utf-8")
        req_headers = {**req_headers, "Content-Type": "application/json"}

    req = request.Request(url=url, method=method, data=payload, headers=req_headers)
    try:
        with request.urlopen(req, timeout=12) as resp:
            raw = resp.read().decode("utf-8")
            if not raw:
                return resp.status, {}
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8") if exc.fp else ""
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def wait_for_health(timeout_seconds: int = 30) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            status, body = http_json("GET", f"{API_BASE}/health")
            if status == 200 and isinstance(body, dict) and body.get("status") == "ok":
                return
        except Exception:
            pass
        time.sleep(0.5)
    fail("API did not become healthy in time")


def assert_status(actual: int, expected: int, context: str) -> None:
    if actual != expected:
        fail(f"{context}: expected {expected}, got {actual}")


def basic_auth_header(username: str, password: str) -> dict[str, str]:
    token = b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def test_supabase_auth_reachable(supabase_url: str, anon_key: str) -> None:
    url = f"{supabase_url.rstrip('/')}/auth/v1/user"
    status, _ = http_json(
        "GET",
        url,
        headers={
            "apikey": anon_key,
            "Authorization": "Bearer invalid-token",
        },
    )
    if status not in (401, 403):
        fail(f"Supabase auth reachability failed: expected 401/403 for invalid token, got {status}")


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    backend_dir = repo_root / "backend"
    env_path = backend_dir / ".env"

    if not env_path.exists():
        fail(f"Missing environment file: {env_path}")

    file_env = {
        str(k): str(v)
        for k, v in dotenv_values(env_path).items()
        if k is not None and v is not None
    }

    supabase_url = file_env.get("SUPABASE_URL", "").strip()
    supabase_anon_key = file_env.get("SUPABASE_ANON_KEY", "").strip()
    supabase_db_url = file_env.get("SUPABASE_DB_URL", "").strip()
    fallback_db_url = file_env.get("DATABASE_URL", "").strip()
    ingest_api_token = file_env.get("INGEST_API_TOKEN", "").strip()
    test_mobile_access_token = file_env.get("SUPABASE_TEST_ACCESS_TOKEN", "").strip()
    admin_username = file_env.get("ADMIN_USERNAME", "").strip()
    admin_password = file_env.get("ADMIN_PASSWORD", "")

    if not supabase_url or not supabase_anon_key:
        fail("SUPABASE_URL or SUPABASE_ANON_KEY is missing in backend/.env")
    if not supabase_db_url and not fallback_db_url:
        fail("SUPABASE_DB_URL (or DATABASE_URL fallback) is missing in backend/.env")
    if not ingest_api_token:
        fail("INGEST_API_TOKEN is missing in backend/.env")
    if file_env.get("REQUIRE_ADMIN_AUTH", "true").strip().lower() in {"1", "true", "yes", "on"}:
        if not admin_username or not admin_password:
            fail("ADMIN_USERNAME or ADMIN_PASSWORD is missing in backend/.env")

    test_supabase_auth_reachable(supabase_url=supabase_url, anon_key=supabase_anon_key)

    env = os.environ.copy()
    env.update(file_env)
    admin_headers = basic_auth_header(admin_username, admin_password) if admin_username and admin_password else {}

    uvicorn_cmd = [
        str(backend_dir / ".venv" / "bin" / "python"),
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        API_HOST,
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

    server_output = ""
    try:
        wait_for_health()

        status, body = http_json("GET", f"{API_BASE}/health")
        assert_status(status, 200, "GET /health")
        if not isinstance(body, dict) or body.get("status") != "ok":
            fail("GET /health returned unexpected payload")

        status, _ = http_json("GET", f"{API_BASE}/api/v1/overview", headers=admin_headers)
        assert_status(status, 200, "GET /api/v1/overview")

        host_tag = int(time.time())
        ingest_payload = {
            "server": {
                "hostname": f"real-smoke-{host_tag}",
                "ip_address": "10.0.99.10",
                "environment": "production",
                "tags": ["real", "smoke"],
            },
            "metrics": {
                "cpu_percent": 15.2,
                "memory_percent": 42.1,
                "disk_percent": 33.9,
                "load_1m": 0.2,
                "load_5m": 0.1,
                "load_15m": 0.05,
                "uptime_seconds": 4096,
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
            headers={"Authorization": f"Bearer {ingest_api_token}"},
        )
        assert_status(status, 200, "POST /api/v1/ingest")

        status, servers = http_json("GET", f"{API_BASE}/api/v1/servers", headers=admin_headers)
        assert_status(status, 200, "GET /api/v1/servers")
        if not isinstance(servers, list):
            fail("GET /api/v1/servers returned unexpected payload")

        status, _ = http_json("GET", f"{API_BASE}/api/v1/mobile/me")
        assert_status(status, 401, "GET /api/v1/mobile/me (no token)")

        status, _ = http_json(
            "GET",
            f"{API_BASE}/api/v1/mobile/me",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert_status(status, 401, "GET /api/v1/mobile/me (invalid token)")

        if test_mobile_access_token:
            headers = {"Authorization": f"Bearer {test_mobile_access_token}"}
            status, me = http_json("GET", f"{API_BASE}/api/v1/mobile/me", headers=headers)
            assert_status(status, 200, "GET /api/v1/mobile/me (valid token)")
            if not isinstance(me, dict) or not me.get("id"):
                fail("GET /api/v1/mobile/me (valid token) returned unexpected payload")

            status, _ = http_json("GET", f"{API_BASE}/api/v1/mobile/bootstrap", headers=headers)
            assert_status(status, 200, "GET /api/v1/mobile/bootstrap (valid token)")
        else:
            print("INFO: SUPABASE_TEST_ACCESS_TOKEN not set; skipped valid-token mobile endpoint checks.")

        print("REAL SUPABASE SMOKE TEST PASSED")
    finally:
        api_proc.terminate()
        try:
            server_output, _ = api_proc.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            api_proc.kill()
            server_output, _ = api_proc.communicate(timeout=8)

        if api_proc.returncode not in (0, -15):
            print("---- API process output ----")
            print(server_output[-4000:])


if __name__ == "__main__":
    main()
