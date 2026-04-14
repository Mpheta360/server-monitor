from datetime import datetime, timedelta
import logging

from .config import settings
from .schemas import AgentPayload, AlertOut, MetricOut, NginxMetricOut, OverviewOut, ServerOut, ServiceOut

logger = logging.getLogger(__name__)

def upsert_server_with_metric(db, payload: AgentPayload, commit: bool = True) -> tuple[dict, dict]:
    """Upsert server and related metric data to Supabase"""
    if not db or not db.client:
        raise RuntimeError("Database not configured")
    
    client = db.client
    tags = ",".join(payload.server.tags)
    
    # Check if server exists by hostname
    servers = client.table('servers').select().eq('hostname', payload.server.hostname).execute()
    server = servers.data[0] if servers.data else None
    
    if not server:
        # Create new server
        server_data = {
            'hostname': payload.server.hostname,
            'ip_address': payload.server.ip_address,
            'environment': payload.server.environment,
            'tags': tags,
        }
        result = client.table('servers').insert(server_data).execute()
        server = result.data[0] if result.data else server_data
    else:
        # Update existing server
        server_update = {
            'ip_address': payload.server.ip_address,
            'environment': payload.server.environment,
            'tags': tags,
        }
        result = client.table('servers').update(server_update).eq('id', server['id']).execute()
        if result.data:
            server = result.data[0]
    
    # Insert metric
    metric_data = {
        'server_id': server['id'],
        'cpu_percent': payload.metrics.cpu_percent,
        'memory_percent': payload.metrics.memory_percent,
        'disk_percent': payload.metrics.disk_percent,
        'load_1m': payload.metrics.load_1m,
        'load_5m': payload.metrics.load_5m,
        'load_15m': payload.metrics.load_15m,
        'uptime_seconds': payload.metrics.uptime_seconds,
    }
    result = client.table('metrics').insert(metric_data).execute()
    metric = result.data[0] if result.data else metric_data
    
    # Insert services
    for service in payload.services:
        service_data = {
            'server_id': server['id'],
            'name': service.name,
            'status': service.status,
        }
        try:
            client.table('service_statuses').insert(service_data).execute()
        except Exception as e:
            logger.error(f"Failed to insert service status: {e}")
    
    # Insert nginx metric if present
    if payload.nginx:
        nginx_data = {
            'server_id': server['id'],
            'active_connections': payload.nginx.active_connections,
            'accepts_total': payload.nginx.accepts_total,
            'handled_total': payload.nginx.handled_total,
            'requests_total': payload.nginx.requests_total,
            'reading': payload.nginx.reading,
            'writing': payload.nginx.writing,
            'waiting': payload.nginx.waiting,
        }
        try:
            client.table('nginx_metrics').insert(nginx_data).execute()
        except Exception as e:
            logger.error(f"Failed to insert nginx metric: {e}")
    
    return server, metric

def _metric_to_schema(metric: dict | None) -> MetricOut | None:
    if not metric:
        return None

    return MetricOut(
        cpu_percent=metric.get('cpu_percent'),
        memory_percent=metric.get('memory_percent'),
        disk_percent=metric.get('disk_percent'),
        load_1m=metric.get('load_1m'),
        load_5m=metric.get('load_5m'),
        load_15m=metric.get('load_15m'),
        uptime_seconds=metric.get('uptime_seconds'),
        created_at=metric.get('created_at'),
    )


def _service_to_schema(service: dict) -> ServiceOut:
    return ServiceOut(name=service.get('name'), status=service.get('status'), created_at=service.get('created_at'))


def _nginx_metric_to_schema(metric: dict | None) -> NginxMetricOut | None:
    if not metric:
        return None

    return NginxMetricOut(
        active_connections=metric.get('active_connections'),
        accepts_total=metric.get('accepts_total'),
        handled_total=metric.get('handled_total'),
        requests_total=metric.get('requests_total'),
        reading=metric.get('reading'),
        writing=metric.get('writing'),
        waiting=metric.get('waiting'),
        created_at=metric.get('created_at'),
    )


def _alert_to_schema(alert: dict, server_hostname: str | None) -> AlertOut:
    return AlertOut(
        id=alert.get('id'),
        server_id=alert.get('server_id'),
        server_hostname=server_hostname,
        alert_key=alert.get('alert_key'),
        severity=alert.get('severity'),
        message=alert.get('message'),
        source=alert.get('source'),
        delivered=alert.get('delivered'),
        suppressed=alert.get('suppressed'),
        created_at=alert.get('created_at'),
    )


def _has_failing_service(services: list[dict]) -> bool:
    bad_states = {"down", "failed", "inactive", "stopped", "dead"}
    return any(service.get('status', '').strip().lower() in bad_states for service in services)


def _status_from_metric(metric: dict | None, last_seen: datetime | None, services: list[dict]) -> str:
    if not last_seen:
        return "unknown"

    stale_cutoff = datetime.utcnow() - timedelta(seconds=settings.heartbeat_timeout_seconds)
    if last_seen < stale_cutoff:
        return "stale"

    if not metric:
        return "unknown"

    if _has_failing_service(services):
        return "critical"

    cpu = metric.get('cpu_percent', 0)
    mem = metric.get('memory_percent', 0)
    disk = metric.get('disk_percent', 0)
    
    if (
        cpu >= settings.alert_cpu_threshold
        or mem >= settings.alert_memory_threshold
        or disk >= settings.alert_disk_threshold
    ):
        return "critical"

    return "healthy"


def get_servers(db) -> list[ServerOut]:
    """Fetch all servers from Supabase"""
    if not db or not db.client:
        return []
    
    client = db.client
    output: list[ServerOut] = []
    
    try:
        # Get all servers ordered by hostname
        servers_result = client.table('servers').select().order('hostname', desc=False).execute()
        servers = servers_result.data if servers_result.data else []
        
        for server in servers:
            server_id = server.get('id')
            
            # Get latest metric
            metrics_result = client.table('metrics').select().eq('server_id', server_id).order('created_at', desc=True).limit(1).execute()
            latest_metric = metrics_result.data[0] if metrics_result.data else None
            
            # Get latest services
            services_result = client.table('service_statuses').select().eq('server_id', server_id).order('created_at', desc=True).limit(10).execute()
            latest_services_raw = services_result.data if services_result.data else []
            
            # Get latest nginx metric
            nginx_result = client.table('nginx_metrics').select().eq('server_id', server_id).order('created_at', desc=True).limit(1).execute()
            latest_nginx_metric = nginx_result.data[0] if nginx_result.data else None
            
            # Group services by name (keep only latest of each)
            latest_by_name: dict[str, dict] = {}
            for service in latest_services_raw:
                svc_name = service.get('name')
                if svc_name not in latest_by_name:
                    latest_by_name[svc_name] = service
            
            last_seen = None
            if latest_metric:
                last_seen_str = latest_metric.get('created_at')
                if last_seen_str:
                    last_seen = datetime.fromisoformat(last_seen_str.replace('Z', '+00:00'))
            
            status = _status_from_metric(latest_metric, last_seen, list(latest_by_name.values()))
            
            output.append(
                ServerOut(
                    id=server_id,
                    hostname=server.get('hostname'),
                    ip_address=server.get('ip_address'),
                    environment=server.get('environment'),
                    tags=[t for t in server.get('tags', '').split(",") if t],
                    status=status,
                    last_seen=last_seen,
                    latest_metric=_metric_to_schema(latest_metric),
                    latest_nginx_metric=_nginx_metric_to_schema(latest_nginx_metric),
                    latest_services=[_service_to_schema(svc) for svc in latest_by_name.values()],
                )
            )
        
        return output
    except Exception as e:
        logger.error(f"Error fetching servers: {e}")
        return []


def get_server(db, server_id: int) -> ServerOut | None:
    """Fetch a specific server by ID"""
    for server in get_servers(db):
        if server.id == server_id:
            return server
    return None


def get_servers_page(
    db,
    status: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ServerOut], int]:
    """Fetch paginated servers with optional filtering"""
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


def get_overview(db) -> OverviewOut:
    """Get overview statistics"""
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


def get_server_metrics(db, server_id: int, minutes: int = 60) -> list[MetricOut]:
    """Fetch server metrics from the last N minutes"""
    if not db or not db.client:
        return []
    
    client = db.client
    try:
        since = datetime.utcnow() - timedelta(minutes=minutes)
        since_str = since.isoformat() + 'Z'
        
        metrics_result = client.table('metrics').select().eq('server_id', server_id).gte('created_at', since_str).order('created_at', desc=False).execute()
        metrics = metrics_result.data if metrics_result.data else []
        
        return [_metric_to_schema(metric) for metric in metrics if metric]
    except Exception as e:
        logger.error(f"Error fetching server metrics: {e}")
        return []


def get_server_nginx_metrics(db, server_id: int, minutes: int = 60) -> list[NginxMetricOut]:
    """Fetch server nginx metrics from the last N minutes"""
    if not db or not db.client:
        return []
    
    client = db.client
    try:
        since = datetime.utcnow() - timedelta(minutes=minutes)
        since_str = since.isoformat() + 'Z'
        
        metrics_result = client.table('nginx_metrics').select().eq('server_id', server_id).gte('created_at', since_str).order('created_at', desc=False).execute()
        metrics = metrics_result.data if metrics_result.data else []
        
        return [_nginx_metric_to_schema(metric) for metric in metrics if metric]
    except Exception as e:
        logger.error(f"Error fetching nginx metrics: {e}")
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
    commit: bool = True,
) -> AlertOut | None:
    """Create an alert event"""
    if not db or not db.client:
        return None
    
    client = db.client
    try:
        alert_data = {
            'server_id': server_id,
            'alert_key': alert_key,
            'severity': severity,
            'message': message,
            'source': source,
            'delivered': delivered,
            'suppressed': suppressed,
        }
        
        result = client.table('alert_events').insert(alert_data).execute()
        alert = result.data[0] if result.data else alert_data
        
        server_hostname = None
        if server_id is not None:
            servers_result = client.table('servers').select().eq('id', server_id).execute()
            if servers_result.data:
                server_hostname = servers_result.data[0].get('hostname')
        
        return _alert_to_schema(alert, server_hostname=server_hostname)
    except Exception as e:
        logger.error(f"Error creating alert event: {e}")
        return None


def get_alert_events(db, limit: int = 50, server_id: int | None = None) -> list[AlertOut]:
    """Fetch alert events"""
    if not db or not db.client:
        return []
    
    client = db.client
    try:
        query = client.table('alert_events').select('*, servers(hostname)').order('created_at', desc=True).limit(limit)
        
        if server_id is not None:
            query = query.eq('server_id', server_id)
        
        result = query.execute()
        alerts = result.data if result.data else []
        
        output = []
        for alert_row in alerts:
            server_hostname = None
            if alert_row.get('servers'):
                server_hostname = alert_row['servers'].get('hostname') if isinstance(alert_row['servers'], dict) else None
            output.append(_alert_to_schema(alert_row, server_hostname))
        
        return output
    except Exception as e:
        logger.error(f"Error fetching alert events: {e}")
        return []


def cleanup_old_metrics(db, keep_days: int = 7) -> int:
    """Delete metrics older than keep_days"""
    if not db or not db.client:
        return 0
    
    client = db.client
    try:
        cutoff = datetime.utcnow() - timedelta(days=keep_days)
        cutoff_str = cutoff.isoformat() + 'Z'
        
        # First count how many we're deleting
        count_result = client.table('metrics').select('id').lt('created_at', cutoff_str).execute()
        old_count = len(count_result.data) if count_result.data else 0
        
        # Delete them
        if old_count > 0:
            client.table('metrics').delete().lt('created_at', cutoff_str).execute()
        
        return old_count
    except Exception as e:
        logger.error(f"Error cleaning up old metrics: {e}")
        return 0

