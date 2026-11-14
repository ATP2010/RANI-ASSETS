/* RANI UI: custom report — jalankan SQL, render grid dengan filter per kolom. */
(function () {
  function el(id) { return document.getElementById(id); }

  function cell(text) {
    const td = document.createElement('td');
    td.className = 'small';
    td.textContent = text === null || text === undefined ? '' : String(text);
    return td;
  }

  function renderTable(data, columns, rows, meta) {
    const out = el('report-output');
    out.textContent = '';

    const wrap = document.createElement('div');
    wrap.className = 'table-responsive';
    const table = document.createElement('table');
    table.className = 'table table-sm table-tight table-hover mb-0 align-middle';

    const thead = document.createElement('thead');
    thead.className = 'table-light';
    const hrow = document.createElement('tr');
    const frow = document.createElement('tr');
    columns.forEach(function (name, idx) {
      const th = document.createElement('th');
      th.className = 'small text-nowrap';
      th.textContent = name;
      hrow.appendChild(th);

      const fth = document.createElement('th');
      fth.className = 'py-1';
      const input = document.createElement('input');
      input.className = 'form-control form-control-sm report-filter';
      input.placeholder = 'filter';
      input.dataset.col = String(idx);
      input.setAttribute('aria-label', 'filter kolom ' + name);
      fth.appendChild(input);
      frow.appendChild(fth);
    });
    thead.appendChild(hrow);
    thead.appendChild(frow);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    table.appendChild(tbody);
    wrap.appendChild(table);
    out.appendChild(wrap);

    function draw(source) {
      tbody.textContent = '';
      source.forEach(function (row) {
        const tr = document.createElement('tr');
        row.forEach(function (value) { tr.appendChild(cell(value)); });
        tbody.appendChild(tr);
      });
      if (!source.length) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = Math.max(columns.length, 1);
        td.className = 'small-muted p-3';
        td.textContent = 'tidak ada baris yang cocok dengan filter';
        tr.appendChild(td);
        tbody.appendChild(tr);
      }
    }
    draw(rows);

    const filters = out.querySelectorAll('.report-filter');
    filters.forEach(function (input) {
      input.addEventListener('input', function () {
        const active = [];
        out.querySelectorAll('.report-filter').forEach(function (f) {
          const v = f.value.trim().toLowerCase();
          if (v) active.push([Number(f.dataset.col), v]);
        });
        const filtered = rows.filter(function (row) {
          return active.every(function (pair) {
            const value = row[pair[0]];
            return String(value === null || value === undefined ? '' : value)
              .toLowerCase().indexOf(pair[1]) !== -1;
          });
        });
        draw(filtered);
        meta.textContent = data.row_count + ' baris · ' + data.duration_ms + ' ms' +
          (active.length ? ' · filter: ' + filtered.length + ' tampil' : '') +
          (data.truncated ? ' · dipotong di ' + data.max_rows + ' baris' : '');
      });
    });

    meta.textContent = data.row_count + ' baris · ' + data.duration_ms + ' ms' +
      (data.truncated ? ' · dipotong di ' + data.max_rows + ' baris' : '');

    const footer = document.createElement('div');
    footer.className = 'd-flex justify-content-between align-items-center p-2 border-top';
    const info = document.createElement('span');
    info.className = 'small-muted';
    info.textContent = columns.length + ' kolom · ' + data.row_count + ' baris' +
      (data.truncated ? ' (dipotong)' : '');
    const link = document.createElement('a');
    link.className = 'btn btn-sm btn-outline-secondary';
    link.href = '/reports/' + data.report_id + '/export.csv';
    link.textContent = 'Export CSV';
    footer.appendChild(info);
    footer.appendChild(link);
    out.appendChild(footer);
  }

  function showMessage(html, cls) {
    const out = el('report-output');
    out.textContent = '';
    const div = document.createElement('div');
    div.className = 'p-3 ' + (cls || 'small-muted');
    div.textContent = html;
    out.appendChild(div);
  }

  async function runReport(id) {
    const meta = el('report-meta');
    if (!id) return;
    showMessage('menjalankan query…');
    if (meta) meta.textContent = 'menjalankan…';
    const button = el('report-run');
    if (button) button.disabled = true;
    try {
      const resp = await fetch('/api/v1/reports/' + id + '/run', {
        method: 'POST', headers: { 'Accept': 'application/json' }
      });
      const data = await resp.json().catch(function () { return {}; });
      if (!resp.ok) {
        const detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data);
        showMessage(detail, 'text-danger small');
        if (meta) meta.textContent = 'gagal';
        return;
      }
      renderTable(data, data.columns, data.rows, meta || { textContent: '' });
    } catch (err) {
      showMessage('gagal memanggil server: ' + err, 'text-danger small');
      if (meta) meta.textContent = 'gagal';
    } finally {
      if (button) button.disabled = false;
    }
  }

  window.raniRunReport = runReport;

  document.addEventListener('DOMContentLoaded', function () {
    const box = el('report-result');
    if (!box) return;
    const id = box.dataset.reportId;
    if (id && box.dataset.runNow === '1') runReport(id);

    const btn = el('report-run');
    if (btn) btn.addEventListener('click', function () { runReport(btn.dataset.reportId || id); });

    document.querySelectorAll('.example-query').forEach(function (item) {
      item.addEventListener('click', function () {
        const area = el('sql_text');
        if (!area) return;
        if (area.value.trim() && !confirm('Ganti isi editor dengan contoh ini?')) return;
        area.value = item.dataset.sql;
        area.focus();
      });
    });
  });
})();