from datetime import datetime, timedelta

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .config import settings
from .models import AlertEvent, Metric, NginxMetric, Server, ServiceStatus
from .schemas import AgentPayload, AlertOut, MetricOut, NginxMetricOut, OverviewOut, ServerOut, ServiceOut


def upsert_server_with_metric(db: Session, payload: AgentPayload, commit: bool = True) -> tuple[Server, Metric]:
    server = db.execute(select(Server).where(Server.hostname == payload.server.hostname)).scalar_one_or_none()

    tags = ",".join(payload.server.tags)

    if not server:
        server = Server(
            hostname=payload.server.hostname,
            ip_address=payload.server.ip_address,
            environment=payload.server.environment,
            tags=tags,
        )
        db.add(server)
        db.flush()
    else:
        server.ip_address = payload.server.ip_address
        server.environment = payload.server.environment
        server.tags = tags

    metric = Metric(
        server_id=server.id,
        cpu_percent=payload.metrics.cpu_percent,
        memory_percent=payload.metrics.memory_percent,
        disk_percent=payload.metrics.disk_percent,
        load_1m=payload.metrics.load_1m,
        load_5m=payload.metrics.load_5m,
        load_15m=payload.metrics.load_15m,
        uptime_seconds=payload.metrics.uptime_seconds,
    )
    db.add(metric)
    db.flush()

    for service in payload.services:
        db.add(
            ServiceStatus(
                server_id=server.id,
                name=service.name,
                status=service.status,
            )
        )

    if payload.nginx:
        db.add(
            NginxMetric(
                server_id=server.id,
                active_connections=payload.nginx.active_connections,
                accepts_total=payload.nginx.accepts_total,
                handled_total=payload.nginx.handled_total,
                requests_total=payload.nginx.requests_total,
                reading=payload.nginx.reading,
                writing=payload.nginx.writing,
                waiting=payload.nginx.waiting,
            )
        )

    if commit:
        db.commit()
        db.refresh(server)
        db.refresh(metric)

    return server, metric


def _metric_to_schema(metric: Metric | None) -> MetricOut | None:
    if not metric:
        return None

    return MetricOut(
        cpu_percent=metric.cpu_percent,
        memory_percent=metric.memory_percent,
        disk_percent=metric.disk_percent,
        load_1m=metric.load_1m,
        load_5m=metric.load_5m,
        load_15m=metric.load_15m,
        uptime_seconds=metric.uptime_seconds,
        created_at=metric.created_at,
    )


def _service_to_schema(service: ServiceStatus) -> ServiceOut:
    return ServiceOut(name=service.name, status=service.status, created_at=service.created_at)


def _nginx_metric_to_schema(metric: NginxMetric | None) -> NginxMetricOut | None:
    if not metric:
        return None

    return NginxMetricOut(
        active_connections=metric.active_connections,
        accepts_total=metric.accepts_total,
        handled_total=metric.handled_total,
        requests_total=metric.requests_total,
        reading=metric.reading,
        writing=metric.writing,
        waiting=metric.waiting,
        created_at=metric.created_at,
    )


def _alert_to_schema(alert: AlertEvent, server_hostname: str | None) -> AlertOut:
    return AlertOut(
        id=alert.id,
        server_id=alert.server_id,
        server_hostname=server_hostname,
        alert_key=alert.alert_key,
        severity=alert.severity,
        message=alert.message,
        source=alert.source,
        delivered=alert.delivered,
        suppressed=alert.suppressed,
        created_at=alert.created_at,
    )


def _has_failing_service(services: list[ServiceStatus]) -> bool:
    bad_states = {"down", "failed", "inactive", "stopped", "dead"}
    return any(service.status.strip().lower() in bad_states for service in services)


def _status_from_metric(metric: Metric | None, last_seen: datetime | None, services: list[ServiceStatus]) -> str:
    if not last_seen:
        return "unknown"

    stale_cutoff = datetime.utcnow() - timedelta(seconds=settings.heartbeat_timeout_seconds)
    if last_seen < stale_cutoff:
        return "stale"

    if not metric:
        return "unknown"

    if _has_failing_service(services):
        return "critical"

    if (
        metric.cpu_percent >= settings.alert_cpu_threshold
        or metric.memory_percent >= settings.alert_memory_threshold
        or metric.disk_percent >= settings.alert_disk_threshold
    ):
        return "critical"

    return "healthy"


def get_servers(db: Session) -> list[ServerOut]:
    servers = db.execute(select(Server).order_by(Server.hostname.asc())).scalars().all()
    output: list[ServerOut] = []

    for server in servers:
        latest_metric = db.execute(
            select(Metric).where(Metric.server_id == server.id).order_by(desc(Metric.created_at)).limit(1)
        ).scalar_one_or_none()

        latest_services_raw = db.execute(
            select(ServiceStatus)
            .where(ServiceStatus.server_id == server.id)
            .order_by(desc(ServiceStatus.created_at))
            .limit(10)
        ).scalars().all()
        latest_nginx_metric = db.execute(
            select(NginxMetric).where(NginxMetric.server_id == server.id).order_by(desc(NginxMetric.created_at)).limit(1)
        ).scalar_one_or_none()

        latest_by_name: dict[str, ServiceStatus] = {}
        for service in latest_services_raw:
            if service.name not in latest_by_name:
                latest_by_name[service.name] = service

        last_seen = latest_metric.created_at if latest_metric else None
        status = _status_from_metric(latest_metric, last_seen, list(latest_by_name.values()))

        output.append(
            ServerOut(
                id=server.id,
                hostname=server.hostname,
                ip_address=server.ip_address,
                environment=server.environment,
                tags=[t for t in server.tags.split(",") if t],
                status=status,
                last_seen=last_seen,
                latest_metric=_metric_to_schema(latest_metric),
                latest_nginx_metric=_nginx_metric_to_schema(latest_nginx_metric),
                latest_services=[_service_to_schema(svc) for svc in latest_by_name.values()],
            )
        )

    return output


def get_server(db: Session, server_id: int) -> ServerOut | None:
    for server in get_servers(db):
        if server.id == server_id:
            return server
    return None


def get_servers_page(
    db: Session,
    status: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ServerOut], int]:
    servers = get_servers(db)

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


def get_overview(db: Session) -> OverviewOut:
    servers = get_servers(db)
    total = len(servers)
    healthy = len([s for s in servers if s.status == "healthy"])
    stale = len([s for s in servers if s.status == "stale"])
    critical = len([s for s in servers if s.status == "critical"])

    return OverviewOut(
        total_servers=total,
        healthy_servers=healthy,
        stale_servers=stale,
        critical_servers=critical,
    )


def get_server_metrics(db: Session, server_id: int, minutes: int = 60) -> list[MetricOut]:
    since = datetime.utcnow() - timedelta(minutes=minutes)
    metrics = db.execute(
        select(Metric)
        .where(Metric.server_id == server_id, Metric.created_at >= since)
        .order_by(Metric.created_at.asc())
    ).scalars().all()

    return [_metric_to_schema(metric) for metric in metrics if metric]


def get_server_nginx_metrics(db: Session, server_id: int, minutes: int = 60) -> list[NginxMetricOut]:
    since = datetime.utcnow() - timedelta(minutes=minutes)
    metrics = db.execute(
        select(NginxMetric)
        .where(NginxMetric.server_id == server_id, NginxMetric.created_at >= since)
        .order_by(NginxMetric.created_at.asc())
    ).scalars().all()
    return [_nginx_metric_to_schema(metric) for metric in metrics if metric]


def create_alert_event(
    db: Session,
    alert_key: str,
    severity: str,
    message: str,
    source: str,
    server_id: int | None,
    delivered: bool,
    suppressed: bool,
    commit: bool = True,
) -> AlertOut | None:
    alert = AlertEvent(
        server_id=server_id,
        alert_key=alert_key,
        severity=severity,
        message=message,
        source=source,
        delivered=delivered,
        suppressed=suppressed,
    )
    db.add(alert)

    if not commit:
        return None

    db.commit()
    db.refresh(alert)

    server_hostname = None
    if server_id is not None:
        server = db.execute(select(Server).where(Server.id == server_id)).scalar_one_or_none()
        server_hostname = server.hostname if server else None

    return _alert_to_schema(alert, server_hostname=server_hostname)


def get_alert_events(db: Session, limit: int = 50, server_id: int | None = None) -> list[AlertOut]:
    stmt = (
        select(AlertEvent, Server.hostname)
        .outerjoin(Server, Server.id == AlertEvent.server_id)
        .order_by(desc(AlertEvent.created_at))
        .limit(limit)
    )
    if server_id is not None:
        stmt = stmt.where(AlertEvent.server_id == server_id)

    rows = db.execute(stmt).all()
    return [_alert_to_schema(alert=row[0], server_hostname=row[1]) for row in rows]


def cleanup_old_metrics(db: Session, keep_days: int = 7) -> int:
    cutoff = datetime.utcnow() - timedelta(days=keep_days)
    old_count = db.execute(select(func.count()).select_from(Metric).where(Metric.created_at < cutoff)).scalar_one()
    db.query(Metric).filter(Metric.created_at < cutoff).delete()
    db.commit()
    return int(old_count)
