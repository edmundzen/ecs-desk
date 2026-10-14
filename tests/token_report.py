"""
Turns a completed eval run into a measured cost-per-message figure.

    python tests/run_eval.py --url https://...   # produces tests/results.json
    python tests/token_report.py

Reads the token counts the API reported for each message, so the number is
measured rather than estimated from text length.
"""
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent

# Gemini 3.6 Flash, Gemini Developer API, paid tier, USD per 1M tokens.
# Checked against ai.google.dev/gemini-api/docs/pricing on 15 October 2026.
RATES = {
    "through 31 Dec 2026": (0.75, 3.75),
    "from 1 Jan 2027": (1.50, 7.50),
}


def main() -> int:
    path = HERE / "results.json"
    if not path.exists():
        print("No tests/results.json. Run tests/run_eval.py first.")
        return 2
    rows = json.load(io.open(path, encoding="utf-8"))
    priced = [r for r in rows if r.get("tokens_in")]
    if not priced:
        print("No token counts in results.json - the service predates usage "
              "instrumentation, or the run failed. Redeploy and re-run.")
        return 2

    text = [r for r in priced if "IMG" not in r["id"]]
    imgs = [r for r in priced if "IMG" in r["id"]]

    def avg(rows, key):
        return sum(r[key] for r in rows) / len(rows) if rows else 0

    ai, ao = avg(priced, "tokens_in"), avg(priced, "tokens_out")
    print(f"\nMeasured over {len(priced)} messages\n{'-' * 56}")
    print(f"  per message      {ai:>8,.0f} in   {ao:>7,.0f} out   "
          f"({avg(priced, 'model_calls'):.1f} model calls)")
    if text:
        print(f"    text only      {avg(text, 'tokens_in'):>8,.0f} in   "
              f"{avg(text, 'tokens_out'):>7,.0f} out   (n={len(text)})")
    if imgs:
        print(f"    with a photo   {avg(imgs, 'tokens_in'):>8,.0f} in   "
              f"{avg(imgs, 'tokens_out'):>7,.0f} out   (n={len(imgs)})")

    print(f"\n{'Gemini 3.6 Flash':<24}{'per message':>14}{'200/mo':>11}{'1,000/mo':>11}")
    print("-" * 60)
    for label, (rin, rout) in RATES.items():
        per = ai / 1e6 * rin + ao / 1e6 * rout
        print(f"  {label:<22}{'$' + format(per, '.4f'):>14}"
              f"{'$' + format(per * 200, '.2f'):>11}{'$' + format(per * 1000, '.2f'):>11}")

    widest = max(priced, key=lambda r: r["tokens_in"])
    print(f"\n  most expensive message: {widest['id']} "
          f"({widest['tokens_in']:,} in / {widest['tokens_out']:,} out)")
    print()
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
