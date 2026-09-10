"""
Subdomain Enumeration Tool - Flask application

Workflow implemented by this file:
  Domain Input -> Validate Domain -> Generate Candidates -> DNS Resolution
  -> Identify Active Subdomains -> Display Results -> Error Handling

Scans run in a background thread so the browser can poll for live
progress instead of blocking on one long request. No shell commands are
ever executed - only dnspython performs DNS lookups.
"""

import os
import threading
import time
import uuid

from flask import Flask, render_template, request, jsonify

from scanner import is_valid_domain, load_wordlist, enumerate_subdomains

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WORDLIST_PATH = os.path.join(BASE_DIR, 'wordlists', 'subdomains.txt')

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(32).hex())

# ---------------------------------------------------------------------------
# In-memory job store
# ---------------------------------------------------------------------------
# Keyed by job_id -> {status, total, scanned, results, error, domain}
# A dict + lock is sufficient for a single-process local demo; a real
# deployment would use Redis/Celery instead of in-process state.
jobs = {}
jobs_lock = threading.Lock()

JOB_TTL_SECONDS = 15 * 60  # stale jobs are purged after 15 minutes

# ---------------------------------------------------------------------------
# Basic app-level rate limiting (per client IP)
# ---------------------------------------------------------------------------
# Prevents someone from spamming the /scan endpoint with back-to-back scans.
# This is separate from the per-lookup delay inside the scanner itself.
RATE_LIMIT_SECONDS = 15
_last_scan_by_ip = {}
_rate_lock = threading.Lock()


def _client_ip():
    return request.headers.get('X-Forwarded-For', request.remote_addr) or 'unknown'


def _is_rate_limited(ip):
    now = time.time()
    with _rate_lock:
        last = _last_scan_by_ip.get(ip)
        if last is not None and (now - last) < RATE_LIMIT_SECONDS:
            return True, RATE_LIMIT_SECONDS - (now - last)
        _last_scan_by_ip[ip] = now
        return False, 0


def _purge_stale_jobs():
    cutoff = time.time() - JOB_TTL_SECONDS
    with jobs_lock:
        stale = [jid for jid, j in jobs.items() if j.get('created_at', 0) < cutoff]
        for jid in stale:
            del jobs[jid]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/scan', methods=['POST'])
def start_scan():
    _purge_stale_jobs()

    data = request.get_json(silent=True) or {}
    domain = (data.get('domain') or '').strip().lower()

    if not domain:
        return jsonify({'error': 'Please enter a domain to scan.'}), 400

    if not is_valid_domain(domain):
        return jsonify({'error': f'"{domain}" is not a valid domain name.'}), 400

    # Only a well-formed request that is actually about to trigger DNS
    # lookups counts against the cooldown - typos and empty submissions
    # shouldn't lock a user out of retrying immediately.
    ip = _client_ip()
    limited, wait_seconds = _is_rate_limited(ip)
    if limited:
        return jsonify({
            'error': f'Please wait {int(wait_seconds) + 1} more second(s) before starting another scan.'
        }), 429

    try:
        wordlist = load_wordlist(WORDLIST_PATH)
    except OSError:
        return jsonify({'error': 'Server error: wordlist could not be loaded.'}), 500

    if not wordlist:
        return jsonify({'error': 'Server error: wordlist is empty.'}), 500

    job_id = uuid.uuid4().hex
    with jobs_lock:
        jobs[job_id] = {
            'status': 'pending',
            'domain': domain,
            'total': 0,
            'scanned': 0,
            'results': [],
            'error': None,
            'created_at': time.time(),
        }

    def run_job():
        try:
            enumerate_subdomains(
                domain,
                wordlist,
                job=jobs[job_id],
                jobs_lock=jobs_lock,
            )
        except Exception as exc:  # pragma: no cover - defensive
            with jobs_lock:
                jobs[job_id]['status'] = 'error'
                jobs[job_id]['error'] = 'An unexpected error occurred during the scan.'
            app.logger.exception('Scan job %s failed: %s', job_id, exc)

    thread = threading.Thread(target=run_job, daemon=True)
    thread.start()

    return jsonify({'job_id': job_id}), 202


@app.route('/scan/status/<job_id>')
def scan_status(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            return jsonify({'error': 'Unknown or expired scan job.'}), 404
        # Return a shallow copy so we don't hold the lock while serializing
        snapshot = dict(job)

    return jsonify({
        'status': snapshot['status'],
        'domain': snapshot['domain'],
        'total': snapshot['total'],
        'scanned': snapshot['scanned'],
        'results': snapshot['results'],
        'error': snapshot['error'],
    })


# ---------------------------------------------------------------------------
# Error handlers - never leak stack traces
# ---------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(_e):
    return render_template('index.html'), 404


@app.errorhandler(500)
def server_error(_e):
    return jsonify({'error': 'An internal server error occurred.'}), 500


if __name__ == '__main__':
    app.run(debug=False, host='127.0.0.1', port=5001)
