const qs = (id) => document.getElementById(id);
const screens = ['authScreen', 'wizardScreen', 'appShell'];
let testedFingerprint = null;

function showScreen(id) {
  screens.forEach((name) => qs(name).classList.toggle('hidden', name !== id));
}

function showResult(el, message, ok = false) {
  el.className = `result ${ok ? 'success' : 'error'}`;
  el.textContent = message;
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    credentials: 'same-origin',
    headers: {'Content-Type': 'application/json', ...(options.headers || {})},
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
}

function servicePayload() {
  return {
    name: qs('wizardName').value.trim(),
    kind: qs('wizardKind').value,
    url: qs('wizardUrl').value.trim(),
    api_key: qs('wizardApiKey').value.trim(),
  };
}

function fingerprint(payload) {
  return JSON.stringify(payload);
}

function resetServiceTest() {
  testedFingerprint = null;
  qs('wizardAdd').disabled = true;
  qs('wizardResult').className = 'result hidden';
}

function prepareNextService() {
  qs('wizardName').value = '';
  qs('wizardUrl').value = '';
  qs('wizardApiKey').value = '';
  resetServiceTest();
  qs('wizardName').focus();
}

async function loadInstances(target = 'both') {
  const data = await api('/api/instances');
  const items = data.items || [];
  qs('connectedCount').textContent = items.length;
  qs('wizardCount').textContent = `${items.length} added`;
  qs('finishWizard').disabled = items.length === 0;

  const card = (item, removable = false) => `
    <div class="service-item">
      <div>
        <strong>${escapeHtml(item.name)}</strong>
        <span>${item.kind.toUpperCase()} · ${escapeHtml(item.url)}</span>
        <small>Version ${escapeHtml(item.version || 'unknown')} · ${escapeHtml(item.os_name || 'unknown')}</small>
      </div>
      ${removable ? `<button class="danger-button" data-delete="${item.id}">Remove</button>` : '<span class="status-dot">Connected</span>'}
    </div>`;

  if (target === 'both' || target === 'wizard') {
    qs('wizardServices').classList.toggle('empty-state', items.length === 0);
    qs('wizardServices').innerHTML = items.length ? items.map((i) => card(i, true)).join('') : 'No services added yet.';
  }
  if (target === 'both' || target === 'app') {
    qs('instanceList').innerHTML = items.length ? items.map((i) => card(i, false)).join('') : '<div class="empty-state">No services configured.</div>';
  }
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
}

async function bootstrap() {
  try {
    const status = await api('/api/setup/status');
    if (!status.configured) {
      qs('authTitle').textContent = 'Welcome to ArrMedic';
      qs('authSubtitle').textContent = 'Create the administrator account for this ArrMedic installation.';
      qs('setupForm').classList.remove('hidden');
      qs('loginForm').classList.add('hidden');
      showScreen('authScreen');
      return;
    }
    if (!status.authenticated) {
      qs('authTitle').textContent = 'Sign in to ArrMedic';
      qs('authSubtitle').textContent = 'Use the administrator account created during setup.';
      qs('setupForm').classList.add('hidden');
      qs('loginForm').classList.remove('hidden');
      showScreen('authScreen');
      return;
    }
    await loadInstances('both');
    showScreen('appShell');
    checkApi();
  } catch (error) {
    showScreen('authScreen');
    showResult(qs('authResult'), error.message);
  }
}

qs('setupForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const payload = {
    username: qs('setupUsername').value.trim(),
    password: qs('setupPassword').value,
    confirm_password: qs('setupPassword2').value,
  };
  try {
    await api('/api/setup/admin', {method: 'POST', body: JSON.stringify(payload)});
    showScreen('wizardScreen');
    await loadInstances('wizard');
  } catch (error) {
    showResult(qs('authResult'), error.message);
  }
});

qs('loginForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    await api('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({username: qs('loginUsername').value.trim(), password: qs('loginPassword').value}),
    });
    await loadInstances('both');
    showScreen('appShell');
    checkApi();
  } catch (error) {
    showResult(qs('authResult'), error.message);
  }
});

['wizardName', 'wizardKind', 'wizardUrl', 'wizardApiKey'].forEach((id) => qs(id).addEventListener('input', resetServiceTest));
qs('wizardKind').addEventListener('change', () => {
  const defaults = {sonarr:8989, radarr:7878, prowlarr:9696, lidarr:8686, readarr:8787, whisparr:6969};
  const kind = qs('wizardKind').value;
  qs('wizardName').value = `${kind.charAt(0).toUpperCase() + kind.slice(1)} Main`;
  qs('wizardUrl').placeholder = `http://${kind}:${defaults[kind] || 80}`;
  resetServiceTest();
});

qs('wizardTest').addEventListener('click', async () => {
  const payload = servicePayload();
  const button = qs('wizardTest');
  button.disabled = true;
  button.textContent = 'Testing…';
  try {
    const data = await api('/api/instances/test', {method:'POST', body:JSON.stringify(payload)});
    testedFingerprint = fingerprint(payload);
    qs('wizardAdd').disabled = false;
    showResult(qs('wizardResult'), `✓ Connected to ${data.appName} ${data.version} on ${data.osName}`, true);
  } catch (error) {
    testedFingerprint = null;
    qs('wizardAdd').disabled = true;
    showResult(qs('wizardResult'), `✕ ${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = 'Test connection';
  }
});

qs('wizardServiceForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const payload = servicePayload();
  if (fingerprint(payload) !== testedFingerprint) {
    showResult(qs('wizardResult'), 'Please test this connection again before adding it.');
    qs('wizardAdd').disabled = true;
    return;
  }
  const button = qs('wizardAdd');
  button.disabled = true;
  button.textContent = 'Adding…';
  try {
    const data = await api('/api/instances', {method:'POST', body:JSON.stringify(payload)});
    showResult(qs('wizardResult'), `✓ ${payload.name} added successfully (${data.version})`, true);
    await loadInstances('wizard');
    setTimeout(prepareNextService, 550);
  } catch (error) {
    showResult(qs('wizardResult'), `✕ ${error.message}`);
    button.disabled = false;
  } finally {
    button.textContent = 'Add service';
  }
});

qs('wizardServices').addEventListener('click', async (event) => {
  const button = event.target.closest('[data-delete]');
  if (!button) return;
  try {
    await api(`/api/instances/${button.dataset.delete}`, {method:'DELETE'});
    await loadInstances('wizard');
  } catch (error) {
    showResult(qs('wizardResult'), error.message);
  }
});

qs('finishWizard').addEventListener('click', async () => {
  await loadInstances('both');
  showScreen('appShell');
  checkApi();
});

qs('addMoreButton').addEventListener('click', async () => {
  prepareNextService();
  await loadInstances('wizard');
  showScreen('wizardScreen');
});

qs('logoutButton').addEventListener('click', async () => {
  await api('/api/auth/logout', {method:'POST'});
  window.location.reload();
});

async function checkApi() {
  try {
    const data = await api('/api/health');
    qs('apiStatus').textContent = `${data.name} API healthy`;
    qs('apiStatus').classList.add('ok');
  } catch (_) {
    qs('apiStatus').textContent = 'API unavailable';
  }
}

bootstrap();
