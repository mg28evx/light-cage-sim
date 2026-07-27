import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "confgs"
LAMP_DIR = ROOT / "uploaded_lamps"


class ReconstructionAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(
            (CONFIG_DIR / "reconstruction_assets_manifest.json").read_text(encoding="utf-8")
        )

    def test_manifest_targets_exist(self):
        for reconstruction in self.manifest["reconstructions"].values():
            for filename in reconstruction.get("configs", []):
                self.assertTrue((CONFIG_DIR / filename).is_file(), filename)
            for filename in reconstruction.get("lamps", []):
                self.assertTrue((LAMP_DIR / filename).is_file(), filename)

    def test_leclercq_geometry_and_extended_green_source(self):
        two_b = json.loads((CONFIG_DIR / "leclercq_2011_2b.json").read_text())
        six_c = json.loads((CONFIG_DIR / "leclercq_2011_6c.json").read_text())
        four_g = json.loads((CONFIG_DIR / "leclercq_2011_4g.json").read_text())
        self.assertEqual(two_b["env"]["x"], 20.0)
        self.assertEqual([lamp["z"] for lamp in two_b["lamps"]], [4.5, 4.5])
        self.assertEqual(len(six_c["lamps"]), 6)
        self.assertEqual({lamp["z"] for lamp in six_c["lamps"]}, {3.0, 6.0})
        self.assertEqual(four_g["source_model"], "area")
        self.assertTrue(all(lamp["cob"]["length"] == 1.8 for lamp in four_g["lamps"]))

    def test_hansen_legacy_alias_is_corrected_primary(self):
        alias = json.loads((CONFIG_DIR / "hansen_2017_led100_synthetic.json").read_text())
        primary = json.loads((CONFIG_DIR / "hansen_2017_led100_depth5m.json").read_text())
        self.assertEqual(alias["reconstruction"]["canonical_config"], "hansen_2017_led100_depth5m.json")
        self.assertAlmostEqual(alias["lamps"][0]["power"], primary["lamps"][0]["power"])
        self.assertEqual(alias["env"], primary["env"])

    def test_oppedal_configs_share_water_and_ordered_power(self):
        configs = [
            json.loads((CONFIG_DIR / f"oppedal_1997_ll_{level}.json").read_text())
            for level in ("low", "med", "high")
        ]
        coefficients = {cfg["optics"]["kd_fijo"] for cfg in configs}
        powers = [cfg["lamps"][0]["power"] for cfg in configs]
        self.assertEqual(len(coefficients), 1)
        self.assertEqual(powers, sorted(powers))


if __name__ == "__main__":
    unittest.main()
