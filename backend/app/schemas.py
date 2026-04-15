from datetime import datetime

from pydantic import BaseModel, Field


class ServiceInput(BaseModel):
    name: str
    status: str = "unknown"


class AgentServerInfo(BaseModel):
    agent_key: str | None = None
    hostname: str
    display_name: str | None = None
    ip_address: str = ""
    environment: str = "production"
    region: str | None = None
    tags: list[str] = Field(default_factory=list)


class AgentMetricInput(BaseModel):
    cpu_percent: float = Field(ge=0, le=100)
    memory_percent: float = Field(ge=0, le=100)
    disk_percent: float = Field(ge=0, le=100)
    network_io_mbps: float = Field(default=0, ge=0)
    response_time_ms: float = Field(default=0, ge=0)
    load_1m: float = 0
    load_5m: float = 0
    load_15m: float = 0
    uptime_seconds: int = Field(ge=0)


class AgentNginxInput(BaseModel):
    active_connections: int = Field(ge=0)
    accepts_total: int = Field(ge=0)
    handled_total: int = Field(ge=0)
    requests_total: int = Field(ge=0)
    reading: int = Field(ge=0)
    writing: int = Field(ge=0)
    waiting: int = Field(ge=0)


class AgentNginxAppInput(BaseModel):
    app_name: str
    check_url: str
    status_code: int | None = None
    response_time_ms: float = Field(default=0, ge=0)
    healthy: bool = False
    error: str | None = None


class AgentPayload(BaseModel):
    user_id: str | None = None
    server: AgentServerInfo
    metrics: AgentMetricInput
    services: list[ServiceInput] = Field(default_factory=list)
    nginx: AgentNginxInput | None = None
    nginx_apps: list[AgentNginxAppInput] = Field(default_factory=list)


class IngestResponse(BaseModel):
    server_id: int
    metric_id: int
    status: str


class MetricOut(BaseModel):
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    network_io_mbps: float = 0
    response_time_ms: float = 0
    load_1m: float
    load_5m: float
    load_15m: float
    uptime_seconds: int
    created_at: datetime


class NginxMetricOut(BaseModel):
    active_connections: int
    accepts_total: int
    handled_total: int
    requests_total: int
    reading: int
    writing: int
    waiting: int
    created_at: datetime


class ServiceOut(BaseModel):
    name: str
    status: str
    created_at: datetime


class ServerOut(BaseModel):
    id: int
    agent_key: str
    hostname: str
    display_name: str | None = None
    ip_address: str
    environment: str
    region: str | None = None
    tags: list[str]
    status: str
    last_seen: datetime | None
    latest_metric: MetricOut | None
    latest_nginx_metric: NginxMetricOut | None
    latest_services: list[ServiceOut] = Field(default_factory=list)


class OverviewOut(BaseModel):
    total_servers: int
    healthy_servers: int
    stale_servers: int
    critical_servers: int
    avg_cpu_percent: float = 0
    avg_memory_percent: float = 0
    total_network_io_mbps: float = 0
    avg_response_time_ms: float = 0
    uptime_percentage: float = 0


class AlertOut(BaseModel):
    id: int
    server_id: int | None
    server_hostname: str | None
    alert_key: str
    severity: str
    message: str
    source: str
    delivered: bool
    suppressed: bool
    created_at: datetime


class BootstrapOut(BaseModel):
    overview: OverviewOut
    servers: list[ServerOut]
    alerts: list[AlertOut]


class NginxAppCheckOut(BaseModel):
    id: int
    server_id: int
    server_hostname: str | None
    app_name: str
    check_url: str
    status_code: int | None
    response_time_ms: float
    healthy: bool
    error: str | None
    created_at: datetime


class LogEventOut(BaseModel):
    id: int
    server_id: int | None
    server_hostname: str | None
    level: str
    source: str
    message: str
    context_json: dict = Field(default_factory=dict)
    created_at: datetime


class IssueReportIn(BaseModel):
    server_id: int | None = None
    nginx_app_name: str | None = None
    severity: str = "warning"
    title: str
    description: str


class IssueReportOut(BaseModel):
    id: int
    server_id: int | None
    server_hostname: str | None
    nginx_app_name: str | None
    severity: str
    title: str
    description: str
    status: str
    created_at: datetime


class SparklinePointOut(BaseModel):
    ts: datetime
    value: float


class DashboardKpisOut(BaseModel):
    cpu_percent: float
    cpu_delta_percent: float
    memory_gb: float
    memory_delta_percent: float
    network_mbps: float
    network_delta_percent: float
    response_ms: float
    response_delta_percent: float
    uptime_percentage: float


class DashboardTrendsOut(BaseModel):
    cpu: list[SparklinePointOut] = Field(default_factory=list)
    memory: list[SparklinePointOut] = Field(default_factory=list)
    network: list[SparklinePointOut] = Field(default_factory=list)
    response: list[SparklinePointOut] = Field(default_factory=list)


class DashboardAnalyticsOut(BaseModel):
    overview: OverviewOut
    kpis: DashboardKpisOut
    trends: DashboardTrendsOut
    servers: list[ServerOut]
    alerts: list[AlertOut]


class ServersPageOut(BaseModel):
    items: list[ServerOut]
    total: int
    limit: int
    offset: int


class MobileUserOut(BaseModel):
    id: str
    email: str | None
    role: str | None
