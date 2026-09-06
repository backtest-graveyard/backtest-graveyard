#!/usr/bin/env python3
"""scrub_audit.py — refuse to publish anything containing secrets or PII.

Run from the repo root BEFORE making this public. Exit 0 = clean.
Pattern set extends the SDVOSB Handbook's pii_audit.py with credential and
broker-account shapes, which a code repo needs and a manuscript doesn't.
"""
import pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent
SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules"}

PATTERNS = [
    ("US Social Security number",  r"\b\d{3}-\d{2}-\d{4}\b", "HIGH"),
    ("EIN (federal tax ID)",       r"\b\d{2}-\d{7}\b", "REVIEW"),
    ("payment card number",        r"\b(?:\d[ -]?){13,19}\b", "HIGH"),   # Luhn-gated below
    ("email address",              r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b", "HIGH"),
    ("US phone number",            r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)", "REVIEW"),
    ("local filesystem path",      r"/Users/[\w.-]+", "HIGH"),
    ("IP address",                 r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "REVIEW"),
    # credential + broker shapes
    # real broker ids always mix digits in; requiring one stops the MIT licence's
    # "PARTICULAR" (and any other all-letter word starting PA) from tripping this
    ("Alpaca-style account id",    r"\bP[AK](?=[A-Z0-9]{8,12}\b)[A-Z0-9]*\d[A-Z0-9]*\b", "HIGH"),
    ("API key assignment",         r"(?i)\b(api[_-]?key|secret|token|passwd|password)\b\s*[:=]\s*['\"][^'\"]{8,}", "HIGH"),
    ("AWS access key",             r"\bAKIA[0-9A-Z]{16}\b", "HIGH"),
    ("private key block",          r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", "HIGH"),
    ("bearer token",               r"(?i)bearer\s+[A-Za-z0-9._-]{20,}", "HIGH"),
    ("dotenv-style secret",        r"(?m)^[A-Z][A-Z0-9_]*(?:KEY|SECRET|TOKEN|PASS)\s*=\s*\S+", "HIGH"),
]

# things that look like matches but aren't
ALLOW = [
    re.compile(r"os\.environ|getenv|\.get\(['\"]|credentials file|~/\.alpaca"),
    re.compile(r"KEY\s*=\s*(?:None|''|\"\"|os\.|<)"),
    re.compile(r"example\.com|your-?key|REDACTED|xxxx", re.I),
]

def _luhn(s: str) -> bool:
    """Real card numbers pass Luhn. 19-digit social-post IDs do not, and this repo
    cites several as provenance for the claims it examines."""
    d = [int(c) for c in re.sub(r"\D", "", s)][::-1]
    if len(d) < 13:
        return False
    tot = 0
    for i, x in enumerate(d):
        if i % 2:
            x *= 2
            x -= 9 if x > 9 else 0
        tot += x
    return tot % 10 == 0


def scan():
    findings = []
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file() or any(d in p.parts for d in SKIP_DIRS):
            continue
        if p.name == "scrub_audit.py" or p.suffix in {".png", ".jpg", ".pdf"}:
            continue
        try:
            text = p.read_text(errors="ignore")
        except Exception:
            continue
        for i, line in enumerate(text.split("\n"), 1):
            if any(a.search(line) for a in ALLOW):
                continue
            for name, pat, sev in PATTERNS:
                m = re.search(pat, line)
                if m:
                    if name == "payment card number" and not _luhn(m.group(0)):
                        continue
                    findings.append((sev, p.relative_to(ROOT), i, name, m.group(0)[:60]))
    return findings

if __name__ == "__main__":
    f = scan()
    high = [x for x in f if x[0] == "HIGH"]
    rev  = [x for x in f if x[0] == "REVIEW"]
    for sev, path, ln, name, snip in f:
        mark = "\033[31mHIGH  \033[0m" if sev == "HIGH" else "\033[33mREVIEW\033[0m"
        print(f"{mark} {path}:{ln}  {name}  ->  {snip!r}")
    print(f"\n{len(high)} HIGH, {len(rev)} REVIEW across "
          f"{sum(1 for _ in ROOT.rglob('*') if _.is_file())} files")
    if high:
        print("\nREFUSING TO PUBLISH: resolve every HIGH finding first.")
    sys.exit(1 if high else 0)
