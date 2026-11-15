/* RANI UI: custom report — jalankan SQL, render grid dengan filter + pagination. */
(function () {
  var S = (window.RANI_REPORT_VIEW) || {};
  function t(key, def) { return S[key] || def || key; }
  function fmt(tpl, vars) {
    return Object.keys(vars || {}).reduce(function (acc, k) {
      return acc.split('{' + k + '}').join(String(vars[k]));
    }, tpl);
  }
  function el(id) { return document.getElementById(id); }

  function cell(text) {
    const td = document.createElement('td');
    td.className = 'small';
    td.textContent = text === null || text === undefined ? '' : String(text);
    return td;
  }

  function paginationWindow(current, total) {
    const out = [];
    if (total <= 7) {
      for (let i = 1; i <= total; i++) out.push(i);
      return out;
    }
    if (current <= 4) {
      for (let j = 1; j <= 5; j++) out.push(j);
      out.push('…');
      out.push(total);
      return out;
    }
    if (current >= total - 3) {
      out.push(1);
      out.push('…');
      for (let k = total - 4; k <= total; k++) out.push(k);
      return out;
    }
    out.push(1);
    out.push('…');
    out.push(current - 1);
    out.push(current);
    out.push(current + 1);
    out.push('…');
    out.push(total);
    return out;
  }

  function liButton(label, opts) {
    const li = document.createElement('li');
    li.className = 'page-item' + (opts && opts.disabled ? ' disabled' : '') +
      (opts && opts.active ? ' active' : '');
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'page-link';
    btn.innerHTML = label;
    if (opts && opts.disabled) {
      btn.tabIndex = -1;
      btn.setAttribute('aria-disabled', 'true');
    } else if (opts && opts.onClick) {
      btn.addEventListener('click', opts.onClick);
    }
    li.appendChild(btn);
    return li;
  }

  function renderTable(data, columns, rows, meta) {
    const out = el('report-output');
    if (!out) return;
    out.textContent = '';

    const state = { page: 1, perPage: 25, filters: [] };

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
      input.placeholder = t('filterPlaceholder', 'filter');
      input.dataset.col = String(idx);
      input.setAttribute('aria-label', fmt(t('filterAria', 'filter column {name}'), { name: name }));
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

    function filteredRows() {
      if (!state.filters.length) return rows.slice();
      return rows.filter(function (row) {
        return state.filters.every(function (f) {
          const value = row[f.col];
          return String(value === null || value === undefined ? '' : value)
            .toLowerCase().indexOf(f.value) !== -1;
        });
      });
    }

    const footer = document.createElement('div');
    footer.className = 'd-flex flex-wrap justify-content-between align-items-center gap-2 p-2 border-top';
    const info = document.createElement('span');
    info.className = 'small-muted';

    const right = document.createElement('div');
    right.className = 'd-flex flex-wrap align-items-center gap-3';

    const label = document.createElement('label');
    label.className = 'd-flex align-items-center gap-1 mb-0 small-muted';
    label.textContent = t('showLabel', 'Show');
    const perPage = document.createElement('select');
    perPage.className = 'form-select form-select-sm';
    perPage.style.width = 'auto';
    perPage.setAttribute('aria-label', t('perPageAria', 'rows per page'));
    [10, 25, 50, 100].forEach(function (n) {
      const opt = document.createElement('option');
      opt.value = String(n);
      opt.textContent = String(n);
      if (n === state.perPage) opt.selected = true;
      perPage.appendChild(opt);
    });
    const perPageSuffix = document.createElement('span');
    perPageSuffix.className = 'd-none d-sm-inline';
    perPageSuffix.textContent = t('perPageLabel', 'per page');
    label.appendChild(perPage);
    label.appendChild(perPageSuffix);

    const exportLink = document.createElement('a');
    exportLink.className = 'btn btn-sm btn-outline-secondary';
    exportLink.href = '/reports/' + data.report_id + '/export.csv';
    exportLink.textContent = 'Export CSV';

    const nav = document.createElement('nav');
    nav.setAttribute('aria-label', t('nav', 'Result page navigation'));
    const pag = document.createElement('ul');
    pag.className = 'pagination pagination-sm mb-0';
    nav.appendChild(pag);

    right.appendChild(label);
    right.appendChild(exportLink);
    right.appendChild(nav);

    footer.appendChild(info);
    footer.appendChild(right);
    out.appendChild(footer);

    function drawPage() {
      tbody.textContent = '';
      const vis = filteredRows();
      const totalPages = Math.max(1, Math.ceil(vis.length / state.perPage));
      if (state.page > totalPages) state.page = totalPages;
      if (state.page < 1) state.page = 1;
      const start = (state.page - 1) * state.perPage;
      const end = Math.min(start + state.perPage, vis.length);
      const pageRows = vis.slice(start, end);

      pageRows.forEach(function (row) {
        const tr = document.createElement('tr');
        row.forEach(function (value) { tr.appendChild(cell(value)); });
        tbody.appendChild(tr);
      });
      if (!pageRows.length) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = Math.max(columns.length, 1);
        td.className = 'small-muted p-3';
        td.textContent = state.filters.length
          ? t('noRowsFilter', 'no rows match the filter')
          : t('noRows', 'query returned no rows');
        tr.appendChild(td);
        tbody.appendChild(tr);
      }

      const filterNote = state.filters.length
        ? fmt(t('filterNote', ' · filter: {vis} of {total} match'), { vis: vis.length, total: rows.length })
        : '';
      meta.textContent = fmt(t('metaRows', '{rows} rows · {ms} ms'),
        { rows: data.row_count, ms: data.duration_ms }) +
        (data.truncated ? ' · ' + fmt(t('truncated', 'truncated at {n} rows'), { n: data.max_rows }) : '') +
        filterNote;
      info.textContent = fmt(t('showing', 'Showing {a}–{b} of {n} rows'),
        { a: vis.length ? start + 1 : 0, b: end, n: vis.length });

      pag.innerHTML = '';
      pag.appendChild(liButton('‹', {
        disabled: state.page === 1,
        onClick: function () { state.page -= 1; drawPage(); }
      }));
      paginationWindow(state.page, totalPages).forEach(function (p) {
        if (p === '…') {
          pag.appendChild(liButton('…', { disabled: true }));
        } else {
          pag.appendChild(liButton(String(p), {
            active: p === state.page,
            onClick: function () { state.page = p; drawPage(); }
          }));
        }
      });
      pag.appendChild(liButton('›', {
        disabled: state.page === totalPages,
        onClick: function () { state.page += 1; drawPage(); }
      }));
    }

    out.querySelectorAll('.report-filter').forEach(function (input) {
      input.addEventListener('input', function () {
        const active = [];
        out.querySelectorAll('.report-filter').forEach(function (f) {
          const v = f.value.trim().toLowerCase();
          if (v) active.push({ col: Number(f.dataset.col), value: v });
        });
        state.filters = active;
        state.page = 1;
        drawPage();
      });
    });

    perPage.addEventListener('change', function () {
      state.perPage = Number(perPage.value) || 25;
      state.page = 1;
      drawPage();
    });

    drawPage();
  }

  function showMessage(html, cls) {
    const out = el('report-output');
    if (!out) return;
    out.textContent = '';
    const div = document.createElement('div');
    div.className = 'p-3 ' + (cls || 'small-muted');
    div.textContent = html;
    out.appendChild(div);
  }

  async function runReport(id) {
    const meta = el('report-meta');
    if (!id) return;
    showMessage(t('runningQuery', 'running query…'));
    if (meta) meta.textContent = t('running', 'running…');
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
        if (meta) meta.textContent = t('fail', 'failed');
        return;
      }
      renderTable(data, data.columns, data.rows, meta || { textContent: '' });
    } catch (err) {
      showMessage(fmt(t('fetchError', 'failed to reach the server: {err}'), { err: err }), 'text-danger small');
      if (meta) meta.textContent = t('fail', 'failed');
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
        if (area.value.trim() && !confirm(t('replaceConfirm', 'Replace the editor contents with this example?'))) return;
        area.value = item.dataset.sql;
        area.focus();
      });
    });
  });
})();
