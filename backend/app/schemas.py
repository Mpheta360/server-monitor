from datetime import datetime

from pydantic import BaseModel, Field


class ServiceInput(BaseModel):
    name: str
    status: str = "unknown"


class AgentServerInfo(BaseModel):
    hostname: str
    ip_address: str = ""
    environment: str = "production"
    tags: list[str] = Field(default_factory=list)


class AgentMetricInput(BaseModel):
    cpu_percent: float = Field(ge=0, le=100)
    memory_percent: float = Field(ge=0, le=100)
    disk_percent: float = Field(ge=0, le=100)
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


class AgentPayload(BaseModel):
    server: AgentServerInfo
    metrics: AgentMetricInput
    services: list[ServiceInput] = Field(default_factory=list)
    nginx: AgentNginxInput | None = None


class IngestResponse(BaseModel):
    server_id: int
    metric_id: int
    status: str


class MetricOut(BaseModel):
    cpu_percent: float
    memory_percent: float
    disk_percent: float
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
    hostname: str
    ip_address: str
    environment: str
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


class ServersPageOut(BaseModel):
    items: list[ServerOut]
    total: int
    limit: int
    offset: int


class MobileUserOut(BaseModel):
    id: str
    email: str | None
    role: str | None
