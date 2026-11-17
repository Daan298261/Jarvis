// Emergency controls deliberately do not depend on core health or model APIs.
const root = document.querySelector('#model-processes');
const list = root.querySelector('.process-list');
const status = root.querySelector('[role=status]');
const scan = root.querySelector('button');
let busy = false, refreshing = false;
const make = (tag, text, cls) => {
  const node = document.createElement(tag);
  node.textContent = text;
  if (cls) node.className = cls;
  return node;
};

async function request(path = '', body) {
  const options = {};
  if (body) {
    const response = await fetch('/api/manager/v1/session');
    if (!response.ok) throw new Error('Manager session unavailable.');
    const session = await response.json();
    options.method = 'POST';
    options.headers = {'content-type': 'application/json', [session.header]: session.token};
    options.body = JSON.stringify(body);
  }
  const response = await fetch('/api/manager/v1/model-processes' + path, options);
  const value = await response.json();
  if (!response.ok) throw new Error(value.detail || 'Process monitor unavailable.');
  return value;
}

function render(value) {
  root.querySelector('.process-warning').textContent = value.warning;
  list.replaceChildren();
  for (const row of value.processes) {
    const card = make('article', '', 'model-server');
    card.append(make('h3', row.model || row.kind));
    const ram = row.rss_bytes == null ? 'RAM unavailable' : `${(row.rss_bytes / 1024 ** 3).toFixed(2)} GB RAM`;
    card.append(make('p', `${row.name} · PID ${row.pid} · ${row.status} · ${ram}`, 'model-meta'));
    if (row.error) card.append(make('p', row.error, 'model-warning'));
    const kill = make('button', 'Hard kill', 'danger');
    kill.disabled = busy || !row.can_kill;
    kill.setAttribute('aria-label', `Hard kill ${row.model || row.kind} PID ${row.pid}`);
    kill.onclick = () => hardKill(row);
    card.append(kill);
    list.append(card);
  }
  if (!value.processes.length) list.append(make('p', 'No recognized model processes found.'));
}

async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try { render(await request()); }
  finally { refreshing = false; }
}

async function hardKill(row) {
  if (busy) return;
  if (!confirm(`Hard kill ${row.model || row.kind} (${row.name}, PID ${row.pid})?\n\nActive requests will fail. If this server hosts several models, all of them will stop. Its parent application may restart it.`)) return;
  busy = true;
  root.setAttribute('aria-busy', 'true');
  root.querySelectorAll('button').forEach(button => { button.disabled = true; });
  status.textContent = `Killing PID ${row.pid}…`;
  try {
    await request(`/${row.id}/kill`, {confirm: true});
    status.textContent = `PID ${row.pid} exited.`;
  } catch (error) {
    status.textContent = error.message;
  } finally {
    busy = false;
    root.setAttribute('aria-busy', 'false');
    scan.disabled = false;
    try { await refresh(); }
    catch (error) { status.textContent += ` Refresh failed: ${error.message}`; }
  }
}

scan.onclick = () => refresh().catch(error => { status.textContent = error.message; });
refresh().catch(error => { status.textContent = error.message; });
setInterval(() => {
  if (!busy && !document.hidden) refresh().catch(error => { status.textContent = error.message; });
}, 5000);
