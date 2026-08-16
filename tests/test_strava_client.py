import unittest

from scripts.strava_client import StravaClient, TemporaryStravaError


class Transport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, headers, data, timeout):
        self.calls.append((method, url, headers, data, timeout))
        return self.responses.pop(0)


class StravaClientTests(unittest.TestCase):
    def test_pagination_until_short_page(self):
        transport = Transport([(200, [{"id": 1}, {"id": 2}], {}), (200, [{"id": 3}], {})])
        client = StravaClient("access", transport=transport, sleep=lambda _: None)
        self.assertEqual([item["id"] for item in client.list_club_activities(99, per_page=2)], [1, 2, 3])
        self.assertIn("page=1", transport.calls[0][1])
        self.assertIn("page=2", transport.calls[1][1])

    def test_empty_first_page(self):
        transport = Transport([(200, [], {})])
        self.assertEqual(StravaClient("access", transport=transport).list_club_activities(99), [])

    def test_refresh_token_rotation_is_returned(self):
        transport = Transport([(200, {"access_token": "new-access", "refresh_token": "rotated", "expires_at": 7}, {})])
        bundle = StravaClient(transport=transport).refresh("id", "secret", "old")
        self.assertEqual(bundle.refresh_token, "rotated")
        self.assertEqual(bundle.access_token, "new-access")
        self.assertIn(b"grant_type=refresh_token", transport.calls[0][3])

    def test_temporary_api_error_is_retried_then_classified(self):
        transport = Transport([(503, {"message": "unavailable"}, {})] * 5)
        with self.assertRaises(TemporaryStravaError):
            StravaClient("access", transport=transport, sleep=lambda _: None).list_club_activities(99)
        self.assertEqual(len(transport.calls), 5)


if __name__ == "__main__":
    unittest.main()
