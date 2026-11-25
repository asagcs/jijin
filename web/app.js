// 基金纪律面板 · 前端（原生 JS，无依赖）
const S = {
  data: null,
  plan: 'all',
  pri: 'all',
  q: '',
  sort: 'amount',
  activeDate: null,
  openRow: null,
  mode: 'final',      // final | estimate
  preview: null,
};

const money = n => (n === null || n === undefined || Number.isNaN(n)) ? '—'
  : (n < 0 ? '-' : '') + Math.abs(n).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const money0 = n => (n === null || n === undefined) ? '—'
  : (n < 0 ? '-' : '') + Math.abs(n).toLocaleString('zh-CN', { maximumFractionDigits: 0 });
const pct = n => (n === null || n === undefined) ? '—' : (n > 0 ? '+' : '') + n.toFixed(2) + '%';
const cls = n => (n > 0.0001 ? 'up' : n < -0.0001 ? 'down' : 'flat');
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const $ = sel => document.querySelector(sel);
const today = () => {
  const d = new Date();
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
};

/* ---------------- 载入 ---------------- */
async function load() {
  try {
    const r = await fetch('/api/data', { cache: 'no-store' });
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    S.data = d;
    if (!S.activeDate) S.activeDate = d.summary.latest_date;
    S.mode = 'final';
    S.preview = null;
    setBadge();
    render();
  } catch (e) {
    $('#cards').innerHTML = `<div class="card empty">读取数据失败：${esc(e.message)}<br>先运行一次 <code>run.py</code> 再刷新。</div>`;
  }
}

function setBadge() {
  const b = $('#modeBadge');
  if (S.mode === 'estimate') {
    b.hidden = false;
    b.className = 'badge est';
    b.innerHTML = `预计模式 · 未入库 <a id="dropPreview">回到实际</a>`;
    const a = $('#dropPreview');
    if (a) a.onclick = () => { S.mode = 'final'; S.preview = null; setBadge(); load(); };
  } else {
    b.hidden = true;
  }
}

/* ---------------- 指标卡 ---------------- */
function renderCards() {
  const d = S.data, s = d.summary, cap = s.capital || 30000;
  const techCap = 35, cashTarget = 30;
  const cards = [
    { k: '总市值', v: money(s.total), small: '元', note: `成本 ${money0(s.cost_total)} 元` },
    { k: '持仓盈亏', v: pct(s.rate), cls: cls(s.rate), small: `${money0(s.pnl)} 元`, note: '按各只收益率反推成本' },
    { k: '科技相关', v: s.tech_ratio.toFixed(1) + '%', small: `上限 ${techCap}%`,
      bar: Math.min(100, s.tech_ratio / techCap * 100), barColor: 'var(--orange)',
      note: s.tech_ratio > techCap ? `超限 ${money0(s.tech_amount - cap * techCap / 100)} 元` : '在规则范围内' },
    { k: '现金 / 预备金', v: money0(s.cash), small: '元',
      bar: Math.min(100, s.cash_ratio / (cashTarget * 2) * 100), barColor: 'var(--blue)',
      note: `占总资金 ${s.cash_ratio.toFixed(1)}%，目标 ${cashTarget}%` },
    { k: '持仓只数', v: s.fund_count, small: `只 / 定投 ${s.dca_count} 只`, note: s.fund_count > 10 ? '目标精简到 6~8 只' : '结构已较清爽' },
    { k: '历史记录', v: d.history.length || 0, small: '个交易日', note: d.dates.length ? `最早 ${d.dates[0]}` : '开始记录中' },
  ];
  $('#cards').innerHTML = cards.map(c => `
    <div class="stat">
      <div class="k">${c.k}</div>
      <div class="v ${c.cls || ''}">${c.v}${c.small ? `<small>${c.small}</small>` : ''}</div>
      ${c.bar !== undefined ? `<div class="bar"><i style="width:${c.bar}%;background:${c.barColor}"></i></div>` : ''}
      <div class="note">${c.note}</div>
    </div>`).join('');

  const warns = d.warnings || [];
  const bar = $('#alertbar');
  bar.hidden = warns.length === 0;
  bar.innerHTML = warns.map(x => `<div>⚠ ${esc(x)}</div>`).join('');
}

/* ---------------- 曲线 ---------------- */
function renderChart() {
  const svg = $('#chart');
  const box = svg.parentElement.getBoundingClientRect();
  const W = Math.max(520, Math.round(box.width || 900));
  const H = Math.max(280, Math.round(box.height || 360));
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
  const hist = (S.data.history || []).slice();
  if (hist.length === 0) {
    svg.innerHTML = `<text x="${W / 2}" y="${H / 2}" text-anchor="middle" fill="#8b94a3" font-size="13">还没有历史数据，运行一次最终更新后开始累积</text>`;
    $('#chartHint').textContent = '';
    return;
  }
  $('#chartHint').textContent = hist.length < 3
    ? `${hist.length} 个交易日 · 继续每天记录即可连成曲线`
    : `${hist.length} 个交易日`;

  const mL = 58, mr = 46, mt = 22, mb = 36;
  const iw = W - mL - mr, ih = H - mt - mb;
  const totals = hist.map(h => h.total), costs = hist.map(h => h.cost_total), techs = hist.map(h => h.tech_ratio);
  const lo = Math.min(...totals, ...costs), hi = Math.max(...totals, ...costs);
  const pad = Math.max((hi - lo) * 0.12, hi * 0.01, 100);
  const y0 = lo - pad, y1 = hi + pad;
  const x = i => hist.length === 1 ? mL + iw / 2 : mL + (i / (hist.length - 1)) * iw;
  const yP = v => mt + ih - (v - y0) / (y1 - y0) * ih;
  const yT = v => mt + ih - (Math.min(v, 60) / 60) * ih;

  let g = `<rect x="${mL}" y="${mt}" width="${iw}" height="${ih}" rx="10" fill="#f6f8fb"/>`;
  for (let i = 0; i <= 3; i++) {
    const v = y0 + (y1 - y0) * i / 3, y = yP(v);
    g += `<line x1="${mL}" x2="${W - mr}" y1="${y}" y2="${y}" stroke="#e3e8f0"/>`;
    g += `<text x="${mL - 8}" y="${y + 4}" text-anchor="end" fill="#8b94a3" font-size="12">${(Math.round(v / 100) / 10).toFixed(1)}k</text>`;
  }
  [0, 30, 60].forEach(v => {
    g += `<text x="${W - mr + 8}" y="${yT(v) + 4}" text-anchor="start" fill="#d59a44" font-size="12">${v}%</text>`;
  });
  const line = (arr, color, wd, dash) =>
    `<polyline points="${arr.map((v, i) => `${x(i)},${yP(v)}`).join(' ')}" fill="none" stroke="${color}" stroke-width="${wd}" ${dash ? `stroke-dasharray="${dash}"` : ''} stroke-linejoin="round"/>`;
  const area = hist.length > 1
    ? `<path d="M ${x(0)},${yP(totals[0])} L ${totals.map((v, i) => `${x(i)},${yP(v)}`).join(' L ')} L ${x(hist.length - 1)},${mt + ih} L ${x(0)},${mt + ih} Z" fill="#2f6fed" opacity="0.06"/>`
    : '';
  const mark = (cx, cy, color, label, anchor) => {
    const lx = anchor === 'end' ? cx - 10 : cx + 10;
    return `<circle cx="${cx}" cy="${cy}" r="5" fill="${color}"/>
      <text x="${lx}" y="${cy + 4}" text-anchor="${anchor}" fill="${color}" font-size="13">${label}</text>`;
  };
  const dots = hist.length === 1
    ? mark(x(0), yP(costs[0]), '#8b94a3', `成本 ${money0(costs[0])}`, 'end')
      + mark(x(0), yP(totals[0]), '#2f6fed', `${money0(totals[0])} 元`, 'start')
      + `<circle cx="${x(0)}" cy="${yT(techs[0])}" r="5" fill="#e8890c"/>`
    : '';
  const labels = hist.map((h, i) => {
    const step = Math.ceil(hist.length / 8);
    if (i % step !== 0 && i !== hist.length - 1) return '';
    return `<text x="${x(i)}" y="${H - 12}" text-anchor="middle" fill="#8b94a3" font-size="12">${h.date.slice(5)}</text>`;
  }).join('');
  svg.innerHTML = g + area + line(costs, '#b9c1d0', 1.2, '3 3') + line(totals, '#2f6fed', 2.2)
    + `<polyline points="${techs.map((v, i) => `${x(i)},${yT(v)}`).join(' ')}" fill="none" stroke="#e8890c" stroke-width="1.5" stroke-dasharray="4 4"/>`
    + dots + labels;
}

/* ---------------- 基金表 ---------------- */
function filtered() {
  const list = S.data.funds.filter(f => {
    if (S.plan !== 'all') {
      if (S.plan === 'CORE') { if (f.plan !== 'CORE' && f.plan !== 'CORE_OPT') return false; }
      else if (f.plan !== S.plan) return false;
    }
    if (S.pri !== 'all' && f.today_priority !== S.pri) return false;
    if (S.q && !f.name.toLowerCase().includes(S.q.toLowerCase())) return false;
    return true;
  });
  const key = { amount: f => f.amount, rate: f => f.rate, rebound: f => f.rebound, pct: f => f.last_pct ?? -99 }[S.sort];
  list.sort((a, b) => key(b) - key(a));
  return list;
}

function renderChips() {
  const d = S.data;
  const cnt = p => d.funds.filter(f => p === 'all' ? true : (p === 'CORE' ? (f.plan === 'CORE' || f.plan === 'CORE_OPT') : f.plan === p)).length;
  const groups = [['all', '全部'], ['CLEAR', '清理名单'], ['CORE', '科技核心'], ['HOLD', '海外宽基'], ['HOLD_DEF', '防守']];
  const pris = [['all', '全部优先级'], ['必做', '必做'], ['择机', '择机'], ['观察', '观察'], ['持有', '持有']];
  $('#chips').innerHTML =
    groups.map(([k, t]) => `<button class="chip ${S.plan === k ? 'on' : ''}" data-plan="${k}">${t}<span class="n">${cnt(k)}</span></button>`).join('')
    + `<span style="width:10px"></span>`
    + pris.map(([k, t]) => `<button class="chip ${S.pri === k ? 'on' : ''}" data-pri="${k}">${t}</button>`).join('');
  $('#chips').querySelectorAll('.chip').forEach(c => c.onclick = () => {
    if (c.dataset.plan !== undefined) S.plan = c.dataset.plan;
    if (c.dataset.pri !== undefined) S.pri = c.dataset.pri;
    renderChips(); renderFunds();
  });
}

function renderFunds() {
  const list = filtered();
  const total = S.data.summary.total || 1;
  const rows = [];
  for (const f of list) {
    const w = (f.amount / total) * 100;
    rows.push(`<tr data-id="${f.id}">
      <td><div class="name">
        <span class="tag ${f.plan}">${f.plan === 'CORE_OPT' ? '可选' : f.plan === 'HOLD_DEF' ? '防守' : f.plan === 'HOLD' ? '海外' : f.plan === 'CLEAR' ? '清理' : '核心'}</span>
        <div class="fn"><b>${esc(f.name)}</b><span>${f.dca_on ? `<i class="dotdca"></i> ${esc(dcaLabel(f))}` : '未定投'}${f.tech ? ' · 科技' : ''}</span></div>
      </div></td>
      <td class="num ${cls(f.last_pct)}">${pct(f.last_pct)}</td>
      <td class="num ${cls(f.rate)}">${pct(f.rate)}</td>
      <td class="num ${f.rebound > 0 ? 'up' : 'flat'}">${f.rebound > 0 ? '+' + f.rebound.toFixed(2) + '%' : '—'}</td>
      <td class="num">${money(f.amount)}</td>
      <td class="num">${w.toFixed(1)}%</td>
      <td class="acts">${f.today_priority ? `<span class="pri ${f.today_priority}">${f.today_priority}</span>` : ''}${esc(f.today_action)}${f.today_money ? ` <span class="m">（${money0(f.today_money)} 元）</span>` : ''}</td>
    </tr>`);
    if (S.openRow === f.id) {
      const a = ((S.data.advice_by_date || {})[S.activeDate || ''] || []).find(x => x.fund_id === f.id);
      rows.push(`<tr class="detail-row"><td colspan="7"><div class="detail">
        ${a ? '<div style="font-weight:600;margin-bottom:4px">当日理由</div><ul>'
          + String(a.reasons || '').split('；').map(r => `<li>· ${esc(r)}</li>`).join('') + '</ul>'
          : '<div class="tiny">该日期没有记录到这只基金的动作</div>'}
        <div class="tiny">分类：${esc(f.plan_label)}｜建议出现 ${f.advice_count} 次｜备注：${esc(f.note || '—')}</div>
      </div></td></tr>`);
    }
  }
  $('#fundRows').innerHTML = rows.join('') || '<tr><td colspan="7" class="empty">没有匹配的基金</td></tr>';
  $('#fundRows').querySelectorAll('tr[data-id]').forEach(tr => tr.onclick = () => {
    S.openRow = S.openRow === tr.dataset.id ? null : tr.dataset.id;
    renderFunds();
  });
}

/* ---------------- 侧栏 ---------------- */
function renderChecks() {
  const warns = S.data.warnings || [], s = S.data.summary;
  $('#checks').innerHTML = (warns.length ? warns.map(w => `<li>${esc(w)}</li>`).join('')
    : '<li class="ok">科技占比、现金比例、单只上限都在规则范围内</li>')
    + `<li class="ok">科技 ${s.tech_ratio.toFixed(1)}% / 上限 35%｜现金 ${s.cash_ratio.toFixed(1)}% / 目标 30%</li>`;
}

function renderDates() {
  const d = S.data;
  $('#dateCount').textContent = `${d.dates.length} 天`;
  $('#dates').innerHTML = d.dates.slice().reverse().map(dt => {
    const snap = d.history.find(h => h.date === dt);
    const n = ((d.advice_by_date || {})[dt] || []).filter(x => x.priority === '必做' || x.priority === '择机').length;
    return `<li class="${S.activeDate === dt ? 'on' : ''}" data-d="${dt}"><span>${dt}</span><span class="n">${snap ? money0(snap.total) + ' 元' : ''}${n ? ' · ' + n + ' 项' : ''}</span></li>`;
  }).join('') || '<li class="empty">暂无记录</li>';
  $('#dates').querySelectorAll('li[data-d]').forEach(li => li.onclick = () => {
    S.activeDate = li.dataset.d; S.openRow = null;
    renderDates(); renderAdvice(); renderFunds();
  });
}

function renderAdvice() {
  const dt = S.activeDate;
  const list = ((S.data.advice_by_date || {})[dt] || [])
    .filter(x => x.priority === '必做' || x.priority === '择机');
  $('#adviceTitle').textContent = dt ? `当日建议 · ${dt}` : '当日建议';
  if (!list.length) { $('#adviceBody').innerHTML = '<div class="tiny">这一天没有需要变动的建议</div>'; return; }
  const order = ['必做', '择机'];
  $('#adviceBody').innerHTML = order.map(p => {
    const rs = list.filter(x => x.priority === p);
    if (!rs.length) return '';
    return `<div class="grp ${p}"><div class="gt">${p} · ${rs.length}</div>`
      + rs.map(r => `<div class="it"><b>${esc(r.name)}</b>：${esc(r.actions)}${r.money ? ` <span class="m">（${money0(r.money)} 元）</span>` : ''}</div>`).join('')
      + `</div>`;
  }).join('');
}

function renderTrades() {
  const ts = S.data.trades || [];
  $('#tradeHint').textContent = ts.length ? `最近 ${ts.length} 笔` : '还没有调仓';
  const label = { buy: '买入', sell: '卖出', switch: '转换' };
  $('#trades').innerHTML = ts.map(t => `<li>
    <span class="td">${t.date.slice(5)}</span>
    <span class="tt ${t.side}">${label[t.side] || t.side}</span>
    <span class="tn">${esc(t.name)}</span>
    <span class="tm">${money0(t.amount)} 元</span>
  </li>`).join('') || '<li class="empty">买卖、转换会记在这里</li>';
}

function render() {
  renderCards(); renderChart(); renderChips(); renderFunds();
  renderChecks(); renderDates(); renderAdvice(); renderTrades();
  $('#updated').textContent = S.data.summary.updated_at || '—';
  $('#runs').textContent = S.data.run_count ?? 0;
}

/* ---------------- 弹窗 ---------------- */
function shotBar(hint) {
  return `<div class="shot">
    <div class="shot-left">
      <label class="file">选择 APP 截图<input type="file" id="shotFile" accept="image/*" hidden></label>
      <span class="hint">${hint}</span>
    </div>
    <div class="shot-right" id="shotStatus">未上传</div>
  </div>`;
}

function readShot(file) {
  return new Promise((res, rej) => {
    const fr = new FileReader();
    fr.onload = () => res(fr.result);
    fr.onerror = () => rej(new Error('读图失败'));
    fr.readAsDataURL(file);
  });
}

function shotReport(d, summary) {
  const box = $('#shotStatus');
  if (!box) return;
  box.innerHTML = summary
    + (d.note ? `<br><small>${esc(d.note)}</small>` : '')
    + (d.ai_error ? `<br><small>${esc(d.ai_error)}</small>` : '')
    + `<details class="ocr-raw"><summary>看 OCR 原文</summary><pre class="raw">${esc(d.raw_text || '')}</pre></details>`;
}

function bindShot(kind, apply, extra) {
  const drop = $('#modal').querySelector('.shot');
  const onFile = async file => {
    if (!file) return;
    $('#shotStatus').textContent = '识别中…（本地 OCR + DeepSeek，约 10~30 秒）';
    try {
      const image = await readShot(file);
      const r = await fetch('/api/ocr', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(Object.assign({ image, kind }, extra || {})),
      });
      const d = await r.json();
      if (!d.ok) { $('#shotStatus').textContent = '识别失败：' + (d.error || '未知错误'); return; }
      apply(d);
    } catch (e) {
      $('#shotStatus').textContent = '识别失败：' + e.message;
    }
  };
  const input = $('#shotFile');
  if (input) input.onchange = e => onFile(e.target.files[0]);
  if (drop) {
    drop.addEventListener('dragover', e => e.preventDefault());
    drop.addEventListener('drop', e => { e.preventDefault(); onFile(e.dataTransfer.files[0]); });
  }
}

function openModal(html) {
  $('#modal').innerHTML = html;
  $('#mask').hidden = false;
  $('#mask').onclick = e => { if (e.target.id === 'mask') closeModal(); };
  $('#modal').querySelectorAll('[data-close]').forEach(b => b.onclick = closeModal);
}
function closeModal() { $('#mask').hidden = true; $('#modal').innerHTML = ''; }

/* 预计 / 最终 录入 */
function openInput(kind) {
  const isEst = kind === 'estimate';
  const funds = S.data.funds.slice().sort((a, b) => b.amount - a.amount);
  const rows = funds.map(f => `
    <tr data-id="${f.id}" data-prev="${f.amount}">
      <td><div class="fn"><b>${esc(f.name)}</b><span>${esc(f.plan === 'CLEAR' ? '清理' : f.plan === 'CORE' ? '核心' : f.plan === 'CORE_OPT' ? '可选' : f.plan === 'HOLD' ? '海外' : '防守')} · 现值 ${money(f.amount)}</span></div></td>
      <td class="num"><input class="cell" data-id="${f.id}" inputmode="decimal" value="" placeholder="${f.amount.toFixed(2)}"></td>
      <td class="num"><span class="dlt" data-dlt="${f.id}">—</span></td>
    </tr>`).join('');

  openModal(`
    <div class="m-head">
      <h3>${isEst ? '预计录入 · 14:30 盘中预估' : '最终更新 · 收盘实际值'}</h3>
      <button class="ico" data-close>×</button>
    </div>
    <p class="m-desc">${isEst
      ? '按你估的收盘值算一遍建议，<b>不入库、不写历史</b>，刷新页面就恢复实际数据。'
      : '保存后按你确认的名单替换持仓。上传截图时，以识别结果为准：金额用新的，截图里没有的旧基金清掉，新基金补上。'}</p>

    ${shotBar(isEst
      ? '传持仓截图，按预估市值填入，核对后再生成建议'
      : '上传持仓截图。识别结果和原来不一致时，按最新持仓替换')}

    <div class="m-tools">
      <span>录入方式</span>
      <div class="seg" id="segMode">
        <button class="on" data-m="amount">按市值</button>
        <button data-m="pct">按涨跌幅</button>
      </div>
      <span class="divider"></span>
      <span>统一填</span>
      <input class="input w90" id="bulkVal" placeholder="如 -1.2">
      <button class="btn btn-ghost" id="bulkApply">应用到全部</button>
      <span class="spacer"></span>
      <button class="btn btn-ghost" id="pullQuotes">${isEst ? '拉取盘中估值' : '拉取最新净值'}</button>
      <button class="btn btn-ghost" id="clearAll">清空</button>
      <button class="btn btn-ghost" id="fillNow">填回现值</button>
    </div>

    <div class="m-table"><table class="grid">
      <thead><tr><th>基金</th><th class="num">${isEst ? '预计市值 / 涨跌幅' : '收盘市值 / 涨跌幅'}</th><th class="num">变化</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>

    <div class="m-foot">
      <span class="m-note" id="mNote">${isEst ? '只算不存' : '保存后当天记录会被覆盖更新'}</span>
      <button class="btn btn-ghost" data-close>取消</button>
      <button class="btn ${isEst ? 'btn-est' : 'btn-main'}" id="submitInput">${isEst ? '生成预计建议' : '保存为最终值'}</button>
    </div>
  `);

  let mode = 'amount';
  let cells = [...$('#modal').querySelectorAll('.cell')];
  const upd = () => cells.forEach(c => {
    const prev = +c.closest('tr').dataset.prev;
    const val = parseFloat(c.value);
    const dlt = c.closest('tr').querySelector('.dlt');
    if (!isFinite(val) || c.value === '') { dlt.textContent = '—'; dlt.className = 'dlt'; return; }
    let diff;
    if (mode === 'amount') diff = (val / prev - 1) * 100;
    else diff = val;
    dlt.textContent = (diff > 0 ? '+' : '') + diff.toFixed(2) + '%';
    dlt.className = 'dlt ' + cls(diff);
  });
  cells.forEach(c => c.oninput = upd);

  $('#segMode').querySelectorAll('button').forEach(b => b.onclick = () => {
    $('#segMode').querySelectorAll('button').forEach(x => x.classList.remove('on'));
    b.classList.add('on'); mode = b.dataset.m;
    $('#modal').querySelectorAll('th')[1].textContent = (isEst ? '预计' : '收盘') + (mode === 'amount' ? '市值' : '涨跌幅');
    cells.forEach(c => {
      c.placeholder = mode === 'amount' ? (+c.closest('tr').dataset.prev).toFixed(2) : '';
    });
    upd();
  });
  $('#clearAll').onclick = () => { cells.forEach(c => c.value = ''); upd(); };
  $('#fillNow').onclick = () => {
    cells.forEach(c => {
      const prev = +c.closest('tr').dataset.prev;
      c.value = mode === 'amount' ? prev.toFixed(2) : '0';
    });
    upd();
  };
  $('#pullQuotes').onclick = async () => {
    const btn = $('#pullQuotes');
    btn.disabled = true;
    $('#shotStatus').textContent = '正在拉取行情…';
    try {
      const r = await fetch(`/api/quotes?mode=${isEst ? 'estimate' : 'final'}`, { cache: 'no-store' });
      const d = await r.json();
      if (!d.ok) { $('#shotStatus').textContent = '拉取失败：' + (d.error || '未知错误'); btn.disabled = false; return; }
      let n = 0;
      cells.forEach(c => {
        const it = (d.items || []).find(x => x.id === c.dataset.id);
        if (!it || it.pct === null || it.pct === undefined) return;
        const prev = +c.closest('tr').dataset.prev;
        c.value = mode === 'amount' ? (prev * (1 + it.pct / 100)).toFixed(2) : it.pct.toFixed(2);
        n++;
      });
      upd();
      const miss = (d.missing || []).length;
      shotReport(d, `拉到 ${n} 只${miss ? `，${miss} 只无行情` : ''}。${d.note || ''}`);
    } catch (e) {
      $('#shotStatus').textContent = '拉取失败：' + e.message;
    }
    btn.disabled = false;
  };
  $('#bulkApply').onclick = () => {
    const v = parseFloat($('#bulkVal').value);
    if (!isFinite(v)) { $('#mNote').textContent = '统一填的值不是数字'; return; }
    cells.forEach(c => {
      const prev = +c.closest('tr').dataset.prev;
      c.value = mode === 'amount' ? (prev * (1 + v / 100)).toFixed(2) : v.toFixed(2);
    });
    upd();
  };

  let replacing = false;
  const codeLabel = h => {
    if (h.code) return h.status === 'new' ? `新增 · ${esc(h.code)}` : `现值 ${money(h.prev)} · ${esc(h.code)}`;
    const lead = h.status === 'new' ? '' : `现值 ${money(h.prev)} · `;
    return `${lead}<button type="button" class="code-miss" data-fill-code>未查到代码，点击补充</button>`;
  };
  const paintRows = list => {
    const tbody = $('#modal').querySelector('tbody');
    tbody.innerHTML = list.map(h => `
      <tr data-id="${esc(h.id)}" data-name="${esc(h.name)}" data-code="${esc(h.code || '')}" data-prev="${h.prev}" data-status="${h.status}">
        <td class="${h.code ? '' : 'code-gap'}" ${h.code ? '' : 'data-fill-code'}><div class="fn"><b>${esc(h.name)}</b><span>${codeLabel(h)}</span></div></td>
        <td class="num"><input class="cell" data-id="${esc(h.id)}" inputmode="decimal" value="${(+h.amount).toFixed(2)}"></td>
        <td class="num"><span class="dlt">—</span></td>
      </tr>`).join('');
    cells = [...$('#modal').querySelectorAll('.cell')];
    cells.forEach(c => c.oninput = upd);
    replacing = true;
    upd();
  };
  const openCodeInput = tr => {
    if (!tr || tr.querySelector('.code-in')) {
      const exist = tr && tr.querySelector('.code-in');
      if (exist) exist.focus();
      return;
    }
    const span = tr.querySelector('.fn span');
    span.innerHTML = `<input class="code-in" inputmode="numeric" maxlength="6" placeholder="6位代码" value="${esc(tr.dataset.code || '')}">`;
    const input = span.querySelector('input');
    const commit = () => {
      const code = (input.value || '').replace(/\D/g, '').slice(0, 6);
      const td = tr.querySelector('td');
      if (code.length === 6) {
        tr.dataset.code = code;
        td.classList.remove('code-gap');
        td.removeAttribute('data-fill-code');
        td.setAttribute('data-edit-code', '');
        const lead = tr.dataset.status === 'new' ? '新增 · ' : '代码 ';
        span.innerHTML = `<button type="button" class="code-miss" data-edit-code>${lead}${code}</button>`;
      } else {
        tr.dataset.code = '';
        td.classList.add('code-gap');
        td.removeAttribute('data-edit-code');
        td.setAttribute('data-fill-code', '');
        const lead = tr.dataset.status === 'new' ? '' : `现值 ${money(+tr.dataset.prev)} · `;
        span.innerHTML = `${lead}<button type="button" class="code-miss" data-fill-code>未查到代码，点击补充</button>`;
      }
    };
    const original = tr.dataset.code || '';
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
      if (e.key === 'Escape') { input.value = original; input.blur(); }
    });
    input.addEventListener('blur', commit);
    input.focus();
    input.select();
  };
  if (!$('#modal').dataset.codeFill) {
    $('#modal').dataset.codeFill = '1';
    $('#modal').addEventListener('click', e => {
      if (e.target.closest('.code-in')) return;
      const edit = e.target.closest('[data-edit-code]');
      const gap = e.target.closest('[data-fill-code]');
      const tr = (edit || gap) && (edit || gap).closest('tr');
      if (!tr) return;
      e.preventDefault();
      openCodeInput(tr);
    });
  }
  bindShot('amount', d => {
    if (!isEst && d.holdings) {
      if (!d.holdings.length) {
        shotReport(d, '没有识别出持仓，原来的名单没有改');
        return;
      }
      paintRows(d.holdings);
      const added = d.holdings.filter(h => h.status === 'new').length;
      const kept = d.holdings.length - added;
      const gone = (d.removed || []).map(x => x.name);
      const noCode = d.holdings.filter(h => h.status === 'new' && !h.code).length;
      let summary = `按最新持仓：沿用 ${kept} 只，新增 ${added} 只`;
      if (gone.length) summary += `，将清掉 ${gone.length} 只`;
      if (noCode) summary += `，${noCode} 只没查到代码`;
      summary += '。核对后再保存';
      shotReport(d, summary);
      const shown = gone.slice(0, 6).join('、');
      $('#mNote').textContent = gone.length
        ? `将清掉 ${gone.length} 只：${shown}${gone.length > 6 ? ' 等' : ''}`
        : '保存后按这张表替换持仓';
      return;
    }
    let n = 0;
    cells.forEach(c => {
      const v = (d.values || {})[c.dataset.id];
      if (v === undefined) return;
      const prev = +c.closest('tr').dataset.prev;
      c.value = mode === 'amount' ? (+v).toFixed(2) : (prev ? ((v / prev - 1) * 100).toFixed(2) : '');
      n++;
    });
    upd();
    shotReport(d, `识别到 ${n} 只${d.ai === 'deepseek' ? '（DeepSeek 结构化）' : ''}，请核对后再${isEst ? '生成建议' : '保存'}`);
  }, isEst ? null : { sync: true });

  $('#submitInput').onclick = async () => {
    const values = {};
    const holdings = [];
    cells.forEach(c => {
      const v = parseFloat(c.value);
      if (!isFinite(v) || c.value === '') return;
      values[c.dataset.id] = v;
      const tr = c.closest('tr');
      holdings.push({
        id: tr.dataset.id || '',
        name: tr.dataset.name || '',
        code: tr.dataset.code || '',
        amount: v,
      });
    });
    if (!(replacing ? holdings.length : Object.keys(values).length)) {
      $('#mNote').textContent = '还没填任何数值';
      return;
    }
    $('#submitInput').disabled = true;
    $('#mNote').textContent = '计算中…';
    const payload = replacing
      ? { date: today(), replace: true, holdings }
      : { date: today(), values, mode };
    try {
      const r = await fetch(isEst ? '/api/estimate' : '/api/final', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const d = await r.json();
      if (!d.ok) { $('#mNote').textContent = d.error; $('#submitInput').disabled = false; return; }
      closeModal();
      if (isEst) applyPreview(d, values, mode);
      else { S.activeDate = d.date; await load(); }
    } catch (e) {
      $('#mNote').textContent = '提交失败：' + e.message;
      $('#submitInput').disabled = false;
    }
  };
}

/* 预计结果 → 覆盖显示（不落库） */
function applyPreview(d, values, mode) {
  values = values || {};
  const byId = {};
  (d.records || []).forEach(r => byId[r.fund_id] = r);
  const funds = S.data.funds.map(f => {
    const r = byId[f.id];
    let amount = f.amount;
    let pctv = f.last_pct;
    if (values[f.id] !== undefined) {
      if (mode === 'pct') { pctv = values[f.id]; amount = f.amount * (1 + pctv / 100); }
      else { amount = values[f.id]; pctv = f.amount > 0 ? (amount / f.amount - 1) * 100 : 0; }
    }
    const cost = f.cost || amount;
    return {
      ...f,
      amount: Math.round(amount * 100) / 100,
      last_pct: (pctv === null || pctv === undefined) ? null : Math.round(pctv * 100) / 100,
      rate: cost ? Math.round(((amount / cost - 1) * 100) * 100) / 100 : 0,
      today_action: r ? r.actions.join(' + ') : f.today_action,
      today_priority: r ? r.priority : f.today_priority,
      today_money: r ? r.money : f.today_money,
    };
  });
  const p = d.portfolio;
  S.preview = {
    ...S.data,
    funds,
    summary: {
      ...S.data.summary,
      total: p.total, cost_total: p.cost_total, pnl: p.pnl, rate: p.rate,
      tech_ratio: p.tech_ratio, tech_amount: p.tech, cash: p.cash,
      cash_ratio: p.cash_ratio, fund_count: p.fund_count, dca_count: p.dca_count,
      updated_at: d.updated_at,
    },
    warnings: d.warnings || [],
  };
  S.data = S.preview;
  S.mode = 'estimate';
  S.activeDate = d.date;
  setBadge();
  render();
  renderAdvicePreview(d);
}

function renderAdvicePreview(d) {
  const order = ['必做', '择机'];
  const list = (d.records || []).filter(x => x.priority === '必做' || x.priority === '择机');
  $('#adviceTitle').textContent = `预计建议 · ${d.date}`;
  if (!list.length) { $('#adviceBody').innerHTML = '<div class="tiny">这一天没有需要变动的建议</div>'; return; }
  $('#adviceBody').innerHTML = order.map(p => {
    const rs = list.filter(x => x.priority === p);
    if (!rs.length) return '';
    return `<div class="grp ${p}"><div class="gt">${p} · ${rs.length}</div>`
      + rs.map(r => `<div class="it"><b>${esc(r.name)}</b>：${esc(r.actions.join(' + '))}${r.money ? ` <span class="m">（${money0(r.money)} 元）</span>` : ''}</div>`).join('')
      + `</div>`;
  }).join('');
}

/* 调仓 */
function openTrade() {
  const funds = S.data.funds.slice().sort((a, b) => b.amount - a.amount);
  const opts = funds.map(f => `<option value="${f.id}">${esc(f.name)}（${money0(f.amount)} 元）</option>`).join('');
  openModal(`
    <div class="m-head"><h3>记一笔调仓</h3><button class="ico" data-close>×</button></div>
    <p class="m-desc">记录买入、卖出或转换后，持仓市值与成本会立即更新，并写入当日快照。传成交截图只预填，核对后再记入。</p>
    ${shotBar('或直接把成交截图拖进来 / Ctrl+V 粘贴')}
    <div class="form">
      <label>操作</label>
      <div class="seg" id="segSide">
        <button class="on" data-s="sell">卖出</button>
        <button data-s="buy">买入</button>
        <button data-s="switch">转换</button>
      </div>
      <label>基金</label>
      <select class="input" id="tFund">${opts}</select>
      <label id="tToLabel" hidden>转入到</label>
      <select class="input" id="tTo" hidden>${opts}</select>
      <label>金额（元）</label>
      <input class="input" id="tAmt" inputmode="decimal" placeholder="如 1034.50">
      <label>备注</label>
      <input class="input" id="tNote" placeholder="可选，如：按建议反弹减仓">
    </div>
    <div class="m-foot">
      <span class="m-note" id="tMsg">金额按当日市值计</span>
      <button class="btn btn-ghost" data-close>取消</button>
      <button class="btn btn-main" id="tSubmit">记入</button>
    </div>
  `);
  let side = 'sell';
  $('#segSide').querySelectorAll('button').forEach(b => b.onclick = () => {
    $('#segSide').querySelectorAll('button').forEach(x => x.classList.remove('on'));
    b.classList.add('on'); side = b.dataset.s;
    const show = side === 'switch';
    $('#tToLabel').hidden = !show; $('#tTo').hidden = !show;
  });
  const setSide = next => {
    side = next;
    $('#segSide').querySelectorAll('button').forEach(x => x.classList.toggle('on', x.dataset.s === side));
    const show = side === 'switch';
    $('#tToLabel').hidden = !show; $('#tTo').hidden = !show;
  };
  bindShot('trade', d => {
    const t = d.trade;
    if (!t) { shotReport(d, '没有识别出一笔完整交易，请看原文后手工填'); return; }
    setSide(t.side);
    if ([...$('#tFund').options].some(o => o.value === t.fund_id)) $('#tFund').value = t.fund_id;
    if (t.to_fund_id && [...$('#tTo').options].some(o => o.value === t.to_fund_id)) $('#tTo').value = t.to_fund_id;
    $('#tAmt').value = (+t.amount).toFixed(2);
    if (t.note) $('#tNote').value = t.note;
    const label = { sell: '卖出', buy: '买入', switch: '转换' }[t.side] || t.side;
    shotReport(d, `识别为${label} ${money0(t.amount)} 元，请核对后再记入`);
  });
  $('#tSubmit').onclick = async () => {
    const amount = parseFloat($('#tAmt').value);
    if (!isFinite(amount) || amount <= 0) { $('#tMsg').textContent = '金额要大于 0'; return; }
    $('#tSubmit').disabled = true;
    try {
      const r = await fetch('/api/trade', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          date: today(), fund_id: $('#tFund').value, side, amount,
          to_fund_id: side === 'switch' ? $('#tTo').value : null,
          note: $('#tNote').value.trim(),
        }),
      });
      const d = await r.json();
      if (!d.ok) { $('#tMsg').textContent = d.error; $('#tSubmit').disabled = false; return; }
      closeModal();
      await load();
      $('#modeBadge').hidden = false;
      $('#modeBadge').className = 'badge ok';
      $('#modeBadge').textContent = `已记录：${d.trade.detail}`;
      setTimeout(() => { $('#modeBadge').hidden = true; }, 6000);
    } catch (e) {
      $('#tMsg').textContent = '提交失败：' + e.message;
      $('#tSubmit').disabled = false;
    }
  };
}

const DCA_DAY = ['', '周一', '周二', '周三', '周四', '周五', '周六', '周日'];

function dcaLabel(f) {
  const amount = Number(f.dca_amount ?? f.dca_weekly ?? 0);
  const n = amount ? String(Math.round(amount * 100) / 100) : '0';
  if (f.dca_cycle === 'daily') return `每日 ${n} 元`;
  const day = DCA_DAY[Number(f.dca_weekday) || 0];
  return day ? `每${day} ${n} 元` : `每周 ${n} 元`;
}

function syncDcaRow(tr) {
  const daily = tr.querySelector('.dca-cycle').value === 'daily';
  const day = tr.querySelector('.dca-day');
  day.disabled = daily;
  if (daily) day.value = '0';
}

/* 定投策略 */
function openDca() {
  const funds = S.data.funds.slice().sort((a, b) => b.amount - a.amount);
  const dayOpts = (selected) => [0, 1, 2, 3, 4, 5, 6, 7].map(n =>
    `<option value="${n}" ${Number(selected) === n ? 'selected' : ''}>${n ? DCA_DAY[n] : '—'}</option>`).join('');
  const rows = funds.map(f => {
    const cycle = f.dca_cycle === 'daily' ? 'daily' : 'weekly';
    const day = cycle === 'daily' ? 0 : (Number(f.dca_weekday) || 0);
    const amount = Number(f.dca_amount ?? f.dca_weekly ?? 0);
    return `
    <tr data-id="${f.id}">
      <td><div class="fn"><b>${esc(f.name)}</b><span>现值 ${money(f.amount)}</span></div></td>
      <td class="num"><input type="checkbox" class="dca-on" ${f.dca_on ? 'checked' : ''}></td>
      <td class="num"><select class="dca-cycle"><option value="daily" ${cycle === 'daily' ? 'selected' : ''}>每日</option><option value="weekly" ${cycle === 'weekly' ? 'selected' : ''}>每周</option></select></td>
      <td class="num"><select class="dca-day" ${cycle === 'daily' ? 'disabled' : ''}>${dayOpts(day)}</select></td>
      <td class="num"><input class="cell dca-amt" inputmode="decimal" value="${amount > 0 ? amount.toFixed(2) : ''}" placeholder="每次金额"></td>
    </tr>`;
  }).join('');
  openModal(`
    <div class="m-head"><h3>定投策略</h3><button class="ico" data-close>×</button></div>
    <p class="m-desc">传「买卖计划」截图。每日定投填每次金额；每周定投再选星期几。金额用买入金额，不是累计定投。核对后再保存。</p>
    ${shotBar('或直接把定投页截图拖进来 / Ctrl+V 粘贴')}
    <div class="m-table"><table class="grid">
      <thead><tr><th>基金</th><th class="num">定投中</th><th class="num">周期</th><th class="num">星期</th><th class="num">每次金额（元）</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
    <div class="m-foot">
      <span class="m-note" id="dcaMsg">截图里没出现的基金保持原样。同一只基金有两笔时，表里只填第一笔，另一笔写在这里。</span>
      <button class="btn btn-ghost" data-close>取消</button>
      <button class="btn btn-main" id="dcaSave">保存定投</button>
    </div>
  `);
  $('#modal').querySelectorAll('.dca-cycle').forEach(sel => {
    sel.onchange = () => syncDcaRow(sel.closest('tr'));
  });
  bindShot('dca', d => {
    const items = d.items || [];
    const used = {};
    const extra = [];
    let n = 0;
    items.forEach(it => {
      const tr = $(`#modal tr[data-id="${it.id}"]`);
      if (!tr) return;
      if (used[it.id]) { extra.push({ tr, it }); return; }
      used[it.id] = true;
      tr.querySelector('.dca-on').checked = !!it.on;
      tr.querySelector('.dca-cycle').value = it.cycle === 'daily' ? 'daily' : 'weekly';
      tr.querySelector('.dca-day').value = String(it.cycle === 'weekly' ? (it.weekday || 0) : 0);
      tr.querySelector('.dca-amt').value = (+it.amount).toFixed(2);
      syncDcaRow(tr);
      n++;
    });
    const more = extra.map(({ tr, it }) => {
      const name = tr.querySelector('.fn b').textContent;
      const when = it.cycle === 'daily' ? '每日' : (DCA_DAY[it.weekday] ? `每${DCA_DAY[it.weekday]}` : '每周');
      return `${name} 另有一笔 ${when} ${it.amount} 元`;
    }).join('；');
    shotReport(d, items.length
      ? `识别到 ${n} 只${more ? '。' + more + '，表里只保留第一笔' : ''}，请核对后再保存`
      : '没有识别出定投计划，请看原文后手工改');
  });
  $('#dcaSave').onclick = async () => {
    const items = [...$('#modal').querySelectorAll('tr[data-id]')].map(tr => {
      const on = tr.querySelector('.dca-on').checked;
      const cycle = tr.querySelector('.dca-cycle').value;
      const weekday = cycle === 'weekly' ? Number(tr.querySelector('.dca-day').value) : 0;
      const raw = tr.querySelector('.dca-amt').value.trim();
      const amount = raw === '' ? 0 : parseFloat(raw);
      return { id: tr.dataset.id, on, cycle, weekday, amount };
    });
    if (items.some(it => it.on && (!isFinite(it.amount) || it.amount <= 0))) {
      $('#dcaMsg').textContent = '已勾选的基金要填大于 0 的每次金额';
      return;
    }
    if (items.some(it => it.on && it.cycle === 'weekly' && !(it.weekday >= 1 && it.weekday <= 7))) {
      $('#dcaMsg').textContent = '每周定投要选星期几';
      return;
    }
    if (items.some(it => !isFinite(it.amount) || it.amount < 0)) {
      $('#dcaMsg').textContent = '金额要是大于等于 0 的数字';
      return;
    }
    $('#dcaSave').disabled = true;
    $('#dcaMsg').textContent = '保存中…';
    try {
      const r = await fetch('/api/dca', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items }),
      });
      const d = await r.json();
      if (!d.ok) { $('#dcaMsg').textContent = d.error; $('#dcaSave').disabled = false; return; }
      closeModal();
      await load();
      $('#modeBadge').hidden = false;
      $('#modeBadge').className = 'badge ok';
      $('#modeBadge').textContent = `定投已更新 ${d.count} 只`;
      setTimeout(() => { $('#modeBadge').hidden = true; }, 6000);
    } catch (e) {
      $('#dcaMsg').textContent = '保存失败：' + e.message;
      $('#dcaSave').disabled = false;
    }
  };
}

async function exportAi() {
  const btn = $('#btnExport');
  btn.disabled = true;
  try {
    const r = await fetch('/api/ai-brief', { cache: 'no-store' });
    const d = await r.json();
    if (!d.ok) throw new Error(d.error || '导出失败');
    const blob = new Blob([d.markdown], { type: 'text/markdown;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = d.filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(a.href);
    $('#modeBadge').hidden = false;
    $('#modeBadge').className = 'badge ok';
    $('#modeBadge').textContent = `已导出 ${d.filename}`;
  } catch (e) {
    $('#modeBadge').hidden = false;
    $('#modeBadge').className = 'badge est';
    $('#modeBadge').textContent = e.message;
  } finally {
    btn.disabled = false;
  }
}

/* ---------------- 绑定 ---------------- */
$('#refresh').onclick = load;
$('#btnExport').onclick = exportAi;
$('#btnEstimate').onclick = () => openInput('estimate');
$('#btnFinal').onclick = () => openInput('final');
$('#btnTrade').onclick = openTrade;
$('#btnDca').onclick = openDca;
$('#search').oninput = e => { S.q = e.target.value.trim(); renderFunds(); };
$('#sort').onchange = e => { S.sort = e.target.value; renderFunds(); };
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
document.addEventListener('paste', e => {
  if ($('#mask').hidden) return;
  const item = [...(e.clipboardData?.items || [])].find(i => i.type.startsWith('image/'));
  if (!item) return;
  const file = item.getAsFile();
  const input = $('#shotFile');
  if (input && file) {
    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    input.dispatchEvent(new Event('change'));
  }
});
load();
if (window.ResizeObserver) {
  let frame = 0;
  new ResizeObserver(() => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => { if (S.data) renderChart(); });
  }).observe(document.querySelector('.chart-wrap'));
}
