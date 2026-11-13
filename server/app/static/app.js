/* RANI UI: WebSocket realtime + chart dashboard. */
(function () {
  const PALETTE = ['#0d6efd', '#6c757d', '#198754', '#ffc107', '#0dcaf0', '#dc3545',
                   '#6f42c1', '#fd7e14', '#20c997', '#adb5bd'];

  function el(id) { return document.getElementById(id); }

  function toast(title, body, cls) {
    const host = el('toasts');
    if (!host) return;
    const wrap = document.createElement('div');
    wrap.className = 'toast align-items-center border-0 text-bg-' + (cls || 'primary');
    wrap.setAttribute('role', 'alert');
    wrap.innerHTML =
      '<div class="d-flex"><div class="toast-body"><strong></strong> <span></span></div>' +
      '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>';
    wrap.querySelector('strong').textContent = title;
    wrap.querySelector('span').textContent = body || '';
    host.appendChild(wrap);
    new bootstrap.Toast(wrap, { delay: 5000 }).show();
    wrap.addEventListener('hidden.bs.toast', () => wrap.remove());
  }

  function setStatus(text, ok) {
    const node = el('ws-status');
    if (!node) return;
    node.textContent = text;
    node.style.color = ok ? 'var(--bs-success)' : 'var(--bs-secondary-color)';
  }

  let retry = 0;
  function connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    let ws;
    try {
      ws = new WebSocket(proto + '://' + location.host + '/ws');
    } catch (e) {
      setStatus('realtime: gagal', false);
      return;
    }
    ws.onopen = function () {
      retry = 0;
      setStatus('realtime: aktif', true);
      setInterval(() => { if (ws.readyState === 1) ws.send('ping'); }, 25000);
    };
    ws.onclose = function () {
      setStatus('realtime: terputus', false);
      retry = Math.min(retry + 1, 6);
      setTimeout(connect, 1000 * Math.pow(2, retry));
    };
    ws.onmessage = function (evt) {
      let msg;
      try { msg = JSON.parse(evt.data); } catch (e) { return; }
      if (msg.type === 'asset.new') {
        toast('Aset baru', (msg.hostname || '') + ' — ' + (msg.os || 'unknown'), 'success');
        refreshDashboard();
      } else if (msg.type === 'asset.update') {
        const s = msg.software || {};
        const delta = ['+' + (s.installed || 0) + ' / -' + (s.uninstalled || 0) +
                       ' / ~' + (s.changed || 0)].join('');
        toast('Push diterima', (msg.hostname || '') + ' — software ' + delta, 'primary');
        refreshDashboard();
      } else if (msg.type === 'asset.offline') {
        toast('Aset offline', msg.hostname || '', 'secondary');
        refreshDashboard();
      }
    };
  }

  function chartConfig(type, labels, data, horizontal) {
    return {
      type: type,
      data: {
        labels: labels,
        datasets: [{
          data: data,
          backgroundColor: labels.map((_, i) => PALETTE[i % PALETTE.length]),
          borderWidth: 1
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: horizontal ? 'y' : 'x',
        plugins: { legend: { display: type === 'doughnut', position: 'bottom' } },
        scales: type === 'doughnut' ? {} : { x: { beginAtZero: true } }
      }
    };
  }

  function renderStats(stats) {
    ['total', 'online', 'offline', 'software', 'installs'].forEach(function (key) {
      const map = { total: 'assets_total', online: 'assets_online', offline: 'assets_offline',
                    software: 'software_titles', installs: 'software_installs' };
      const node = el('stat-' + key);
      if (node) node.textContent = stats[map[key]];
    });
    if (typeof Chart === 'undefined') return;
    const os = stats.os_mix || [];
    const top = stats.top_software || [];
    const trend = stats.reports_trend || [];

    const make = (id, cfg) => {
      const canvas = el(id);
      if (!canvas) return;
      if (canvas._chart) canvas._chart.destroy();
      canvas._chart = new Chart(canvas, cfg);
    };
    make('chart-os', chartConfig('doughnut', os.map(o => o.label), os.map(o => o.count)));
    make('chart-status', chartConfig('doughnut', ['online', 'offline'],
      [stats.assets_online, stats.assets_offline]));
    make('chart-software', chartConfig('bar', top.map(t => t.label), top.map(t => t.count), true));
    make('chart-trend', {
      type: 'line',
      data: {
        labels: trend.map(t => t.hour.slice(11, 16)),
        datasets: [{ label: 'push/jam', data: trend.map(t => t.count), tension: .3,
                     fill: true, borderColor: PALETTE[0],
                     backgroundColor: 'rgba(13,110,253,.15)' }]
      },
      options: { responsive: true, maintainAspectRatio: false }
    });
  }

  let dashboardActive = false;
  function refreshDashboard() {
    if (!dashboardActive) return;
    fetch('/api/v1/stats', { headers: { 'Accept': 'application/json' } })
      .then(r => r.ok ? r.json() : null)
      .then(s => { if (s) renderStats(s); })
      .catch(() => {});
  }

  window.raniInitDashboard = function (stats) {
    dashboardActive = true;
    renderStats(stats);
  };

  document.addEventListener('DOMContentLoaded', connect);
})();