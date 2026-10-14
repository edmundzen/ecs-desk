"""
ECS Desk - Day 3: Intake -> Triage -> Draft (+ save for human approval)
Nothing is ever sent automatically. Every draft waits in outbox.json for a human.
"""
import json
from datetime import datetime
from pathlib import Path

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.models.google_llm import Gemini
from google.genai import types

MODEL = Gemini(
    model="gemini-3.6-flash",
    retry_options=types.HttpRetryOptions(attempts=5, initial_delay=2),
)

OUTBOX = Path(__file__).parent / "outbox.json"


# ---------- TOOL: save a draft as "waiting for approval" ----------
def save_for_approval(
    category: str, urgency: str, customer: str, subject: str, draft_reply: str
) -> dict:
    """Saves a drafted reply to the approval queue. Nothing is sent to anyone.

    Args:
        category: quote_request, booking, complaint, invoice or other.
        urgency: high, medium or low.
        customer: name and company of the person or business this is about.
        subject: a short subject line for the reply or note.
        draft_reply: the full draft text for a human to review.

    Returns:
        A dict with the item id and its status.
    """
    items = json.loads(OUTBOX.read_text(encoding="utf-8")) if OUTBOX.exists() else []
    item = {
        "id": len(items) + 1,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "category": category,
        "urgency": urgency,
        "customer": customer,
        "subject": subject,
        "draft_reply": draft_reply,
        "status": "waiting_for_approval",
    }
    items.append(item)
    OUTBOX.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"id": item["id"], "status": item["status"]}


# ---------- 1. INTAKE ----------
intake_agent = LlmAgent(
    name="intake_agent",
    model=MODEL,
    description="Reads an incoming email, invoice or chat message and extracts the facts.",
    instruction="""
You are the Intake agent for ECS Desk, a back-office assistant for small businesses.

Read the user's message and any attached image or PDF.
Extract FACTS ONLY. Do not reply to the customer. Do not give advice.

Answer in exactly this format:
SOURCE: email | invoice | chat message | other
LANGUAGE: <language the sender wrote in, e.g. English, Chinese, Malay, Tamil, Singlish>
FROM: <who SENT or ISSUED it - not who it is addressed to>
TO: <who it is addressed to, or "unknown">
COMPANY: <the sender's company, or "unknown">
SUMMARY: <one or two plain sentences>
KEY DETAILS:
- <amounts, dates, items, quantities, contact details you can actually see>

Rules:
- Pasted text with no email headers (no To/From/Subject lines) is a "chat message".
- On an invoice, FROM is the supplier who issued it; TO is the "Bill To" customer.
- If something is not visible, write "unknown". Never guess.
- Never copy card numbers, bank account numbers, UEN or ID numbers. Write "[hidden]".
""",
    output_key="intake",
)

# ---------- 2. TRIAGE ----------
triage_agent = LlmAgent(
    name="triage_agent",
    model=MODEL,
    description="Classifies the intake result and decides urgency and next step.",
    instruction="""
You are the Triage agent for ECS Desk.

Here is what the Intake agent found:
{intake}

Answer in exactly this format:
CATEGORY: quote_request | booking | complaint | invoice | other
URGENCY: high | medium | low
REASON: <one short sentence>
NEXT STEP: <one action>

Urgency rules:
- high: angry customer, wrong information already sent to customers, payment overdue,
        or anything affecting a client's customers today.
- medium: new quote or booking request, or an invoice due within 7 days.
- low: general questions, newsletters, FYI messages, invoices due later.

Do not write the reply itself. A human reviews everything.
""",
    output_key="triage",
)

# ---------- 3. DRAFT + SAVE FOR APPROVAL ----------
draft_agent = LlmAgent(
    name="draft_agent",
    model=MODEL,
    description="Drafts a reply or internal note and saves it for human approval.",
    instruction="""
You are the Draft agent for ECS Desk. You write drafts; a human approves them.

Facts:
{intake}

Decision:
{triage}

Write ONE draft based on the category:
- complaint: a calm, sincere apology. Acknowledge the problem, say the owner is looking
  into it personally, and ask for a good time to call. Do NOT promise refunds,
  discounts or fixed dates.
- quote_request or booking: a warm reply thanking them, and ask only for the details
  still missing (e.g. outlet addresses, preferred dates, budget range).
  Never state prices or confirm a booking.
- invoice: an INTERNAL note for the business owner (not a reply to the supplier):
  supplier, invoice number, total, due date, and "please check and approve payment".
- other: a short, polite reply asking what they need help with.

Language: reply in the SAME language the customer used (see LANGUAGE in the facts).
- Chinese -> reply in Simplified Chinese. Malay -> Malay. Tamil -> Tamil.
- Singlish or mixed -> warm, plain standard English (never mock or copy Singlish).
- Internal invoice notes for the owner are always in English.
Put the subject line in English so the owner can scan the queue.

Style: short sentences, friendly, plain language, sign off as "[Your name]".

Then call the save_for_approval tool with category, urgency, customer, subject and the
draft text. After the tool returns, reply with:
"Draft #<id> saved - waiting for your approval. Nothing has been sent."
followed by the draft so the user can read it.
""",
    tools=[save_for_approval],
    output_key="draft",
)

# ---------- PIPELINE ----------
root_agent = SequentialAgent(
    name="ecs_desk",
    description="ECS Desk: intake, triage and drafting for small-business admin. Human approves.",
    sub_agents=[intake_agent, triage_agent, draft_agent],
)
