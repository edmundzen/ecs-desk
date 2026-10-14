"""
The fast checks: syntax, the offline test suite, and a secret scan.

    python tests/checks.py             # everything tracked by git
    python tests/checks.py --staged    # only what is staged, for a commit hook

Seconds, no API key, no network, no cost. The eval suite in run_eval.py is the
opposite on every count, so it is deliberately not run here: 17 live Gemini
calls take about fifteen minutes and cost real money. Run that before a
submission or after a prompt change, not on every commit.
"""
import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Things that must never reach a public repository.
SECRET_PATTERNS = [
    (r"AIza[0-9A-Za-z_\-]{30,}", "Google API key"),
    (r"sk-[A-Za-z0-9]{20,}", "API key"),
    (r"ya29\.[A-Za-z0-9_\-]{20,}", "OAuth access token"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key"),
    (r"\"type\"\s*:\s*\"service_account\"", "service account JSON"),
]

# Files that must never be committed at all, whatever is in them.
FORBIDDEN_PATHS = [
    (re.compile(r"(^|/)\.env$"), ".env"),
    (re.compile(r"(^|/)outbox\.json$"), "local queue dump"),
    (re.compile(r"service[-_]?account.*\.json$"), "service account key"),
]


def git(*args) -> list:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return [l for l in out.stdout.splitlines() if l.strip()]


def files(staged: bool) -> list:
    if staged:
        return git("diff", "--cached", "--name-only", "--diff-filter=ACM")
    return git("ls-files")


def read(path: str, staged: bool) -> str:
    """Staged content, not the working copy - they can differ."""
    if staged:
        out = subprocess.run(["git", "show", f":{path}"], cwd=ROOT,
                             capture_output=True, text=True)
        return out.stdout if out.returncode == 0 else ""
    p = ROOT / path
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staged", action="store_true")
    args = parser.parse_args()

    paths = files(args.staged)
    if not paths:
        print("Nothing to check.")
        return 0

    failures = []

    # 1. no forbidden files
    for path in paths:
        for pattern, label in FORBIDDEN_PATHS:
            if pattern.search(path):
                failures.append(f"{path}: {label} must never be committed")

    # 2. no secrets in content
    for path in paths:
        if path.endswith((".png", ".jpg", ".jpeg", ".gif", ".pdf", ".pptx", ".ico")):
            continue
        body = read(path, args.staged)
        for pattern, label in SECRET_PATTERNS:
            if re.search(pattern, body):
                failures.append(f"{path}: looks like a {label}")

    # 3. python files must parse
    for path in paths:
        if path.endswith(".py"):
            body = read(path, args.staged)
            try:
                ast.parse(body)
            except SyntaxError as exc:
                failures.append(f"{path}:{exc.lineno}: syntax error: {exc.msg}")

    print(f"checked {len(paths)} file(s)")
    for f in failures:
        print(f"  FAIL  {f}")

    # 4. the offline test suite
    suite = subprocess.run([sys.executable, str(ROOT / "tests" / "test_fallback.py")],
                           cwd=ROOT, capture_output=True, text=True)
    tail = [l for l in suite.stdout.splitlines() if "checks passed" in l]
    print(f"  {'pass' if suite.returncode == 0 else 'FAIL'}  "
          f"model ladder and enum validation: {tail[0].strip() if tail else 'no output'}")
    if suite.returncode != 0:
        failures.append("tests/test_fallback.py failed")
        print(suite.stdout[-1500:])

    if failures:
        print(f"\n{len(failures)} problem(s). Commit blocked.\n")
        return 1
    print("\nall good\n")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
