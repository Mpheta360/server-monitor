from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from postgrest.exceptions import APIError

from .config import settings
from .schemas import (
    AgentPayload,
    AlertOut,
    DashboardAnalyticsOut,
    DashboardKpisOut,
    DashboardTrendsOut,
    IssueReportIn,
    IssueReportOut,
    LogEventOut,
    MetricOut,
    NginxAppCheckOut,
    NginxMetricOut,
    OverviewOut,
    ServerOut,
    ServiceOut,
    SparklinePointOut,
)

logger = logging.getLogger(__name__)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _scoped_query(table, user_id: str | None):
    if user_id:
        return table.eq("user_id", user_id)
    return table


def _agent_key_from_payload(payload: AgentPayload) -> str:
    explicit = (payload.server.agent_key or "").strip()
    if explicit:
        return explicit
    env = (payload.server.environment or "production").strip() or "production"
    return f"{payload.server.hostname}:{env}"


def upsert_server_with_metric(db, payload: AgentPayload, commit: bool = True) -> tuple[dict, dict]:
    """Upsert server and related metric data to Supabase."""
    if not db or not db.client:
        raise RuntimeError("Database not configured")

    client = db.client
    tags = ",".join(payload.server.tags)
    user_id = (payload.user_id or settings.monitor_default_user_id).strip() or None

    agent_key = _agent_key_from_payload(payload)

    server = None

    if user_id:
        try:
            servers_query = client.table("servers").select().eq("agent_key", agent_key).eq("user_id", user_id).limit(1)
            servers = servers_query.execute()
            server = servers.data[0] if servers.data else None
        except APIError:
            server = None

    if not server:
        try:
            fallback_query = client.table("servers").select().eq("agent_key", agent_key).limit(1)
            fallback_result = fallback_query.execute()
            if fallback_result.data:
                server = fallback_result.data[0]
                user_id = str(server.get("user_id") or "").strip() or user_id
        except APIError:
            server = None

    if not user_id and server:
        user_id = str(server.get("user_id") or "").strip() or None

    if not user_id:
        raise RuntimeError("Agent payload is missing user_id and MONITOR_DEFAULT_USER_ID is not configured")

    server_data = {
        "user_id": user_id,
        "agent_key": agent_key,
        "hostname": payload.server.hostname,
        "display_name": payload.server.display_name,
        "ip_address": payload.server.ip_address,
        "environment": payload.server.environment,
        "region": payload.server.region,
        "tags": tags,
    }
    result = client.table("servers").upsert(server_data, on_conflict="user_id,agent_key").execute()
    server = result.data[0] if result.data else server_data

    metric_data = {
        "server_id": server["id"],
        "user_id": user_id,
        "cpu_percent": payload.metrics.cpu_percent,
        "memory_percent": payload.metrics.memory_percent,
        "disk_percent": payload.metrics.disk_percent,
        "network_io_mbps": payload.metrics.network_io_mbps,
        "response_time_ms": payload.metrics.response_time_ms,
        "load_1m": payload.metrics.load_1m,
        "load_5m": payload.metrics.load_5m,
        "load_15m": payload.metrics.load_15m,
        "uptime_seconds": payload.metrics.uptime_seconds,
    }
    result = client.table("metrics").insert(metric_data).execute()
    metric = result.data[0] if result.data else metric_data

    for service in payload.services:
        service_data = {
            "server_id": server["id"],
            "user_id": user_id,
            "name": service.name,
            "status": service.status,
        }
        try:
            client.table("service_statuses").insert(service_data).execute()
        except Exception as exc:  # pragma: no cover - remote API failure path
            logger.error("Failed to insert service status: %s", exc)

    if payload.nginx:
        nginx_data = {
            "server_id": server["id"],
            "user_id": user_id,
            "active_connections": payload.nginx.active_connections,
            "accepts_total": payload.nginx.accepts_total,
            "handled_total": payload.nginx.handled_total,
            "requests_total": payload.nginx.requests_total,
            "reading": payload.nginx.reading,
            "writing": payload.nginx.writing,
            "waiting": payload.nginx.waiting,
        }
        try:
            client.table("nginx_metrics").insert(nginx_data).execute()
        except Exception as exc:  # pragma: no cover - remote API failure path
            logger.error("Failed to insert nginx metric: %s", exc)

    return server, metric


def _metric_to_schema(metric: dict | None) -> MetricOut | None:
    if not metric:
        return None

    return MetricOut(
        cpu_percent=_to_float(metric.get("cpu_percent")),
        memory_percent=_to_float(metric.get("memory_percent")),
        disk_percent=_to_float(metric.get("disk_percent")),
        network_io_mbps=_to_float(metric.get("network_io_mbps")),
        response_time_ms=_to_float(metric.get("response_time_ms")),
        load_1m=_to_float(metric.get("load_1m")),
        load_5m=_to_float(metric.get("load_5m")),
        load_15m=_to_float(metric.get("load_15m")),
        uptime_seconds=int(metric.get("uptime_seconds") or 0),
        created_at=metric.get("created_at"),
    )


def _service_to_schema(service: dict) -> ServiceOut:
    return ServiceOut(name=service.get("name"), status=service.get("status"), created_at=service.get("created_at"))


def _nginx_metric_to_schema(metric: dict | None) -> NginxMetricOut | None:
    if not metric:
        return None

    return NginxMetricOut(
        active_connections=int(metric.get("active_connections") or 0),
        accepts_total=int(metric.get("accepts_total") or 0),
        handled_total=int(metric.get("handled_total") or 0),
        requests_total=int(metric.get("requests_total") or 0),
        reading=int(metric.get("reading") or 0),
        writing=int(metric.get("writing") or 0),
        waiting=int(metric.get("waiting") or 0),
        created_at=metric.get("created_at"),
    )


def _alert_to_schema(alert: dict, server_hostname: str | None) -> AlertOut:
    return AlertOut(
        id=alert.get("id"),
        server_id=alert.get("server_id"),
        server_hostname=server_hostname,
        alert_key=alert.get("alert_key"),
        severity=alert.get("severity"),
        message=alert.get("message"),
        source=alert.get("source"),
        delivered=bool(alert.get("delivered")),
        suppressed=bool(alert.get("suppressed")),
        created_at=alert.get("created_at"),
    )


def _nginx_app_check_to_schema(row: dict, server_hostname: str | None) -> NginxAppCheckOut:
    return NginxAppCheckOut(
        id=int(row.get("id") or 0),
        server_id=int(row.get("server_id") or 0),
        server_hostname=server_hostname,
        app_name=row.get("app_name") or "",
        check_url=row.get("check_url") or "",
        status_code=row.get("status_code"),
        response_time_ms=_to_float(row.get("response_time_ms")),
        healthy=bool(row.get("healthy")),
        error=row.get("error"),
        created_at=row.get("created_at"),
    )


def _log_event_to_schema(row: dict, server_hostname: str | None) -> LogEventOut:
    ctx = row.get("context_json")
    if not isinstance(ctx, dict):
        ctx = {}
    return LogEventOut(
        id=int(row.get("id") or 0),
        server_id=row.get("server_id"),
        server_hostname=server_hostname,
        level=row.get("level") or "info",
        source=row.get("source") or "system",
        message=row.get("message") or "",
        context_json=ctx,
        created_at=row.get("created_at"),
    )


def _issue_report_to_schema(row: dict, server_hostname: str | None) -> IssueReportOut:
    return IssueReportOut(
        id=int(row.get("id") or 0),
        server_id=row.get("server_id"),
        server_hostname=server_hostname,
        nginx_app_name=row.get("nginx_app_name"),
        severity=row.get("severity") or "warning",
        title=row.get("title") or "",
        description=row.get("description") or "",
        status=row.get("status") or "open",
        created_at=row.get("created_at"),
    )


def _has_failing_service(services: list[dict]) -> bool:
    bad_states = {"down", "failed", "inactive", "stopped", "dead"}
    return any((service.get("status") or "").strip().lower() in bad_states for service in services)


def _status_from_metric(metric: dict | None, last_seen: datetime | None, services: list[dict]) -> str:
    if not last_seen:
        return "unknown"

    stale_cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.heartbeat_timeout_seconds)
    if last_seen < stale_cutoff:
        return "stale"

    if not metric:
        return "unknown"

    if _has_failing_service(services):
        return "critical"

    cpu = _to_float(metric.get("cpu_percent"))
    mem = _to_float(metric.get("memory_percent"))
    disk = _to_float(metric.get("disk_percent"))

    if cpu >= settings.alert_cpu_threshold or mem >= settings.alert_memory_threshold or disk >= settings.alert_disk_threshold:
        return "critical"

    return "healthy"


def get_servers(db, user_id: str | None = None) -> list[ServerOut]:
    """Fetch all servers from Supabase."""
    if not db or not db.client:
        return []

    client = db.client
    output: list[ServerOut] = []

    try:
        servers_query = _scoped_query(client.table("servers").select(), user_id).order("hostname", desc=False)
        servers_result = servers_query.execute()
        servers = servers_result.data if servers_result.data else []

        for server in servers:
            server_id = server.get("id")

            metrics_query = (
                _scoped_query(client.table("metrics").select().eq("server_id", server_id), user_id)
                .order("created_at", desc=True)
                .limit(1)
            )
            metrics_result = metrics_query.execute()
            latest_metric = metrics_result.data[0] if metrics_result.data else None

            services_query = (
                _scoped_query(client.table("service_statuses").select().eq("server_id", server_id), user_id)
                .order("created_at", desc=True)
                .limit(20)
            )
            services_result = services_query.execute()
            latest_services_raw = services_result.data if services_result.data else []

            nginx_query = (
                _scoped_query(client.table("nginx_metrics").select().eq("server_id", server_id), user_id)
                .order("created_at", desc=True)
                .limit(1)
            )
            nginx_result = nginx_query.execute()
            latest_nginx_metric = nginx_result.data[0] if nginx_result.data else None

            latest_by_name: dict[str, dict] = {}
            for service in latest_services_raw:
                svc_name = service.get("name")
                if svc_name and svc_name not in latest_by_name:
                    latest_by_name[svc_name] = service

            last_seen = _parse_dt(latest_metric.get("created_at")) if latest_metric else None
            status = _status_from_metric(latest_metric, last_seen, list(latest_by_name.values()))

            output.append(
                ServerOut(
                    id=server_id,
                    agent_key=server.get("agent_key") or f"{server.get('hostname')}:{server.get('environment') or 'production'}",
                    hostname=server.get("hostname"),
                    display_name=server.get("display_name"),
                    ip_address=server.get("ip_address") or "",
                    environment=server.get("environment") or "production",
                    region=server.get("region"),
                    tags=[t for t in (server.get("tags") or "").split(",") if t],
                    status=status,
                    last_seen=last_seen,
                    latest_metric=_metric_to_schema(latest_metric),
                    latest_nginx_metric=_nginx_metric_to_schema(latest_nginx_metric),
                    latest_services=[_service_to_schema(svc) for svc in latest_by_name.values()],
                )
            )

        return output
    except Exception as exc:
        logger.error("Error fetching servers: %s", exc)
        return []


def get_server(db, server_id: int, user_id: str | None = None) -> ServerOut | None:
    """Fetch a specific server by ID."""
    for server in get_servers(db, user_id=user_id):
        if server.id == server_id:
            return server
    return None


def get_servers_page(
    db,
    status: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user_id: str | None = None,
) -> tuple[list[ServerOut], int]:
    """Fetch paginated servers with optional filtering."""
    servers = get_servers(db, user_id=user_id)

    if status:
        normalized_status = status.strip().lower()
        servers = [server for server in servers if server.status == normalized_status]

    if search:
        term = search.strip().lower()
        servers = [
            server
            for server in servers
            if term in server.hostname.lower()
            or term in server.ip_address.lower()
            or term in server.environment.lower()
            or any(term in tag.lower() for tag in server.tags)
        ]

    total = len(servers)
    paged = servers[offset : offset + limit]
    return paged, total


def get_overview(db, user_id: str | None = None) -> OverviewOut:
    """Get overview statistics."""
    servers = get_servers(db, user_id=user_id)
    total = len(servers)
    healthy = len([s for s in servers if s.status == "healthy"])
    stale = len([s for s in servers if s.status == "stale"])
    critical = len([s for s in servers if s.status == "critical"])

    metrics = [s.latest_metric for s in servers if s.latest_metric]
    avg_cpu = round(sum(m.cpu_percent for m in metrics) / len(metrics), 1) if metrics else 0.0
    avg_memory = round(sum(m.memory_percent for m in metrics) / len(metrics), 1) if metrics else 0.0
    total_network = round(sum(m.network_io_mbps for m in metrics), 1) if metrics else 0.0
    avg_response = round(sum(m.response_time_ms for m in metrics) / len(metrics), 1) if metrics else 0.0
    uptime_pct = round((healthy / total) * 100, 2) if total else 0.0

    return OverviewOut(
        total_servers=total,
        healthy_servers=healthy,
        stale_servers=stale,
        critical_servers=critical,
        avg_cpu_percent=avg_cpu,
        avg_memory_percent=avg_memory,
        total_network_io_mbps=total_network,
        avg_response_time_ms=avg_response,
        uptime_percentage=uptime_pct,
    )


def _bucket_series(
    rows: list[dict],
    *,
    value_key: str,
    start: datetime,
    end: datetime,
    bucket_minutes: int,
    aggregator: str = "avg",
) -> list[SparklinePointOut]:
    if bucket_minutes <= 0:
        bucket_minutes = 5

    bucket_seconds = bucket_minutes * 60
    buckets: dict[int, list[float]] = {}
    cursor = start
    while cursor <= end:
        bucket_id = int(cursor.timestamp()) // bucket_seconds
        buckets[bucket_id] = []
        cursor += timedelta(seconds=bucket_seconds)

    for row in rows:
        dt = _parse_dt(row.get("created_at"))
        if not dt:
            continue
        bucket_id = int(dt.timestamp()) // bucket_seconds
        if bucket_id not in buckets:
            continue
        buckets[bucket_id].append(_to_float(row.get(value_key)))

    points: list[SparklinePointOut] = []
    for bucket_id in sorted(buckets.keys()):
        values = buckets[bucket_id]
        if not values:
            value = 0.0
        elif aggregator == "sum":
            value = float(sum(values))
        else:
            value = float(sum(values) / len(values))
        ts = datetime.fromtimestamp(bucket_id * bucket_seconds, tz=timezone.utc)
        points.append(SparklinePointOut(ts=ts, value=round(value, 2)))
    return points


def _delta_percent(points: list[SparklinePointOut], *, inverse_good: bool = False) -> float:
    if len(points) < 2:
        return 0.0
    previous = points[-2].value
    current = points[-1].value
    if previous == 0:
        if current == 0:
            return 0.0
        change = 100.0
    else:
        change = ((current - previous) / previous) * 100.0
    if inverse_good:
        change = -change
    return round(change, 1)


def get_dashboard_analytics(
    db,
    *,
    window_minutes: int = 60,
    bucket_minutes: int = 5,
    server_limit: int = 100,
    alerts_limit: int = 12,
    user_id: str | None = None,
) -> DashboardAnalyticsOut:
    overview = get_overview(db, user_id=user_id)
    servers, _ = get_servers_page(db, limit=server_limit, offset=0, user_id=user_id)
    alerts = get_alert_events(db, limit=alerts_limit, user_id=user_id)

    if not db or not db.client:
        empty_kpis = DashboardKpisOut(
            cpu_percent=0.0,
            cpu_delta_percent=0.0,
            memory_gb=0.0,
            memory_delta_percent=0.0,
            network_mbps=0.0,
            network_delta_percent=0.0,
            response_ms=0.0,
            response_delta_percent=0.0,
            uptime_percentage=overview.uptime_percentage,
        )
        return DashboardAnalyticsOut(
            overview=overview,
            kpis=empty_kpis,
            trends=DashboardTrendsOut(),
            servers=servers,
            alerts=alerts,
        )

    now = datetime.now(timezone.utc)
    since = now - timedelta(minutes=window_minutes)
    since_str = since.isoformat().replace("+00:00", "Z")

    client = db.client
    metrics_query = _scoped_query(
        client.table("metrics")
        .select("cpu_percent,memory_percent,network_io_mbps,response_time_ms,created_at")
        .gte("created_at", since_str),
        user_id,
    ).order("created_at", desc=False)

    metrics_result = metrics_query.execute()
    metrics_rows = metrics_result.data if metrics_result.data else []

    cpu_points = _bucket_series(metrics_rows, value_key="cpu_percent", start=since, end=now, bucket_minutes=bucket_minutes)
    memory_pct_points = _bucket_series(
        metrics_rows,
        value_key="memory_percent",
        start=since,
        end=now,
        bucket_minutes=bucket_minutes,
    )
    network_points = _bucket_series(
        metrics_rows,
        value_key="network_io_mbps",
        start=since,
        end=now,
        bucket_minutes=bucket_minutes,
        aggregator="sum",
    )
    response_points = _bucket_series(
        metrics_rows,
        value_key="response_time_ms",
        start=since,
        end=now,
        bucket_minutes=bucket_minutes,
    )

    # For a fleet-level memory card, use percent-of-total converted to "GB-equivalent"
    # by summing percentages and scaling by assumed 16GB/server baseline.
    memory_gb_points: list[SparklinePointOut] = []
    for point in memory_pct_points:
        memory_gb_points.append(SparklinePointOut(ts=point.ts, value=round((point.value / 100.0) * 16.0, 2)))

    current_cpu = cpu_points[-1].value if cpu_points else 0.0
    current_memory_gb = memory_gb_points[-1].value if memory_gb_points else 0.0
    current_network = network_points[-1].value if network_points else 0.0
    current_response = response_points[-1].value if response_points else 0.0

    kpis = DashboardKpisOut(
        cpu_percent=round(current_cpu, 1),
        cpu_delta_percent=_delta_percent(cpu_points),
        memory_gb=round(current_memory_gb, 1),
        memory_delta_percent=_delta_percent(memory_gb_points),
        network_mbps=round(current_network, 1),
        network_delta_percent=_delta_percent(network_points),
        response_ms=round(current_response, 1),
        response_delta_percent=_delta_percent(response_points, inverse_good=True),
        uptime_percentage=overview.uptime_percentage,
    )

    trends = DashboardTrendsOut(
        cpu=cpu_points,
        memory=memory_gb_points,
        network=network_points,
        response=response_points,
    )

    return DashboardAnalyticsOut(
        overview=overview,
        kpis=kpis,
        trends=trends,
        servers=servers,
        alerts=alerts,
    )


def get_server_metrics(db, server_id: int, minutes: int = 60, user_id: str | None = None) -> list[MetricOut]:
    """Fetch server metrics from the last N minutes."""
    if not db or not db.client:
        return []

    client = db.client
    try:
        since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        since_str = since.isoformat().replace("+00:00", "Z")

        query = (
            _scoped_query(client.table("metrics").select().eq("server_id", server_id), user_id)
            .gte("created_at", since_str)
            .order("created_at", desc=False)
        )
        metrics_result = query.execute()
        metrics = metrics_result.data if metrics_result.data else []

        return [_metric_to_schema(metric) for metric in metrics if metric]
    except Exception as exc:
        logger.error("Error fetching server metrics: %s", exc)
        return []


def get_server_nginx_metrics(db, server_id: int, minutes: int = 60, user_id: str | None = None) -> list[NginxMetricOut]:
    """Fetch server nginx metrics from the last N minutes."""
    if not db or not db.client:
        return []

    client = db.client
    try:
        since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        since_str = since.isoformat().replace("+00:00", "Z")

        query = (
            _scoped_query(client.table("nginx_metrics").select().eq("server_id", server_id), user_id)
            .gte("created_at", since_str)
            .order("created_at", desc=False)
        )
        metrics_result = query.execute()
        metrics = metrics_result.data if metrics_result.data else []

        return [_nginx_metric_to_schema(metric) for metric in metrics if metric]
    except Exception as exc:
        logger.error("Error fetching nginx metrics: %s", exc)
        return []


def create_log_event(
    db,
    *,
    user_id: str | None,
    level: str,
    source: str,
    message: str,
    server_id: int | None = None,
    context_json: dict | None = None,
) -> LogEventOut | None:
    if not db or not db.client or not user_id:
        return None

    try:
        row = {
            "user_id": user_id,
            "server_id": server_id,
            "level": level,
            "source": source,
            "message": message,
            "context_json": context_json or {},
        }
        result = db.client.table("log_events").insert(row).execute()
        saved = result.data[0] if result.data else row
        server_hostname = None
        if saved.get("server_id"):
            srv_result = db.client.table("servers").select("hostname").eq("id", saved["server_id"]).limit(1).execute()
            if srv_result.data:
                server_hostname = srv_result.data[0].get("hostname")
        return _log_event_to_schema(saved, server_hostname)
    except Exception as exc:
        logger.error("Error creating log event: %s", exc)
        return None


def create_nginx_app_checks(
    db,
    *,
    user_id: str | None,
    server_id: int,
    checks: list[dict],
) -> list[NginxAppCheckOut]:
    if not db or not db.client or not user_id or not checks:
        return []

    rows: list[dict] = []
    for check in checks:
        rows.append(
            {
                "user_id": user_id,
                "server_id": server_id,
                "app_name": check.get("app_name"),
                "check_url": check.get("check_url"),
                "status_code": check.get("status_code"),
                "response_time_ms": _to_float(check.get("response_time_ms")),
                "healthy": bool(check.get("healthy")),
                "error": check.get("error"),
            }
        )
    try:
        result = db.client.table("nginx_app_checks").insert(rows).execute()
        saved_rows = result.data if result.data else rows
        server_hostname = None
        srv_result = db.client.table("servers").select("hostname").eq("id", server_id).limit(1).execute()
        if srv_result.data:
            server_hostname = srv_result.data[0].get("hostname")
        return [_nginx_app_check_to_schema(row, server_hostname) for row in saved_rows]
    except Exception as exc:
        logger.error("Error creating nginx app checks: %s", exc)
        return []


def get_nginx_app_checks(
    db,
    *,
    user_id: str | None,
    limit: int = 100,
    server_id: int | None = None,
    healthy: bool | None = None,
) -> list[NginxAppCheckOut]:
    if not db or not db.client:
        return []
    try:
        query = _scoped_query(
            db.client.table("nginx_app_checks").select("*, servers(hostname)").order("created_at", desc=True),
            user_id,
        ).limit(limit)
        if server_id is not None:
            query = query.eq("server_id", server_id)
        if healthy is not None:
            query = query.eq("healthy", healthy)
        result = query.execute()
        rows = result.data if result.data else []
        out: list[NginxAppCheckOut] = []
        for row in rows:
            hostname = None
            if isinstance(row.get("servers"), dict):
                hostname = row["servers"].get("hostname")
            out.append(_nginx_app_check_to_schema(row, hostname))
        return out
    except Exception as exc:
        logger.error("Error fetching nginx app checks: %s", exc)
        return []


def get_log_events(
    db,
    *,
    user_id: str | None,
    limit: int = 100,
    server_id: int | None = None,
    level: str | None = None,
) -> list[LogEventOut]:
    if not db or not db.client:
        return []
    try:
        query = _scoped_query(
            db.client.table("log_events").select("*, servers(hostname)").order("created_at", desc=True),
            user_id,
        ).limit(limit)
        if server_id is not None:
            query = query.eq("server_id", server_id)
        if level:
            query = query.eq("level", level.strip().lower())
        result = query.execute()
        rows = result.data if result.data else []
        output: list[LogEventOut] = []
        for row in rows:
            hostname = None
            if isinstance(row.get("servers"), dict):
                hostname = row["servers"].get("hostname")
            output.append(_log_event_to_schema(row, hostname))
        return output
    except Exception as exc:
        logger.error("Error fetching log events: %s", exc)
        return []


def create_issue_report(
    db,
    *,
    user_id: str | None,
    payload: IssueReportIn,
) -> IssueReportOut | None:
    if not db or not db.client or not user_id:
        return None
    try:
        row = {
            "user_id": user_id,
            "server_id": payload.server_id,
            "nginx_app_name": payload.nginx_app_name,
            "severity": payload.severity.strip().lower(),
            "title": payload.title.strip(),
            "description": payload.description.strip(),
            "status": "open",
        }
        result = db.client.table("issue_reports").insert(row).execute()
        saved = result.data[0] if result.data else row

        server_hostname = None
        if saved.get("server_id") is not None:
            srv_result = db.client.table("servers").select("hostname").eq("id", saved["server_id"]).limit(1).execute()
            if srv_result.data:
                server_hostname = srv_result.data[0].get("hostname")

        issue = _issue_report_to_schema(saved, server_hostname)
        create_log_event(
            db,
            user_id=user_id,
            level=issue.severity if issue.severity in {"critical", "warning"} else "info",
            source="issue-report",
            message=f"Issue reported: {issue.title}",
            server_id=issue.server_id,
            context_json={
                "issue_id": issue.id,
                "nginx_app_name": issue.nginx_app_name,
            },
        )
        return issue
    except Exception as exc:
        logger.error("Error creating issue report: %s", exc)
        return None


def get_issue_reports(
    db,
    *,
    user_id: str | None,
    limit: int = 100,
    status: str | None = None,
) -> list[IssueReportOut]:
    if not db or not db.client:
        return []
    try:
        query = _scoped_query(
            db.client.table("issue_reports").select("*, servers(hostname)").order("created_at", desc=True),
            user_id,
        ).limit(limit)
        if status:
            query = query.eq("status", status.strip().lower())
        result = query.execute()
        rows = result.data if result.data else []
        output: list[IssueReportOut] = []
        for row in rows:
            hostname = None
            if isinstance(row.get("servers"), dict):
                hostname = row["servers"].get("hostname")
            output.append(_issue_report_to_schema(row, hostname))
        return output
    except Exception as exc:
        logger.error("Error fetching issue reports: %s", exc)
        return []


def create_alert_event(
    db,
    alert_key: str,
    severity: str,
    message: str,
    source: str,
    server_id: int | None,
    delivered: bool,
    suppressed: bool,
    user_id: str | None,
    commit: bool = True,
) -> AlertOut | None:
    """Create an alert event."""
    if not db or not db.client:
        return None

    client = db.client
    try:
        if not user_id:
            return None

        alert_data = {
            "server_id": server_id,
            "user_id": user_id,
            "alert_key": alert_key,
            "severity": severity,
            "message": message,
            "source": source,
            "delivered": delivered,
            "suppressed": suppressed,
        }

        result = client.table("alert_events").insert(alert_data).execute()
        alert = result.data[0] if result.data else alert_data

        server_hostname = None
        if server_id is not None:
            servers_result = client.table("servers").select().eq("id", server_id).limit(1).execute()
            if servers_result.data:
                server_hostname = servers_result.data[0].get("hostname")

        alert_out = _alert_to_schema(alert, server_hostname=server_hostname)
        create_log_event(
            db,
            user_id=user_id,
            level=severity if severity in {"critical", "warning"} else "info",
            source=source,
            message=message,
            server_id=server_id,
            context_json={"alert_key": alert_key, "delivered": delivered, "suppressed": suppressed},
        )
        return alert_out
    except Exception as exc:
        logger.error("Error creating alert event: %s", exc)
        return None


def get_alert_events(db, limit: int = 50, server_id: int | None = None, user_id: str | None = None) -> list[AlertOut]:
    """Fetch alert events."""
    if not db or not db.client:
        return []

    client = db.client
    try:
        query = _scoped_query(
            client.table("alert_events").select("*, servers(hostname)").order("created_at", desc=True),
            user_id,
        ).limit(limit)

        if server_id is not None:
            query = query.eq("server_id", server_id)

        result = query.execute()
        alerts = result.data if result.data else []

        output = []
        for alert_row in alerts:
            server_hostname = None
            if alert_row.get("servers"):
                server_hostname = alert_row["servers"].get("hostname") if isinstance(alert_row["servers"], dict) else None
            output.append(_alert_to_schema(alert_row, server_hostname))

        return output
    except Exception as exc:
        logger.error("Error fetching alert events: %s", exc)
        return []


def cleanup_old_metrics(db, keep_days: int = 7, user_id: str | None = None) -> int:
    """Delete metrics older than keep_days."""
    if not db or not db.client:
        return 0

    client = db.client
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
        cutoff_str = cutoff.isoformat().replace("+00:00", "Z")

        count_query = _scoped_query(client.table("metrics").select("id").lt("created_at", cutoff_str), user_id)
        count_result = count_query.execute()
        old_count = len(count_result.data) if count_result.data else 0

        if old_count > 0:
            delete_query = _scoped_query(client.table("metrics").delete().lt("created_at", cutoff_str), user_id)
            delete_query.execute()

        return old_count
    except Exception as exc:
        logger.error("Error cleaning up old metrics: %s", exc)
        return 0
