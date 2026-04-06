from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import crud
from ..database import get_db
from ..deps import AuthenticatedUser, require_supabase_user
from ..schemas import AlertOut, BootstrapOut, MetricOut, MobileUserOut, NginxMetricOut, ServerOut, ServersPageOut

router = APIRouter(prefix="/api/v1/mobile", tags=["mobile"], dependencies=[Depends(require_supabase_user)])


@router.get("/me", response_model=MobileUserOut)
def me(current_user: AuthenticatedUser = Depends(require_supabase_user)) -> MobileUserOut:
    return MobileUserOut(
        id=current_user.id,
        email=current_user.email,
        role=current_user.role,
    )


@router.get("/bootstrap", response_model=BootstrapOut)
def bootstrap(
    server_limit: int = Query(default=30, ge=1, le=200),
    alerts_limit: int = Query(default=30, ge=1, le=200),
    db: Session = Depends(get_db),
) -> BootstrapOut:
    servers, _ = crud.get_servers_page(db, limit=server_limit, offset=0)
    alerts = crud.get_alert_events(db, limit=alerts_limit)
    return BootstrapOut(
        overview=crud.get_overview(db),
        servers=servers,
        alerts=alerts,
    )


@router.get("/servers", response_model=ServersPageOut)
def list_servers(
    status: str | None = Query(default=None, pattern="^(healthy|critical|stale|unknown)?$"),
    search: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> ServersPageOut:
    items, total = crud.get_servers_page(db, status=status, search=search, limit=limit, offset=offset)
    return ServersPageOut(items=items, total=total, limit=limit, offset=offset)


@router.get("/servers/{server_id}", response_model=ServerOut)
def get_server(server_id: int, db: Session = Depends(get_db)) -> ServerOut:
    server = crud.get_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    return server


@router.get("/servers/{server_id}/metrics", response_model=list[MetricOut])
def get_server_metrics(
    server_id: int,
    minutes: int = Query(default=60, ge=1, le=60 * 24),
    db: Session = Depends(get_db),
) -> list[MetricOut]:
    if not crud.get_server(db, server_id):
        raise HTTPException(status_code=404, detail="Server not found")
    return crud.get_server_metrics(db, server_id=server_id, minutes=minutes)


@router.get("/servers/{server_id}/nginx-metrics", response_model=list[NginxMetricOut])
def get_server_nginx_metrics(
    server_id: int,
    minutes: int = Query(default=60, ge=1, le=60 * 24),
    db: Session = Depends(get_db),
) -> list[NginxMetricOut]:
    if not crud.get_server(db, server_id):
        raise HTTPException(status_code=404, detail="Server not found")
    return crud.get_server_nginx_metrics(db, server_id=server_id, minutes=minutes)


@router.get("/alerts", response_model=list[AlertOut])
def get_alerts(
    limit: int = Query(default=50, ge=1, le=200),
    server_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[AlertOut]:
    return crud.get_alert_events(db, limit=limit, server_id=server_id)
