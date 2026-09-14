const apiStatus = document.getElementById('apiStatus');
const form = document.getElementById('instanceForm');
const result = document.getElementById('result');
const button = document.getElementById('testButton');
const connectedCount = document.getElementById('connectedCount');
let connected = 0;

async function checkApi() {
  try {
    const response = await fetch('/api/health');
    if (!response.ok) throw new Error('API unavailable');
    const data = await response.json();
    apiStatus.textContent = `${data.name} API healthy`;
    apiStatus.classList.add('ok');
  } catch (_) {
    apiStatus.textContent = 'API unavailable';
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  result.className = 'result hidden';
  button.disabled = true;
  button.textContent = 'Testing…';

  const payload = {
    kind: document.getElementById('kind').value,
    url: document.getElementById('url').value,
    api_key: document.getElementById('apiKey').value,
  };

  try {
    const response = await fetch('/api/instances/test', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Connection failed');

    connected += 1;
    connectedCount.textContent = connected;
    result.className = 'result success';
    result.innerHTML = `<strong>✓ Connected to ${data.appName}</strong><br>Version ${data.version} · ${data.osName} · Runtime ${data.runtimeVersion}`;
  } catch (error) {
    result.className = 'result error';
    result.textContent = `✕ ${error.message}`;
  } finally {
    document.getElementById('apiKey').value = '';
    button.disabled = false;
    button.textContent = 'Test connection';
  }
});

checkApi();
