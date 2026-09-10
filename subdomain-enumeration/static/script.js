/**
 * Subdomain Enumeration Tool - client-side logic
 *
 * Flow: submit domain -> POST /scan (starts a background job) ->
 * poll GET /scan/status/<job_id> every ~700ms -> update progress bar
 * and results table until the job status is "done" or "error".
 *
 * All real validation and DNS work happens server-side in Python;
 * this file only handles UX (light client-side sanity check, polling,
 * and rendering).
 */

const form = document.getElementById('scan-form');
const domainInput = document.getElementById('domain');
const scanBtn = document.getElementById('scan-btn');
const alertBox = document.getElementById('alert-box');
const progressSection = document.getElementById('progress-section');
const progressLabel = document.getElementById('progress-label');
const progressCount = document.getElementById('progress-count');
const progressFill = document.getElementById('progress-fill');
const resultsCard = document.getElementById('results-card');
const resultsDomain = document.getElementById('results-domain');
const resultsCount = document.getElementById('results-count');
const resultsBody = document.getElementById('results-body');
const emptyState = document.getElementById('empty-state');

let pollTimer = null;

// Light client-side format check for instant feedback only.
// The server performs the authoritative validation.
const DOMAIN_PATTERN = /^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*\.[A-Za-z]{2,63}$/;

form.addEventListener('submit', (e) => {
  e.preventDefault();
  const domain = domainInput.value.trim().toLowerCase();

  hideAlert();
  clearResults();

  if (!domain) {
    showAlert('Please enter a domain to scan.');
    return;
  }
  if (domain.includes('://') || domain.includes('/') || domain.includes(' ')) {
    showAlert('Enter a bare domain only (no http://, no paths, no spaces).');
    return;
  }
  if (!DOMAIN_PATTERN.test(domain)) {
    showAlert('That does not look like a valid domain name (e.g. example.com).');
    return;
  }

  startScan(domain);
});

async function startScan(domain) {
  setScanning(true);
  showProgress(0, 0, 'Starting scan...');

  try {
    const res = await fetch('/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ domain }),
    });

    const data = await res.json();

    if (!res.ok) {
      showAlert(data.error || 'Could not start the scan.');
      setScanning(false);
      hideProgress();
      return;
    }

    pollStatus(data.job_id, domain);
  } catch (err) {
    showAlert('Network error while starting the scan. Is the server running?');
    setScanning(false);
    hideProgress();
  }
}

function pollStatus(jobId, domain) {
  if (pollTimer) clearInterval(pollTimer);

  pollTimer = setInterval(async () => {
    try {
      const res = await fetch(`/scan/status/${jobId}`);
      const data = await res.json();

      if (!res.ok) {
        clearInterval(pollTimer);
        showAlert(data.error || 'Lost track of the scan job.');
        setScanning(false);
        hideProgress();
        return;
      }

      showProgress(data.scanned, data.total, `Scanning ${domain}...`);
      renderResults(domain, data.results);

      if (data.status === 'done') {
        clearInterval(pollTimer);
        setScanning(false);
        progressLabel.textContent = 'Scan complete';
      } else if (data.status === 'error') {
        clearInterval(pollTimer);
        showAlert(data.error || 'The scan failed.');
        setScanning(false);
        hideProgress();
      }
    } catch (err) {
      clearInterval(pollTimer);
      showAlert('Network error while checking scan progress.');
      setScanning(false);
      hideProgress();
    }
  }, 700);
}

function renderResults(domain, results) {
  resultsCard.classList.remove('hidden');
  resultsDomain.textContent = domain;
  resultsCount.textContent = `${results.length} active subdomain${results.length === 1 ? '' : 's'} found`;

  resultsBody.innerHTML = '';

  if (results.length === 0) {
    emptyState.classList.remove('hidden');
    return;
  }
  emptyState.classList.add('hidden');

  results.forEach((r, idx) => {
    const row = document.createElement('tr');
    row.innerHTML = `
      <td>${idx + 1}</td>
      <td class="subdomain-cell">${escapeHtml(r.subdomain)}</td>
      <td class="ip-cell">${r.ip_addresses.map(escapeHtml).join(', ')}</td>
      <td><span class="status-pill">Active</span></td>
    `;
    resultsBody.appendChild(row);
  });
}

function clearResults() {
  resultsCard.classList.add('hidden');
  resultsBody.innerHTML = '';
  emptyState.classList.add('hidden');
}

function showProgress(scanned, total, label) {
  progressSection.classList.remove('hidden');
  progressLabel.textContent = label;
  progressCount.textContent = `${scanned} / ${total}`;
  const pct = total > 0 ? Math.round((scanned / total) * 100) : 0;
  progressFill.style.width = `${pct}%`;
}

function hideProgress() {
  progressSection.classList.add('hidden');
  progressFill.style.width = '0%';
}

function setScanning(isScanning) {
  scanBtn.disabled = isScanning;
  scanBtn.textContent = isScanning ? 'Scanning...' : 'Start Scan';
}

function showAlert(message) {
  alertBox.textContent = message;
  alertBox.classList.remove('hidden');
}

function hideAlert() {
  alertBox.classList.add('hidden');
  alertBox.textContent = '';
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
