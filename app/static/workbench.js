(function () {
  var state = { payload: null, kind: 'bars', run: null, approved: false };
  var $ = function (id) { return document.getElementById(id); };
  function esc(value) {
    return String(value === null || value === undefined ? '' : value).replace(/[&<>"']/g, function (ch) {
      return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch];
    });
  }
  async function request(url, options) {
    var response = await fetch(url, Object.assign({headers: {'Content-Type': 'application/json'}}, options || {}));
    var data = await response.json().catch(function () { return {}; });
    if (!response.ok) throw new Error(data.error || ('HTTP ' + response.status));
    return data;
  }
  function setNotice(text) { $('notice').textContent = text || ''; }
  function renderIssues(data) {
    $('issue-count').textContent = data.issues.length + ' 条';
    $('issue-list').innerHTML = data.issues.length ? data.issues.map(function (item) {
      return '<li><span>' + esc(item.line || '-') + '</span><span>' + esc(item.key || '无主键') + '</span><code>' + esc(item.code) + '</code></li>';
    }).join('') : '<li class="empty">暂无异常</li>';
  }
  function renderBreakdown(items) {
    if (!items || !items.length) return '';
    return '<details><summary>' + items.length + ' 项</summary><ul>' + items.map(function (item) {
      return '<li>' + esc(item) + '</li>';
    }).join('') + '</ul></details>';
  }
  function renderRows(data) {
    var labels = Object.assign({label: '记录'}, state.resultColumns);
    var source = data.row_kind === 'source';
    var hasBreakdown = data.rows.some(function (row) { return row.breakdown && row.breakdown.length; });
    var keys = source ? state.inputColumns : Object.keys(labels).filter(function (key) {
      return data.rows.some(function (row) { return Object.hasOwn(row, key); });
    });
    $('row-count').textContent = source ? data.rows.length + ' 行预览' :
      data.summary.PASS + ' 通过 / ' + data.summary.REVIEW + ' 复核 / ' + data.summary.REJECT + ' 阻断';
    var tail = source ? '' : '<th>结论</th>' + (hasBreakdown ? '<th>计算分项</th>' : '');
    $('row-head').innerHTML = '<tr>' + keys.map(function (key) { return '<th>' + esc(labels[key] || key) + '</th>'; }).join('') + tail + '</tr>';
    $('row-body').innerHTML = data.rows.length ? data.rows.map(function (row) {
      var values = keys.map(function (key) { return '<td class="' + (typeof row[key] === 'number' ? 'num' : '') + '">' + esc(row[key]) + '</td>'; }).join('');
      var verdict = source ? '' : '<td><span class="verdict" data-v="' + esc(row.verdict) + '">' + esc(row.verdict || '') + '</span><br><small>' + esc(row.reason || '') + '</small></td>';
      var breakdown = hasBreakdown ? '<td>' + renderBreakdown(row.breakdown) + '</td>' : '';
      return '<tr>' + values + verdict + breakdown + '</tr>';
    }).join('') : '<tr><td class="empty" colspan="' + (keys.length + (source ? 0 : 1)) + '">没有可展示条目</td></tr>';
  }
  function renderLedger(data) {
    if (!data.ledger) { $('ledger-list').innerHTML = '<p class="empty">运行对账后显示</p>'; return; }
    var values = data.ledger;
    $('ledger-list').innerHTML = [
      ['来源行', values.counts.input], ['采信行', values.counts.accepted], ['隔离行', values.counts.isolated],
      ['精确重复', values.counts.duplicates], ['忽略行', values.counts.ignored], ['计算条目', values.counts.computed]
    ].map(function (row) { return '<div class="ledger-row"><span>' + row[0] + '</span><strong>' + row[1] + '</strong></div>'; }).join('') +
      '<div class="ledger-row"><span>' + esc(values.metric_field) + '</span><strong>' + esc(values.metric_total) + '</strong></div>' +
      values.checks.map(function (check) { return '<div class="ledger-row"><span>' + esc(check.label) + '</span><strong class="' + (check.ok ? 'check-ok' : 'check-bad') + '">' + (check.ok ? '通过' : '异常') + '</strong></div>'; }).join('');
  }
  function render(data) {
    state.payload = data;
    $('chart-label').textContent = Object.values(state.resultColumns)[0];
    $('m-input').textContent = data.counts.input;
    $('m-accepted').textContent = data.counts.accepted;
    $('m-isolated').textContent = data.counts.isolated + data.counts.duplicates;
    $('m-rejected').textContent = data.summary.REJECT;
    renderRows(data);
    renderIssues(data);
    renderLedger(data);
    window.renderChart($('chart'), data.chart && data.chart.length ? (state.kind || 'bars') : 'bars', data.chart || []);
  }
  function stageButtons(stages) {
    $('stage-nav').innerHTML = stages.map(function (stage, index) {
      return '<button type="button" data-stage="' + stage.id + '" aria-pressed="' + (index === 0 ? 'true' : 'false') + '">' + esc(stage.name) + '</button>';
    }).join('');
    Array.from(document.querySelectorAll('[data-stage]')).forEach(function (button) {
      button.addEventListener('click', function () {
        document.querySelectorAll('[data-stage]').forEach(function (other) { other.setAttribute('aria-pressed', String(other === button)); });
        loadStage(button.getAttribute('data-stage'));
      });
    });
  }
  async function loadStage(stage) {
    try {
      setNotice('');
      document.body.setAttribute('aria-busy', 'true');
      var payload = await request('/api/stages/' + stage, {method: 'POST', body: JSON.stringify({profile: $('profile').value})});
      render(payload);
    } catch (error) { setNotice(error.message); }
    finally { document.body.removeAttribute('aria-busy'); }
  }
  async function runBatch() {
    try {
      setNotice('');
      $('run').disabled = true;
      var run = await request('/api/runs', {method: 'POST', body: JSON.stringify({profile: $('profile').value})});
      state.run = run;
      state.approved = run.status === 'APPROVED';
      render(run);
      $('run-status').textContent = run.status + ' · rev ' + run.revision;
      $('revision').textContent = 'rev ' + run.revision;
      $('sign').disabled = run.summary.REJECT > 0 || state.approved;
      $('hold').disabled = state.approved;
      $('download').hidden = !state.approved;
      if (state.approved) $('download').href = '/api/runs/' + run.run_id + '/evidence';
    } catch (error) { setNotice(error.message); }
    finally { $('run').disabled = false; }
  }
  async function review(decision) {
    if (!state.run) return;
    try {
      var run = await request('/api/runs/' + state.run.run_id + '/review', {
        method: 'POST',
        body: JSON.stringify({decision: decision, comment: $('comment').value, expected_revision: state.run.revision})
      });
      state.run = run;
      state.approved = run.status === 'APPROVED';
      $('run-status').textContent = run.status + ' · rev ' + run.revision;
      $('revision').textContent = 'rev ' + run.revision;
      $('sign').disabled = true;
      $('hold').disabled = true;
      $('download').hidden = !state.approved;
      if (state.approved) $('download').href = '/api/runs/' + run.run_id + '/evidence';
    } catch (error) { setNotice(error.message); }
  }
  async function boot() {
    try {
      var catalog = await request('/api/catalog');
      state.kind = catalog.chart;
      state.resultColumns = catalog.result_columns;
      state.inputColumns = catalog.columns;
      stageButtons(catalog.stages.slice(0, 5));
      document.querySelector('.rail-note').textContent = catalog.code + ' · ' + catalog.stages[6].name;
      await loadStage('intake');
    } catch (error) { setNotice(error.message); }
    $('run').addEventListener('click', runBatch);
    $('sign').addEventListener('click', function () { review('APPROVED'); });
    $('hold').addEventListener('click', function () { review('HELD'); });
    $('profile').addEventListener('change', function () {
      state.run = null; state.approved = false;
      $('sign').disabled = true; $('hold').disabled = true; $('download').hidden = true;
      $('run-status').textContent = '未执行批次'; $('revision').textContent = 'rev 0';
      loadStage('intake');
    });
  }
  document.addEventListener('DOMContentLoaded', boot);

  // 顺位结算：晚到高顺位重算、追回确认与待补补付的工作台核对
  async function settleRequest(url, options) {
    var response = await fetch(url, Object.assign({headers: {'Content-Type': 'application/json'}}, options || {}));
    var data = await response.json().catch(function () { return {}; });
    if (!response.ok) throw new Error(data.error || ('HTTP ' + response.status));
    return data;
  }
  function num(value) { return String(value); }
  function renderSettlement(groups) {
    var body = $('settle-body');
    $('settle-count').textContent = groups.length + ' 个结算组';
    if (!groups.length) {
      body.innerHTML = '<tr><td class="empty" colspan="10">暂无结算组，先登记理赔</td></tr>';
      $('settle-summary').innerHTML = '';
      return;
    }
    body.innerHTML = groups.map(function (group) {
      return group.claims.map(function (row) {
        var state = row.settled ? '已结清' : (row.pending_topup_cents > 0 ? '待补付' : '待追回');
        return '<tr>' +
          '<td>' + esc(group.group_id) + '</td><td>' + esc(row.payer) + (row.late ? ' <small>晚到</small>' : '') + '</td>' +
          '<td>' + esc(row.claim_id) + '</td>' +
          '<td class="num">' + num(row.due_cents) + '</td><td class="num">' + num(row.paid_cents) + '</td>' +
          '<td class="num">' + num(row.recovered_cents) + '</td><td class="num">' + num(row.net_paid_cents) + '</td>' +
          '<td class="num">' + num(row.pending_topup_cents) + '</td><td class="num">' + num(row.overpaid_recovery_cents) + '</td>' +
          '<td>' + esc(state) + '</td></tr>';
      }).join('');
    }).join('');
    $('settle-summary').innerHTML = groups.map(function (group) {
      var cap = group.within_cap ? '通过' : '超上限';
      return '<div class="ledger-row"><span>' + esc(group.group_id) + ' · 净实付/上限</span>' +
        '<strong class="num">' + num(group.net_paid_total_cents) + ' / ' + num(group.cap_cents) +
        ' 待补 ' + num(group.pending_topup_total_cents) + ' 待追回 ' + num(group.overpaid_recovery_total_cents) +
        '</strong><strong class="' + (group.within_cap ? 'check-ok' : 'settle-bad') + '">' + cap + '</strong></div>';
    }).join('');
  }
  async function loadSettlement() {
    try {
      var data = await settleRequest('/api/settlement/groups');
      renderSettlement(data.groups || []);
    } catch (error) { setNotice(error.message); }
  }
  async function registerSettlementClaim() {
    try {
      setNotice('');
      var payload = {
        claim_id: $('st-claim').value.trim(), member_id: $('st-member').value.trim(),
        service_date: $('st-date').value.trim(), payer: $('st-payer').value,
        billed_cents: $('st-billed').value, approved_cents: $('st-approved').value,
        deductible_cents: 0, late: $('st-late').checked
      };
      await settleRequest('/api/settlement/claims', {method: 'POST', body: JSON.stringify(payload)});
      await loadSettlement();
    } catch (error) { setNotice(error.message); }
  }
  async function confirmSettlementRecovery() {
    try {
      setNotice('');
      var payload = {
        claim_id: $('st-recover-claim').value.trim(),
        amount_cents: Number($('st-recover-amount').value),
        confirmation_key: $('st-recover-key').value.trim()
      };
      var view = await settleRequest('/api/settlement/groups/' + encodeURIComponent($('st-group').value.trim()) + '/recoveries',
        {method: 'POST', body: JSON.stringify(payload)});
      if (view.idempotent_hit) setNotice('同一确认键已处理，本次为幂等重试，未重复补付');
      await loadSettlement();
    } catch (error) { setNotice(error.message); }
  }
  function bootSettlement() {
    $('st-register').addEventListener('click', registerSettlementClaim);
    $('st-recover').addEventListener('click', confirmSettlementRecovery);
    $('st-refresh').addEventListener('click', loadSettlement);
    loadSettlement();
  }
  document.addEventListener('DOMContentLoaded', bootSettlement);
})();
