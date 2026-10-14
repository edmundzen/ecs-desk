"""
ECS Desk - Day 4: approval dashboard + agent runner in one small web app.

Run (from the ecs-agents folder, with .venv active):
    python desk_server.py
Then open http://127.0.0.1:8080
"""
import base64
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

HERE = Path(__file__).parent
load_dotenv(HERE / "ecs_desk" / ".env")  # same API key file adk web uses

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

from ecs_desk import store  # noqa: E402
from ecs_desk.agent import MODEL, root_agent  # noqa: E402
from ecs_desk.config import STATUSES  # noqa: E402

logger = logging.getLogger(__name__)

APP_NAME = "ecs_desk"
USER = "desk"
runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
app = FastAPI(title="ECS Desk")

LANGUAGE_LINE = re.compile(r"^LANGUAGE:\s*([^\r\n]+)", re.MULTILINE | re.IGNORECASE)


# ---------- request shapes ----------
class ProcessIn(BaseModel):
    text: str = ""
    image_b64: Optional[str] = None
    mime_type: Optional[str] = None


class UpdateIn(BaseModel):
    status: str
    draft_reply: Optional[str] = None


# ---------- routes ----------
@app.get("/", response_class=HTMLResponse)
def home():
    return (HERE / "desk.html").read_text(encoding="utf-8")


@app.get("/api/items")
def list_items():
    return list(reversed(store.load_items()))


@app.get("/api/health")
def health():
    """Readiness: proves the process is up and Firestore answers.

    Not /healthz - Google's front end intercepts that path on Cloud Run and
    returns its own 404 before the request reaches the container.
    """
    store.load_items()
    return {"ok": True}


@app.post("/api/process")
async def process(body: ProcessIn):
    text = body.text.strip()
    if not text and not body.image_b64:
        raise HTTPException(400, "Add a message or attach an image.")

    highest_before = max((i["id"] for i in store.load_items()), default=0)
    usage_before = MODEL.usage
    session = await runner.session_service.create_session(app_name=APP_NAME, user_id=USER)

    parts = []
    if text:
        parts.append(types.Part(text=text))
    if body.image_b64:
        parts.append(
            types.Part.from_bytes(
                data=base64.b64decode(body.image_b64),
                mime_type=body.mime_type or "image/png",
            )
        )
        if not text:
            parts.append(types.Part(text="process this"))

    message = types.Content(role="user", parts=parts)
    try:
        async for _ in runner.run_async(user_id=USER, session_id=session.id, new_message=message):
            pass
    except Exception:
        # The model ladder in config.py has already been walked by this point,
        # so every model refused. Say so plainly instead of a bare 500.
        logger.exception("Agent run failed")
        raise HTTPException(503, "The AI service is busy right now. Please try again in a moment.")

    done = await runner.session_service.get_session(
        app_name=APP_NAME, user_id=USER, session_id=session.id
    )
    fresh = [i for i in store.load_items() if i["id"] > highest_before]
    if not fresh:
        raise HTTPException(500, "The agents finished but no draft was saved. Please try again.")

    new = fresh[-1]
    intake = done.state.get("intake", "")
    language = LANGUAGE_LINE.search(intake)
    extras = {
        "intake": intake,
        "triage": done.state.get("triage", ""),
        "language": language.group(1).strip() if language else "English",
        "source_text": text[:600],
        "had_image": bool(body.image_b64),
        # Which rung of the ladder actually answered. The dashboard shows this
        # instead of claiming the primary model every time.
        "model": MODEL.last_model,
        # Tokens this message actually cost, as counted by the API across all
        # three agents. Lets the cost estimate be measured, not guessed.
        "tokens_in": MODEL.usage["input"] - usage_before["input"],
        "tokens_out": MODEL.usage["output"] - usage_before["output"],
        "model_calls": MODEL.usage["calls"] - usage_before["calls"],
    }
    return store.update_item(new["id"], extras) or {**new, **extras}


@app.post("/api/items/{item_id}")
def update_item(item_id: int, body: UpdateIn):
    if body.status not in STATUSES:
        raise HTTPException(400, "Unknown status.")

    item = store.get_item(item_id)
    if item is None:
        raise HTTPException(404, "Item not found.")

    changes = {"status": body.status}
    if body.draft_reply is not None and body.draft_reply != item.get("draft_reply"):
        changes["draft_reply"] = body.draft_reply
        changes["edited_by_human"] = True
    changes["decided"] = (
        datetime.now().strftime("%Y-%m-%d %H:%M")
        if body.status != "waiting_for_approval"
        else None
    )
    return store.update_item(item_id, changes)


if __name__ == "__main__":
    import uvicorn

    print("\n  ECS Desk running at  http://127.0.0.1:8080\n")
    uvicorn.run(app, host="127.0.0.1", port=8080)
