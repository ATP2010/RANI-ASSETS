/* RANI UI: scan SNMP — mulai, polling progres, render hasil, cancel. */
(function () {
  function el(id) { return document.getElementById(id); }
  var timer = null;
  var currentRun = null;

  function setBar(done, total) {
    var bar = el('scan-bar');
    if (!bar) return;
    var pct = total > 0 ? Math.round((done / total) * 100) : 0;
    bar.style.width = pct + '%';
    bar.className = 'progress-bar' + (pct === 100 ? ' bg-success' : '');
  }

  function td(text, cls) {
    var cell = document.createElement('td');
    if (cls) cell.className = cls;
    cell.textContent = text === null || text === undefined ? '—' : String(text);
    return cell;
  }

  function statusBadge(status) {
    var cell = document.createElement('td');
    var span = document.createElement('span');
    var map = { ok: 'text-bg-success', timeout: 'text-bg-secondary', error: 'text-bg-danger' };
    span.className = 'badge ' + (map[status] || 'text-bg-secondary');
    span.textContent = status;
    cell.appendChild(span);
    return cell;
  }

  function renderRows(results) {
    var body = document.querySelector('#scan-results tbody');
    if (!body) return;
    body.textContent = '';
    if (!results.length) {
      var tr = document.createElement('tr');
      var cell = td('belum ada hasil scan', 'small-muted p-3');
      cell.colSpan = 8;
      tr.appendChild(cell);
      body.appendChild(tr);
    }
    results.forEach(function (row) {
      var tr = document.createElement('tr');
      tr.appendChild(td(row.ip, 'mono'));
      tr.appendChild(statusBadge(row.status));

      var nameCell = document.createElement('td');
      nameCell.className = 'small';
      if (row.asset_id) {
        var link = document.createElement('a');
        link.href = '/assets/' + row.asset_id;
        link.textContent = row.sys_name || '—';
        nameCell.appendChild(link);
      } else {
        nameCell.textContent = row.sys_name || '—';
      }
      tr.appendChild(nameCell);

      tr.appendChild(td(row.vendor ? row.vendor + (row.model ? ' · ' + row.model : '') : '—',
                        'small-muted'));
      tr.appendChild(td(row.serial, 'mono small'));
      tr.appendChild(td(row.if_count, 'mono small'));
      tr.appendChild(td(row.fdb_count, 'mono small'));

      var oidCell = document.createElement('td');
      oidCell.className = 'small';
      var values = row.oid_values || {};
      Object.keys(values).forEach(function (key) {
        var line = document.createElement('div');
        line.className = 'mono';
        var value = values[key];
        line.textContent = key + ' = ' + (typeof value === 'object' ? JSON.stringify(value) : value);
        oidCell.appendChild(line);
      });
      if (row.error) {
        var errLine = document.createElement('div');
        errLine.className = 'text-danger';
        errLine.textContent = row.error;
        oidCell.appendChild(errLine);
      }
      if (!oidCell.textContent) oidCell.textContent = '—';
      tr.appendChild(oidCell);
      body.appendChild(tr);
    });
  }

  function setRunning(on) {
    var cancel = el('scan-cancel');
    var start = el('scan-start');
    if (cancel) cancel.classList.toggle('d-none', !on);
    if (start) start.disabled = on;
  }

  function finish(state, note) {
    setRunning(false);
    var label = el('scan-state');
    if (label) label.textContent = state;
    var noteEl = el('scan-note');
    if (noteEl && note) noteEl.textContent = note;
    var open = el('scan-open');
    if (open && currentRun) {
      open.href = '/agents/scan?run=' + currentRun;
      open.classList.remove('d-none');
    }
    if (timer) { clearInterval(timer); timer = null; }
  }

  function poll() {
    if (!currentRun) return;
    fetch('/api/v1/scan/runs/' + currentRun, { headers: { 'Accept': 'application/json' } })
      .then(function (resp) { return resp.ok ? resp.json() : null; })
      .then(function (data) {
        if (!data) { finish('error', 'gagal membaca status scan'); return; }
        setBar(data.hosts_done, data.hosts_total);
        var state = el('scan-state');
        if (state) state.textContent = data.status;
        var counts = el('scan-counts');
        if (counts) counts.textContent = data.hosts_done + '/' + data.hosts_total +
          ' host · ' + data.hosts_found + ' ditemukan';
        var meta = el('scan-result-meta');
        if (meta) meta.textContent = data.results.length + ' baris ditampilkan';
        renderRows(data.results || []);
        if (data.status !== 'running') {
          finish(data.status, 'Scan ' + data.status + ': ' + data.hosts_found + '/' +
            data.hosts_done + ' host menjawab SNMP' +
            (data.error ? ' — ' + data.error : ''));
        }
      })
      .catch(function () { finish('error', 'gagal menghubungi server'); });
  }

  function startPolling(runId) {
    currentRun = runId;
    setRunning(true);
    var state = el('scan-state');
    if (state) state.textContent = 'running';
    var note = el('scan-note');
    if (note) note.textContent = 'scan berjalan…';
    var open = el('scan-open');
    if (open) open.classList.add('d-none');
    if (timer) clearInterval(timer);
    poll();
    timer = setInterval(poll, 1200);
  }

  document.addEventListener('DOMContentLoaded', function () {
    var cfg = window.RANI_SCAN || {};
    if (cfg.running && cfg.runId) startPolling(cfg.runId);

    var startBtn = el('scan-start');
    if (startBtn) {
      startBtn.addEventListener('click', function () {
        var select = el('scan-group');
        if (!select || !select.value) return;
        startBtn.disabled = true;
        fetch('/api/v1/scan/groups/' + select.value + '/run', {
          method: 'POST', headers: { 'Accept': 'application/json' }
        })
          .then(function (resp) {
            return resp.json().then(function (data) { return { ok: resp.ok, data: data }; });
          })
          .then(function (res) {
            if (!res.ok) {
              var detail = res.data && res.data.detail ? res.data.detail : 'gagal memulai scan';
              finish('error', detail);
              return;
            }
            startPolling(res.data.run_id);
          })
          .catch(function () { finish('error', 'gagal menghubungi server'); });
      });
    }

    var cancelBtn = el('scan-cancel');
    if (cancelBtn) {
      cancelBtn.addEventListener('click', function () {
        if (!currentRun) return;
        fetch('/api/v1/scan/runs/' + currentRun + '/cancel', {
          method: 'POST', headers: { 'Accept': 'application/json' }
        }).catch(function () {});
      });
    }
  });
})();