"""
One model call, several models behind it.

Global rules section 6.1: never single-try a model call. ADK takes a single
model per agent, so this wraps the ladder from config.py behind one BaseLlm and
walks it on recoverable errors.

The detail that makes this work: google_llm.Gemini reads the model id from
`llm_request.model`, not from its own `model` field, so switching models means
rewriting the request before each attempt.
"""
import logging
from typing import AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.models.google_llm import Gemini
from google.genai import types
from google.genai.errors import APIError
from pydantic import PrivateAttr

from .config import (
    ATTEMPTS_PER_MODEL,
    INITIAL_BACKOFF_SECONDS,
    MODEL_LADDER,
    RETRYABLE_STATUS,
)

logger = logging.getLogger(__name__)


class FallbackGemini(BaseLlm):
    """Tries each model in `ladder` until one answers."""

    ladder: list[str] = list(MODEL_LADDER)
    _delegates: dict = PrivateAttr(default_factory=dict)
    _last_model: str | None = PrivateAttr(default=None)
    _usage: dict = PrivateAttr(default_factory=lambda: {"input": 0, "output": 0, "calls": 0})

    def __init__(self, **data):
        data.setdefault("ladder", list(MODEL_LADDER))
        data.setdefault("model", data["ladder"][0])
        super().__init__(**data)

    def _delegate(self, model_name: str) -> Gemini:
        """One Gemini client per rung, built on first use."""
        if model_name not in self._delegates:
            self._delegates[model_name] = Gemini(
                model=model_name,
                retry_options=types.HttpRetryOptions(
                    attempts=ATTEMPTS_PER_MODEL,
                    initial_delay=INITIAL_BACKOFF_SECONDS,
                ),
            )
        return self._delegates[model_name]

    @property
    def last_model(self) -> str | None:
        """The rung that answered most recently, for the UI to report.

        One desk, one owner, so this is read straight after the run that set
        it. Two runs overlapping would see the later one win; that is a wrong
        label on a draft, not a wrong draft.
        """
        return self._last_model

    @property
    def usage(self) -> dict:
        """Tokens billed so far, counted by the API rather than estimated.

        Cumulative since process start; a caller takes a before/after
        difference around one run. Same single-owner caveat as `last_model`.
        """
        return dict(self._usage)

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        last_error = None

        for model_name in self.ladder:
            llm_request.model = model_name
            started = False
            billed = None
            try:
                async for response in self._delegate(model_name).generate_content_async(
                    llm_request, stream=stream
                ):
                    started = True
                    self._last_model = model_name
                    # Streaming repeats the figures on later chunks, so keep
                    # the latest and add it once the call finishes.
                    if response.usage_metadata is not None:
                        billed = response.usage_metadata
                    yield response
                if billed is not None:
                    # Thinking tokens are billed at the output rate.
                    self._usage["input"] += billed.prompt_token_count or 0
                    self._usage["output"] += ((billed.candidates_token_count or 0)
                                              + (billed.thoughts_token_count or 0))
                    self._usage["calls"] += 1
                return
            except APIError as exc:
                # Part of an answer is already out. Restarting would duplicate
                # it, so this one is not recoverable however tempting it looks.
                if started:
                    raise
                if exc.code not in RETRYABLE_STATUS:
                    raise
                last_error = exc
                logger.warning(
                    "Model %s returned %s, falling back to the next model.",
                    model_name,
                    exc.code,
                )

        logger.error("Every model in the ladder failed: %s", self.ladder)
        raise last_error
