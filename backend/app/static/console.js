const page = document.body?.dataset?.page || 'overview';

const el = {
  fleetStatusDot: document.getElementById('fleet-status-dot'),
  fleetStatusText: document.getElementById('fleet-status-text'),
  fleetTotal: document.getElementById('fleet-total'),
  content: document.getElementById('page-content'),
  refresh: document.getElementById('refresh-btn'),
};

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function pct(value) {
  return `${Number(value || 0).toFixed(1)}%`;
}

function ago(iso) {
  if (!iso) return 'unknown';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const d = Math.max(0, Date.now() - t);
  const mins = Math.floor(d / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function statusClass(status) {
  const s = String(status || '').toLowerCase();
  if (s === 'healthy') return 'ok';
  if (s === 'critical') return 'bad';
  if (s === 'stale') return 'warn';
  return 'muted';
}

function levelClass(level) {
  const l = String(level || '').toLowerCase();
  if (l === 'critical' || l === 'error') return 'bad';
  if (l === 'warning' || l === 'warn') return 'warn';
  return 'ok';
}

async function fetchJSON(url, options) {
  const res = await fetch(url, options);
  if (res.status === 401) {
    window.location.assign('/sign-in');
    throw new Error('Session expired');
  }
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || `Request failed (${res.status})`);
  }
  return res.json();
}

function renderHeader(overview) {
  el.fleetTotal.textContent = String(overview?.total_servers || 0);
  const hasCritical = Number(overview?.critical_servers || 0) > 0;
  el.fleetStatusText.textContent = hasCritical ? 'Critical issues detected in fleet' : 'All systems operational';
  el.fleetStatusDot.classList.toggle('bad', hasCritical);
}

function empty(message) {
  el.content.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
}

function renderOverview(data) {
  const { overview, servers, alerts, kpis } = data;
  const recentServers = (servers || []).slice(0, 8);
  const recentAlerts = (alerts || []).slice(0, 8);

  el.content.innerHTML = `
    <section class="kpi-grid compact-grid">
      <article class="kpi-card"><div class="kpi-head"><span>CPU</span></div><div class="kpi-value">${Number(kpis?.cpu_percent || 0).toFixed(0)}%</div></article>
      <article class="kpi-card"><div class="kpi-head"><span>Memory</span></div><div class="kpi-value">${Number(kpis?.memory_gb || 0).toFixed(1)} GB</div></article>
      <article class="kpi-card"><div class="kpi-head"><span>Network</span></div><div class="kpi-value">${Number(kpis?.network_mbps || 0).toFixed(0)} Mb/s</div></article>
      <article class="kpi-card"><div class="kpi-head"><span>Response</span></div><div class="kpi-value">${Number(kpis?.response_ms || 0).toFixed(0)}ms</div></article>
    </section>

    <section class="board-grid">
      <article class="panel">
        <header class="panel-head"><h2>Servers</h2></header>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Server</th><th>Status</th><th>CPU</th><th>Memory</th><th>Last Seen</th></tr></thead>
            <tbody>
              ${recentServers.map((s) => `
                <tr>
                  <td>${escapeHtml(s.display_name || s.hostname)}</td>
                  <td><span class="pill ${statusClass(s.status)}">${escapeHtml(s.status)}</span></td>
                  <td>${pct(s.latest_metric?.cpu_percent || 0)}</td>
                  <td>${pct(s.latest_metric?.memory_percent || 0)}</td>
                  <td>${ago(s.last_seen)}</td>
                </tr>
              `).join('') || '<tr><td colspan="5">No servers yet</td></tr>'}
            </tbody>
          </table>
        </div>
      </article>
      <article class="panel">
        <header class="panel-head"><h2>Activity</h2></header>
        <div class="activity-list">
          ${recentAlerts.map((a) => `
            <article class="activity-item">
              <span class="activity-icon ${levelClass(a.severity)}"></span>
              <div>
                <div class="activity-message">${escapeHtml(a.message)}</div>
                <div class="activity-time">${ago(a.created_at)}</div>
              </div>
            </article>
          `).join('') || '<div class="empty-state">No recent alerts</div>'}
        </div>
      </article>
    </section>
  `;

  renderHeader(overview);
}

async function loadOverview() {
  const data = await fetchJSON('/api/v1/dashboard/analytics?window_minutes=60&bucket_minutes=5&server_limit=100&alerts_limit=20');
  renderOverview(data);
}

function buildLatestNginxMap(checks) {
  const latest = new Map();
  for (const item of checks || []) {
    const key = `${item.server_id}:${item.app_name}`;
    if (!latest.has(key)) latest.set(key, item);
  }
  return latest;
}

async function loadServers() {
  const [servers, checks] = await Promise.all([
    fetchJSON('/api/v1/servers'),
    fetchJSON('/api/v1/nginx/apps?limit=400'),
  ]);

  const latest = buildLatestNginxMap(checks);
  const unhealthyByServer = new Map();
  for (const item of latest.values()) {
    if (!item.healthy) {
      const n = unhealthyByServer.get(item.server_id) || 0;
      unhealthyByServer.set(item.server_id, n + 1);
    }
  }

  const critical = servers.filter((s) => s.status === 'critical').length;
  el.fleetTotal.textContent = String(servers.length);
  el.fleetStatusText.textContent = critical > 0 ? `Critical: ${critical} server(s)` : 'Server fleet healthy';
  el.fleetStatusDot.classList.toggle('bad', critical > 0);

  el.content.innerHTML = `
    <article class="panel">
      <header class="panel-head"><h2>Servers</h2></header>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Name</th><th>Environment</th><th>Status</th><th>CPU</th><th>MEM</th><th>Nginx Apps Unhealthy</th><th>Last Seen</th></tr></thead>
          <tbody>
            ${(servers || []).map((s) => `
              <tr>
                <td>${escapeHtml(s.display_name || s.hostname)}<br /><small>${escapeHtml(s.region || s.ip_address || '-')}</small></td>
                <td>${escapeHtml(s.environment)}</td>
                <td><span class="pill ${statusClass(s.status)}">${escapeHtml(s.status)}</span></td>
                <td>${pct(s.latest_metric?.cpu_percent || 0)}</td>
                <td>${pct(s.latest_metric?.memory_percent || 0)}</td>
                <td>${unhealthyByServer.get(s.id) || 0}</td>
                <td>${ago(s.last_seen)}</td>
              </tr>
            `).join('') || '<tr><td colspan="7">No servers found.</td></tr>'}
          </tbody>
        </table>
      </div>
    </article>
  `;
}

async function loadMetrics() {
  const data = await fetchJSON('/api/v1/dashboard/analytics?window_minutes=180&bucket_minutes=10&server_limit=200&alerts_limit=8');
  const servers = data.servers || [];
  renderHeader(data.overview);

  el.content.innerHTML = `
    <section class="kpi-grid compact-grid">
      <article class="kpi-card"><div class="kpi-head"><span>Avg CPU</span></div><div class="kpi-value">${Number(data.overview?.avg_cpu_percent || 0).toFixed(1)}%</div></article>
      <article class="kpi-card"><div class="kpi-head"><span>Avg Memory</span></div><div class="kpi-value">${Number(data.overview?.avg_memory_percent || 0).toFixed(1)}%</div></article>
      <article class="kpi-card"><div class="kpi-head"><span>Total Network</span></div><div class="kpi-value">${Number(data.overview?.total_network_io_mbps || 0).toFixed(1)} Mb/s</div></article>
      <article class="kpi-card"><div class="kpi-head"><span>Avg Response</span></div><div class="kpi-value">${Number(data.overview?.avg_response_time_ms || 0).toFixed(1)}ms</div></article>
    </section>
    <article class="panel">
      <header class="panel-head"><h2>Per-Server Metrics</h2></header>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Server</th><th>CPU</th><th>Memory</th><th>Disk</th><th>Network I/O</th><th>Response</th><th>Load 1m</th></tr></thead>
          <tbody>
            ${servers.map((s) => {
              const m = s.latest_metric || {};
              return `
                <tr>
                  <td>${escapeHtml(s.display_name || s.hostname)}</td>
                  <td>${pct(m.cpu_percent || 0)}</td>
                  <td>${pct(m.memory_percent || 0)}</td>
                  <td>${pct(m.disk_percent || 0)}</td>
                  <td>${Number(m.network_io_mbps || 0).toFixed(2)} Mb/s</td>
                  <td>${Number(m.response_time_ms || 0).toFixed(1)} ms</td>
                  <td>${Number(m.load_1m || 0).toFixed(2)}</td>
                </tr>
              `;
            }).join('') || '<tr><td colspan="7">No metrics available.</td></tr>'}
          </tbody>
        </table>
      </div>
    </article>
  `;
}

async function loadAlerts() {
  const [overview, alerts] = await Promise.all([
    fetchJSON('/api/v1/overview'),
    fetchJSON('/api/v1/alerts?limit=200'),
  ]);
  renderHeader(overview);
  el.content.innerHTML = `
    <article class="panel">
      <header class="panel-head"><h2>Alerts</h2></header>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Severity</th><th>Server</th><th>Message</th><th>Source</th><th>When</th></tr></thead>
          <tbody>
            ${(alerts || []).map((a) => `
              <tr>
                <td><span class="pill ${levelClass(a.severity)}">${escapeHtml(a.severity)}</span></td>
                <td>${escapeHtml(a.server_hostname || '-')}</td>
                <td>${escapeHtml(a.message)}</td>
                <td>${escapeHtml(a.source)}</td>
                <td>${ago(a.created_at)}</td>
              </tr>
            `).join('') || '<tr><td colspan="5">No alerts.</td></tr>'}
          </tbody>
        </table>
      </div>
    </article>
  `;
}

function issueForm(servers, nginxChecks) {
  const options = (servers || []).map((s) => `<option value="${s.id}">${escapeHtml(s.display_name || s.hostname)}</option>`).join('');
  const apps = Array.from(new Set((nginxChecks || []).map((x) => x.app_name))).sort();
  const appOptions = apps.map((a) => `<option value="${escapeHtml(a)}">${escapeHtml(a)}</option>`).join('');

  return `
    <form id="issue-form" class="issue-form">
      <h3>Report Nginx/Application Issue</h3>
      <label>Server</label>
      <select name="server_id"><option value="">Optional</option>${options}</select>
      <label>Nginx App</label>
      <select name="nginx_app_name"><option value="">Optional</option>${appOptions}</select>
      <label>Severity</label>
      <select name="severity">
        <option value="warning">Warning</option>
        <option value="critical">Critical</option>
        <option value="info">Info</option>
      </select>
      <label>Title</label>
      <input name="title" required placeholder="e.g. API health endpoint failing" />
      <label>Description</label>
      <textarea name="description" required placeholder="Describe the observed issue"></textarea>
      <button type="submit" class="btn-secondary">Submit Issue</button>
      <p id="issue-form-status" class="form-status"></p>
    </form>
  `;
}

async function loadLogs() {
  const [overview, logs, issues, servers, unhealthyApps] = await Promise.all([
    fetchJSON('/api/v1/overview'),
    fetchJSON('/api/v1/logs?limit=200'),
    fetchJSON('/api/v1/issues?limit=100'),
    fetchJSON('/api/v1/servers'),
    fetchJSON('/api/v1/nginx/apps?limit=200&healthy=false'),
  ]);
  renderHeader(overview);

  el.content.innerHTML = `
    <section class="board-grid logs-grid">
      <article class="panel">
        <header class="panel-head"><h2>System Logs</h2></header>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Level</th><th>Source</th><th>Server</th><th>Message</th><th>When</th></tr></thead>
            <tbody>
              ${(logs || []).map((l) => `
                <tr>
                  <td><span class="pill ${levelClass(l.level)}">${escapeHtml(l.level)}</span></td>
                  <td>${escapeHtml(l.source)}</td>
                  <td>${escapeHtml(l.server_hostname || '-')}</td>
                  <td>${escapeHtml(l.message)}</td>
                  <td>${ago(l.created_at)}</td>
                </tr>
              `).join('') || '<tr><td colspan="5">No logs.</td></tr>'}
            </tbody>
          </table>
        </div>
      </article>
      <article class="panel">
        <header class="panel-head"><h2>Open Issues</h2></header>
        <div class="stack-list">
          ${(issues || []).map((i) => `
            <div class="stack-item">
              <div><span class="pill ${levelClass(i.severity)}">${escapeHtml(i.severity)}</span> ${escapeHtml(i.title)}</div>
              <small>${escapeHtml(i.server_hostname || '-')}${i.nginx_app_name ? ` · ${escapeHtml(i.nginx_app_name)}` : ''} · ${ago(i.created_at)}</small>
            </div>
          `).join('') || '<div class="empty-state">No issues reported.</div>'}
        </div>
      </article>
    </section>
    <article class="panel">
      <header class="panel-head"><h2>Unhealthy Nginx App Checks</h2></header>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Server</th><th>App</th><th>URL</th><th>Status</th><th>Error</th><th>When</th></tr></thead>
          <tbody>
            ${(unhealthyApps || []).map((a) => `
              <tr>
                <td>${escapeHtml(a.server_hostname || '-')}</td>
                <td>${escapeHtml(a.app_name)}</td>
                <td>${escapeHtml(a.check_url)}</td>
                <td>${a.status_code ?? '-'}</td>
                <td>${escapeHtml(a.error || '-')}</td>
                <td>${ago(a.created_at)}</td>
              </tr>
            `).join('') || '<tr><td colspan="6">No unhealthy checks.</td></tr>'}
          </tbody>
        </table>
      </div>
    </article>
    <article class="panel">${issueForm(servers, unhealthyApps)}</article>
  `;

  const form = document.getElementById('issue-form');
  const status = document.getElementById('issue-form-status');
  if (form && status) {
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      status.textContent = 'Submitting...';
      const formData = new FormData(form);
      const payload = {
        server_id: formData.get('server_id') ? Number(formData.get('server_id')) : null,
        nginx_app_name: formData.get('nginx_app_name') || null,
        severity: String(formData.get('severity') || 'warning'),
        title: String(formData.get('title') || '').trim(),
        description: String(formData.get('description') || '').trim(),
      };
      try {
        await fetchJSON('/api/v1/issues/report', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        status.textContent = 'Issue submitted successfully.';
        form.reset();
      } catch (error) {
        status.textContent = `Failed: ${error.message}`;
      }
    });
  }
}

async function refreshPage() {
  try {
    if (page === 'overview') {
      await loadOverview();
      return;
    }
    if (page === 'servers') {
      await loadServers();
      return;
    }
    if (page === 'metrics') {
      await loadMetrics();
      return;
    }
    if (page === 'alerts') {
      await loadAlerts();
      return;
    }
    if (page === 'logs') {
      await loadLogs();
      return;
    }
    empty(`Unknown page: ${page}`);
  } catch (error) {
    empty(error?.message || 'Failed to load data');
  }
}

el.refresh.addEventListener('click', refreshPage);
refreshPage();
setInterval(refreshPage, 10000);
