"""
ECS Desk - Day 4: approval dashboard + agent runner in one small web app.

Run (from the ecs-agents folder, with .venv active):
    python desk_server.py
Then open http://127.0.0.1:8080
"""
import base64
import json
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

from ecs_desk.agent import OUTBOX, root_agent  # noqa: E402

APP_NAME = "ecs_desk"
USER = "desk"
runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
app = FastAPI(title="ECS Desk")


# ---------- storage (swapped for Firestore on Day 5) ----------
def load_items() -> list:
    return json.loads(OUTBOX.read_text(encoding="utf-8")) if OUTBOX.exists() else []


def save_items(items: list) -> None:
    OUTBOX.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")


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
    return list(reversed(load_items()))


@app.post("/api/process")
async def process(body: ProcessIn):
    text = body.text.strip()
    if not text and not body.image_b64:
        raise HTTPException(400, "Add a message or attach an image.")

    before = len(load_items())
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
    async for _ in runner.run_async(user_id=USER, session_id=session.id, new_message=message):
        pass

    done = await runner.session_service.get_session(
        app_name=APP_NAME, user_id=USER, session_id=session.id
    )
    items = load_items()
    if len(items) <= before:
        raise HTTPException(500, "The agents finished but no draft was saved. Please try again.")

    new = items[-1]
    new["intake"] = done.state.get("intake", "")
    new["triage"] = done.state.get("triage", "")
    new["source_text"] = text[:600]
    new["had_image"] = bool(body.image_b64)
    save_items(items)
    return new


@app.post("/api/items/{item_id}")
def update_item(item_id: int, body: UpdateIn):
    if body.status not in {"waiting_for_approval", "approved", "rejected"}:
        raise HTTPException(400, "Unknown status.")
    items = load_items()
    for item in items:
        if item["id"] == item_id:
            if body.draft_reply is not None and body.draft_reply != item.get("draft_reply"):
                item["draft_reply"] = body.draft_reply
                item["edited_by_human"] = True
            item["status"] = body.status
            item["decided"] = (
                datetime.now().strftime("%Y-%m-%d %H:%M")
                if body.status != "waiting_for_approval"
                else None
            )
            save_items(items)
            return item
    raise HTTPException(404, "Item not found.")


if __name__ == "__main__":
    import uvicorn

    print("\n  ECS Desk running at  http://127.0.0.1:8080\n")
    uvicorn.run(app, host="127.0.0.1", port=8080)
