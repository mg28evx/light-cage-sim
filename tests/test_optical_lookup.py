import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path

from optical_lookup import build_optical_weekly_profile


class OpticalLookupTests(unittest.TestCase):
    def _write_weekly_observations(self, years):
        handle = tempfile.NamedTemporaryFile("w", newline="", suffix=".csv", delete=False)
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        with handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "center_id", "date", "source", "tss", "spm", "turbidity_fnu",
                    "chl", "cdom_a440", "cdom_a443", "kd490", "zsd", "quality",
                ],
            )
            writer.writeheader()
            for year in years:
                for day in range(1, 5):
                    writer.writerow({
                        "center_id": "pilpilehue",
                        "date": date.fromisocalendar(year, 10, day).isoformat(),
                        "source": "test",
                        "tss": "8.0",
                        "spm": "",
                        "turbidity_fnu": "8.0",
                        "chl": "1.5",
                        "cdom_a440": "0.8",
                        "cdom_a443": "",
                        "kd490": "0.2",
                        "zsd": "",
                        "quality": "usable",
                    })
        return handle.name

    def test_one_year_history_can_mark_week_useful(self):
        end_year = date.today().year - 1
        observations_path = self._write_weekly_observations([end_year])

        profile = build_optical_weekly_profile(
            center="pilpilehue",
            observations_path=observations_path,
            source="cache",
            years_back=1,
        )

        week_10 = next(week for week in profile["weeks"] if week["iso_week"] == 10)
        self.assertTrue(week_10["useful"])
        self.assertEqual(week_10["status"], "util")
        self.assertEqual(week_10["years"], [end_year])

    def test_two_year_history_still_requires_two_represented_years(self):
        end_year = date.today().year - 1
        observations_path = self._write_weekly_observations([end_year])

        profile = build_optical_weekly_profile(
            center="pilpilehue",
            observations_path=observations_path,
            source="cache",
            years_back=2,
        )

        week_10 = next(week for week in profile["weeks"] if week["iso_week"] == 10)
        self.assertFalse(week_10["useful"])
        self.assertEqual(week_10["status"], "limitada")

    def test_target_year_week_can_query_current_year_data(self):
        target_year = date.today().year
        observations_path = self._write_weekly_observations([target_year])

        historical = build_optical_weekly_profile(
            center="pilpilehue",
            observations_path=observations_path,
            source="cache",
            years_back=1,
        )
        historical_week_10 = next(week for week in historical["weeks"] if week["iso_week"] == 10)
        self.assertEqual(historical_week_10["status"], "sin_datos")

        targeted = build_optical_weekly_profile(
            center="pilpilehue",
            observations_path=observations_path,
            source="cache",
            target_year=target_year,
            target_week=10,
        )

        targeted_week_10 = next(week for week in targeted["weeks"] if week["iso_week"] == 10)
        self.assertEqual(targeted["period_mode"], "iso_week")
        self.assertEqual(targeted["target_year"], target_year)
        self.assertEqual(targeted["target_week"], 10)
        self.assertEqual(targeted_week_10["status"], "util")
        self.assertEqual(targeted_week_10["years"], [target_year])


if __name__ == "__main__":
    unittest.main()
