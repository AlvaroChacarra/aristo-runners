import json
import subprocess
import unittest

from tests.helpers import ROOT


class FrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.data = json.loads((ROOT / "data.json").read_text(encoding="utf-8"))
        cls.logic = cls.html.split(
            "/* TESTABLE_COMPETITION_LOGIC_START */", 1
        )[1].split("/* TESTABLE_COMPETITION_LOGIC_END */", 1)[0]

    def run_logic(self, expression):
        result = subprocess.run(
            ["node", "-e", self.logic + "\n" + expression],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    def test_reads_v2_data_without_hardcoded_competitors(self):
        self.assertIn('fetch("./data.json"', self.html)
        self.assertIn("data.schema_version!==2", self.html)
        for hardcoded_name in (
            "Borja Glez",
            "Pablo Meijide",
            "Kept ES",
            "Antonio Meijide",
        ):
            self.assertNotIn(hardcoded_name, self.html)

    def test_v3_brand_author_and_routes(self):
        self.assertIn('name:"ARISTO RUNNERS"', self.html)
        self.assertIn('challengeName:"SUMMER 125"', self.html)
        self.assertIn('authorSlug:"alvaro-lopez-chacarra"', self.html)
        self.assertIn('<meta name="author" content="Alvaro López-Chacarra">', self.html)
        self.assertIn('"WebApplication"', self.html)
        self.assertIn("new URLSearchParams(location.search)", self.html)
        self.assertNotIn("DASHBOARD V2", self.html)

    def test_required_rendering_contract_is_present(self):
        required = (
            "renderHeader",
            "renderHero",
            "renderPodium",
            "renderStandings",
            "renderRunnerRow",
            "renderRelegationCut",
            "renderGroupChart",
            "renderPerformance",
            "renderDataStatus",
            "renderFooter",
            "getRunnerCompetitionState",
            "isCreator",
            "isRelegationRunner",
            "isRelegationCutInPodium",
            "getLastSafeRank",
            "getNextFinisher",
        )
        for name in required:
            self.assertIn("function " + name + "(", self.html)
        home_start = self.html.index("function renderHome")
        order = (
            self.html.index("renderHero()+renderPodium()+renderStandings()", home_start),
            self.html.index('"PACE TO "', home_start),
            self.html.index("renderPerformance()+renderDataStatus()", home_start),
        )
        self.assertLess(order[0], order[1])
        self.assertLess(order[1], order[2])

    def test_accessibility_motion_and_chart_fallbacks(self):
        self.assertIn("@media (prefers-reduced-motion:reduce)", self.html)
        self.assertIn('aria-label="Corte de descenso"', self.html)
        self.assertIn('aria-valuetext="', self.html)
        self.assertIn('role="img"', self.html)
        self.assertIn("chartUnavailable", self.html)
        self.assertIn('legend:{display:true', self.html)

    def test_no_emojis_frameworks_or_secret_references(self):
        for forbidden in ("🏆", "🎯", "🦕", "📏", "🚀"):
            self.assertNotIn(forbidden, self.html)
        lowered = self.html.lower()
        for framework in ("react", "next.js", "vue", "svelte", "tailwind", "vite"):
            self.assertNotIn(framework, lowered)
        self.assertNotIn("strava.com/api", lowered)
        self.assertNotIn("STRAVA_CLIENT_SECRET", self.html)
        self.assertNotIn("STRAVA_REFRESH_TOKEN", self.html)

    def test_podium_tiers_are_exact_and_semantic(self):
        result = self.run_logic(
            'console.log(JSON.stringify([1,2,3,4].map(rank=>'
            'getPodiumTier({rank}))));'
        )
        self.assertEqual(result, ["gold", "silver", "bronze", None])
        self.assertIn(
            "const podium=runners.filter(runner=>runner.rank<=3)",
            self.html,
        )
        self.assertIn("filter(runner=>runner.rank>3)", self.html)

    def test_red_zone_is_exactly_bottom_three(self):
        result = self.run_logic(
            'const twelve=Array.from({length:12},(_,i)=>({rank:i+1}));'
            'const five=Array.from({length:5},(_,i)=>({rank:i+1}));'
            'console.log(JSON.stringify({'
            'safe12:getLastSafeRank(twelve),'
            'red12:twelve.filter(r=>isRelegationRunner(r,twelve)).map(r=>r.rank),'
            'safe5:getLastSafeRank(five),'
            'red5:five.filter(r=>isRelegationRunner(r,five)).map(r=>r.rank)'
            '}));'
        )
        self.assertEqual(result["safe12"], 9)
        self.assertEqual(result["red12"], [10, 11, 12])
        self.assertEqual(result["safe5"], 2)
        self.assertEqual(result["red5"], [3, 4, 5])
        self.assertEqual(self.html.count('data-testid="relegation-cut"'), 1)

    def test_small_field_cut_moves_before_the_first_red_podium_runner(self):
        result = self.run_logic(
            'const five=Array.from({length:5},(_,i)=>({rank:i+1}));'
            'const six=Array.from({length:6},(_,i)=>({rank:i+1}));'
            'console.log(JSON.stringify({'
            'five:isRelegationCutInPodium(five),'
            'six:isRelegationCutInPodium(six)'
            '}));'
        )
        self.assertTrue(result["five"])
        self.assertFalse(result["six"])
        self.assertIn(
            "cut+renderPodiumCard(runner)",
            self.html,
        )

    def test_partial_elevation_is_explained_and_target_contrast_is_aa(self):
        self.assertIn("El desnivel acumulado es parcial", self.html)
        self.assertIn("El histórico no incluye el desnivel completo", self.html)
        self.assertIn(
            'borderColor:"#92989F",backgroundColor:"#92989F"',
            self.html,
        )
        self.assertIn(".milestone-pct", self.html)
        self.assertIn("color:var(--grey)}", self.html)

    def test_creator_uses_only_slug_and_keeps_sport_state(self):
        result = self.run_logic(
            'const runners=Array.from({length:12},(_,i)=>({'
            'rank:i+1,slug:i===10?"alvaro-lopez-chacarra":"r"+(i+1),'
            'completed:false,remaining_km:120-i,on_track:false}));'
            'const creator=runners[10];'
            'console.log(JSON.stringify({'
            'bySlug:isCreator(creator),'
            'notByName:isCreator({name:"Alvaro López-Chacarra",slug:"other"}),'
            'count:runners.filter(isCreator).length,'
            'rank:creator.rank,'
            'states:getRunnerCompetitionState(creator,runners)'
            '}));'
        )
        self.assertTrue(result["bySlug"])
        self.assertFalse(result["notByName"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["rank"], 11)
        self.assertIn("ZONA ROJA", result["states"])
        actual_creator = [
            runner for runner in self.data["runners"]
            if runner["slug"] == "alvaro-lopez-chacarra"
        ]
        self.assertEqual(len(actual_creator), 1)

    def test_creator_can_coexist_with_podium(self):
        result = self.run_logic(
            'const runners=['
            '{rank:1,slug:"r1",completed:true,remaining_km:0,on_track:true},'
            '{rank:2,slug:"alvaro-lopez-chacarra",completed:true,remaining_km:0,on_track:true},'
            '{rank:3,slug:"r3",completed:false,remaining_km:1,on_track:true},'
            '{rank:4,slug:"r4",completed:false,remaining_km:2,on_track:false}];'
            'console.log(JSON.stringify({'
            'creator:isCreator(runners[1]),'
            'tier:getPodiumTier(runners[1]),'
            'states:getRunnerCompetitionState(runners[1],runners)'
            '}));'
        )
        self.assertTrue(result["creator"])
        self.assertEqual(result["tier"], "silver")
        self.assertIn("P2", result["states"])
        self.assertIn("125 CLUB", result["states"])

    def test_next_finisher_excludes_completed_and_handles_all_complete(self):
        result = self.run_logic(
            'const runners=['
            '{rank:1,slug:"done",completed:true,remaining_km:0},'
            '{rank:2,slug:"far",completed:false,remaining_km:8},'
            '{rank:3,slug:"near",completed:false,remaining_km:2}];'
            'const allDone=runners.map(r=>({...r,completed:true}));'
            'console.log(JSON.stringify({'
            'next:getNextFinisher(runners).slug,'
            'none:getNextFinisher(allDone)'
            '}));'
        )
        self.assertEqual(result["next"], "near")
        self.assertIsNone(result["none"])

    def test_runner_row_handles_zero_completed_long_and_missing_values(self):
        result = self.run_logic(
            'const runners=['
            '{rank:1,slug:"zero",name:"Francisco Javier Moreno Muñoz & <Team>",'
            'km:0,progress_pct:0,remaining_km:125,completed:false,on_track:false},'
            '{rank:2,slug:"done",name:"Done",km:125,progress_pct:100,remaining_km:0,completed:true,on_track:true},'
            '{rank:3,slug:"over",name:"Over",km:160,progress_pct:128,remaining_km:0,completed:true,on_track:true},'
            '{rank:4,slug:"missing",name:"Missing",completed:false,on_track:false}];'
            'console.log(JSON.stringify(runners.map(r=>renderRunnerRow(r,runners,125))));'
        )
        self.assertIn("0,0", result[0])
        self.assertIn("&amp;", result[0])
        self.assertIn("&lt;Team&gt;", result[0])
        self.assertIn("125 CLUB", result[1])
        self.assertIn('aria-valuenow="100"', result[2])
        self.assertNotIn("NaN", result[3])
        self.assertNotIn("undefined", result[3])


if __name__ == "__main__":
    unittest.main()
