from fastapi import APIRouter, Depends, HTTPException

from .. import crud
from ..config import settings
from ..database import get_db
from ..deps import verify_ingest_token
from ..schemas import AgentPayload, IngestResponse
from ..services.alerts import AlertDispatcher

router = APIRouter(prefix="/api/v1", tags=["ingest"])
alerts = AlertDispatcher()


@router.post("/ingest", response_model=IngestResponse, dependencies=[Depends(verify_ingest_token)])
def ingest_metrics(payload: AgentPayload, db = Depends(get_db)) -> IngestResponse:
    if db is None or db.client is None:
        raise HTTPException(
            status_code=503,
            detail="Database not configured. Set SUPABASE_URL, SUPABASE_ANON_KEY, and SUPABASE_SERVICE_ROLE_KEY in .env"
        )
    
    server, metric = crud.upsert_server_with_metric(db, payload, commit=False)
    user_id = str(payload.user_id or settings.monitor_default_user_id or server.get("user_id") or "").strip() or None
    
    metric_checks = [
        ("cpu", metric.get('cpu_percent'), settings.alert_cpu_threshold),
        ("memory", metric.get('memory_percent'), settings.alert_memory_threshold),
        ("disk", metric.get('disk_percent'), settings.alert_disk_threshold),
    ]

    for metric_name, metric_value, threshold in metric_checks:
        if metric_value is not None and metric_value >= threshold:
            alert_key = f"{server.get('hostname')}:{metric_name}"
            message = (
                f"{server.get('hostname')}: {metric_name} usage is {metric_value:.1f}% "
                f"(threshold {threshold:.1f}%)"
            )
            result = alerts.dispatch(
                key=alert_key,
                severity="critical",
                message=message,
            )
            crud.create_alert_event(
                db=db,
                alert_key=alert_key,
                severity="critical",
                message=message,
                source="ingest-metric-threshold",
                server_id=server.get('id'),
                delivered=result.delivered,
                suppressed=result.suppressed,
                user_id=user_id,
                commit=False,
            )

    bad_service_statuses = {"down", "failed", "inactive", "stopped", "dead"}
    for service in payload.services:
        current_status = service.status.strip().lower()
        if current_status in bad_service_statuses:
            alert_key = f"{server.get('hostname')}:service:{service.name}"
            message = f"{server.get('hostname')}: service {service.name} is {current_status}"
            result = alerts.dispatch(
                key=alert_key,
                severity="critical",
                message=message,
            )
            crud.create_alert_event(
                db=db,
                alert_key=alert_key,
                severity="critical",
                message=message,
                source="ingest-service-status",
                server_id=server.get('id'),
                delivered=result.delivered,
                suppressed=result.suppressed,
                user_id=user_id,
                commit=False,
            )

    if payload.nginx_apps:
        checks = []
        for app_check in payload.nginx_apps:
            checks.append(
                {
                    "app_name": app_check.app_name,
                    "check_url": app_check.check_url,
                    "status_code": app_check.status_code,
                    "response_time_ms": app_check.response_time_ms,
                    "healthy": app_check.healthy,
                    "error": app_check.error,
                }
            )
        crud.create_nginx_app_checks(
            db,
            user_id=user_id,
            server_id=server.get("id"),
            checks=checks,
        )
        for app_check in payload.nginx_apps:
            if app_check.healthy:
                continue
            alert_key = f"{server.get('hostname')}:nginx-app:{app_check.app_name}"
            message = (
                f"{server.get('hostname')}: nginx app {app_check.app_name} unhealthy "
                f"(status={app_check.status_code}, error={app_check.error or 'n/a'})"
            )
            result = alerts.dispatch(
                key=alert_key,
                severity="critical",
                message=message,
            )
            crud.create_alert_event(
                db=db,
                alert_key=alert_key,
                severity="critical",
                message=message,
                source="ingest-nginx-app-check",
                server_id=server.get("id"),
                delivered=result.delivered,
                suppressed=result.suppressed,
                user_id=user_id,
                commit=False,
            )

    crud.create_log_event(
        db,
        user_id=user_id,
        level="info",
        source="ingest",
        message=f"Ingested metrics from {server.get('hostname')}",
        server_id=server.get("id"),
        context_json={
            "cpu_percent": metric.get("cpu_percent"),
            "memory_percent": metric.get("memory_percent"),
            "disk_percent": metric.get("disk_percent"),
        },
    )

    return IngestResponse(server_id=server.get('id'), metric_id=metric.get('id'), status="ok")
