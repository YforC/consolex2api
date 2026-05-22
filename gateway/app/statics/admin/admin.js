const loginView = document.querySelector('#loginView');
const adminShell = document.querySelector('.admin-shell');
const loginAdminKey = document.querySelector('#loginAdminKey');
const loginBtn = document.querySelector('#loginBtn');
const logoutBtn = document.querySelector('#logoutBtn');
const gatewayKeyMeta = document.querySelector('#gatewayKeyMeta');
const configForm = document.querySelector('#configForm');
const txt = document.querySelector('#txt');
const file = document.querySelector('#file');
const statusEl = document.querySelector('#status');
const countEl = document.querySelector('#count');
const sourceEl = document.querySelector('#source');
const fallbackEl = document.querySelector('#fallback');
const failedCountEl = document.querySelector('#failedCount');
const selectableCountEl = document.querySelector('#selectableCount');
const problemCountEl = document.querySelector('#problemCount');
const totalUseCountEl = document.querySelector('#totalUseCount');
const totalFailCountEl = document.querySelector('#totalFailCount');
const pathEl = document.querySelector('#path');
const tableMetaEl = document.querySelector('#tableMeta');
const accountsTable = document.querySelector('#accountsTable');
const importModal = document.querySelector('#modal-import');
const editAccountModal = document.querySelector('#modal-edit-account');
const accountDetailModal = document.querySelector('#modal-account-detail');
const accountDetailBody = document.querySelector('#accountDetailBody');
const selectAllAccounts = document.querySelector('#selectAllAccounts');
const selectedMeta = document.querySelector('#selectedMeta');
const accountSearch = document.querySelector('#accountSearch');
const statusFilter = document.querySelector('#statusFilter');
const pageTitle = document.querySelector('.page-title');
const pageSub = document.querySelector('.page-sub');
const cancelRefreshBtn = document.querySelector('#cancelRefreshBtn');
const refreshSelectedBtn = document.querySelector('#refreshSelectedBtn');
const refreshJobPanel = document.querySelector('#refreshJobPanel');
const refreshJobSummary = document.querySelector('#refreshJobSummary');
const refreshJobResults = document.querySelector('#refreshJobResults');
const batchButtons = Array.from(document.querySelectorAll('#disableSelectedBtn, #enableSelectedBtn, #editSelectedBtn, #refreshSelectedBtn, #deleteSelectedBtn'));
const tabButtons = document.querySelectorAll('[data-tab]');
const viewPanels = document.querySelectorAll('[data-view]');
let latest = null;
let latestSettings = null;
let filteredAccountRows = [];
let refreshJobRows = new Map();
let sortState = { key: 'status', direction: 'asc' };
let toastTimer = null;
let activeRefreshJob = '';
let adminKeyValue = sessionStorage.getItem('gateway_admin_key') || '';
loginAdminKey.value = adminKeyValue;

const CONFIG_KEY_HINTS = {
  'app.openai_api_key': '客户端调用 /v1/* 时使用的 Bearer Key。',
  'app.admin_key': '进入管理后台使用的 Key。建议和网关 API Key 分开。',
  'upstream.proxy': '本地代理示例：http://127.0.0.1:7897。服务器直连时留空。',
  'upstream.referer': '只作为没有 team_id 的账号兜底；正常不要写固定 team URL。',
  'upstream.cf_cookies': 'Cloudflare 相关 cookie；不要把 sso 放在这里。',
  'models.ids': '一行一个模型 ID；留空时从 HAR 或默认列表读取。',
};

function setStatus(message, isError=false) {
  window.clearTimeout(toastTimer);
  statusEl.textContent = message;
  statusEl.className = isError ? 'toast error show' : 'toast show';
  toastTimer = window.setTimeout(() => statusEl.classList.remove('show'), isError ? 7000 : 2600);
}
function headers() {
  sessionStorage.setItem('gateway_admin_key', adminKeyValue);
  return { 'Authorization': `Bearer ${adminKeyValue}`, 'Content-Type': 'application/json' };
}
function showLogin() {
  adminShell.classList.add('hidden');
  loginView.classList.remove('hidden');
  loginAdminKey.focus();
}
function showAdmin() {
  loginView.classList.add('hidden');
  adminShell.classList.remove('hidden');
}
async function login() {
  adminKeyValue = loginAdminKey.value.trim();
  if (!adminKeyValue) throw new Error('请输入 Admin Key。');
  await refresh({ quiet: true });
  showAdmin();
  setStatus('已进入管理界面。');
}
function logout() {
  adminKeyValue = '';
  sessionStorage.removeItem('gateway_admin_key');
  loginAdminKey.value = '';
  showLogin();
}
function switchTab(tab) {
  tabButtons.forEach(button => button.classList.toggle('active', button.dataset.tab === tab));
  viewPanels.forEach(panel => panel.classList.toggle('hidden', panel.dataset.view !== tab));
  pageTitle.textContent = tab === 'settings' ? '运行配置' : '账号列表';
  pageSub.textContent = tab === 'settings'
    ? '设置 OpenAI 兼容接口使用的网关 API Key。'
    : '使用 Admin Key 管理账号池和批量操作。';
}
function sourceText(value) {
  if (value === 'accounts_file') return '导入账号文件';
  if (value === 'env_fallback') return '.env 默认 UPSTREAM_SSO';
  return '未配置';
}
function badgeClass(status) {
  const normalized = (status || 'pending').toLowerCase();
  if (['ok','active','success'].includes(normalized)) return 'badge badge-ok';
  if (['failed','invalid','expired','disabled'].includes(normalized)) return `badge badge-${normalized}`;
  if (normalized === 'cooling') return 'badge badge-cooling';
  return 'badge badge-pending';
}
function cell(text, className='') {
  const td = document.createElement('td');
  if (className) td.className = className;
  td.textContent = text || '-';
  if (text) td.title = text;
  return td;
}
function buttonCell(buttons) {
  const td = document.createElement('td');
  const wrap = document.createElement('div');
  wrap.className = 'row-actions';
  buttons.forEach(button => wrap.appendChild(button));
  td.appendChild(wrap);
  return td;
}
function rowButton(label, onClick, danger=false) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = danger ? 'row-action danger' : 'row-action';
  button.textContent = label;
  button.addEventListener('click', onClick);
  return button;
}
function formatTime(value) {
  const seconds = Number(value || 0);
  if (!seconds) return '-';
  return new Date(seconds * 1000).toLocaleString();
}
function errorCategoryText(value) {
  const map = {
    auth: '认证',
    rate_limit: '限流',
    cloudflare: 'Cloudflare',
    team: 'Team',
    request: '请求',
    network: '网络',
    upstream: '上游',
  };
  return map[value] || '';
}
function selectedIndexes() {
  return Array.from(document.querySelectorAll('.account-select:checked'))
    .map(input => Number(input.dataset.index))
    .filter(Number.isInteger);
}
function updateSelectionMeta() {
  const selected = selectedIndexes().length;
  const total = latest?.accounts?.length || 0;
  selectedMeta.textContent = selected ? `已选择 ${selected} / ${total}` : '未选择账号';
  selectAllAccounts.checked = total > 0 && selected === total;
  selectAllAccounts.indeterminate = selected > 0 && selected < total;
}
function setRefreshingState(isRefreshing, done=0, total=0) {
  batchButtons.forEach(button => { button.disabled = isRefreshing; });
  refreshSelectedBtn.textContent = isRefreshing && total ? `刷新中 ${done}/${total}` : '刷新状态';
  cancelRefreshBtn.classList.toggle('hidden', !isRefreshing);
}
function render(data) {
  latest = data;
  const accounts = data.accounts || [];
  const failed = accounts.filter(a => ['failed','invalid','expired'].includes((a.status || '').toLowerCase()) || a.last_error).length;
  countEl.textContent = data.count ?? '-';
  selectableCountEl.textContent = data.selectable_count ?? '-';
  problemCountEl.textContent = data.problem_count ?? '-';
  totalUseCountEl.textContent = data.total_use_count ?? 0;
  totalFailCountEl.textContent = data.total_fail_count ?? 0;
  sourceEl.textContent = sourceText(data.effective_source);
  fallbackEl.textContent = data.env_fallback_configured ? '已配置' : '未配置';
  failedCountEl.textContent = failed;
  pathEl.textContent = data.accounts_file || '未配置账号文件路径';
  renderFilteredAccounts();
}
function isProblemAccount(item) {
  const itemStatus = (item.status || '').toLowerCase();
  return ['cooling','invalid','expired','failed'].includes(itemStatus)
    || Boolean(item.error_category)
    || Boolean(item.last_error);
}
function sortAccounts(rows) {
  const { key, direction } = sortState;
  const sign = direction === 'desc' ? -1 : 1;
  rows.sort((left, right) => {
    const a = left.item?.[key];
    const b = right.item?.[key];
    if (key === 'fail_count' || key === 'last_checked_at') {
      return ((Number(a || 0) - Number(b || 0)) || (left.index - right.index)) * sign;
    }
    return (String(a || '').localeCompare(String(b || '')) || (left.index - right.index)) * sign;
  });
  return rows;
}
function renderFilteredAccounts() {
  const accounts = latest?.accounts || [];
  const query = (accountSearch.value || '').trim().toLowerCase();
  const status = (statusFilter.value || '').trim().toLowerCase();
  filteredAccountRows = sortAccounts(accounts
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => {
      const itemStatus = (item.status || '').toLowerCase();
      if (status === 'problem' && !isProblemAccount(item)) return false;
      if (status && status !== 'problem' && itemStatus !== status) return false;
      if (!query) return true;
      return [item.name, item.sso, item.team_id, item.referer, item.status, item.error_category, item.last_error]
        .some(value => String(value || '').toLowerCase().includes(query));
    }));
  tableMetaEl.textContent = accounts.length
    ? `显示 ${filteredAccountRows.length} / ${accounts.length} 条记录`
    : '暂无账号';
  accountsTable.innerHTML = '';
  if (!filteredAccountRows.length) {
    const row = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 10;
    td.innerHTML = '<div class="empty-state">暂无匹配账号。</div>';
    row.appendChild(td);
    accountsTable.appendChild(row);
    updateSelectionMeta();
    return;
  }
  filteredAccountRows.forEach(({ item, index }) => {
    const tr = document.createElement('tr');
    const selectTd = document.createElement('td');
    selectTd.className = 'select-col';
    const checkbox = document.createElement('input');
    checkbox.className = 'account-select';
    checkbox.type = 'checkbox';
    checkbox.dataset.index = String(index);
    checkbox.setAttribute('aria-label', `选择 ${item.name || String(index + 1)}`);
    checkbox.addEventListener('change', updateSelectionMeta);
    selectTd.appendChild(checkbox);
    tr.appendChild(selectTd);
    tr.appendChild(cell(item.name, 'mono'));
    tr.appendChild(cell(item.sso, 'mono'));
    const statusTd = document.createElement('td');
    const badge = document.createElement('span');
    badge.className = badgeClass(item.status);
    badge.textContent = item.status || 'pending';
    statusTd.appendChild(badge);
    tr.appendChild(statusTd);
    tr.appendChild(cell(item.team_id || 'sso-only', 'truncate'));
    tr.appendChild(cell(item.referer || '-', 'truncate'));
    tr.appendChild(cell(`${item.use_count || 0} / ${item.fail_count || 0}`, 'mono'));
    tr.appendChild(cell(formatTime(item.last_checked_at), 'truncate'));
    const errorText = [errorCategoryText(item.error_category), item.last_error].filter(Boolean).join(' · ');
    tr.appendChild(cell(errorText || '-', 'truncate'));
    tr.appendChild(buttonCell([
      rowButton('详情', () => openAccountDetail(index)),
      rowButton('刷新', () => quickRefreshAccount(index)),
      rowButton((item.status || '').toLowerCase() === 'disabled' ? '启用' : '禁用', () => quickToggleAccountDisabled(index, (item.status || '').toLowerCase() !== 'disabled')),
      rowButton('编辑', () => openEditAccount(index)),
    ]));
    accountsTable.appendChild(tr);
  });
  updateSelectionMeta();
}
function renderSettings(data) {
  latestSettings = data;
  renderConfigForm(data);
  const runtimePath = data.runtime_config_path || 'gateway/config.toml';
  const adminHint = data.admin_key_configured ? '' : ' ADMIN_KEY 未配置，管理后台临时使用网关 API Key 登录。';
  gatewayKeyMeta.textContent = `配置文件：${runtimePath}。环境变量会覆盖这里保存的值。${adminHint}`;
}
function inputIdForKey(key) {
  return `config-${key.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
}
function fieldValue(settings, key) {
  if (settings?.masked_values?.[key]) return '';
  const value = settings?.values?.[key];
  if (Array.isArray(value)) return value.join('\n');
  if (typeof value === 'boolean') return value;
  return value ?? '';
}
function fieldPlaceholder(settings, key, field) {
  if (field.type !== 'password') return '';
  return settings?.masked_values?.[key] ? `configured: ${settings.masked_values[key]}` : 'leave blank to keep existing value';
}
function renderConfigForm(settings) {
  configForm.innerHTML = '';
  for (const group of settings.fields || []) {
    const section = document.createElement('section');
    section.className = 'config-group';
    const title = document.createElement('div');
    title.className = 'config-group-title';
    title.textContent = group.label || group.id;
    section.appendChild(title);
    for (const field of group.fields || []) {
      const row = document.createElement('label');
      row.className = 'config-row';
      row.htmlFor = inputIdForKey(field.key);
      const info = document.createElement('span');
      info.className = 'config-info';
      const name = document.createElement('span');
      name.className = 'config-label';
      name.textContent = field.label || field.key;
      const hint = document.createElement('span');
      hint.className = 'config-hint';
      const source = settings.sources?.[field.key] || '';
      hint.textContent = `${field.key}${source ? ` · ${source}` : ''}${CONFIG_KEY_HINTS[field.key] ? ` · ${CONFIG_KEY_HINTS[field.key]}` : ''}`;
      info.appendChild(name);
      info.appendChild(hint);
      row.appendChild(info);

      let input;
      if (field.type === 'textarea' || field.type === 'list') {
        input = document.createElement('textarea');
        input.className = 'textarea config-input';
        input.rows = field.type === 'list' ? 4 : 3;
        input.value = fieldValue(settings, field.key);
      } else if (field.type === 'bool') {
        input = document.createElement('input');
        input.className = 'config-checkbox';
        input.type = 'checkbox';
        input.checked = Boolean(fieldValue(settings, field.key));
      } else {
        input = document.createElement('input');
        input.className = 'input config-input';
        input.type = field.type === 'password' ? 'password' : field.type === 'number' ? 'number' : 'text';
        if (field.type === 'number') input.step = 'any';
        input.value = fieldValue(settings, field.key);
        input.placeholder = fieldPlaceholder(settings, field.key, field);
      }
      input.id = inputIdForKey(field.key);
      input.dataset.configKey = field.key;
      input.dataset.configType = field.type || 'text';
      row.appendChild(input);
      section.appendChild(row);
    }
    configForm.appendChild(section);
  }
}
function download(name, text, type) {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
async function refresh(options={}) {
  if (!adminKeyValue) { setStatus('先填写 Admin Key。', true); return; }
  const authHeaders = headers();
  const [accountsRes, settingsRes] = await Promise.all([
    fetch('/admin/api/accounts', { headers: authHeaders }),
    fetch('/admin/api/settings', { headers: authHeaders }),
  ]);
  if (!accountsRes.ok) throw new Error(await accountsRes.text());
  if (!settingsRes.ok) throw new Error(await settingsRes.text());
  render(await accountsRes.json());
  renderSettings(await settingsRes.json());
  if (!options.quiet) setStatus('状态已刷新。');
}
async function saveGatewayKey() {
  if (!adminKeyValue) throw new Error('先填写 Admin Key。');
  const values = {};
  configForm.querySelectorAll('[data-config-key]').forEach(input => {
    const key = input.dataset.configKey;
    const type = input.dataset.configType;
    if (type === 'bool') values[key] = input.checked;
    else if (type === 'number') values[key] = input.value === '' ? 0 : Number(input.value);
    else if (type === 'list') values[key] = input.value.split(/\r?\n/).map(v => v.trim()).filter(Boolean);
    else values[key] = input.value;
  });
  const res = await fetch('/admin/api/settings', {
    method:'PUT',
    headers:headers(),
    body:JSON.stringify({ values }),
  });
  if (!res.ok) throw new Error(await res.text());
  renderSettings(await res.json());
  setStatus('运行配置已保存。');
}
async function postBatch(url, body, successMessage) {
  const indexes = selectedIndexes();
  if (!adminKeyValue) throw new Error('先填写 Admin Key。');
  if (!indexes.length) throw new Error('先选择账号。');
  const res = await fetch(url, {
    method:'POST',
    headers:headers(),
    body:JSON.stringify({ indexes, ...body }),
  });
  if (!res.ok) throw new Error(await res.text());
  render(await res.json());
  setStatus(successMessage);
}
function parseSseBlock(block) {
  const eventLine = block.split('\n').find(line => line.startsWith('event:'));
  const dataLine = block.split('\n').find(line => line.startsWith('data:'));
  if (!eventLine || !dataLine) return null;
  return {
    event: eventLine.slice(6).trim(),
    data: JSON.parse(dataLine.slice(5).trim()),
  };
}
function renderRefreshJobResult(eventName, data) {
  if (!refreshJobPanel || !refreshJobResults || !refreshJobSummary) return;
  refreshJobPanel.classList.remove('hidden');
  if (eventName === 'start') {
    refreshJobRows = new Map();
    refreshJobResults.innerHTML = '';
    refreshJobSummary.textContent = `0 / ${data.total || 0}`;
    return;
  }
  if (eventName === 'progress') {
    const key = String(data.index ?? data.name ?? refreshJobRows.size);
    refreshJobRows.set(key, data);
    refreshJobSummary.textContent = `${data.done || 0} / ${data.total || 0}`;
  } else if (eventName === 'complete') {
    refreshJobSummary.textContent = `complete ${data.done || 0} / ${data.total || 0}`;
  } else if (eventName === 'cancelled') {
    refreshJobSummary.textContent = `cancelled ${data.done || 0} / ${data.total || 0}`;
  }
  refreshJobResults.innerHTML = '';
  for (const row of refreshJobRows.values()) {
    const item = document.createElement('div');
    item.className = 'job-result';
    const category = errorCategoryText(row.error_category) || row.error_category || '-';
    item.textContent = `${row.name || row.index}: ${row.status || '-'} / ${row.status_code || '-'} / ${category}${row.last_error ? ` / ${row.last_error}` : ''}`;
    refreshJobResults.appendChild(item);
  }
}
async function runStreamRefresh() {
  const indexes = selectedIndexes();
  if (!adminKeyValue) throw new Error('先填写 Admin Key。');
  if (!indexes.length) throw new Error('先选择账号。');
  activeRefreshJob = (globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : `refresh-${Date.now()}`);
  setRefreshingState(true, 0, indexes.length);
  renderRefreshJobResult('start', { total: indexes.length });
  const res = await fetch('/admin/api/accounts/refresh/stream', {
    method:'POST',
    headers:headers(),
    body:JSON.stringify({ indexes, job_id: activeRefreshJob }),
  });
  if (!res.ok) throw new Error(await res.text());
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split('\n\n');
      buffer = blocks.pop() || '';
      for (const block of blocks) {
        const parsed = parseSseBlock(block);
        if (!parsed) continue;
        if (parsed.event === 'progress') {
          renderRefreshJobResult(parsed.event, parsed.data);
          setRefreshingState(true, parsed.data.done, parsed.data.total);
          setStatus(`刷新中 ${parsed.data.done} / ${parsed.data.total}`);
        } else if (parsed.event === 'cancelled') {
          renderRefreshJobResult(parsed.event, parsed.data);
          setStatus(`已取消刷新，完成 ${parsed.data.done} / ${parsed.data.total}`);
        } else if (parsed.event === 'complete') {
          renderRefreshJobResult(parsed.event, parsed.data);
          setStatus(`刷新完成 ${parsed.data.done} / ${parsed.data.total}`);
        }
      }
    }
  } finally {
    setRefreshingState(false);
    activeRefreshJob = '';
    await refresh();
  }
}
async function cancelStreamRefresh() {
  if (!activeRefreshJob) return;
  const res = await fetch('/admin/api/accounts/refresh/cancel', {
    method:'POST',
    headers:headers(),
    body:JSON.stringify({ job_id: activeRefreshJob }),
  });
  if (!res.ok) throw new Error(await res.text());
  setStatus('正在取消刷新。');
}
function openImport() {
  importModal.classList.add('open');
  importModal.setAttribute('aria-hidden', 'false');
  txt.focus();
}
function closeImport() {
  importModal.classList.remove('open');
  importModal.setAttribute('aria-hidden', 'true');
}
function openEditAccount(index=null) {
  if (index === null) {
    const indexes = selectedIndexes();
    if (indexes.length !== 1) throw new Error('请选择一个账号进行编辑。');
    index = indexes[0];
  }
  const item = latest?.accounts?.[index];
  if (!item) throw new Error('账号不存在，请刷新后重试。');
  document.querySelector('#editAccountIndex').value = String(index);
  document.querySelector('#editAccountSso').value = '';
  document.querySelector('#editAccountTeam').value = item.team_id || '';
  document.querySelector('#editAccountStatus').value = item.status || 'pending';
  editAccountModal.classList.add('open');
  editAccountModal.setAttribute('aria-hidden', 'false');
}
function closeEditAccount() {
  editAccountModal.classList.remove('open');
  editAccountModal.setAttribute('aria-hidden', 'true');
}
function openAccountDetail(index) {
  const item = latest?.accounts?.[index];
  if (!item) throw new Error('账号不存在，请刷新后重试。');
  const rows = [
    ['名称', item.name],
    ['状态', item.status],
    ['SSO', item.sso],
    ['Team ID', item.team_id || '-'],
    ['Referer', item.referer || '-'],
    ['错误分类', errorCategoryText(item.error_category) || '-'],
    ['使用次数', item.use_count || 0],
    ['失败次数', item.fail_count || 0],
    ['最近检查', formatTime(item.last_checked_at)],
    ['最近使用', formatTime(item.last_used_at)],
    ['错误信息', item.last_error || '-'],
  ];
  accountDetailBody.innerHTML = '';
  rows.forEach(([label, value]) => {
    const key = document.createElement('div');
    key.className = 'detail-key';
    key.textContent = label;
    const val = document.createElement('div');
    val.className = 'detail-value';
    val.textContent = String(value ?? '-');
    val.title = val.textContent;
    accountDetailBody.appendChild(key);
    accountDetailBody.appendChild(val);
  });
  accountDetailModal.classList.add('open');
  accountDetailModal.setAttribute('aria-hidden', 'false');
}
function closeAccountDetail() {
  accountDetailModal.classList.remove('open');
  accountDetailModal.setAttribute('aria-hidden', 'true');
}
async function quickRefreshAccount(index) {
  if (!adminKeyValue) throw new Error('先填写 Admin Key。');
  const res = await fetch('/admin/api/accounts/refresh', {
    method:'POST',
    headers:headers(),
    body:JSON.stringify({ indexes:[index] }),
  });
  if (!res.ok) throw new Error(await res.text());
  render(await res.json());
  setStatus('账号状态已刷新。');
}
async function quickToggleAccountDisabled(index, disabled) {
  if (!adminKeyValue) throw new Error('先填写 Admin Key。');
  const res = await fetch('/admin/api/accounts/disabled', {
    method:'POST',
    headers:headers(),
    body:JSON.stringify({ indexes:[index], disabled }),
  });
  if (!res.ok) throw new Error(await res.text());
  render(await res.json());
  setStatus(disabled ? '账号已禁用。' : '账号已启用。');
}
async function saveEditAccount() {
  if (!adminKeyValue) throw new Error('先填写 Admin Key。');
  const payload = {
    index: Number(document.querySelector('#editAccountIndex').value),
    sso: document.querySelector('#editAccountSso').value.trim(),
    team_id: document.querySelector('#editAccountTeam').value.trim(),
    status: document.querySelector('#editAccountStatus').value,
  };
  const res = await fetch('/admin/api/accounts/edit', {
    method:'POST',
    headers:headers(),
    body:JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  render(await res.json());
  closeEditAccount();
  setStatus('账号已保存。');
}
file.addEventListener('change', async () => { const f = file.files[0]; if (f) txt.value = await f.text(); });
importModal.addEventListener('click', event => { if (event.target === importModal) closeImport(); });
editAccountModal.addEventListener('click', event => { if (event.target === editAccountModal) closeEditAccount(); });
accountDetailModal.addEventListener('click', event => { if (event.target === accountDetailModal) closeAccountDetail(); });
document.addEventListener('keydown', event => { if (event.key === 'Escape') { closeImport(); closeEditAccount(); closeAccountDetail(); } });
document.querySelector('#openImportBtn').addEventListener('click', openImport);
document.querySelector('#closeImportBtn').addEventListener('click', closeImport);
document.querySelector('#closeEditAccountBtn').addEventListener('click', closeEditAccount);
document.querySelector('#closeAccountDetailBtn').addEventListener('click', closeAccountDetail);
document.querySelector('#saveEditAccountBtn').addEventListener('click', () => saveEditAccount().catch(err => setStatus(err.message, true)));
loginBtn.addEventListener('click', () => login().catch(err => setStatus(err.message, true)));
loginAdminKey.addEventListener('keydown', event => { if (event.key === 'Enter') login().catch(err => setStatus(err.message, true)); });
logoutBtn.addEventListener('click', logout);
tabButtons.forEach(button => button.addEventListener('click', () => switchTab(button.dataset.tab)));
document.querySelector('#refreshBtn').addEventListener('click', () => refresh().catch(err => setStatus(err.message, true)));
document.querySelector('#saveGatewayKeyBtn').addEventListener('click', () => saveGatewayKey().catch(err => setStatus(err.message, true)));
document.querySelector('#clearBtn').addEventListener('click', () => { txt.value = ''; setStatus('文本已清空。'); });
accountSearch.addEventListener('input', renderFilteredAccounts);
statusFilter.addEventListener('change', renderFilteredAccounts);
document.querySelectorAll('[data-sort]').forEach(button => button.addEventListener('click', () => {
  const key = button.dataset.sort;
  sortState = {
    key,
    direction: sortState.key === key && sortState.direction === 'asc' ? 'desc' : 'asc',
  };
  renderFilteredAccounts();
}));
selectAllAccounts.addEventListener('change', () => {
  document.querySelectorAll('.account-select').forEach(input => { input.checked = selectAllAccounts.checked; });
  updateSelectionMeta();
});
document.querySelector('#disableSelectedBtn').addEventListener('click', () => {
  postBatch('/admin/api/accounts/disabled', { disabled: true }, '已禁用所选账号。').catch(err => setStatus(err.message, true));
});
document.querySelector('#enableSelectedBtn').addEventListener('click', () => {
  postBatch('/admin/api/accounts/disabled', { disabled: false }, '已启用所选账号。').catch(err => setStatus(err.message, true));
});
document.querySelector('#editSelectedBtn').addEventListener('click', () => {
  try { openEditAccount(); } catch (err) { setStatus(err.message, true); }
});
document.querySelector('#refreshSelectedBtn').addEventListener('click', () => {
  runStreamRefresh().catch(err => {
    setRefreshingState(false);
    activeRefreshJob = '';
    setStatus(err.message, true);
  });
});
cancelRefreshBtn.addEventListener('click', () => {
  cancelStreamRefresh().catch(err => setStatus(err.message, true));
});
document.querySelector('#deleteSelectedBtn').addEventListener('click', () => {
  if (!window.confirm('确定删除所选账号？')) return;
  postBatch('/admin/api/accounts/delete', {}, '已删除所选账号。').catch(err => setStatus(err.message, true));
});
document.querySelector('#exportTxtBtn').addEventListener('click', () => {
  const lines = (latest?.accounts || []).map(a => `${a.name}\t${a.sso}\t${a.team_id || ''}\t${a.status || ''}\t${a.error_category || ''}\t${a.use_count || 0}\t${a.fail_count || 0}`);
  download('consolex-accounts-summary.txt', lines.join('\n') + (lines.length ? '\n' : ''), 'text/plain');
});
document.querySelector('#exportJsonBtn').addEventListener('click', () => download('consolex-accounts-summary.json', JSON.stringify(latest || {}, null, 2), 'application/json'));
document.querySelector('#importBtn').addEventListener('click', async () => {
  try {
    if (!adminKeyValue) throw new Error('先填写 Admin Key。');
    const res = await fetch('/admin/api/accounts/import', { method:'POST', headers:headers(), body:JSON.stringify({ text: txt.value }) });
    if (!res.ok) throw new Error(await res.text());
    render(await res.json());
    closeImport();
    setStatus('导入完成，账号池已重载。');
  } catch (err) { setStatus(err.message, true); }
});
document.querySelector('#addImportBtn').addEventListener('click', async () => {
  try {
    if (!adminKeyValue) throw new Error('先填写 Admin Key。');
    const res = await fetch('/admin/api/accounts/add', { method:'POST', headers:headers(), body:JSON.stringify({ text: txt.value }) });
    if (!res.ok) throw new Error(await res.text());
    render(await res.json());
    closeImport();
    setStatus('追加导入完成，重复账号已跳过。');
  } catch (err) { setStatus(err.message, true); }
});

if (adminKeyValue) {
  login().catch(() => showLogin());
} else {
  showLogin();
}
