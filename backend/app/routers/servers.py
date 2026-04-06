from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import crud
from ..database import get_db
from ..deps import verify_admin_basic_auth
from ..schemas import MetricOut, NginxMetricOut, OverviewOut, ServerOut

router = APIRouter(prefix="/api/v1", tags=["servers"], dependencies=[Depends(verify_admin_basic_auth)])


@router.get("/overview", response_model=OverviewOut)
def overview(db: Session = Depends(get_db)) -> OverviewOut:
    return crud.get_overview(db)


@router.get("/servers", response_model=list[ServerOut])
def list_servers(db: Session = Depends(get_db)) -> list[ServerOut]:
    return crud.get_servers(db)


@router.get("/servers/{server_id}/metrics", response_model=list[MetricOut])
def server_metrics(
    server_id: int,
    minutes: int = Query(default=60, ge=1, le=60 * 24),
    db: Session = Depends(get_db),
) -> list[MetricOut]:
    metrics = crud.get_server_metrics(db, server_id=server_id, minutes=minutes)
    if not metrics:
        # Return empty list if no metrics exist yet; only 404 on impossible IDs.
        known_server_ids = {server.id for server in crud.get_servers(db)}
        if server_id not in known_server_ids:
            raise HTTPException(status_code=404, detail="Server not found")
    return metrics


@router.get("/servers/{server_id}/nginx-metrics", response_model=list[NginxMetricOut])
def server_nginx_metrics(
    server_id: int,
    minutes: int = Query(default=60, ge=1, le=60 * 24),
    db: Session = Depends(get_db),
) -> list[NginxMetricOut]:
    metrics = crud.get_server_nginx_metrics(db, server_id=server_id, minutes=minutes)
    if not metrics:
        known_server_ids = {server.id for server in crud.get_servers(db)}
        if server_id not in known_server_ids:
            raise HTTPException(status_code=404, detail="Server not found")
    return metrics
