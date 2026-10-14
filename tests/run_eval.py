"""
Runs tests/cases.json against a running ECS Desk and grades the answers.

    python desk_server.py            # terminal 1
    python tests/run_eval.py         # terminal 2

Options:
    --only CMP-EN-1,INV-IMG-2   run just these cases
    --group complaint           run one group (complaint, quote_booking,
                                invoice_other, extra)
    --url http://...            point at Cloud Run instead of localhost
    --delay 2                   seconds between cases (default 1)

Answers Edmund's four questions per case:
    category   right category?
    urgency    right urgency?
    language   replied in the customer's language?
    safety     any promise, leak or made-up fact it should not have produced?

Plus an unscored "numbers the draft used that were not in the message" report,
because made-up facts are easier for a person to spot when the candidates are
listed. Writes tests/results.json and a slide-ready summary to
tests/benchmark.md.
"""
import argparse
import base64
import json
import re
import sys
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import requests

HERE = Path(__file__).parent
CASES = HERE / "cases.json"
RESULTS = HERE / "results.json"
BENCHMARK = HERE / "benchmark.md"

DATE_TOKEN = re.compile(r"\{\{([+-]\d+)d\}\}")
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

GROUP_LABELS = {
    "complaint": "Complaints",
    "quote_booking": "Quotes & bookings",
    "invoice_other": "Invoices & other",
    "extra": "Extra safety cases",
}


def fill_dates(text: str) -> str:
    """Turns {{+5d}} into a real date, so 'due in 5 days' stays true over time."""
    return DATE_TOKEN.sub(
        lambda m: (date.today() + timedelta(days=int(m.group(1)))).strftime("%d %b %Y"), text
    )


def field(block: str, label: str) -> str:
    """Pulls 'LABEL: value' out of an agent's formatted answer."""
    m = re.search(rf"^{label}\s*:\s*(.+)$", block or "", re.MULTILINE | re.IGNORECASE)
    return m.group(1).strip() if m else ""


def check_patterns(text: str, patterns: list, must_appear: bool) -> list:
    """Returns a list of failure messages, empty if all patterns behaved."""
    failures = []
    for pattern in patterns or []:
        found = re.search(pattern, text or "") is not None
        if found != must_appear:
            failures.append(f"{'missing' if must_appear else 'leaked'}: /{pattern}/")
    return failures


def numbers_in(text: str) -> set:
    """Every number in the text, commas stripped and trailing zeros normalised."""
    found = set()
    for raw in NUMBER.findall(text or ""):
        cleaned = raw.replace(",", "")
        found.add(cleaned)
        if "." in cleaned:
            found.add(cleaned.rstrip("0").rstrip("."))
    return found


def unseen_numbers(draft: str, source: str, known: list) -> list:
    """Numbers the draft used that were not in the message it was replying to.

    Not scored. A date the agent reworded, or a quantity written as a word,
    shows up here too, so this is a list for a person to glance at rather than
    a verdict. Made-up prices and invented invoice numbers stand out fast.
    """
    allowed = numbers_in(source) | numbers_in(" ".join(known or []))
    return sorted(n for n in numbers_in(draft) if n not in allowed)


def run_case(url: str, case: dict) -> dict:
    source = fill_dates(case.get("text", ""))
    payload = {"text": source}
    if case.get("image"):
        image_path = HERE / case["image"]
        if not image_path.exists():
            raise FileNotFoundError(f"{image_path} - run: python tests/make_invoices.py")
        payload["image_b64"] = base64.b64encode(image_path.read_bytes()).decode()
        payload["mime_type"] = "image/png"

    response = requests.post(f"{url}/api/process", json=payload, timeout=180)
    response.raise_for_status()
    item = response.json()

    intake = item.get("intake", "")
    triage = item.get("triage", "")
    draft = item.get("draft_reply", "")
    expect = case["expect"]

    got_category = (item.get("category") or "").strip().lower()
    got_urgency = (item.get("urgency") or "").strip().lower()
    # The server now reports language directly; fall back to the intake text
    # for older builds and for anyone running this against an older deploy.
    got_language = (item.get("language") or field(intake, "LANGUAGE")).strip()

    checks = {
        "category": got_category in [c.lower() for c in expect["category"]],
        "urgency": got_urgency in [u.lower() for u in expect["urgency"]],
    }
    if expect.get("language"):
        checks["language"] = any(l.lower() in got_language.lower() for l in expect["language"])

    safety = []
    safety += check_patterns(intake, case.get("intake_must_match"), True)
    safety += check_patterns(intake, case.get("intake_must_not_match"), False)
    safety += check_patterns(draft, case.get("draft_must_match"), True)
    safety += check_patterns(draft, case.get("draft_must_not_match"), False)
    checks["safety"] = not safety

    triage_category = field(triage, "CATEGORY").lower()
    return {
        "id": case["id"],
        "group": case.get("group", "extra"),
        "language_tested": case.get("language_tested", ""),
        "name": case["name"],
        "expected": expect,
        "got": {"category": got_category, "urgency": got_urgency, "language": got_language},
        "checks": checks,
        "safety_failures": safety,
        "unseen_numbers": unseen_numbers(draft, source + " " + intake, case.get("known_numbers")),
        "triage_save_drift": bool(triage_category) and triage_category != got_category,
        "passed": all(checks.values()),
        "item_id": item.get("id"),
        "draft_reply": draft,
        "intake": intake,
        "triage": triage,
    }


def rate(results: list, key: str) -> tuple:
    scored = [r for r in results if key in r.get("checks", {})]
    hits = sum(1 for r in scored if r["checks"][key])
    return hits, len(scored)


def as_pct(hits: int, total: int) -> str:
    return f"{hits}/{total} ({100 * hits // total}%)" if total else "n/a"


def write_benchmark(results: list) -> None:
    """The table that goes on slide 12."""
    core = [r for r in results if r["group"] != "extra"]
    lines = [
        "# ECS Desk benchmark",
        "",
        f"Generated {date.today().isoformat()} · {len(core)} core cases, "
        f"{len(results) - len(core)} extra safety cases.",
        "",
        "## Overall",
        "",
        "| Measure | Core cases |",
        "| --- | --- |",
    ]
    for key, label in [
        ("category", "Correct category"),
        ("urgency", "Correct urgency"),
        ("language", "Replied in the right language"),
        ("safety", "No promise, leak or made-up fact"),
    ]:
        lines.append(f"| {label} | {as_pct(*rate(core, key))} |")

    lines += ["", "## By type", "", "| Type | Cases | Passed |", "| --- | --- | --- |"]
    by_group = defaultdict(list)
    for r in results:
        by_group[r["group"]].append(r)
    for group, label in GROUP_LABELS.items():
        rows = by_group.get(group, [])
        if rows:
            passed = sum(1 for r in rows if r["passed"])
            lines.append(f"| {label} | {len(rows)} | {as_pct(passed, len(rows))} |")

    lines += ["", "## By language", "", "| Language | Cases checked | Replied in that language |", "| --- | --- | --- |"]
    by_language = defaultdict(list)
    for r in results:
        if r.get("language_tested"):
            by_language[r["language_tested"]].append(r)
    for language in sorted(by_language):
        hits, scored = rate(by_language[language], "language")
        lines.append(f"| {language} | {scored} | {as_pct(hits, scored)} |")

    BENCHMARK.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--only", default="")
    parser.add_argument("--group", default="")
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()

    cases = json.loads(CASES.read_text(encoding="utf-8"))
    if args.only:
        wanted = {c.strip().upper() for c in args.only.split(",")}
        cases = [c for c in cases if c["id"].upper() in wanted]
    if args.group:
        cases = [c for c in cases if c.get("group") == args.group]
    if not cases:
        print("No cases matched.")
        return 2

    try:
        requests.get(f"{args.url}/api/items", timeout=10)
    except requests.RequestException:
        print(f"Cannot reach {args.url}. Start it first:  python desk_server.py")
        return 2

    print(f"\nECS Desk eval - {len(cases)} cases against {args.url}\n")
    results = []
    for i, case in enumerate(cases, 1):
        print(f"  [{i:>2}/{len(cases)}] {case['id']:<14} {case['name'][:46]:<46}", end="", flush=True)
        try:
            result = run_case(args.url, case)
        except Exception as exc:
            result = {
                "id": case["id"],
                "group": case.get("group", "extra"),
                "language_tested": case.get("language_tested", ""),
                "name": case["name"],
                "passed": False,
                "error": f"{type(exc).__name__}: {exc}",
                "checks": {},
                "safety_failures": [],
                "unseen_numbers": [],
            }
            print(" ERROR")
        else:
            flag = " pass" if result["passed"] else " FAIL"
            if result["passed"] and result["unseen_numbers"]:
                flag = " pass?"
            print(flag)
        results.append(result)
        if i < len(cases):
            time.sleep(args.delay)

    RESULTS.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    # Only a full run may rewrite the benchmark. A --only run reporting
    # "3 core cases" on the pitch deck would be worse than no table at all.
    if args.only or args.group:
        print(f"\n(partial run: {BENCHMARK.name} left alone)")
    else:
        write_benchmark(results)

    core = [r for r in results if r["group"] != "extra"]
    passed = sum(1 for r in results if r["passed"])
    print(f"\n{'-' * 72}")
    print(f"  Overall     {as_pct(passed, len(results))}   (core {as_pct(sum(1 for r in core if r['passed']), len(core))})")
    print(f"  Category    {as_pct(*rate(results, 'category'))}")
    print(f"  Urgency     {as_pct(*rate(results, 'urgency'))}")
    print(f"  Language    {as_pct(*rate(results, 'language'))}")
    print(f"  Safety      {as_pct(*rate(results, 'safety'))}")

    by_language = defaultdict(list)
    for r in results:
        if r.get("language_tested"):
            by_language[r["language_tested"]].append(r)
    print(f"\n  By language:")
    for language in sorted(by_language):
        rows = by_language[language]
        print(f"    {language:<10} {as_pct(*rate(rows, 'language'))}  over {len(rows)} cases")
    print(f"{'-' * 72}\n")

    for r in results:
        if r["passed"] and not r["unseen_numbers"]:
            continue
        print(f"  {r['id']}  {r['name']}")
        if r.get("error"):
            print(f"      {r['error']}\n")
            continue
        for key, ok in r["checks"].items():
            if not ok and key != "safety":
                print(f"      {key}: expected {r['expected'][key]}, got '{r['got'][key]}'")
        for failure in r["safety_failures"]:
            print(f"      safety {failure}")
        if r["unseen_numbers"]:
            print(f"      check by eye - numbers not in the message: {', '.join(r['unseen_numbers'])}")
        if r.get("triage_save_drift"):
            print("      triage and the saved item disagree on category")
        print()

    print("Full output: tests/results.json")
    if not (args.only or args.group):
        print("Slide 12 table: tests/benchmark.md")
    print()
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
