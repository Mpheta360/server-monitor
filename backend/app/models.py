from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Server(Base):
    __tablename__ = "servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    hostname: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    ip_address: Mapped[str] = mapped_column(String(64), default="")
    environment: Mapped[str] = mapped_column(String(64), default="production")
    tags: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    metrics: Mapped[list["Metric"]] = relationship("Metric", back_populates="server", cascade="all, delete-orphan")
    services: Mapped[list["ServiceStatus"]] = relationship("ServiceStatus", back_populates="server", cascade="all, delete-orphan")
    nginx_metrics: Mapped[list["NginxMetric"]] = relationship(
        "NginxMetric", back_populates="server", cascade="all, delete-orphan"
    )


class Metric(Base):
    __tablename__ = "metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    cpu_percent: Mapped[float] = mapped_column(Float)
    memory_percent: Mapped[float] = mapped_column(Float)
    disk_percent: Mapped[float] = mapped_column(Float)
    load_1m: Mapped[float] = mapped_column(Float, default=0.0)
    load_5m: Mapped[float] = mapped_column(Float, default=0.0)
    load_15m: Mapped[float] = mapped_column(Float, default=0.0)
    uptime_seconds: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    server: Mapped["Server"] = relationship("Server", back_populates="metrics")


class ServiceStatus(Base):
    __tablename__ = "service_statuses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    server: Mapped["Server"] = relationship("Server", back_populates="services")


class NginxMetric(Base):
    __tablename__ = "nginx_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    active_connections: Mapped[int] = mapped_column(Integer, default=0)
    accepts_total: Mapped[int] = mapped_column(Integer, default=0)
    handled_total: Mapped[int] = mapped_column(Integer, default=0)
    requests_total: Mapped[int] = mapped_column(Integer, default=0)
    reading: Mapped[int] = mapped_column(Integer, default=0)
    writing: Mapped[int] = mapped_column(Integer, default=0)
    waiting: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    server: Mapped["Server"] = relationship("Server", back_populates="nginx_metrics")


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    server_id: Mapped[int | None] = mapped_column(ForeignKey("servers.id", ondelete="SET NULL"), nullable=True, index=True)
    alert_key: Mapped[str] = mapped_column(String(255), index=True)
    severity: Mapped[str] = mapped_column(String(32), default="critical")
    message: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(64), default="ingest")
    delivered: Mapped[bool] = mapped_column(default=False)
    suppressed: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
