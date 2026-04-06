from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import crud
from ..config import settings
from ..database import get_db
from ..deps import verify_ingest_token
from ..schemas import AgentPayload, IngestResponse
from ..services.alerts import AlertDispatcher

router = APIRouter(prefix="/api/v1", tags=["ingest"])
alerts = AlertDispatcher()


@router.post("/ingest", response_model=IngestResponse, dependencies=[Depends(verify_ingest_token)])
def ingest_metrics(payload: AgentPayload, db: Session = Depends(get_db)) -> IngestResponse:
    server, metric = crud.upsert_server_with_metric(db, payload, commit=False)
    metric_checks = [
        ("cpu", metric.cpu_percent, settings.alert_cpu_threshold),
        ("memory", metric.memory_percent, settings.alert_memory_threshold),
        ("disk", metric.disk_percent, settings.alert_disk_threshold),
    ]

    for metric_name, metric_value, threshold in metric_checks:
        if metric_value >= threshold:
            alert_key = f"{server.hostname}:{metric_name}"
            message = (
                f"{server.hostname}: {metric_name} usage is {metric_value:.1f}% "
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
                server_id=server.id,
                delivered=result.delivered,
                suppressed=result.suppressed,
                commit=False,
            )

    bad_service_statuses = {"down", "failed", "inactive", "stopped", "dead"}
    for service in payload.services:
        current_status = service.status.strip().lower()
        if current_status in bad_service_statuses:
            alert_key = f"{server.hostname}:service:{service.name}"
            message = f"{server.hostname}: service {service.name} is {current_status}"
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
                server_id=server.id,
                delivered=result.delivered,
                suppressed=result.suppressed,
                commit=False,
            )

    # Persist server metric + optional alert events in one transaction for lower latency.
    db.commit()

    return IngestResponse(server_id=server.id, metric_id=metric.id, status="ok")
