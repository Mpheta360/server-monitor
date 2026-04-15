from fastapi import APIRouter, Depends, HTTPException, Query

from .. import crud
from ..database import get_db
from ..deps import AuthenticatedUser, require_dashboard_user
from ..schemas import (
    AlertOut,
    BootstrapOut,
    DashboardAnalyticsOut,
    IssueReportIn,
    IssueReportOut,
    LogEventOut,
    MetricOut,
    NginxAppCheckOut,
    NginxMetricOut,
    OverviewOut,
    ServerOut,
)

router = APIRouter(prefix="/api/v1", tags=["servers"])


@router.get("/overview", response_model=OverviewOut)
def overview(
    db=Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_dashboard_user),
) -> OverviewOut:
    if db is None or db.client is None:
        raise HTTPException(
            status_code=503,
            detail="Database not configured. Set SUPABASE_URL, SUPABASE_ANON_KEY, and SUPABASE_SERVICE_ROLE_KEY in .env, then run SQL from app/schema.sql in Supabase"
        )
    return crud.get_overview(db)


@router.get("/servers", response_model=list[ServerOut])
def list_servers(
    db=Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_dashboard_user),
) -> list[ServerOut]:
    if db is None or db.client is None:
        raise HTTPException(
            status_code=503,
            detail="Database not configured. Set SUPABASE_URL, SUPABASE_ANON_KEY, and SUPABASE_SERVICE_ROLE_KEY in .env, then run SQL from app/schema.sql in Supabase"
        )
    return crud.get_servers(db)


@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(
    limit: int = Query(default=30, ge=1, le=200),
    db=Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_dashboard_user),
) -> list[AlertOut]:
    if db is None or db.client is None:
        raise HTTPException(
            status_code=503,
            detail="Database not configured. Set SUPABASE_URL, SUPABASE_ANON_KEY, and SUPABASE_SERVICE_ROLE_KEY in .env, then run SQL from app/schema.sql in Supabase"
        )
    return crud.get_alert_events(db, limit=limit)


@router.get("/dashboard/bootstrap", response_model=BootstrapOut)
def dashboard_bootstrap(
    server_limit: int = Query(default=50, ge=1, le=200),
    alerts_limit: int = Query(default=30, ge=1, le=200),
    db=Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_dashboard_user),
) -> BootstrapOut:
    if db is None or db.client is None:
        raise HTTPException(
            status_code=503,
            detail="Database not configured. Set SUPABASE_URL, SUPABASE_ANON_KEY, and SUPABASE_SERVICE_ROLE_KEY in .env, then run SQL from app/schema.sql in Supabase"
        )
    servers, _ = crud.get_servers_page(db, limit=server_limit, offset=0)
    alerts = crud.get_alert_events(db, limit=alerts_limit)
    return BootstrapOut(
        overview=crud.get_overview(db),
        servers=servers,
        alerts=alerts,
    )


@router.get("/dashboard/analytics", response_model=DashboardAnalyticsOut)
def dashboard_analytics(
    window_minutes: int = Query(default=60, ge=15, le=24 * 60),
    bucket_minutes: int = Query(default=5, ge=1, le=30),
    server_limit: int = Query(default=100, ge=1, le=500),
    alerts_limit: int = Query(default=12, ge=1, le=100),
    db=Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_dashboard_user),
) -> DashboardAnalyticsOut:
    if db is None or db.client is None:
        raise HTTPException(
            status_code=503,
            detail="Database not configured. Set SUPABASE_URL, SUPABASE_ANON_KEY, and SUPABASE_SERVICE_ROLE_KEY in .env, then run SQL from app/schema.sql in Supabase"
        )
    return crud.get_dashboard_analytics(
        db,
        window_minutes=window_minutes,
        bucket_minutes=bucket_minutes,
        server_limit=server_limit,
        alerts_limit=alerts_limit,
    )


@router.get("/servers/{server_id}/metrics", response_model=list[MetricOut])
def server_metrics(
    server_id: int,
    minutes: int = Query(default=60, ge=1, le=60 * 24),
    db=Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_dashboard_user),
) -> list[MetricOut]:
    if db is None or db.client is None:
        raise HTTPException(
            status_code=503,
            detail="Database not configured. Set SUPABASE_URL, SUPABASE_ANON_KEY, and SUPABASE_SERVICE_ROLE_KEY in .env, then run SQL from app/schema.sql in Supabase"
        )
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
    db=Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_dashboard_user),
) -> list[NginxMetricOut]:
    if db is None or db.client is None:
        raise HTTPException(
            status_code=503,
            detail="Database not configured. Set SUPABASE_URL, SUPABASE_ANON_KEY, and SUPABASE_SERVICE_ROLE_KEY in .env, then run SQL from app/schema.sql in Supabase"
        )
    metrics = crud.get_server_nginx_metrics(db, server_id=server_id, minutes=minutes)
    if not metrics:
        known_server_ids = {server.id for server in crud.get_servers(db)}
        if server_id not in known_server_ids:
            raise HTTPException(status_code=404, detail="Server not found")
    return metrics


@router.get("/nginx/apps", response_model=list[NginxAppCheckOut])
def nginx_apps(
    limit: int = Query(default=100, ge=1, le=500),
    server_id: int | None = Query(default=None),
    healthy: bool | None = Query(default=None),
    db=Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_dashboard_user),
) -> list[NginxAppCheckOut]:
    if db is None or db.client is None:
        raise HTTPException(
            status_code=503,
            detail="Database not configured. Set SUPABASE_URL, SUPABASE_ANON_KEY, and SUPABASE_SERVICE_ROLE_KEY in .env, then run SQL from app/schema.sql in Supabase"
        )
    return crud.get_nginx_app_checks(
        db,
        user_id=None,
        limit=limit,
        server_id=server_id,
        healthy=healthy,
    )


@router.get("/logs", response_model=list[LogEventOut])
def logs(
    limit: int = Query(default=100, ge=1, le=500),
    level: str | None = Query(default=None),
    server_id: int | None = Query(default=None),
    db=Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_dashboard_user),
) -> list[LogEventOut]:
    if db is None or db.client is None:
        raise HTTPException(
            status_code=503,
            detail="Database not configured. Set SUPABASE_URL, SUPABASE_ANON_KEY, and SUPABASE_SERVICE_ROLE_KEY in .env, then run SQL from app/schema.sql in Supabase"
        )
    return crud.get_log_events(
        db,
        user_id=None,
        limit=limit,
        server_id=server_id,
        level=level,
    )


@router.post("/issues/report", response_model=IssueReportOut)
def report_issue(
    payload: IssueReportIn,
    db=Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_dashboard_user),
) -> IssueReportOut:
    if db is None or db.client is None:
        raise HTTPException(
            status_code=503,
            detail="Database not configured. Set SUPABASE_URL, SUPABASE_ANON_KEY, and SUPABASE_SERVICE_ROLE_KEY in .env, then run SQL from app/schema.sql in Supabase"
        )
    issue = crud.create_issue_report(
        db,
        user_id=getattr(current_user, "id", None),
        payload=payload,
    )
    if not issue:
        raise HTTPException(status_code=500, detail="Could not create issue report")
    return issue


@router.get("/issues", response_model=list[IssueReportOut])
def list_issues(
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(default=None),
    db=Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_dashboard_user),
) -> list[IssueReportOut]:
    if db is None or db.client is None:
        raise HTTPException(
            status_code=503,
            detail="Database not configured. Set SUPABASE_URL, SUPABASE_ANON_KEY, and SUPABASE_SERVICE_ROLE_KEY in .env, then run SQL from app/schema.sql in Supabase"
        )
    return crud.get_issue_reports(
        db,
        user_id=None,
        limit=limit,
        status=status,
    )
