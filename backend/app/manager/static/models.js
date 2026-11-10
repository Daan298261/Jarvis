// Models share RFC-0210's owner choices. API values are always rendered as text.
const root = document.querySelector('#models');
const make = (tag, text, cls) => { const node = document.createElement(tag); if (text != null) node.textContent = text; if (cls) node.className = cls; return node; };
const gib = n => n == null ? 'unknown' : `${(n / 1024).toFixed(1)} GB`;
let working = false, revision = 0, profiles = [], snapshot = {}, telemetry = {};
const status = root.querySelector('[role=status]'), list = root.querySelector('.model-servers');
const picker = root.querySelector('[name=profile_id]'), form = root.querySelector('form');
const note = root.querySelector('.profile-note'), warning = root.querySelector('.model-warning');

async function api(path, body) {
  const options = {};
  if (body !== undefined) {
    const session = await fetch('/api/manager/v1/session').then(r => r.json());
    options.method = 'POST';
    options.headers = {'content-type': 'application/json', [session.header]: session.token};
    options.body = JSON.stringify(body);
  }
  const response = await fetch('/api/manager/v1/models' + path, options);
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : JSON.stringify(value.detail));
  return value;
}

function updateButtons() {
  root.querySelectorAll('button').forEach(b => { b.disabled = working || b.dataset.requiresCore === 'true' && !snapshot.core_available; });
  root.setAttribute('aria-busy', String(working));
}

function profileChanged() {
  const profile = profiles.find(p => p.id === picker.value);
  if (!profile) { note.textContent = 'Scan to find downloaded models and configured launch profiles.'; return; }
  form.elements.context_size.value = profile.context_size;
  form.elements.context_size.max = profile.context_ceiling;
  note.textContent = profile.notes || '';
  for (const [field, values] of [['kv_cache', profile.kv_cache_options], ['flash_attention', profile.flash_attention_options]]) {
    const select = form.elements[field];
    select.replaceChildren(...values.map(v => { const option = make('option', v === 'server' ? 'Use server settings' : v); option.value = v; return option; }));
  }
  const moe = form.elements.n_cpu_moe;
  moe.closest('label').hidden = profile.n_cpu_moe == null;
  moe.value = profile.n_cpu_moe ?? '';
}

async function refresh(scan = false) {
  const started = revision;
  const value = await api(scan ? '/scan' : '', scan ? {} : undefined);
  const [catalog, gpu] = await Promise.all([api('/profiles'), api('/vram')]);
  if (started !== revision) return;
  snapshot = value; telemetry = gpu; profiles = catalog.profiles;
  const selected = picker.value;
  picker.replaceChildren(...profiles.map(p => { const o = make('option', p.label || p.model); o.value = p.id; return o; }));
  picker.value = profiles.some(p => p.id === selected) ? selected : profiles[0]?.id || '';
  if (!selected || picker.value !== selected) profileChanged();
  render();
}

function render() {
  const expanded = new Set([...list.querySelectorAll('article[data-port]')].filter(card => card.querySelector('details')?.open).map(card => card.dataset.port));
  const gpu = root.querySelector('.model-vram');
  gpu.textContent = telemetry.gpus?.length ? telemetry.gpus.map(g => `${g.name}: ${gib(g.used_mib)} used · ${gib(g.free_mib)} free of ${gib(g.total_mib)}`).join(' | ') : 'GPU memory information unavailable';
  const processes = telemetry.processes?.map(p => `${p.name} (PID ${p.pid}, ${gib(p.used_mib)})`).join('; ');
  root.querySelector('.gpu-processes').textContent = [processes, telemetry.warning].filter(Boolean).join('\n');
  warning.textContent = [...(snapshot.diagnostics || []), snapshot.error,
    !snapshot.core_available ? 'ANZU is stopped. Discovery and Ollama / LM Studio Stop are available. Start ANZU to load or select a model.' : ''].filter(Boolean).join('\n');
  list.replaceChildren();
  for (const server of snapshot.inventory || []) {
    const card = make('article', null, 'model-server');
    card.dataset.port = String(server.port);
    card.append(make('h3', server.kind), make('p', `${server.endpoint} · ${server.owner}${server.pid ? ` · PID ${server.pid}` : ''}`, 'model-meta'));
    const loaded = make('div');
    loaded.append(make('h4', server.verified_loaded ? 'Loaded models' : 'Advertised models · loading unverified'));
    const rows = (snapshot.servers || []).filter(r => r.port === server.port);
    if (!rows.length) loaded.append(make('p', 'No models loaded.'));
    for (const row of rows) {
      const item = make('div', null, 'model-item');
      const metadata = server.metadata?.[row.model] || {};
      item.append(make('strong', row.model + (row.active ? ' · In use by ANZU' : '')));
      const facts = [metadata.context_size ? `${metadata.context_size.toLocaleString()} context` : '',
        metadata.vram_bytes != null ? `${gib(metadata.vram_bytes / 1024 ** 2)} VRAM` : '',
        metadata.size_bytes != null ? `${gib(metadata.size_bytes / 1024 ** 2)} weights` : '',
        metadata.pinned ? 'Pinned (keep_alive -1): stays in VRAM until unloaded' : '',
        row.busy ? 'Another client is busy' : 'Other apps may be using this model'];
      item.append(make('p', facts.filter(Boolean).join(' · '), 'model-meta'));
      const actions = make('div', null, 'model-actions');
      const use = make('button', 'Use in ANZU'); use.dataset.requiresCore = 'true';
      use.onclick = () => choose(row, 'use');
      const native = ['ollama', 'lmstudio'].includes(row.backend);
      const stop = make('button', native ? 'Unload' : 'Stop', 'quiet');
      stop.title = native ? 'Unload from memory to free VRAM; the server keeps running' : 'Stop this verified server process';
      stop.onclick = () => choose(row, 'stop');
      if (row.can_stop && (snapshot.core_available || native)) actions.append(stop);
      if (!row.active) actions.prepend(use);
      item.append(actions); loaded.append(item);
    }
    card.append(loaded);
    const available = make('details'); available.append(make('summary', `Downloaded models (${server.available_models?.length || 0})`));
    available.open = expanded.has(String(server.port));
    for (const model of server.available_models || []) {
      const item = make('div', null, 'model-item'); item.append(make('strong', model.name));
      const profile = profiles.find(p => p.backend === server.backend && p.port === server.port && p.model === model.name);
      if (profile) { const b = make('button', 'Start…', 'quiet'); b.dataset.requiresCore = 'true'; b.onclick = () => { picker.value = profile.id; profileChanged(); form.scrollIntoView({behavior: 'smooth', block: 'center'}); picker.focus(); }; item.append(b); }
      available.append(item);
    }
    card.append(available); list.append(card);
  }
  if (!list.children.length) list.append(make('p', 'No external model servers found. Scan again after starting a server.'));
  updateButtons();
}

async function transaction(message, action) {
  if (working) return;
  revision += 1;
  working = true; status.textContent = message; updateButtons();
  try { const result = await action(); if (result === false) { status.textContent = 'Cancelled.'; return; } await refresh(); status.textContent = 'Done. Inventory refreshed.'; }
  catch (error) { status.textContent = error.message; }
  finally { working = false; updateButtons(); }
}

function choose(row, action) {
  const verb = action !== 'stop' ? 'Use' : ['ollama', 'lmstudio'].includes(row.backend) ? 'Unload' : 'Stop';
  if (!confirm(`${verb} ${row.model}? ${action === 'stop' ? 'Other apps may be using it.' : 'ANZU will switch its active backend.'}`)) return;
  return transaction(action === 'stop' ? `${verb === 'Unload' ? 'Unloading' : 'Stopping'} model…` : 'Connecting ANZU…', () => api(`/${row.id}/choice`, {action, confirm: true}));
}

picker.onchange = profileChanged;
root.querySelector('.model-scan').onclick = () => transaction('Scanning local model servers…', () => refresh(true));
form.onsubmit = event => {
  event.preventDefault();
  const body = Object.fromEntries(new FormData(form));
  body.context_size = Number(body.context_size);
  if (body.n_cpu_moe !== '') body.n_cpu_moe = Number(body.n_cpu_moe); else delete body.n_cpu_moe;
  transaction('Checking memory before starting…', async () => {
    const preview = await api('/start/preview', body);
    const lines = [`Start ${preview.profile.label || preview.profile.model}?`,
      `Estimated GPU memory: ${gib(preview.estimated_mib)}. Free: ${gib(preview.free_mib)}.`, preview.warning];
    if (preview.requires_confirmation) {
      lines.push('This may exceed free VRAM or the estimate is unknown. Proceed anyway?');
      const processes = preview.telemetry?.processes || [];
      if (processes.length) lines.push('Other GPU processes: ' + processes.slice(0, 8).map(p => `${p.name} (PID ${p.pid}, ${gib(p.used_mib)})`).join('; ') + (processes.length > 8 ? `; ${processes.length - 8} more in GPU details.` : ''));
    }
    if (preview.server_restart_required) lines.push('Ollama cache and flash attention are server settings. If they differ, Start will be refused until you configure and restart your server yourself.');
    if (!confirm(lines.join('\n\n'))) return false;
    status.textContent = 'Starting model… This can take a few minutes.';
    await api('/start', {...body, confirm: true, confirm_over_budget: preview.requires_confirmation});
  });
};
refresh(true).then(() => { status.textContent = 'Local inventory ready.'; }).catch(e => { status.textContent = e.message; });
setInterval(() => { if (!working && !document.hidden) refresh().catch(e => { status.textContent = e.message; }); }, 15000);
