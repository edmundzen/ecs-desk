"""
Empties the approval queue. Use it after an eval run, before a demo.

    python tests/clear_queue.py              # asks first, shows what it will delete
    python tests/clear_queue.py --yes        # no prompt
    python tests/clear_queue.py --uid other  # a queue other than the default

Needs GOOGLE_CLOUD_PROJECT set and `gcloud auth application-default login` done.
Deleting is permanent, so it prints the queue and waits for you to confirm.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ecs_desk import store


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uid", default=store.DEMO_UID)
    parser.add_argument("--yes", action="store_true", help="skip the confirmation")
    parser.add_argument("--keep-counter", action="store_true",
                        help="leave the id counter alone, so new items keep counting up")
    args = parser.parse_args()

    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        print("Set GOOGLE_CLOUD_PROJECT first.")
        return 2

    items = store.load_items(args.uid)
    if not items:
        print(f"Queue '{args.uid}' is already empty.")
        return 0

    print(f"\nQueue '{args.uid}' holds {len(items)} items:\n")
    for item in items:
        print(f"  #{item.get('id'):<4} {item.get('urgency','?'):<7} "
              f"{item.get('category','?'):<14} {str(item.get('subject',''))[:44]}")

    if not args.yes:
        print(f"\nDelete all {len(items)} permanently? This cannot be undone.")
        if input("Type 'delete' to confirm: ").strip().lower() != "delete":
            print("Nothing deleted.")
            return 1

    for doc in store._items_ref(args.uid).stream():
        doc.reference.delete()
    if not args.keep_counter:
        store._owner_ref(args.uid).set({"next_id": 0}, merge=True)

    print(f"\nDeleted {len(items)} items from '{args.uid}'."
          f"{'' if args.keep_counter else ' Queue numbers restart at 1.'}\n")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
