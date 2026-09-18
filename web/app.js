let stores = {};
let currentAccesses = [];
let filteredAccesses = [];
let activeAccess = null;
let activeFilter = 'TODOS';
const API_BASE = String(window.QEIVISION_API_BASE || '').replace(/\/$/, '');

function apiUrl(path) {
  return `${API_BASE}${path}`;
}

document.addEventListener('DOMContentLoaded', async () => {
  const today = localDateValue(new Date());
  document.getElementById('input-desde').value = today;
  document.getElementById('input-hasta').value = today;
  bindEvents();
  await loadStores();
  await loadAudit();
});

function bindEvents() {
  const btnCargar = document.getElementById('btn-cargar');
  const selectTienda = document.getElementById('select-tienda');
  const inputDesde = document.getElementById('input-desde');
  const inputHasta = document.getElementById('input-hasta');
  const searchInput = document.getElementById('input-filtro-texto');

  btnCargar.addEventListener('click', loadAudit);

  // Requerimiento 2: Al hacer foco o posarse en Tienda, Desde o Hasta, borrar la lista previa
  // y dejar el botón activo para actualizar.
  const handleInputFocusOrChange = () => {
    resetAccessListForUpdate();
  };

  selectTienda.addEventListener('focus', handleInputFocusOrChange);
  selectTienda.addEventListener('change', handleInputFocusOrChange);
  inputDesde.addEventListener('focus', handleInputFocusOrChange);
  inputDesde.addEventListener('change', (e) => {
    keepDateRangeValid(e);
    handleInputFocusOrChange();
  });
  inputHasta.addEventListener('focus', handleInputFocusOrChange);
  inputHasta.addEventListener('change', (e) => {
    keepDateRangeValid(e);
    handleInputFocusOrChange();
  });

  // Enter en los inputs de fecha o tienda ejecuta Actualizar
  [selectTienda, inputDesde, inputHasta].forEach(element => {
    element.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        loadAudit();
      }
    });
  });

  searchInput.addEventListener('input', applyFilters);

  document.getElementById('ref-time')?.addEventListener('click', copyOnlyTime);
  document.getElementById('btn-scanned')?.addEventListener('click', toggleScannedProducts);

  document.querySelectorAll('.chip').forEach(chip => {
    chip.addEventListener('click', () => {
      document.querySelectorAll('.chip').forEach(item => item.classList.remove('active'));
      chip.classList.add('active');
      activeFilter = chip.dataset.filter;
      applyFilters();
    });
  });

  window.addEventListener('keydown', (e) => {
    if (['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName)) {
      if (e.key === 'Escape') {
        document.activeElement.blur();
      }
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      navigateAccess(1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      navigateAccess(-1);
    } else if (e.key === '/') {
      e.preventDefault();
      searchInput.focus();
    }
  });
}

function resetAccessListForUpdate() {
  currentAccesses = [];
  filteredAccesses = [];
  activeAccess = null;

  document.getElementById('badge-total-accesos').textContent = '0';
  document.querySelector('[data-filter="TODOS"]').textContent = 'Todos (0)';
  document.querySelector('.chip-compro').textContent = '✓ Compró (0)';
  document.querySelector('.chip-sin-compra').textContent = 'Sin compra (0)';

  document.getElementById('access-list-container').innerHTML =
    '<div class="list-placeholder">Pulsá <b>Actualizar</b> para consultar los ingresos del rango seleccionado.</div>';

  clearSelection();

  const button = document.getElementById('btn-cargar');
  button.disabled = false;
  document.getElementById('btn-cargar-label').textContent = 'Actualizar';
}

async function loadStores() {
  try {
    const response = await fetch(apiUrl('/api/tiendas'));
    const data = await response.json();
    if (!response.ok || data.status !== 'ok') throw new Error(data.message || 'No se pudieron cargar las tiendas.');
    stores = data.tiendas || {};
    const select = document.getElementById('select-tienda');
    select.innerHTML = Object.entries(stores).map(([key, store]) =>
      `<option value="${escapeHtml(key)}">${escapeHtml(key)} - ${escapeHtml(store.nombre)}</option>`
    ).join('');
    const savedStore = localStorage.getItem('qeivision-store');
    if (savedStore && stores[savedStore]) select.value = savedStore;
    else if (stores.HME) select.value = 'HME';
  } catch (error) {
    showListMessage(error.message, true);
  }
}

function keepDateRangeValid(event) {
  const from = document.getElementById('input-desde');
  const to = document.getElementById('input-hasta');
  if (!from.value || !to.value) return;
  if (event.target === from && from.value > to.value) to.value = from.value;
  if (event.target === to && to.value < from.value) from.value = to.value;
}

async function loadAudit() {
  const storeKey = document.getElementById('select-tienda').value;
  const from = document.getElementById('input-desde').value;
  const to = document.getElementById('input-hasta').value;
  if (!storeKey || !from || !to) return showToast('Completá la tienda y el rango de fechas.');
  if (from > to) return showToast('La fecha hasta no puede ser anterior a la fecha desde.');

  const button = document.getElementById('btn-cargar');
  button.disabled = true;
  document.getElementById('btn-cargar-label').textContent = 'Consultando…';
  showListMessage('Consultando los ingresos de AutoShop…');
  clearSelection();

  try {
    const params = new URLSearchParams({tienda: storeKey, desde: from, hasta: to});
    const response = await fetch(apiUrl(`/api/accesos?${params}`));
    const data = await response.json();
    if (!response.ok || data.status !== 'ok') throw new Error(data.message || 'No se pudieron cargar los ingresos.');
    currentAccesses = data.accesos || [];
    localStorage.setItem('qeivision-store', storeKey);
    updateFilterCounts();
    applyFilters();
    if (!currentAccesses.length) {
      showListMessage('No se registraron ingresos para esta tienda y rango.');
    } else if (filteredAccesses.length > 0) {
      selectAccess(filteredAccesses[0]);
    }
  } catch (error) {
    currentAccesses = [];
    filteredAccesses = [];
    updateFilterCounts();
    showListMessage(error.message, true);
  } finally {
    button.disabled = false;
    document.getElementById('btn-cargar-label').textContent = 'Actualizar';
  }
}

function applyFilters() {
  const query = document.getElementById('input-filtro-texto').value.toLowerCase().trim();
  let filtered = currentAccesses;
  if (activeFilter === 'COMPRO') filtered = filtered.filter(item => item.compro);
  if (activeFilter === 'SIN_COMPRA') filtered = filtered.filter(item => !item.compro);
  if (query) {
    filtered = filtered.filter(item => [item.usuario, item.dni, item.lote, item.hora, item.fecha]
      .some(value => String(value || '').toLowerCase().includes(query)));
  }
  filteredAccesses = filtered;
  renderAccessList(filteredAccesses);
}

function renderAccessList(accesses) {
  const container = document.getElementById('access-list-container');
  document.getElementById('badge-total-accesos').textContent = accesses.length;
  if (!accesses.length) {
    container.innerHTML = '<div class="list-placeholder">No hay registros para este filtro.</div>';
    return;
  }
  container.innerHTML = '';
  accesses.forEach(access => {
    const card = document.createElement('button');
    card.type = 'button';
    const isActive = Number(activeAccess?.id) === Number(access.id);
    card.className = `access-card ${isActive ? 'active' : ''}`;
    card.id = `card-access-${access.id}`;
    card.innerHTML = `
      <div class="card-top">
        <div><span class="card-date">${escapeHtml(formatDate(access.fecha))}</span><strong class="card-time">${escapeHtml(access.hora)}</strong></div>
        <span class="status-badge ${access.compro ? 'status-success' : 'status-warning'}">${access.compro ? '✓ Compró' : 'Sin compra'}</span>
      </div>
      <strong class="card-user">${escapeHtml(access.usuario)}</strong>
      <div class="card-meta"><span>Lote ${escapeHtml(access.lote)}</span><span>DNI ${escapeHtml(access.dni)}</span></div>`;
    card.addEventListener('click', () => selectAccess(access));
    container.appendChild(card);
  });
}

function updateFilterCounts() {
  const bought = currentAccesses.filter(item => item.compro).length;
  document.querySelector('[data-filter="TODOS"]').textContent = `Todos (${currentAccesses.length})`;
  document.querySelector('.chip-compro').textContent = `✓ Compró (${bought})`;
  document.querySelector('.chip-sin-compra').textContent = `Sin compra (${currentAccesses.length - bought})`;
}

function navigateAccess(direction) {
  if (!filteredAccesses.length) return;
  if (!activeAccess) {
    selectAccess(filteredAccesses[0]);
    return;
  }
  const currentIndex = filteredAccesses.findIndex(item => Number(item.id) === Number(activeAccess.id));
  if (currentIndex === -1) {
    selectAccess(filteredAccesses[0]);
    return;
  }
  const newIndex = currentIndex + direction;
  if (newIndex >= 0 && newIndex < filteredAccesses.length) {
    selectAccess(filteredAccesses[newIndex]);
    const card = document.getElementById(`card-access-${filteredAccesses[newIndex].id}`);
    if (card) {
      card.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }
}

async function selectAccess(access) {
  activeAccess = access;

  // Resaltar en la lista
  document.querySelectorAll('.access-card').forEach(card => card.classList.remove('active'));
  const activeCard = document.getElementById(`card-access-${access.id}`);
  if (activeCard) activeCard.classList.add('active');

  // Requerimiento 1: Ocultar empty-state completamente y mostrar audit-detail arriba sin espacios
  document.getElementById('empty-state').hidden = true;
  document.getElementById('audit-detail').hidden = false;
  document.querySelector('.detail-panel').scrollTop = 0;

  document.getElementById('avatar-user').textContent = (access.usuario || 'U').charAt(0).toUpperCase();
  document.getElementById('selected-user').textContent = access.usuario;
  setStatus(document.getElementById('selected-status'), access.compro);
  const scanButton = document.getElementById('btn-scanned');
  scanButton.classList.remove('active');
  document.getElementById('scan-card').hidden = true;
  await loadTicket(access);
}

async function toggleScannedProducts() {
  const button = document.getElementById('btn-scanned');
  const card = document.getElementById('scan-card');
  if (!card.hidden) {
    card.hidden = true;
    button.classList.remove('active');
    return;
  }
  const tbody = document.getElementById('tbody-escaneados');
  card.hidden = false;
  button.classList.add('active');
  tbody.innerHTML = '<tr><td colspan="3" class="loading-cell">Consultando movimientos del carrito…</td></tr>';
  try {
    const params = new URLSearchParams({ usuario_id: activeAccess.usuario_id, fecha: activeAccess.fecha });
    const response = await fetch(apiUrl(`/api/logs-carritos?${params}`));
    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('application/json')) {
      throw new Error('La API todavía no tiene publicado el endpoint de movimientos de carrito.');
    }
    const data = await response.json();
    if (!response.ok || data.status !== 'ok') throw new Error(data.message || 'No se pudieron cargar los productos escaneados.');
    tbody.innerHTML = data.productos.length ? data.productos.map(item => `
      <tr><td class="mono-muted">${escapeHtml(item.hora)}</td><td class="product-name">${escapeHtml(item.producto)}</td><td class="scan-action ${item.accion === 'Quitó' ? 'removed' : ''}">${escapeHtml(item.accion)}</td></tr>`).join('')
      : '<tr><td colspan="3" class="empty-cell">No hay movimientos de carrito para este ingreso.</td></tr>';
  } catch (error) {
    tbody.innerHTML = `<tr><td colspan="3" class="error-cell">${escapeHtml(error.message)}</td></tr>`;
  }
}

async function loadTicket(access) {
  const tbody = document.getElementById('tbody-abonados');
  document.getElementById('purchase-table-container').hidden = false;
  document.getElementById('no-purchase-state').hidden = true;
  tbody.innerHTML = '<tr><td colspan="4" class="loading-cell">Consultando ticket en AutoShop…</td></tr>';
  document.getElementById('badge-purchase-status').textContent = 'Consultando…';
  document.getElementById('badge-total-ticket').textContent = '$0,00';

  try {
    const params = new URLSearchParams({usuario_id: access.usuario_id, fecha: access.fecha});
    const response = await fetch(apiUrl(`/api/auditoria?${params}`));
    const data = await response.json();
    if (!response.ok || data.status !== 'ok') throw new Error(data.message || 'No se pudo cargar el ticket.');
    renderTicket(data.auditoria);
  } catch (error) {
    tbody.innerHTML = `<tr><td colspan="4" class="error-cell">${escapeHtml(error.message)}</td></tr>`;
    document.getElementById('badge-purchase-status').textContent = 'Error de consulta';
  }
}

function renderTicket(audit) {
  const tbody = document.getElementById('tbody-abonados');
  const table = document.getElementById('purchase-table-container');
  const noPurchase = document.getElementById('no-purchase-state');
  const status = document.getElementById('badge-purchase-status');
  tbody.innerHTML = '';

  // Requerimiento 3: Mensaje explícito cuando el usuario abrió la puerta y no compró
  if (!audit.compro || !audit.tickets.length) {
    table.hidden = true;
    noPurchase.hidden = false;
    setStatus(status, false, 'Sin compra');
    document.getElementById('badge-total-ticket').textContent = '$0,00';
    return;
  }

  table.hidden = false;
  noPurchase.hidden = true;
  setStatus(status, true, '✓ Compra registrada');
  document.getElementById('badge-total-ticket').textContent = formatMoney(audit.total_abonado);

  audit.tickets.forEach(ticket => ticket.items.forEach(item => {
    const row = document.createElement('tr');
    row.innerHTML = `
      <td class="mono-muted">${escapeHtml(ticket.hora)}</td>
      <td class="product-name">${escapeHtml(item.producto)}</td>
      <td class="quantity-cell">${formatQuantity(item.cantidad)}</td>
      <td class="money-cell">${formatMoney(item.subtotal)}</td>
    `;
    tbody.appendChild(row);
  }));
}

function setStatus(element, bought, text) {
  element.className = `status-badge ${bought ? 'status-success' : 'status-warning'}`;
  element.textContent = text || (bought ? '✓ Compró' : 'Sin compra');
}

function clearSelection() {
  activeAccess = null;
  document.getElementById('empty-state').hidden = false;
  document.getElementById('audit-detail').hidden = true;
  document.getElementById('scan-card').hidden = true;
}

async function copyOnlyTime() {
  if (!activeAccess?.hora) return;
  try {
    await navigator.clipboard.writeText(activeAccess.hora);
    showToast(`Hora copiada: ${activeAccess.hora}`);
  } catch {
    showToast('No se pudo copiar la hora.');
  }
}

async function copyDateTime() {
  if (!activeAccess) return;
  const value = `${formatDate(activeAccess.fecha)} ${activeAccess.hora}`;
  try {
    await navigator.clipboard.writeText(value);
    showToast(`Fecha y hora copiadas: ${value}`);
  } catch {
    showToast('No se pudo copiar.');
  }
}

async function copyFullReference() {
  if (!activeAccess) return;
  const storeKey = document.getElementById('select-tienda').value;
  const value = `${storeKey} | ${formatDate(activeAccess.fecha)} | ${activeAccess.hora}`;
  try {
    await navigator.clipboard.writeText(value);
    showToast(`Referencia copiada: ${value}`);
  } catch {
    showToast('No se pudo copiar la referencia.');
  }
}

function showListMessage(message, isError = false) {
  document.getElementById('access-list-container').innerHTML =
    `<div class="list-placeholder ${isError ? 'error-cell' : ''}">${escapeHtml(message)}</div>`;
  document.getElementById('badge-total-accesos').textContent = '0';
}

let toastTimer;
function showToast(message) {
  const toast = document.getElementById('toast');
  toast.textContent = message;
  toast.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('visible'), 2200);
}

function formatDate(value) {
  const day = String(value || '').slice(0, 10);
  const [year, month, date] = day.split('-');
  return year && month && date ? `${date}/${month}/${year}` : '—';
}

function localDateValue(date) {
  return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, '0'), String(date.getDate()).padStart(2, '0')].join('-');
}

function formatMoney(value) {
  return new Intl.NumberFormat('es-AR', {style: 'currency', currency: 'ARS'}).format(Number(value || 0));
}

function formatQuantity(value) {
  const number = Number(value || 0);
  return Number.isInteger(number) ? String(number) : number.toFixed(2);
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, character => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'})[character]);
}
