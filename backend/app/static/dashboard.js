const el = {
  fleetStatusDot: document.getElementById('fleet-status-dot'),
  fleetStatusText: document.getElementById('fleet-status-text'),
  uptimePct: document.getElementById('uptime-pct'),
  cpuValue: document.getElementById('cpu-value'),
  cpuDelta: document.getElementById('cpu-delta'),
  memValue: document.getElementById('mem-value'),
  memDelta: document.getElementById('mem-delta'),
  netValue: document.getElementById('net-value'),
  netDelta: document.getElementById('net-delta'),
  resValue: document.getElementById('res-value'),
  resDelta: document.getElementById('res-delta'),
  sparkCpu: document.getElementById('spark-cpu'),
  sparkMem: document.getElementById('spark-mem'),
  sparkNet: document.getElementById('spark-net'),
  sparkRes: document.getElementById('spark-res'),
  serversList: document.getElementById('servers-list'),
  activityList: document.getElementById('activity-list'),
  refresh: document.getElementById('refresh-btn'),
};

const REFRESH_MS = 10000;

const pct = (value, digits = 1) => `${Number(value || 0).toFixed(digits)}%`;
const gb = (value) => `${Number(value || 0).toFixed(1)} GB`;
const mbps = (value) => `${Number(value || 0).toFixed(0)} Mb/s`;
const ms = (value) => `${Number(value || 0).toFixed(0)}ms`;

function formatUptime(seconds) {
  const s = Number(seconds || 0);
  const days = Math.floor(s / 86400);
  const hours = Math.floor((s % 86400) / 3600);
  return `${days}d ${hours}h`;
}

function ago(iso) {
  if (!iso) return 'unknown';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const diff = Math.max(0, Date.now() - then);
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function percentWidth(value) {
  return Math.max(0, Math.min(100, Number(value || 0)));
}

function barClass(value) {
  const n = Number(value || 0);
  if (n >= 90) return 'bad';
  if (n >= 75) return 'warn';
  return '';
}

function deltaClass(value) {
  if (value <= -0.01) return '';
  if (value >= 5) return 'bad';
  if (value >= 0.01) return 'warn';
  return '';
}

function statusIcon(status) {
  if (status === 'healthy') return '✓';
  if (status === 'critical') return '⨯';
  if (status === 'stale') return '⚠';
  return '?';
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function renderSparkline(svg, series) {
  const points = Array.isArray(series) ? series : [];
  const width = 240;
  const height = 56;
  if (!svg) return;

  if (!points.length) {
    svg.innerHTML = '';
    return;
  }

  const values = points.map((p) => Number(p.value || 0));
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const span = Math.max(max - min, 1);

  const step = points.length > 1 ? width / (points.length - 1) : width;
  const path = values
    .map((value, idx) => {
      const x = idx * step;
      const y = height - ((value - min) / span) * (height - 4) - 2;
      return `${idx === 0 ? 'M' : 'L'}${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(' ');

  const gradientId = `${svg.id}-g`;
  const lastX = (points.length - 1) * step;
  const area = `${path} L${lastX.toFixed(2)} ${height} L0 ${height} Z`;

  svg.innerHTML = `
    <defs>
      <linearGradient id="${gradientId}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="rgba(56,245,201,0.4)"></stop>
        <stop offset="100%" stop-color="rgba(56,245,201,0.03)"></stop>
      </linearGradient>
    </defs>
    <path d="${area}" fill="url(#${gradientId})"></path>
    <path d="${path}" fill="none" stroke="#38f5c9" stroke-width="2.2" stroke-linecap="round"></path>
  `;
}

function setDelta(element, value) {
  if (!element) return;
  const n = Number(value || 0);
  const prefix = n > 0 ? '↑ ' : n < 0 ? '↓ ' : '';
  element.textContent = `${prefix}${Math.abs(n).toFixed(1)}%`;
  element.className = deltaClass(n);
}

function renderTopStatus(overview) {
  const hasIssues = Number(overview?.critical_servers || 0) > 0;
  el.fleetStatusText.textContent = hasIssues ? 'Attention required on critical systems' : 'All systems operational';
  el.fleetStatusDot.classList.toggle('bad', hasIssues);
}

function renderKpis(payload) {
  const { kpis, trends, overview } = payload;
  el.uptimePct.textContent = pct(overview?.uptime_percentage || 0, 2);

  el.cpuValue.textContent = pct(kpis?.cpu_percent || 0, 0);
  el.memValue.textContent = gb(kpis?.memory_gb || 0);
  el.netValue.textContent = mbps(kpis?.network_mbps || 0);
  el.resValue.textContent = ms(kpis?.response_ms || 0);

  setDelta(el.cpuDelta, kpis?.cpu_delta_percent || 0);
  setDelta(el.memDelta, kpis?.memory_delta_percent || 0);
  setDelta(el.netDelta, kpis?.network_delta_percent || 0);
  setDelta(el.resDelta, kpis?.response_delta_percent || 0);

  renderSparkline(el.sparkCpu, trends?.cpu || []);
  renderSparkline(el.sparkMem, trends?.memory || []);
  renderSparkline(el.sparkNet, trends?.network || []);
  renderSparkline(el.sparkRes, trends?.response || []);
}

function renderServers(servers) {
  if (!servers || !servers.length) {
    el.serversList.innerHTML = '<div class="empty-state">No server telemetry yet. Start agents on your hosts to populate the fleet.</div>';
    return;
  }

  el.serversList.innerHTML = servers
    .map((server) => {
      const m = server.latest_metric || {};
      const cpu = Number(m.cpu_percent || 0);
      const mem = Number(m.memory_percent || 0);
      const display = server.display_name || server.hostname;
      return `
        <article class="server-row">
          <div class="server-main">
            <span class="server-status-icon ${escapeHtml(server.status)}">${statusIcon(server.status)}</span>
            <div>
              <div class="server-title">${escapeHtml(display)}</div>
              <div class="server-sub">Uptime: ${formatUptime(m.uptime_seconds)} · ${escapeHtml(server.environment)}${server.region ? ` · ${escapeHtml(server.region)}` : ''}</div>
            </div>
          </div>
          <div class="server-metrics">
            <div class="metric-line">CPU ${cpu.toFixed(0)}% MEM ${mem.toFixed(0)}%
              <span class="metric-bar"><span class="${barClass(Math.max(cpu, mem))}" style="width:${percentWidth(Math.max(cpu, mem))}%"></span></span>
            </div>
          </div>
        </article>
      `;
    })
    .join('');
}

function severityClass(severity) {
  const s = String(severity || '').toLowerCase();
  if (s === 'critical' || s === 'error') return 'critical';
  if (s === 'warning' || s === 'warn') return 'warning';
  return 'info';
}

function renderActivity(alerts) {
  if (!alerts || !alerts.length) {
    el.activityList.innerHTML = '<div class="empty-state">No activity events yet.</div>';
    return;
  }

  el.activityList.innerHTML = alerts
    .map((event) => {
      const iconClass = severityClass(event.severity);
      const title = event.server_hostname ? `${event.message} on ${event.server_hostname}` : event.message;
      return `
        <article class="activity-item">
          <span class="activity-icon ${iconClass}"></span>
          <div>
            <div class="activity-message">${escapeHtml(title)}</div>
            <div class="activity-time">${ago(event.created_at)}</div>
          </div>
        </article>
      `;
    })
    .join('');
}

async function fetchJSON(url) {
  const res = await fetch(url, { headers: { Accept: 'application/json' } });
  if (res.status === 401) {
    window.location.assign('/sign-in');
    throw new Error('Session expired. Redirecting to sign in...');
  }
  if (!res.ok) {
    throw new Error(`Request failed (${res.status})`);
  }
  return res.json();
}

async function refreshDashboard() {
  try {
    const payload = await fetchJSON('/api/v1/dashboard/analytics?window_minutes=60&bucket_minutes=5&server_limit=150&alerts_limit=20');
    renderTopStatus(payload.overview || {});
    renderKpis(payload);
    renderServers(payload.servers || []);
    renderActivity(payload.alerts || []);
  } catch (error) {
    const message = escapeHtml(error?.message || 'Failed to refresh dashboard');
    el.serversList.innerHTML = `<div class="empty-state">${message}</div>`;
    el.activityList.innerHTML = `<div class="empty-state">${message}</div>`;
  }
}

el.refresh.addEventListener('click', refreshDashboard);
refreshDashboard();
setInterval(refreshDashboard, REFRESH_MS);
