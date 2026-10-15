"""
Save the demo queue, then put it back between takes.

    python tests/demo_queue.py save     # snapshot the queue as it stands now
    python tests/demo_queue.py show     # what is in the snapshot
    python tests/demo_queue.py reset    # wipe the queue and restore the snapshot

Filming usually takes several attempts, and each one leaves the queue dirty:
approvals clicked, drafts edited, new items processed on camera. `reset` puts
it back exactly as `save` found it, so take four looks like take one.

Needs GOOGLE_CLOUD_PROJECT set and `gcloud auth application-default login` done.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ecs_desk import store

SNAPSHOT = Path(__file__).parent / "demo_state.json"


def line(item: dict) -> str:
    return (f"  #{item.get('id'):<4} {item.get('status', '?'):<20} "
            f"{item.get('urgency', '?'):<7} {item.get('category', '?'):<11} "
            f"{str(item.get('language', ''))[:8]:<8} {str(item.get('subject', ''))[:40]}")


def save(uid: str) -> int:
    items = store.load_items(uid)
    if not items:
        print("Queue is empty - nothing worth snapshotting.")
        return 1
    owner = store._owner_ref(uid).get().to_dict() or {}
    SNAPSHOT.write_text(json.dumps(
        {"uid": uid, "next_id": owner.get("next_id", 0), "items": items},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved {len(items)} items to {SNAPSHOT.name}\n")
    for i in items:
        print(line(i))
    print()
    return 0


def show() -> int:
    if not SNAPSHOT.exists():
        print(f"No {SNAPSHOT.name} yet. Run: python tests/demo_queue.py save")
        return 1
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    print(f"\n{SNAPSHOT.name}: {len(snap['items'])} items, "
          f"counter at {snap['next_id']}\n")
    for i in snap["items"]:
        print(line(i))
    print()
    return 0


def reset(uid: str, assume_yes: bool) -> int:
    if not SNAPSHOT.exists():
        print(f"No {SNAPSHOT.name} to restore. Run `save` first.")
        return 1
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    current = store.load_items(uid)

    print(f"\nReplace the {len(current)} item(s) now in '{uid}' with the "
          f"{len(snap['items'])} saved ones:\n")
    for i in snap["items"]:
        print(line(i))

    if not assume_yes:
        print("\nThis deletes whatever is in the queue right now. It cannot be undone.")
        if input("Type 'reset' to confirm: ").strip().lower() != "reset":
            print("Nothing changed.")
            return 1

    for doc in store._items_ref(uid).stream():
        doc.reference.delete()
    for item in snap["items"]:
        store.save_item(item, uid)
    # Put the counter back too, so the next draft gets the id it would have had.
    store._owner_ref(uid).set({"next_id": snap["next_id"]}, merge=True)

    print(f"\nQueue restored: {len(snap['items'])} items, next draft will be "
          f"#{snap['next_id'] + 1}.\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["save", "show", "reset"])
    parser.add_argument("--uid", default=store.DEMO_UID)
    parser.add_argument("--yes", action="store_true", help="skip the confirmation")
    args = parser.parse_args()

    if args.action == "show":
        return show()
    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        print("Set GOOGLE_CLOUD_PROJECT first.")
        return 2
    return save(args.uid) if args.action == "save" else reset(args.uid, args.yes)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
