"""
scanner.enumerator
-------------------
Core logic for the Subdomain Enumeration Tool.

Design notes (also explained in the README):
  - This module NEVER shells out. It only uses `dnspython` to perform
    standard DNS 'A' record lookups - there is no os.system, subprocess,
    or shell involved anywhere, so there is no command-injection surface
    from user-supplied domain names.
  - The user-supplied domain is validated against a strict hostname
    regex before it is ever used to build a lookup name. Invalid input
    is rejected outright rather than "cleaned" and reused.
  - A small per-lookup delay and a limited thread pool provide basic,
    good-citizen rate limiting so the tool doesn't hammer DNS resolvers.
"""

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import dns.resolver
import dns.exception


# ---------------------------------------------------------------------------
# Domain validation
# ---------------------------------------------------------------------------
# Matches standard hostnames: labels of 1-63 chars (letters/digits/hyphen,
# no leading/trailing hyphen), separated by dots, ending in a TLD of at
# least 2 letters. Overall length capped at 253 characters (DNS limit).
_DOMAIN_REGEX = re.compile(
    r'^(?=.{1,253}$)'
    r'(?!-)[A-Za-z0-9-]{1,63}(?<!-)'
    r'(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*'
    r'\.[A-Za-z]{2,63}$'
)


def is_valid_domain(domain: str) -> bool:
    """
    Return True only if `domain` looks like a plain, well-formed hostname.

    Deliberately rejects anything that isn't a bare hostname: URLs with a
    scheme (http://), paths, ports, whitespace, or wildcard characters.
    This keeps the value safe to interpolate into a DNS lookup name.
    """
    if not domain:
        return False

    domain = domain.strip()

    if any(ch.isspace() for ch in domain):
        return False
    if '://' in domain or '/' in domain or '\\' in domain:
        return False
    if domain.startswith('.') or domain.endswith('.'):
        return False

    return bool(_DOMAIN_REGEX.match(domain.lower()))


# ---------------------------------------------------------------------------
# Wordlist loading
# ---------------------------------------------------------------------------
def load_wordlist(path: str):
    """Load subdomain prefix candidates from a text file, one per line."""
    words = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            words.append(line.lower())
    return words


# ---------------------------------------------------------------------------
# DNS resolution
# ---------------------------------------------------------------------------
def _resolve_one(hostname: str, resolver: dns.resolver.Resolver, delay: float):
    """
    Attempt to resolve a single hostname's A records.
    Returns a result dict if the hostname is active, otherwise None.
    A small delay is applied before each lookup as a basic rate-limit.
    """
    if delay:
        time.sleep(delay)

    try:
        answers = resolver.resolve(hostname, 'A')
        ip_addresses = sorted({rdata.address for rdata in answers})
        return {
            'subdomain': hostname,
            'ip_addresses': ip_addresses,
            'status': 'active',
        }
    except dns.resolver.NXDOMAIN:
        return None            # Domain does not exist - expected, not an error
    except dns.resolver.NoAnswer:
        return None            # No A record for this name
    except dns.resolver.NoNameservers:
        return None            # All nameservers refused/failed for this name
    except dns.exception.Timeout:
        return None            # Lookup took too long - treat as inactive
    except Exception:
        return None            # Defensive catch-all; never let one lookup crash the scan


def enumerate_subdomains(domain, wordlist, job=None, jobs_lock=None,
                          max_workers=5, per_request_delay=0.05, timeout=2.0):
    """
    Enumerate subdomains of `domain` using the prefixes in `wordlist`.

    If `job` (a dict) and `jobs_lock` are supplied, progress is written
    into `job` under the lock as each lookup completes, so a Flask route
    can poll it to drive a live progress bar.

    Returns the final sorted list of result dicts:
        [{'subdomain': 'www.example.com', 'ip_addresses': ['1.2.3.4'], 'status': 'active'}, ...]
    """
    resolver = dns.resolver.Resolver()
    resolver.timeout = timeout
    resolver.lifetime = timeout

    candidates = [f'{word}.{domain}' for word in wordlist]
    total = len(candidates)

    if job is not None and jobs_lock is not None:
        with jobs_lock:
            job['total'] = total
            job['status'] = 'running'

    results = []
    scanned = 0

    # A small, fixed-size thread pool keeps concurrency (and therefore load
    # on the DNS resolver) bounded and predictable - this is the "basic
    # rate limiting" control for the DNS lookups themselves.
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_host = {
            executor.submit(_resolve_one, host, resolver, per_request_delay): host
            for host in candidates
        }
        for future in as_completed(future_to_host):
            scanned += 1
            result = future.result()
            if result:
                results.append(result)

            if job is not None and jobs_lock is not None:
                with jobs_lock:
                    job['scanned'] = scanned
                    job['results'] = sorted(results, key=lambda r: r['subdomain'])

    final_results = sorted(results, key=lambda r: r['subdomain'])

    if job is not None and jobs_lock is not None:
        with jobs_lock:
            job['status'] = 'done'
            job['results'] = final_results

    return final_results
