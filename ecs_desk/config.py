"""
Configuration for ECS Desk. Values that go stale live here, not in code.

Model names in particular change often, so the ladder is data: edit this list,
not agent.py, when a model is renamed or retired.
"""

# Ordered fallback ladder (project rules section 1). The first model that
# answers wins; a recoverable failure moves to the next one.
MODEL_LADDER = [
    "gemini-3.6-flash",       # primary
    "gemini-3.1-flash-lite",  # high availability
    "gemini-flash-latest",    # dynamic alias
    "gemini-3.7-flash",       # deeper reasoning
]

# HTTP status codes worth trying the next model for. Anything else is a real
# error (bad request, auth failure) and is surfaced immediately.
RETRYABLE_STATUS = frozenset({429, 500, 503, 404})

# Attempts against a single model before moving down the ladder. The genai
# client handles the backoff; this just bounds how long one model is given.
ATTEMPTS_PER_MODEL = 2
INITIAL_BACKOFF_SECONDS = 2

# Enumerated fields the agents fill in. Model output is validated against these
# before it is stored or rendered (global rules section 2).
CATEGORIES = frozenset({"quote_request", "booking", "complaint", "invoice", "other"})
URGENCIES = frozenset({"high", "medium", "low"})
STATUSES = frozenset({"waiting_for_approval", "approved", "rejected"})

CATEGORY_FALLBACK = "other"
URGENCY_FALLBACK = "medium"


def validate_choice(value: str, allowed: frozenset, fallback: str) -> str:
    """Forces a model-supplied field into the known set.

    The agents are told to answer with one of a fixed list, but a model is not a
    contract. Anything unexpected becomes the fallback rather than reaching the
    database or a CSS class name.
    """
    cleaned = (value or "").strip().lower().replace(" ", "_").replace("-", "_")
    return cleaned if cleaned in allowed else fallback
