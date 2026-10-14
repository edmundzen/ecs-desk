"""
The approval queue, stored in Firestore.

Replaces outbox.json, which could not survive Cloud Run: the filesystem is
per-instance and in-memory, so a cold start wiped the queue and two instances
disagreed about what was in it.

Layout follows the project rules: /users/{uid}/items/{id}. Until sign-in is
added the uid is a single constant, so turning auth on later means passing a
real uid in rather than migrating any data.
"""
import os
from datetime import datetime, timezone

from google.cloud import firestore

# One owner for now. When Firebase Auth lands this becomes the verified uid
# from the token and nothing else about this module changes.
DEMO_UID = os.environ.get("ECS_DESK_UID", "demo-owner")

_client = None


def client() -> firestore.Client:
    global _client
    if _client is None:
        project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT")
        _client = firestore.Client(project=project) if project else firestore.Client()
    return _client


def _owner_ref(uid: str = DEMO_UID):
    return client().collection("users").document(uid)


def _items_ref(uid: str = DEMO_UID):
    return _owner_ref(uid).collection("items")


# One counter document means every allocation contends on the same row, and
# Firestore's default of 5 retries runs out under a burst. A desk queue writes
# a handful of items a minute, so the contention ceiling (~1 sustained write a
# second on one document) is far above anything this app will see; the headroom
# is here so a burst of parallel submissions degrades into waiting, not errors.
ID_TRANSACTION_ATTEMPTS = 20


def next_id(uid: str = DEMO_UID) -> int:
    """Allocates the next queue number atomically.

    The old `len(items) + 1` handed the same id to two messages that arrived
    together. A transaction on a single counter cannot.
    """
    owner = _owner_ref(uid)
    transaction = client().transaction(max_attempts=ID_TRANSACTION_ATTEMPTS)

    @firestore.transactional
    def allocate(tx) -> int:
        snapshot = owner.get(transaction=tx)
        current = (snapshot.to_dict() or {}).get("next_id", 0) if snapshot.exists else 0
        allocated = current + 1
        tx.set(owner, {"next_id": allocated}, merge=True)
        return allocated

    return allocate(transaction)


def clean(data: dict) -> dict:
    """Drops None values, which Firestore stores as nulls nobody wants."""
    return {k: v for k, v in data.items() if v is not None}


def save_item(item: dict, uid: str = DEMO_UID) -> dict:
    item = clean(item)
    item.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    _items_ref(uid).document(str(item["id"])).set(item)
    return item


def load_items(uid: str = DEMO_UID) -> list:
    """Every item for this owner, oldest first."""
    return [doc.to_dict() for doc in _items_ref(uid).order_by("id").stream()]


def get_item(item_id: int, uid: str = DEMO_UID) -> dict | None:
    snapshot = _items_ref(uid).document(str(item_id)).get()
    return snapshot.to_dict() if snapshot.exists else None


def update_item(item_id: int, changes: dict, uid: str = DEMO_UID) -> dict | None:
    """Merges changes into one item. Returns the stored item, or None if absent.

    Here None means "clear this field", not "skip it": reopening an item for
    review has to wipe the decided timestamp, not leave yesterday's behind.
    """
    doc = _items_ref(uid).document(str(item_id))
    if not doc.get().exists:
        return None
    merged = {
        key: (firestore.DELETE_FIELD if value is None else value)
        for key, value in changes.items()
    }
    doc.set(merged, merge=True)
    return doc.get().to_dict()
