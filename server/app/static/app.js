/* RANI UI: WebSocket realtime, sidebar persist, chart dashboard (Apache ECharts). */
(function () {
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
    const color = ok ? 'var(--bs-success)' : 'var(--bs-secondary-color)';
    node.title = text;
    node.innerHTML = '<span class="d-inline-flex align-items-center gap-1 fw-semibold"' +
      ' style="color:' + color + '">' +
      '<svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">' +
      '<circle cx="8" cy="8" r="6"/></svg>' +
      '<span class="d-none d-sm-inline">Realtime</span></span>';
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
        const delta = '+' + (s.installed || 0) + ' / -' + (s.uninstalled || 0) +
                      ' / ~' + (s.changed || 0);
        toast('Push diterima', (msg.hostname || '') + ' — software ' + delta, 'primary');
        refreshDashboard();
      } else if (msg.type === 'asset.offline') {
        toast('Aset offline', msg.hostname || '', 'secondary');
        refreshDashboard();
      }
    };
  }

  // --------------------------------------------------------------- charts ---
  const PALETTE = ['#0d6efd', '#198754', '#0dcaf0', '#ffc107', '#6f42c1',
                   '#fd7e14', '#20c997', '#dc3545', '#6c757d'];
  const charts = {};
  let lastStats = null;
  const nf = new Intl.NumberFormat('id-ID');

  function cssVar(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name);
    return (v && v.trim()) || fallback;
  }

  function palette() {
    return {
      text: cssVar('--bs-body-color', '#212529'),
      muted: cssVar('--bs-secondary-color', '#6c757d'),
      border: cssVar('--bs-border-color', '#dee2e6'),
      surface: cssVar('--bs-body-bg', '#ffffff'),
      online: cssVar('--bs-success', '#198754'),
      offline: cssVar('--bs-secondary', '#6c757d'),
    };
  }

  function baseOption(p) {
    return {
      backgroundColor: 'transparent',
      textStyle: { color: p.text, fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif' },
      tooltip: {
        backgroundColor: p.surface, borderColor: p.border, borderWidth: 1,
        textStyle: { color: p.text, fontSize: 12 },
        extraCssText: 'box-shadow:0 4px 16px rgba(0,0,0,.12);border-radius:6px;'
      },
      toolbox: {
        right: 4, top: 0, itemSize: 12, iconStyle: { borderColor: p.muted },
        feature: { saveAsImage: { backgroundColor: 'transparent', pixelRatio: 2,
                                  title: 'Simpan PNG', name: 'rani-chart' } }
      },
    };
  }

  function initChart(id) {
    const node = el(id);
    if (!node || typeof echarts === 'undefined') return null;
    if (charts[id]) charts[id].dispose();
    charts[id] = echarts.init(node, null, { renderer: 'canvas' });
    return charts[id];
  }

  function drawOs(stats) {
    const chart = initChart('chart-os');
    if (!chart) return;
    const p = palette();
    const rows = (stats.os_mix || []).filter(r => r.count > 0);
    const total = rows.reduce((sum, r) => sum + r.count, 0);
    const option = baseOption(p);
    option.color = PALETTE;
    option.tooltip.trigger = 'item';
    option.tooltip.formatter = (pt) => pt.name + '<br/><b>' + nf.format(pt.value) +
      '</b> aset (' + pt.percent + '%)';
    option.legend = {
      bottom: 0, type: 'scroll', icon: 'circle', itemWidth: 8, itemHeight: 8,
      textStyle: { color: p.muted, fontSize: 11 },
      pageIconColor: p.muted, pageTextStyle: { color: p.muted }, pageIconSize: 10
    };
    option.graphic = rows.length ? [
      { type: 'text', left: 'center', top: '33%', silent: true,
        style: { text: nf.format(total), fontSize: 22, fontWeight: 600, fill: p.text } },
      { type: 'text', left: 'center', top: '47%', silent: true,
        style: { text: 'aset', fontSize: 11, fill: p.muted } },
    ] : [{ type: 'text', left: 'center', top: 'middle', silent: true,
           style: { text: 'belum ada aset', fill: p.muted, fontSize: 12 } }];
    option.series = [{
      type: 'pie', radius: ['52%', '74%'], center: ['50%', '42%'],
      avoidLabelOverlap: true, minAngle: 3,
      itemStyle: { borderColor: p.surface, borderWidth: 2, borderRadius: 4 },
      label: { show: false }, labelLine: { show: false },
      emphasis: { scaleSize: 4, label: { show: false } },
      data: rows.map(r => ({ name: r.label, value: r.count })),
    }];
    chart.setOption(option, true);
  }

  function drawStatus(stats) {
    const chart = initChart('chart-status');
    if (!chart) return;
    const p = palette();
    const online = stats.assets_online || 0;
    const offline = stats.assets_offline || 0;
    const total = online + offline;
    const pct = total ? Math.round((online / total) * 100) : 0;
    const option = baseOption(p);
    option.tooltip.trigger = 'item';
    option.tooltip.formatter = (pt) => pt.name + ': <b>' + nf.format(pt.value) + '</b> aset (' +
      pt.percent + '%)';
    option.legend = { bottom: 0, icon: 'circle', itemWidth: 8, itemHeight: 8,
                      textStyle: { color: p.muted, fontSize: 11 } };
    option.graphic = total ? [
      { type: 'text', left: 'center', top: '33%', silent: true,
        style: { text: pct + '%', fontSize: 22, fontWeight: 600, fill: p.online } },
      { type: 'text', left: 'center', top: '47%', silent: true,
        style: { text: 'online', fontSize: 11, fill: p.muted } },
    ] : [{ type: 'text', left: 'center', top: 'middle', silent: true,
           style: { text: 'belum ada aset', fill: p.muted, fontSize: 12 } }];
    option.series = [{
      type: 'pie', radius: ['54%', '76%'], center: ['50%', '42%'], startAngle: 90,
      itemStyle: { borderColor: p.surface, borderWidth: 2, borderRadius: 4 },
      label: { show: false }, labelLine: { show: false },
      data: [
        { name: 'online', value: online, itemStyle: { color: p.online } },
        { name: 'offline', value: offline, itemStyle: { color: p.offline } },
      ],
    }];
    chart.setOption(option, true);
  }

  function drawSoftware(stats) {
    const chart = initChart('chart-software');
    if (!chart) return;
    const p = palette();
    const rows = (stats.top_software || []).slice().sort((a, b) => a.count - b.count);
    const total = stats.assets_total || 0;
    const option = baseOption(p);
    option.grid = { left: 4, right: 34, top: 6, bottom: 4, containLabel: true };
    option.tooltip.trigger = 'axis';
    option.tooltip.axisPointer = { type: 'shadow' };
    option.tooltip.formatter = (pts) => {
      const pt = pts[0];
      const pct = total ? Math.round((pt.value / total) * 100) : 0;
      return pt.name + '<br/><b>' + nf.format(pt.value) + '</b> aset (' + pct + '% dari fleet)';
    };
    option.xAxis = {
      type: 'value', minInterval: 1,
      axisLabel: { color: p.muted, fontSize: 11 },
      splitLine: { lineStyle: { color: p.border, opacity: 0.5 } },
    };
    option.yAxis = {
      type: 'category', data: rows.map(r => r.label),
      axisLabel: { color: p.text, fontSize: 11, width: 120, overflow: 'truncate' },
      axisLine: { lineStyle: { color: p.border } }, axisTick: { show: false },
    };
    option.series = [{
      type: 'bar', barMaxWidth: 14,
      data: rows.map(r => r.count),
      itemStyle: {
        borderRadius: [0, 4, 4, 0],
        color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
          { offset: 0, color: '#0d6efd' }, { offset: 1, color: '#0dcaf0' },
        ]),
      },
      label: { show: true, position: 'right', color: p.muted, fontSize: 11 },
    }];
    option.graphic = rows.length ? [] : [{
      type: 'text', left: 'center', top: 'middle', silent: true,
      style: { text: 'belum ada data software', fill: p.muted, fontSize: 12 },
    }];
    chart.setOption(option, true);
  }

  function drawTrend(stats) {
    const chart = initChart('chart-trend');
    if (!chart) return;
    const p = palette();
    const rows = stats.reports_trend || [];
    const empty = !rows.some(r => r.count > 0);
    const option = baseOption(p);
    option.grid = { left: 4, right: 12, top: 24, bottom: 4, containLabel: true };
    option.tooltip.trigger = 'axis';
    option.tooltip.formatter = (pts) => {
      const pt = pts[0];
      return pt.name + '<br/><b>' + nf.format(pt.value) + '</b> push';
    };
    option.xAxis = {
      type: 'category', boundaryGap: false,
      data: rows.map(r => (r.hour || '').slice(11, 16)),
      axisLabel: { color: p.muted, fontSize: 11, interval: 2 },
      axisLine: { lineStyle: { color: p.border } }, axisTick: { show: false },
    };
    option.yAxis = {
      type: 'value', minInterval: 1,
      axisLabel: { color: p.muted, fontSize: 11 },
      splitLine: { lineStyle: { color: p.border, opacity: 0.5 } },
    };
    option.series = [{
      name: 'push/jam', type: 'line', smooth: true, showSymbol: false,
      symbol: 'circle', symbolSize: 6,
      data: rows.map(r => r.count),
      lineStyle: { width: 2, color: '#0d6efd' },
      itemStyle: { color: '#0d6efd' },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(13,110,253,.35)' },
          { offset: 1, color: 'rgba(13,110,253,0)' },
        ]),
      },
      markLine: {
        silent: true, symbol: 'none',
        lineStyle: { type: 'dashed', color: p.border },
        label: { color: p.muted, fontSize: 10, formatter: 'rata² {c}' },
        data: [{ type: 'average' }],
      },
    }];
    option.graphic = empty ? [{
      type: 'text', left: 'center', top: 'middle', silent: true,
      style: { text: 'belum ada push dalam 24 jam', fill: p.muted, fontSize: 12 },
    }] : [];
    chart.setOption(option, true);
  }

  function renderCharts(stats) {
    if (!stats) return;
    drawOs(stats);
    drawStatus(stats);
    drawSoftware(stats);
    drawTrend(stats);
  }

  function resizeCharts() {
    Object.keys(charts).forEach(k => { try { charts[k].resize(); } catch (e) {} });
  }

  function renderStats(stats) {
    const map = { total: 'assets_total', online: 'assets_online', offline: 'assets_offline',
                  software: 'software_titles', installs: 'software_installs' };
    Object.keys(map).forEach(function (key) {
      const node = el('stat-' + key);
      if (node) node.textContent = nf.format(stats[map[key]] || 0);
    });
    renderCharts(stats);
  }

  let dashboardActive = false;
  function refreshDashboard() {
    if (!dashboardActive) return;
    fetch('/api/v1/stats', { headers: { 'Accept': 'application/json' } })
      .then(r => r.ok ? r.json() : null)
      .then(s => { if (s) { lastStats = s; renderStats(s); } })
      .catch(() => {});
  }

  // -------------------------------------------------- custom widgets ---
  function renderWidgets() {
    document.querySelectorAll('.custom-widget-chart').forEach(function (node) {
      if (typeof echarts === 'undefined') return;
      var labels = [], values = [];
      try {
        labels = JSON.parse(node.dataset.labels || '[]');
        values = JSON.parse(node.dataset.values || '[]');
      } catch (e) { return; }
      var kind = node.dataset.kind;
      if (charts[node.id]) charts[node.id].dispose();
      var chart = echarts.init(node, null, { renderer: 'canvas' });
      charts[node.id] = chart;
      var p = palette();
      var option = baseOption(p);
      option.toolbox = undefined;
      if (kind === 'donut') {
        option.color = PALETTE;
        option.tooltip.trigger = 'item';
        option.tooltip.formatter = '{b}<br/><b>{c}</b> ({d}%)';
        option.legend = labels.length <= 10
          ? { bottom: 0, textStyle: { color: p.text, fontSize: 10 }, itemWidth: 10 }
          : { show: false };
        option.series = [{ type: 'pie', radius: ['45%', '70%'],
          itemStyle: { borderRadius: 6 },
          data: labels.map(function (label, i) { return { name: label, value: values[i] }; }) }];
      } else if (kind === 'bar') {
        option.tooltip.trigger = 'axis';
        option.grid = { left: 8, right: 6, top: 10, bottom: 4, containLabel: true };
        option.xAxis = { type: 'category', data: labels,
          axisLabel: { color: p.muted, interval: 0, width: 90, overflow: 'truncate' },
          axisLine: { lineStyle: { color: p.border } } };
        option.yAxis = { type: 'value', axisLabel: { color: p.muted },
          splitLine: { lineStyle: { color: p.border, type: 'dashed' } } };
        option.series = [{ type: 'bar', data: values, barMaxWidth: 44,
          itemStyle: { color: PALETTE[0], borderRadius: [4, 4, 0, 0] } }];
      } else if (kind === 'line') {
        option.tooltip.trigger = 'axis';
        option.grid = { left: 8, right: 6, top: 10, bottom: 4, containLabel: true };
        option.xAxis = { type: 'category', boundaryGap: false, data: labels,
          axisLabel: { color: p.muted }, axisLine: { lineStyle: { color: p.border } } };
        option.yAxis = { type: 'value', axisLabel: { color: p.muted },
          splitLine: { lineStyle: { color: p.border, type: 'dashed' } } };
        option.series = [{ type: 'line', smooth: true, symbolSize: 5, data: values,
          lineStyle: { width: 2, color: PALETTE[0] },
          itemStyle: { color: PALETTE[0] },
          areaStyle: { opacity: 0.18, color: PALETTE[0] } }];
      }
      chart.setOption(option, true);
    });
  }

  window.raniInitWidgets = function () {
    renderWidgets();
    window.addEventListener('resize', function () {
      Object.keys(charts).forEach(function (k) { try { charts[k].resize(); } catch (e) {} });
    });
  };

  window.raniInitDashboard = function (stats) {
    dashboardActive = true;
    lastStats = stats;
    renderStats(stats);
    window.addEventListener('resize', resizeCharts);
    // sidebar collapse/expand mengubah lebar kanvas → resize setelah transisi
    new MutationObserver(() => setTimeout(resizeCharts, 320))
      .observe(document.body, { attributes: true, attributeFilter: ['class'] });
  };

  // ------------------------------------------------------- tema (AdminLTE) ---
  // warna sumbu/legend ECharts diambil dari CSS var → gambar ulang saat ganti tema
  document.addEventListener('changed.lte.color-mode', function () {
    if (dashboardActive && lastStats) renderCharts(lastStats);
    if (window.raniInitWidgets) window.raniInitWidgets();
  });

  document.addEventListener('DOMContentLoaded', function () {
    // AdminLTE sudah menerapkan body.sidebar-collapse; lepas marker pra-paint
    // supaya perilaku hover-expand bawaan AdminLTE kembali aktif.
    document.documentElement.classList.remove('rani-pre-collapsed');
    connect();
  });
})();