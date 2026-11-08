const state = { settings: null, recurring: [], transactions: [], projection: null, view: 'forecast' };
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const money = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });
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
    $('#forecastStart').value = localISODate();
    await loadProjection();
    renderLists();
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
      <span><b>${escapeHTML(event.name)}</b><br><span class="event-source">${event.source === 'recurring' ? 'Recurring' : event.status}</span></span>
      <b class="event-amount ${event.kind}">${signed(event.amount, event.kind)}</b>
    </div>`).join('') || '<div class="empty-week">No planned activity this week.</div>';
    return `<article class="week-row ${index === 0 ? 'open' : ''}">
      <button class="week-summary" aria-expanded="${index === 0}">
        <span class="week-name">${index === 0 ? 'This week' : `Week ${index + 1}`}<span class="week-dates">${shortDate.format(asUTC(week.start))} – ${longDate.format(asUTC(week.end))}</span></span>
        <span class="amount-block in"><span>Money in</span><b>+${money.format(week.income)}</b></span>
        <span class="amount-block out"><span>Money out</span><b>−${money.format(week.expenses)}</b></span>
        <span class="amount-block"><span>Week ending</span><b class="close-balance ${week.closing_balance < 0 ? 'negative' : ''}">${money.format(week.closing_balance)}</b></span>
        <span class="chevron">⌄</span>
      </button><div class="event-list">${events}</div>
    </article>`;
  }).join('');
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
    const meta = type === 'recurring' ? `${scheduleLabel(item)} · starts ${shortDate.format(asUTC(item.start_date))}${item.active ? '' : ' · paused'}` : `${longDate.format(asUTC(item.date))} · ${item.status}`;
    return `<article class="plan-item ${item.active === 0 ? 'inactive' : ''}">
      <div><div class="plan-item-name">${escapeHTML(item.name)}</div><div class="plan-item-meta">${meta}</div></div>
      ${type === 'transaction' ? `<div class="plan-item-meta">${escapeHTML(item.note || item.source.replace('_', ' '))}</div>` : ''}
      <div class="plan-item-amount ${item.kind}">${signed(item.amount, item.kind)}</div>
      <button class="kebab" data-menu-type="${type}" data-id="${item.id}" aria-label="Edit ${escapeHTML(item.name)}">•••</button>
    </article>`;
  }).join('');
}

function switchView(view) {
  state.view = view;
  $$('.view').forEach(panel => panel.classList.toggle('hidden', panel.dataset.viewPanel !== view));
  $$('.tab').forEach(tab => tab.classList.toggle('active', tab.dataset.view === view));
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
  } else {
    form.elements.kind.value = 'expense';
    form.elements.start_date.value = today;
    form.elements.date.value = today;
    form.elements.schedule_type.value = 'interval';
    form.elements.frequency.value = 'monthly';
    form.elements.status.value = 'planned';
    form.elements.active.checked = true;
  }
  updateScheduleFields();
  $('#itemDialog').showModal();
}

async function saveItem(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form));
  const type = data.item_type;
  data.amount = Number(data.amount);
  data.active = form.elements.active.checked;
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
  renderLists();
  await loadProjection();
}

async function editOrDelete(type, id) {
  const list = type === 'recurring' ? state.recurring : state.transactions;
  const item = list.find(candidate => candidate.id === Number(id));
  if (!item) return;
  const action = prompt(`Type “edit” to change ${item.name}, or “delete” to remove it.`)?.trim().toLowerCase();
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
  const menu = event.target.closest('[data-menu-type]'); if (menu) editOrDelete(menu.dataset.menuType, menu.dataset.id);
  const week = event.target.closest('.week-summary'); if (week) { const row = week.closest('.week-row'); row.classList.toggle('open'); week.setAttribute('aria-expanded', row.classList.contains('open')); }
});
$('#themeToggle').addEventListener('click', () => applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
$('#quickAdd').addEventListener('click', () => openItemDialog(state.view === 'one-time' ? 'transaction' : 'recurring'));
$('#adjustBalance').addEventListener('click', openBalanceDialog);
$('#forecastStart').addEventListener('change', () => loadProjection().catch(error => toast(error.message, true)));
$('#scheduleType').addEventListener('change', updateScheduleFields);
$('#itemForm').addEventListener('submit', saveItem);
$('#balanceForm').addEventListener('submit', saveBalance);
applyTheme(document.documentElement.dataset.theme);
load();

