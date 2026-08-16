import json
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.state import decrypt_refresh_token
from scripts.strava_client import TemporaryStravaError, TokenBundle
from scripts.update_strava import run_update
from tests.helpers import ROOT


class RefreshClient:
    def refresh(self, client_id, client_secret, refresh_token):
        return TokenBundle("access", "rotated-refresh", 1)


class FailingApiClient:
    def list_club_activities(self, club_id):
        raise TemporaryStravaError("temporary")


def factory(access_token=None):
    return FailingApiClient() if access_token else RefreshClient()


class UpdateSafetyTests(unittest.TestCase):
    def test_api_failure_preserves_data_but_persists_rotated_token(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ("config", "bootstrap", "state"):
                shutil.copytree(ROOT / folder, root / folder)
            # The repository may contain live encrypted state after a real update.
            # This test exercises bootstrap rotation with its own synthetic secret.
            (root / "state/refresh_token.enc").unlink(missing_ok=True)
            original = '{"known":"good"}\n'
            (root / "data.json").write_text(original, encoding="utf-8")
            challenge_path = root / "config/challenge.json"
            challenge = json.loads(challenge_path.read_text(encoding="utf-8"))
            challenge["club_id"] = 99
            challenge_path.write_text(json.dumps(challenge), encoding="utf-8")
            with self.assertRaises(TemporaryStravaError):
                run_update(
                    root,
                    {"STRAVA_CLIENT_ID": "id", "STRAVA_CLIENT_SECRET": "secret", "STRAVA_REFRESH_TOKEN": "bootstrap"},
                    datetime(2026, 8, 16, 12, tzinfo=ZoneInfo("Europe/Madrid")),
                    factory,
                )
            self.assertEqual((root / "data.json").read_text(encoding="utf-8"), original)
            encrypted = (root / "state/refresh_token.enc").read_bytes()
            self.assertEqual(decrypt_refresh_token(encrypted, "secret"), "rotated-refresh")

    def test_retirement_guard_needs_no_credentials_or_client(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "config", root / "config")
            result = run_update(
                root, {}, datetime(2026, 9, 1, 0, tzinfo=ZoneInfo("Europe/Madrid")),
                lambda **_: self.fail("client must not be created"),
            )
            self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
