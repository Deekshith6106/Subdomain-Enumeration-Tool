# 🔍 Subdomain Enumeration Tool

A local, educational web application that discovers active subdomains of a
domain using **wordlist-based DNS resolution** — built with Python, Flask,
and `dnspython`. No shell commands, no exploitation, no port scanning —
just standard DNS `A` record lookups, wrapped in a clean cybersecurity-themed
UI with live progress feedback.

> ⚠️ **Authorization required.** Only run this tool against domains you own
> or have explicit written permission to test. Scanning systems you don't
> control may violate laws such as the U.S. Computer Fraud and Abuse Act,
> the UK Computer Misuse Act, or equivalent legislation elsewhere, even when
> the technique itself (DNS lookups) is passive and low-impact.

---

## 📌 Problem Statement

Subdomains are often forgotten, unmonitored, or misconfigured — a `dev.`,
`staging.`, or `old.` subdomain can expose outdated software or internal
tools to the public internet. Security teams and bug bounty researchers
routinely start an assessment by mapping an organization's subdomain
footprint so nothing is overlooked. Doing this by hand (typing `dig
www.example.com`, `dig mail.example.com`, ... one at a time) doesn't scale.

## 🎯 Objective

Build a small, understandable, fully local tool that automates the
"guess common subdomain names, then check if they resolve" workflow, and
present the results in a clear web UI — while explicitly designing out any
capability that would let it be used for anything beyond passive DNS
reconnaissance on infrastructure you're authorized to test.

---

## ✨ Features

- Domain input via a simple web form
- Strict server-side domain format validation (rejects URLs, paths, spaces, malformed hostnames)
- Wordlist-based subdomain candidate generation (`wordlists/subdomains.txt`)
- Concurrent DNS `A`-record resolution via `dnspython` (bounded thread pool)
- Displays each discovered subdomain alongside its resolved IP address(es)
- Live progress bar (scanned / total) via polling, not a blocking spinner
- Clear, non-technical error messages for invalid input, network issues, and server errors
- Prominent authorization warning banner on every page
- Basic rate limiting: a per-lookup delay plus a per-client cooldown between scans
- **No shell execution of any kind** — only `dnspython` API calls

## 🛠️ Technologies

| Layer | Technology |
|---|---|
| Backend | Python 3, Flask |
| DNS resolution | `dnspython` |
| Concurrency | `concurrent.futures.ThreadPoolExecutor` |
| Frontend | HTML5, CSS3 (custom, no framework), vanilla JavaScript |
| Data | Plain-text wordlist file (no database needed) |

---

## 🗂️ Project Structure

```
subdomain-enumeration/
├── app.py                   # Flask routes, job management, rate limiting
├── requirements.txt
├── README.md
├── .gitignore
├── scanner/
│   ├── __init__.py
│   └── enumerator.py        # Domain validation, wordlist loading, DNS resolution
├── wordlists/
│   └── subdomains.txt       # Educational list of common subdomain prefixes
├── templates/
│   ├── base.html            # Shared layout + authorization banner
│   └── index.html           # Scan form, progress bar, results table
└── static/
    ├── style.css            # Cybersecurity-themed responsive styling
    └── script.js            # Form handling, progress polling, results rendering
```

---

## 🚀 Installation

### Prerequisites
- Python 3.9+
- pip

### Steps

```bash
# 1. Clone the repository
git clone https://github.com/<your-username>/subdomain-enumeration.git
cd subdomain-enumeration

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the application
python app.py
```

The app starts at **http://127.0.0.1:5001**. Open it in your browser, enter
a domain **you are authorized to scan**, and click "Start Scan".

---

## 🔬 How Enumeration Works

```
Domain Input
     │
     ▼
Validate Domain          →  Reject anything that isn't a well-formed bare hostname
     │
     ▼
Generate Subdomain        →  Combine each wordlist prefix with the domain,
Candidates                   e.g. "www" + "example.com" → "www.example.com"
     │
     ▼
DNS Resolution             →  Query the A record for each candidate hostname
                              via dnspython, with a bounded thread pool and
                              a small per-lookup delay
     │
     ▼
Identify Active            →  A candidate is "active" only if its A-record
Subdomains                    lookup succeeds and returns at least one IP
     │
     ▼
Display Results            →  Stream results to the browser via progress
                              polling; render a table of subdomain → IP(s)
     │
     ▼
Error Handling              →  Invalid domains, empty input, rate limiting,
                              and unexpected failures all return clear,
                              user-facing messages — never a raw stack trace
```

### Why polling instead of one big blocking request?
A wordlist scan can take a few seconds to a minute depending on wordlist
size and DNS latency. Rather than freezing the UI, `/scan` starts a
background thread and immediately returns a `job_id`. The browser then
polls `/scan/status/<job_id>` every ~700ms, which is what drives the live
progress bar and lets results appear as they're found.

---

## 🧪 Testing

Manual test checklist (all verified while building this project):

1. **Valid domain** (e.g. `example.com`) → scan starts, progress bar moves, results table populates.
2. **Invalid domain formats** (`http://example.com`, `not a domain`, empty input) → rejected with a clear inline error, no request even reaches DNS resolution.
3. **Domain with no matching subdomains** → scan completes cleanly and shows the "no active subdomains found" empty state instead of an error.
4. **Rapid repeated submissions** → second scan within the cooldown window is rejected with a `429` and a "please wait" message instead of stacking jobs.
5. **Unknown/expired job id** polled directly → returns a `404` with a clear error instead of crashing.
6. **Server restarted mid-scan** → in-memory job store is gone, and the frontend surfaces a clear "lost track of the scan" message rather than hanging forever.

You can also test the core logic directly without the web layer:

```bash
python -c "
from scanner import is_valid_domain, load_wordlist, enumerate_subdomains
print(is_valid_domain('example.com'))       # True
print(is_valid_domain('http://example.com')) # False
words = load_wordlist('wordlists/subdomains.txt')
print(len(words), 'candidates loaded')
"
```

---

## 🔒 Security Considerations

- **No shell execution.** The scanner only calls into the `dnspython`
  library's Python API (`resolver.resolve(...)`). There is no
  `os.system`, `subprocess`, or shell interpolation anywhere in the
  codebase, so a malicious domain string cannot be used for command
  injection.
- **Strict input validation.** Domains are validated against a hostname
  regex before being used to build any DNS query name; URLs, paths,
  whitespace, and other unexpected characters are rejected outright
  rather than sanitized-and-reused.
- **Rate limiting at two levels:**
  - A small delay before each individual DNS lookup, plus a bounded
    thread pool (default 5 workers), so the tool doesn't hammer DNS
    resolvers.
  - A per-client cooldown (default 15 seconds) on the `/scan` endpoint
    itself, to prevent one user from queuing unlimited concurrent scans.
- **No stack traces returned to the client.** All error paths return a
  short, generic JSON message; detailed exceptions are only logged
  server-side via `app.logger`.
- **Passive technique only.** This tool performs DNS `A`-record lookups —
  it does not port-scan, brute-force login forms, fetch arbitrary URLs, or
  attempt any exploitation. It is intentionally scoped to reconnaissance
  that is low-impact on the target's infrastructure.
- **Ethical/legal framing is explicit and persistent.** The authorization
  warning is shown in the navigation banner on every page, not just in the
  README, so it can't be missed inside the app itself.
- **Local, single-process design.** The in-memory job store and rate
  limiter are intentionally simple for a local/educational tool. They are
  *not* designed to survive multiple server processes or restarts — see
  Future Improvements for what a hardened deployment would need instead.

---

## 🔮 Future Improvements

- Support additional DNS record types (`CNAME`, `AAAA`, `TXT`, `MX`) in results
- Optional wildcard-DNS detection (some domains resolve *any* subdomain, which produces false positives)
- Larger, categorized wordlists (with a file upload option for custom lists)
- Export results to CSV/JSON
- Persist scan history to a database instead of in-memory job storage
- Replace the in-process rate limiter with Redis so it works correctly behind multiple app workers
- Optional passive-only mode using certificate transparency logs (e.g. crt.sh) as an additional, non-brute-force discovery source
- Dockerfile for one-command setup

---

## 📸 Screenshots

_Add screenshots here after running the app locally, e.g.:_

- `docs/screenshot-scan-form.png` — the input form with the authorization banner
- `docs/screenshot-progress.png` — a scan in progress with the live progress bar
- `docs/screenshot-results.png` — a completed scan showing subdomains and IPs

---

## ⚠️ Legal & Ethical Use

This tool is provided for **educational purposes and authorized security
testing only**. You are solely responsible for ensuring you have permission
to scan any domain you enter. The author(s) accept no liability for misuse.

## 📄 License

MIT License — free to use, modify, and learn from.
