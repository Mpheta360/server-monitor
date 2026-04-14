const el = {
  total: document.getElementById('total-servers'),
  healthy: document.getElementById('healthy-servers'),
  stale: document.getElementById('stale-servers'),
  critical: document.getElementById('critical-servers'),
  body: document.getElementById('servers-body'),
  refresh: document.getElementById('refresh-btn'),
};

const pct = (value) => (typeof value === 'number' ? `${value.toFixed(1)}%` : '-');

const formatDate = (iso) => {
  if (!iso) return 'never';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString();
};

function renderOverview(overview) {
  el.total.textContent = overview.total_servers;
  el.healthy.textContent = overview.healthy_servers;
  el.stale.textContent = overview.stale_servers;
  el.critical.textContent = overview.critical_servers;
}

function renderServers(servers) {
  if (!servers.length) {
    el.body.innerHTML = `<tr><td colspan="8">No data yet. Start an agent to see live metrics.</td></tr>`;
    return;
  }

  el.body.innerHTML = servers
    .map((server) => {
      const metric = server.latest_metric || {};
      const nginxMetric = server.latest_nginx_metric || {};
      return `
        <tr>
          <td>${server.hostname}<br><small>${server.ip_address || '-'}</small></td>
          <td>${server.environment}</td>
          <td><span class="badge ${server.status}">${server.status}</span></td>
          <td>${pct(metric.cpu_percent)}</td>
          <td>${pct(metric.memory_percent)}</td>
          <td>${pct(metric.disk_percent)}</td>
          <td>${typeof nginxMetric.active_connections === 'number' ? nginxMetric.active_connections : '-'}</td>
          <td>${formatDate(server.last_seen)}</td>
        </tr>
      `;
    })
    .join('');
}

async function fetchJSON(url) {
  const res = await fetch(url);
  if (res.status === 401) {
    window.location.assign('/sign-in');
    throw new Error('Your session has expired. Redirecting to sign in...');
  }
  if (!res.ok) {
    throw new Error(`Request failed (${res.status}) for ${url}`);
  }
  return res.json();
}

async function refresh() {
  try {
    const [overview, servers] = await Promise.all([
      fetchJSON('/api/v1/overview'),
      fetchJSON('/api/v1/servers'),
    ]);

    renderOverview(overview);
    renderServers(servers);
  } catch (err) {
    el.body.innerHTML = `<tr><td colspan="8">${err.message}</td></tr>`;
  }
}

el.refresh.addEventListener('click', refresh);
refresh();
setInterval(refresh, 10000);
