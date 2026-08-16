import unittest

from tests.helpers import ROOT


class FrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_reads_data_json_and_has_no_runner_array(self):
        self.assertIn("fetch('./data.json'", self.html)
        self.assertNotIn("const runners =", self.html)

    def test_v2_has_home_and_runner_routes(self):
        self.assertIn("DASHBOARD V2", self.html)
        self.assertIn("new URLSearchParams(location.search).get('runner')", self.html)
        self.assertIn("Eficiencia de las salidas", self.html)
        self.assertIn("Hitos del reto", self.html)
        self.assertIn("schema_version!==2", self.html)

    def test_objective_copy_is_loaded_from_data(self):
        self.assertNotIn("120 km", self.html)
        self.assertNotIn("125 km", self.html)
        self.assertIn("challenge.objective_per_runner_km", self.html)
        self.assertIn("challenge.objective_total_km", self.html)
        self.assertNotIn("OBJ_PER_RUNNER", self.html)

    def test_no_strava_call_or_secret_reference(self):
        self.assertNotIn("strava.com/api", self.html.lower())
        self.assertNotIn("STRAVA_CLIENT_SECRET", self.html)
        self.assertNotIn("STRAVA_REFRESH_TOKEN", self.html)


if __name__ == "__main__":
    unittest.main()
