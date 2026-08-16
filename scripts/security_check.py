from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = (ROOT / "index.html", ROOT / "data.json")


def main() -> None:
    forbidden_names = ("STRAVA_CLIENT_SECRET", "STRAVA_REFRESH_TOKEN")
    for path in PUBLIC_FILES:
        if not path.exists():
            raise SystemExit(f"Missing public artifact: {path.name}")
        payload = path.read_text(encoding="utf-8")
        for name in forbidden_names:
            value = os.environ.get(name)
            if value and value in payload:
                raise SystemExit(f"Secret value leaked into {path.name}")
        if "refresh_token.enc" in payload or "state/activity_ledger" in payload:
            raise SystemExit(f"Private state path leaked into {path.name}")
    print("Public artifact security check passed.")


if __name__ == "__main__":
    main()
