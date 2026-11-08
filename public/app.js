const state = { settings: null, recurring: [], transactions: [], credit_lines: [], projection: null, calendarProjection: null, calendarBalanceProjection: null, calendarDate: null, view: 'forecast' };
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const money = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });
const compactMoney = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
const shortDate = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
const longDate = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' });
const weekday = new Intl.DateTimeFormat('en-US', { weekday: 'short', timeZone: 'UTC' });

function applyTheme(theme) {
  const resolved = theme === 'dark' ? 'dark' : 'light';
  document.documentElement.dataset.theme = resolved;
  localStorage.setItem('truenorth-theme', resolved);
  const toggle = $('#themeToggle');
  const dark = resolved === 'dark';
  toggle.setAttribute('aria-pressed', String(dark));
  toggle.setAttribute('aria-label', `Use ${dark ? 'light' : 'dark'} theme`);
  toggle.querySelector('span').textContent = dark ? '☀' : '☾';
  $('meta[name="theme-color"]').content = dark ? '#111e19' : '#10271f';
}

function localISODate() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
}
function isoUTC(value) { return value.toISOString().slice(0, 10); }
function asUTC(value) { return new Date(`${value}T00:00:00Z`); }
function escapeHTML(value) { const el = document.createElement('div'); el.textContent = String(value ?? ''); return el.innerHTML; }
function signed(value, kind) { return `${kind === 'income' ? '+' : '−'}${money.format(value)}`; }
function frequencyLabel(value) { return ({ weekly: 'Weekly', biweekly: 'Every 2 weeks', monthly: 'Monthly', quarterly: 'Every 3 months', yearly: 'Yearly' })[value] || value; }
const weekdayNames = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const ordinalNames = { 1: 'First', 2: 'Second', 3: 'Third', 4: 'Fourth', '-1': 'Last' };
function scheduleLabel(item) {
  if (item.schedule_type === 'weekday') return `Every ${weekdayNames[item.weekday]}`;
  if (item.schedule_type === 'nth_weekday') return `${ordinalNames[item.ordinal]} ${weekdayNames[item.weekday]} monthly`;
  return frequencyLabel(item.frequency);
}

function updateScheduleFields() {
  const form = $('#itemForm');
  const type = form.elements.schedule_type.value;
  $$('.schedule-interval', form).forEach(el => el.classList.toggle('hidden', type !== 'interval'));
  $$('.schedule-weekday', form).forEach(el => el.classList.toggle('hidden', !['weekday', 'nth_weekday'].includes(type)));
  $$('.schedule-nth', form).forEach(el => el.classList.toggle('hidden', type !== 'nth_weekday'));
}

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Something went wrong');
  return data;
}

async function load() {
  try {
    const data = await api('/api/bootstrap');
    Object.assign(state, data);
    state.calendarDate = new Date(`${localISODate().slice(0, 7)}-01T00:00:00Z`);
    populateFundingOptions();
    $('#forecastStart').value = localISODate();
    await loadProjection();
    renderLists();
    renderCards();
  } catch (error) { toast(error.message, true); }
}

async function loadProjection() {
  const start = $('#forecastStart').value || localISODate();
  state.projection = await api(`/api/projection?start=${start}&weeks=12`);
  renderProjection();
}

function renderProjection() {
  const p = state.projection;
  const nextPay = p.next_income;
  const cards = [
    { label: 'Spendable before payday', value: p.balance_before_next_income, note: nextPay ? `Before ${escapeHTML(nextPay.name)} on ${shortDate.format(asUTC(nextPay.date))}` : 'Add recurring income to calculate this', featured: true },
    { label: 'Available now', value: p.starting_balance, note: `Balance set as of ${longDate.format(asUTC(state.settings.balance_as_of))}` },
    { label: 'Lowest point', value: p.lowest_balance, note: p.lowest_balance < 0 ? 'Your plan falls below zero' : 'Across the next 12 weeks' },
    { label: 'In 12 weeks', value: p.ending_balance, note: `Projected on ${longDate.format(asUTC(p.end))}` }
  ];
  $('#metrics').innerHTML = cards.map(card => `<article class="metric-card ${card.featured ? 'metric-featured' : ''}">
    <div class="metric-label">${card.featured ? '◎' : '◇'} ${card.label}</div>
    <div class="metric-value ${card.value < 0 ? 'negative' : ''}">${money.format(card.value)}</div>
    <div class="metric-note">${card.note}</div>
  </article>`).join('');

  $('#weekList').innerHTML = p.weeks.map((week, index) => {
    const events = week.events.map(event => `<div class="event">
      <span class="event-date">${weekday.format(asUTC(event.date))}, ${shortDate.format(asUTC(event.date))}</span>
      <span><b>${escapeHTML(event.name)}</b><br><span class="event-source">${event.destination_credit_line_id ? `Payment to ${escapeHTML(event.destination_credit_line_name)}` : event.funding_source === 'credit' ? `Charged to ${escapeHTML(event.credit_line_name)}` : event.source === 'recurring' ? 'From Checking · Recurring' : event.status}</span></span>
      <b class="event-amount ${event.kind}">${signed(event.amount, event.kind)}</b>
    </div>`).join('') || '<div class="empty-week">No planned activity this week.</div>';
    return `<article class="week-row ${index === 0 ? 'open' : ''}">
      <button class="week-summary with-cards" aria-expanded="${index === 0}">
        <span class="week-name">${index === 0 ? 'This week' : `Week ${index + 1}`}<span class="week-dates">${shortDate.format(asUTC(week.start))} – ${longDate.format(asUTC(week.end))}</span></span>
        <span class="amount-block in"><span>Money in</span><b>+${money.format(week.income)}</b></span>
        <span class="amount-block out"><span>Money out</span><b>−${money.format(week.expenses)}</b></span>
        <span class="amount-block card"><span>Card charges</span><b>${money.format(week.card_charges)}</b></span>
        <span class="amount-block"><span>Week ending</span><b class="close-balance ${week.closing_balance < 0 ? 'negative' : ''}">${money.format(week.closing_balance)}</b></span>
        <span class="chevron">⌄</span>
      </button><div class="event-list">${events}</div>
    </article>`;
  }).join('');
}

function populateFundingOptions() {
  const select = $('#fundingAccount');
  const selected = select.value;
  select.innerHTML = '<option value="checking">Checking</option>' + state.credit_lines.map(card => `<option value="credit:${card.id}">${escapeHTML(card.name)}</option>`).join('');
  if ([...select.options].some(option => option.value === selected)) select.value = selected;
  const target = $('#paymentTarget');
  const selectedTarget = target.value;
  target.innerHTML = '<option value="none">Regular expense — no card balance reduction</option>' + state.credit_lines.map(card => `<option value="credit:${card.id}">Pay down ${escapeHTML(card.name)}</option>`).join('');
  if ([...target.options].some(option => option.value === selectedTarget)) target.value = selectedTarget;
}

function updateFundingField() {
  const form = $('#itemForm');
  const expense = form.elements.kind.value === 'expense';
  const hasTarget = form.elements.payment_target.value !== 'none';
  $$('.expense-target', form).forEach(el => el.classList.toggle('hidden', !expense));
  $$('.expense-funding', form).forEach(el => el.classList.toggle('hidden', !(expense && !hasTarget)));
  if (hasTarget) form.elements.funding_account.value = 'checking';
}

function renderLists() {
  const incomes = state.recurring.filter(item => item.kind === 'income');
  const expenses = state.recurring.filter(item => item.kind === 'expense');
  $('#incomeCount').textContent = `${incomes.length} item${incomes.length === 1 ? '' : 's'}`;
  $('#expenseCount').textContent = `${expenses.length} item${expenses.length === 1 ? '' : 's'}`;
  $('#incomeList').innerHTML = renderPlanItems(incomes, 'recurring');
  $('#expenseList').innerHTML = renderPlanItems(expenses, 'recurring');
  $('#transactionList').innerHTML = renderPlanItems(state.transactions, 'transaction');
}

function renderPlanItems(items, type) {
  if (!items.length) return '<div class="empty-state">Nothing here yet. Add an item to begin.</div>';
  return items.map(item => {
    const targetCard = state.credit_lines.find(card => card.id === item.destination_credit_line_id)?.name;
    const account = item.kind === 'expense' ? ` · ${targetCard ? `payment to ${escapeHTML(targetCard)}` : item.funding_source === 'credit' ? `on ${escapeHTML(state.credit_lines.find(card => card.id === item.credit_line_id)?.name || 'Credit card')}` : 'from Checking'}` : '';
    const meta = type === 'recurring' ? `${scheduleLabel(item)} · starts ${shortDate.format(asUTC(item.start_date))}${account}${item.active ? '' : ' · paused'}` : `${longDate.format(asUTC(item.date))} · ${item.status}${account}`;
    return `<article class="plan-item ${item.active === 0 ? 'inactive' : ''}">
      <div><div class="plan-item-name">${escapeHTML(item.name)}</div><div class="plan-item-meta">${meta}</div></div>
      ${type === 'transaction' ? `<div class="plan-item-meta">${escapeHTML(item.note || item.source.replace('_', ' '))}</div>` : ''}
      <div class="plan-item-amount ${item.kind}">${signed(item.amount, item.kind)}</div>
      ${itemActionMenu(type, item)}
    </article>`;
  }).join('');
}

function itemActionMenu(type, item) {
  return `<div class="item-menu"><button class="kebab" type="button" aria-label="Actions for ${escapeHTML(item.name)}" aria-haspopup="menu">•••</button><div class="action-menu" role="menu"><button type="button" role="menuitem" data-item-action="edit" data-item-type="${type}" data-id="${item.id}">Edit</button><button type="button" role="menuitem" class="danger" data-item-action="delete" data-item-type="${type}" data-id="${item.id}">Delete</button></div></div>`;
}

function switchView(view) {
  state.view = view;
  $$('.view').forEach(panel => panel.classList.toggle('hidden', panel.dataset.viewPanel !== view));
  $$('.tab').forEach(tab => tab.classList.toggle('active', tab.dataset.view === view));
  if (view === 'calendar') loadCalendar().catch(error => toast(error.message, true));
  if (view === 'cards') renderCards();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function openItemDialog(type, item = null) {
  const form = $('#itemForm'); form.reset();
  form.elements.item_type.value = type;
  form.elements.id.value = item?.id || '';
  const recurring = type === 'recurring';
  $$('.recurring-only', form).forEach(el => el.classList.toggle('hidden', !recurring));
  $$('.transaction-only', form).forEach(el => el.classList.toggle('hidden', recurring));
  $('#dialogEyebrow').textContent = item ? 'UPDATE PLAN ITEM' : 'NEW PLAN ITEM';
  $('#dialogTitle').textContent = `${item ? 'Edit' : 'Add'} ${recurring ? 'recurring' : 'one-time'} item`;
  const today = localISODate();
  if (item) {
    for (const [key, value] of Object.entries(item)) {
      if (!form.elements[key]) continue;
      if (form.elements[key].type === 'checkbox') form.elements[key].checked = Boolean(value);
      else form.elements[key].value = value ?? '';
    }
    form.elements.funding_account.value = item.funding_source === 'credit' ? `credit:${item.credit_line_id}` : 'checking';
    form.elements.payment_target.value = item.destination_credit_line_id ? `credit:${item.destination_credit_line_id}` : 'none';
  } else {
    form.elements.kind.value = 'expense';
    form.elements.start_date.value = today;
    form.elements.date.value = today;
    form.elements.schedule_type.value = 'interval';
    form.elements.frequency.value = 'monthly';
    form.elements.status.value = 'planned';
    form.elements.active.checked = true;
    form.elements.funding_account.value = 'checking';
    form.elements.payment_target.value = 'none';
  }
  updateScheduleFields();
  updateFundingField();
  $('#itemDialog').showModal();
}

async function saveItem(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form));
  const type = data.item_type;
  data.amount = Number(data.amount);
  data.active = form.elements.active.checked;
  const target = data.payment_target || 'none';
  data.destination_credit_line_id = target.startsWith('credit:') ? Number(target.split(':')[1]) : null;
  const funding = data.destination_credit_line_id ? 'checking' : data.funding_account || 'checking';
  data.funding_source = funding.startsWith('credit:') ? 'credit' : 'checking';
  data.credit_line_id = funding.startsWith('credit:') ? Number(funding.split(':')[1]) : null;
  const route = type === 'recurring' ? 'recurring' : 'transactions';
  try {
    await api(`/api/${route}${data.id ? `/${data.id}` : ''}`, { method: data.id ? 'PUT' : 'POST', body: JSON.stringify(data) });
    $('#itemDialog').close();
    await refreshAll();
    toast(`${data.name} saved`);
  } catch (error) { toast(error.message, true); }
}

async function refreshAll() {
  const data = await api('/api/bootstrap');
  Object.assign(state, data);
  populateFundingOptions();
  renderLists();
  await loadProjection();
  renderCards();
  if (state.view === 'calendar') await loadCalendar();
}

async function loadCalendar() {
  const month = state.calendarDate;
  const first = new Date(Date.UTC(month.getUTCFullYear(), month.getUTCMonth(), 1));
  const gridStart = new Date(first); gridStart.setUTCDate(1 - first.getUTCDay());
  const gridEnd = new Date(gridStart); gridEnd.setUTCDate(gridStart.getUTCDate() + 41);
  const balanceStart = asUTC(state.settings.balance_as_of);
  const balanceDays = Math.floor((gridEnd - balanceStart) / 86400000) + 1;
  const gridRequest = api(`/api/projection?start=${isoUTC(gridStart)}&weeks=6`);
  const balanceRequest = balanceDays > 0 && balanceDays <= 364
    ? api(`/api/projection?start=${isoUTC(balanceStart)}&weeks=${Math.ceil(balanceDays / 7)}`)
    : Promise.resolve(null);
  [state.calendarProjection, state.calendarBalanceProjection] = await Promise.all([gridRequest, balanceRequest]);
  renderCalendar(gridStart);
}

function renderCalendar(gridStart) {
  const month = state.calendarDate;
  $('#calendarMonth').textContent = new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(month);
  const eventsByDate = {};
  state.calendarProjection.weeks.flatMap(week => week.events).forEach(event => (eventsByDate[event.date] ||= []).push(event));
  const balancesByDate = {};
  if (state.calendarBalanceProjection) {
    const balanceEvents = {};
    state.calendarBalanceProjection.weeks.flatMap(week => week.events).forEach(event => (balanceEvents[event.date] ||= []).push(event));
    let runningChecking = state.calendarBalanceProjection.starting_balance;
    const cursor = asUTC(state.calendarBalanceProjection.start);
    const gridEnd = new Date(gridStart); gridEnd.setUTCDate(gridStart.getUTCDate() + 41);
    while (cursor <= gridEnd) {
      const iso = isoUTC(cursor);
      runningChecking = Math.round((runningChecking + (balanceEvents[iso] || []).reduce((sum, event) => sum + event.signed_amount, 0)) * 100) / 100;
      if (cursor >= gridStart) balancesByDate[iso] = runningChecking;
      cursor.setUTCDate(cursor.getUTCDate() + 1);
    }
  }
  const today = localISODate();
  $('#calendarGrid').innerHTML = Array.from({ length: 42 }, (_, index) => {
    const day = new Date(gridStart); day.setUTCDate(gridStart.getUTCDate() + index);
    const iso = isoUTC(day); const events = eventsByDate[iso] || [];
    const outside = day.getUTCMonth() !== month.getUTCMonth();
    return `<article class="calendar-day ${outside ? 'outside' : ''} ${iso === today ? 'today' : ''}">
      <span class="day-number">${day.getUTCDate()}</span>
      <div class="day-events">${events.map(event => `<div class="calendar-event ${event.kind} ${event.funding_source === 'credit' ? 'credit' : ''} ${event.destination_credit_line_id ? 'payment' : ''}" title="${escapeHTML(event.name)} · ${money.format(event.amount)}"><span>${escapeHTML(event.name)}</span><b>${event.kind === 'income' ? '+' : '−'}${money.format(event.amount)}</b></div>`).join('')}</div>
      <div class="day-balance ${balancesByDate[iso] < 0 ? 'negative' : ''}" title="${balancesByDate[iso] == null ? `Balance projection begins ${state.settings.balance_as_of}` : `Projected end-of-day Checking balance: ${money.format(balancesByDate[iso])}`}"><span>Checking</span><b>${balancesByDate[iso] == null ? '—' : compactMoney.format(balancesByDate[iso])}</b></div>
    </article>`;
  }).join('');
}

function renderCards() {
  const cards = state.credit_lines;
  const debt = cards.reduce((sum, card) => sum + card.balance, 0);
  const limits = cards.reduce((sum, card) => sum + (card.credit_limit || 0), 0);
  const available = Math.max(0, limits - debt);
  const utilization = limits ? debt / limits * 100 : 0;
  $('#debtSummary').innerHTML = `<article><span>Total card debt</span><b>${money.format(debt)}</b></article><article><span>Available credit</span><b>${limits ? money.format(available) : '—'}</b></article><article><span>Utilization</span><b>${limits ? `${utilization.toFixed(1)}%` : '—'}</b></article>`;
  if (!cards.length) {
    $('#creditGrid').innerHTML = '<div class="empty-state credit-empty">No credit lines yet. Add Discover, Capital One, or another card to begin.</div>';
    return;
  }
  const projected = new Map((state.projection?.credit_lines || []).map(card => [card.id, card]));
  $('#creditGrid').innerHTML = cards.map(card => {
    const usage = card.credit_limit ? Math.min(100, card.balance / card.credit_limit * 100) : 0;
    const futureCard = projected.get(card.id);
    const futureCharges = futureCard?.scheduled_charges || 0;
    const futurePayments = futureCard?.scheduled_payments || 0;
    const projectedBalance = futureCard?.projected_balance ?? card.balance;
    return `<article class="credit-card">
      <div class="credit-card-top"><div><span>Credit line</span><h2>${escapeHTML(card.name)}</h2></div>${itemActionMenu('credit', card)}</div>
      <div class="credit-balance"><span>Current balance</span><b>${money.format(card.balance)}</b></div>
      ${card.credit_limit ? `<div class="util-track"><i style="width:${usage}%"></i></div><div class="credit-limit"><span>${usage.toFixed(1)}% used</span><span>${money.format(card.credit_limit)} limit</span></div>` : '<div class="credit-limit"><span>No limit entered</span></div>'}
      <div class="credit-forecast"><span>Scheduled charges +${money.format(futureCharges)}</span><span>Payments −${money.format(futurePayments)}</span></div>
      <div class="credit-facts"><span><small>Due</small><b>${card.due_day ? `Day ${card.due_day}` : '—'}</b></span><span><small>APR</small><b>${card.apr != null ? `${card.apr}%` : '—'}</b></span><span><small>In 12 weeks</small><b>${money.format(projectedBalance)}</b></span></div>
    </article>`;
  }).join('');
}

function openCreditDialog(card = null) {
  const form = $('#creditForm'); form.reset();
  form.elements.id.value = card?.id || '';
  $('#creditDialogTitle').textContent = `${card ? 'Edit' : 'Add'} credit line`;
  if (card) Object.entries(card).forEach(([key, value]) => { if (form.elements[key]) form.elements[key].value = value ?? ''; });
  else form.elements.balance.value = '0';
  $('#creditDialog').showModal();
}

async function saveCredit(event) {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.currentTarget));
  const id = data.id;
  try {
    await api(`/api/credit-lines${id ? `/${id}` : ''}`, { method: id ? 'PUT' : 'POST', body: JSON.stringify(data) });
    $('#creditDialog').close(); await refreshAll(); toast(`${data.name} saved`);
  } catch (error) { toast(error.message, true); }
}

async function manageCredit(id, action) {
  const card = state.credit_lines.find(item => item.id === Number(id)); if (!card) return;
  if (action === 'edit') openCreditDialog(card);
  if (action === 'delete' && confirm(`Delete ${card.name}? Linked charges will switch to Checking and linked payments will become regular expenses.`)) {
    try { await api(`/api/credit-lines/${id}`, { method: 'DELETE' }); await refreshAll(); toast(`${card.name} deleted`); }
    catch (error) { toast(error.message, true); }
  }
}

async function handleItemAction(type, id, action) {
  const list = type === 'recurring' ? state.recurring : state.transactions;
  const item = list.find(candidate => candidate.id === Number(id));
  if (!item) return;
  if (action === 'edit') openItemDialog(type, item);
  if (action === 'delete' && confirm(`Delete ${item.name}? This cannot be undone.`)) {
    try {
      await api(`/api/${type === 'recurring' ? 'recurring' : 'transactions'}/${id}`, { method: 'DELETE' });
      await refreshAll(); toast(`${item.name} deleted`);
    } catch (error) { toast(error.message, true); }
  }
}

function openBalanceDialog() {
  const form = $('#balanceForm');
  form.elements.current_balance.value = state.settings.current_balance;
  form.elements.balance_as_of.value = state.settings.balance_as_of;
  $('#balanceDialog').showModal();
}

async function saveBalance(event) {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.currentTarget));
  data.current_balance = Number(data.current_balance);
  try {
    state.settings = await api('/api/settings', { method: 'PUT', body: JSON.stringify(data) });
    $('#balanceDialog').close(); await loadProjection(); toast('Starting balance updated');
  } catch (error) { toast(error.message, true); }
}

let toastTimer;
function toast(message, error = false) {
  const el = $('#toast'); el.textContent = message; el.classList.toggle('error', error); el.classList.add('show');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove('show'), 3000);
}

document.addEventListener('click', event => {
  const close = event.target.closest('[data-dialog-close]'); if (close) { close.closest('dialog').close(); return; }
  const tab = event.target.closest('[data-view]'); if (tab) switchView(tab.dataset.view);
  const add = event.target.closest('[data-add-type]'); if (add) openItemDialog(add.dataset.addType);
  const action = event.target.closest('[data-item-action]');
  if (action) {
    if (action.dataset.itemType === 'credit') manageCredit(action.dataset.id, action.dataset.itemAction);
    else handleItemAction(action.dataset.itemType, action.dataset.id, action.dataset.itemAction);
  }
  const week = event.target.closest('.week-summary'); if (week) { const row = week.closest('.week-row'); row.classList.toggle('open'); week.setAttribute('aria-expanded', row.classList.contains('open')); }
});
$('#themeToggle').addEventListener('click', () => applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
$('#quickAdd').addEventListener('click', () => state.view === 'cards' ? openCreditDialog() : openItemDialog(state.view === 'one-time' ? 'transaction' : 'recurring'));
$('#adjustBalance').addEventListener('click', openBalanceDialog);
$('#forecastStart').addEventListener('change', () => loadProjection().catch(error => toast(error.message, true)));
$('#scheduleType').addEventListener('change', updateScheduleFields);
$('#paymentTarget').addEventListener('change', updateFundingField);
$$('input[name="kind"]', $('#itemForm')).forEach(input => input.addEventListener('change', updateFundingField));
$('#itemForm').addEventListener('submit', saveItem);
$('#balanceForm').addEventListener('submit', saveBalance);
$('#creditForm').addEventListener('submit', saveCredit);
$('#addCreditLine').addEventListener('click', () => openCreditDialog());
$('#previousMonth').addEventListener('click', () => { state.calendarDate.setUTCMonth(state.calendarDate.getUTCMonth() - 1); loadCalendar().catch(error => toast(error.message, true)); });
$('#nextMonth').addEventListener('click', () => { state.calendarDate.setUTCMonth(state.calendarDate.getUTCMonth() + 1); loadCalendar().catch(error => toast(error.message, true)); });
applyTheme(document.documentElement.dataset.theme);
load();

