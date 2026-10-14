"""
Offline checks for the model fallback ladder and the enum validator.

No API key and no network: the Gemini delegates are replaced with fakes that
raise the status codes we care about.

    python tests/test_fallback.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai.errors import APIError

from ecs_desk.config import (
    CATEGORIES,
    CATEGORY_FALLBACK,
    URGENCIES,
    URGENCY_FALLBACK,
    validate_choice,
)
from ecs_desk.fallback_model import FallbackGemini

LADDER = ["model-a", "model-b", "model-c", "model-d"]


def api_error(code: int) -> APIError:
    return APIError(code, {"error": {"message": f"simulated {code}"}})


class FakeDelegate:
    """Stands in for a Gemini client. Either raises, or answers."""

    def __init__(self, name, error=None, yield_then_fail=False):
        self.name = name
        self.error = error
        self.yield_then_fail = yield_then_fail

    async def generate_content_async(self, llm_request, stream=False):
        if self.yield_then_fail:
            yield LlmResponse(partial=True)
            raise self.error
        if self.error:
            raise self.error
            yield  # unreachable, keeps this an async generator
        yield LlmResponse(turn_complete=True)


def build(behaviour: dict) -> tuple:
    """A FallbackGemini whose rungs behave as described, plus a call log."""
    model = FallbackGemini(ladder=list(LADDER))
    calls = []

    def fake_delegate(name):
        calls.append(name)
        return behaviour.get(name) or FakeDelegate(name)

    model._delegate = fake_delegate
    return model, calls


async def collect(model) -> tuple:
    """Runs the model and reports which model id the request ended up carrying."""
    request = LlmRequest(model="unset")
    responses = [r async for r in model.generate_content_async(request)]
    return responses, request.model


def check(name: str, condition: bool, detail: str = "") -> bool:
    print(f"  {'pass' if condition else 'FAIL'}  {name}")
    if not condition and detail:
        print(f"        {detail}")
    return condition


async def main() -> int:
    results = []
    print("\nFallback ladder\n")

    # 1. Primary answers: nothing below it is touched.
    model, calls = build({})
    responses, used = await collect(model)
    results.append(check("primary answers, ladder stops at rung 1", calls == ["model-a"], f"calls={calls}"))
    results.append(check("request carries the model that answered", used == "model-a", f"model={used}"))
    results.append(check("response is passed through", len(responses) == 1))

    # 2. Each retryable status moves down one rung.
    for code in (429, 500, 503, 404):
        model, calls = build({"model-a": FakeDelegate("model-a", api_error(code))})
        _, used = await collect(model)
        results.append(
            check(f"{code} falls through to the next model", calls == ["model-a", "model-b"], f"calls={calls}")
        )
        results.append(check(f"{code} leaves the request on model-b", used == "model-b", f"model={used}"))

    # 3. Failures compound all the way down the ladder.
    model, calls = build({
        "model-a": FakeDelegate("model-a", api_error(503)),
        "model-b": FakeDelegate("model-b", api_error(429)),
        "model-c": FakeDelegate("model-c", api_error(404)),
    })
    _, used = await collect(model)
    results.append(check("three failures reach the fourth model", calls == LADDER, f"calls={calls}"))
    results.append(check("fourth model's id is the one used", used == "model-d", f"model={used}"))

    # 4. A non-retryable error must not be masked by a fallback.
    model, calls = build({"model-a": FakeDelegate("model-a", api_error(400))})
    try:
        await collect(model)
        results.append(check("400 is raised, not retried", False, "no exception raised"))
    except APIError as exc:
        results.append(check("400 is raised, not retried", exc.code == 400 and calls == ["model-a"], f"calls={calls}"))

    # 5. Everything down: the last error surfaces.
    model, calls = build({name: FakeDelegate(name, api_error(503)) for name in LADDER})
    try:
        await collect(model)
        results.append(check("exhausted ladder raises", False, "no exception raised"))
    except APIError as exc:
        results.append(check("exhausted ladder raises the last error", exc.code == 503 and calls == LADDER, f"calls={calls}"))

    # 6. Half an answer already sent: retrying would duplicate it.
    model, calls = build({
        "model-a": FakeDelegate("model-a", api_error(503), yield_then_fail=True)
    })
    try:
        await collect(model)
        results.append(check("mid-stream failure is not retried", False, "no exception raised"))
    except APIError:
        results.append(check("mid-stream failure is not retried", calls == ["model-a"], f"calls={calls}"))

    print("\nEnum validation\n")
    cases = [
        ("complaint", CATEGORIES, CATEGORY_FALLBACK, "complaint"),
        ("  COMPLAINT  ", CATEGORIES, CATEGORY_FALLBACK, "complaint"),
        ("quote request", CATEGORIES, CATEGORY_FALLBACK, "quote_request"),
        ("quote-request", CATEGORIES, CATEGORY_FALLBACK, "quote_request"),
        ("URGENT!!", CATEGORIES, CATEGORY_FALLBACK, "other"),
        ("", CATEGORIES, CATEGORY_FALLBACK, "other"),
        (None, CATEGORIES, CATEGORY_FALLBACK, "other"),
        ("high", URGENCIES, URGENCY_FALLBACK, "high"),
        ("very high", URGENCIES, URGENCY_FALLBACK, "medium"),
        ('"><script>', URGENCIES, URGENCY_FALLBACK, "medium"),
    ]
    for raw, allowed, fallback, expected in cases:
        got = validate_choice(raw, allowed, fallback)
        results.append(check(f"{raw!r} -> {expected!r}", got == expected, f"got {got!r}"))

    passed = sum(1 for r in results if r)
    print(f"\n{'-' * 56}\n  {passed}/{len(results)} checks passed\n{'-' * 56}\n")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(asyncio.run(main()))
