import unittest

import numpy as np

from biooptical_analysis import (
    build_outputs,
    compute_biological_indices,
    profile_distribution,
    summarize_volume_tally,
    validate_analysis_config,
)


class BioOpticalAnalysisTests(unittest.TestCase):
    def _analysis_config(self):
        return {
            "enabled": True,
            "depth_min_m": 0.0,
            "depth_max_m": 2.0,
            "layer_height_m": 1.0,
            "bands": {"blue": [400, 500], "green": [500, 600], "red": [600, 700]},
            "thresholds_W_m2": [0.5, 1.5],
            "larval_profiles": ["uniform_0_15"],
            "fish_profiles": ["uniform_0_15"],
            "spectral_weights": {"blue": 1.0, "green": 0.7, "red": 0.2},
        }

    def _volume_tally(self, scale=1.0):
        valid = np.ones((2, 1, 2), dtype=bool)
        total = scale * np.array([[[1.0, 2.0]], [[3.0, 4.0]]])
        return {
            "x_centers_m": [0.5, 1.5],
            "y_centers_m": [0.5],
            "depth_centers_m": [0.5, 1.5],
            "depth_edges_m": [0.0, 1.0, 2.0],
            "cell_volume_m3": 1.0,
            "valid_mask": valid.tolist(),
            "E_total_W_m2": total.tolist(),
            "E_blue_W_m2": (total * 0.5).tolist(),
            "E_green_W_m2": (total * 0.3).tolist(),
            "E_red_W_m2": (total * 0.2).tolist(),
        }

    def test_validation_rejects_overlapping_bands(self):
        cfg = self._analysis_config()
        cfg["bands"]["green"] = [490, 600]
        with self.assertRaises(ValueError):
            validate_analysis_config(cfg)

    def test_profiles_sum_to_one(self):
        layers = [{"top": 0, "bottom": 1, "mid": 0.5}, {"top": 1, "bottom": 2, "mid": 1.5}]
        larval = profile_distribution("surface_strong", layers, "larval")
        fish = profile_distribution("night_lamp_centered", layers, "fish", lamp_depth_m=1.0)
        self.assertAlmostEqual(float(np.sum(larval)), 1.0)
        self.assertAlmostEqual(float(np.sum(fish)), 1.0)

    def test_layer_summary_uses_valid_cells_and_thresholds(self):
        rows, threshold_cols = summarize_volume_tally(
            self._volume_tally(),
            self._analysis_config(),
            "scenario_a",
            {"lamps": [{"xml": "lamp.xml", "z": 5.0}]},
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(threshold_cols, ["frac_volume_E_gt_0_5", "frac_volume_E_gt_1_5"])
        self.assertAlmostEqual(rows[0]["E_total_mean_W_m2"], 1.5)
        self.assertAlmostEqual(rows[0]["frac_volume_E_gt_1_5"], 0.5)
        self.assertAlmostEqual(rows[1]["volume_m3"], 2.0)

    def test_indices_and_relative_normalization(self):
        cfg = self._analysis_config()
        cfg["normalize_against"] = "base"
        base_rows, _ = summarize_volume_tally(self._volume_tally(1.0), cfg, "base", {"lamps": []})
        alt_rows, _ = summarize_volume_tally(self._volume_tally(2.0), cfg, "alt", {"lamps": []})
        indices = compute_biological_indices({"base": base_rows, "alt": alt_rows}, cfg)
        ratios = [row for row in indices if row["relative_metric"] == "IE_contacto_total"]
        self.assertEqual(len(ratios), 1)
        self.assertAlmostEqual(ratios[0]["relative_value"], 2.0)

    def test_outputs_include_csv_headers(self):
        cfg = self._analysis_config()
        rows, _ = summarize_volume_tally(self._volume_tally(), cfg, "scenario_a", {"lamps": []})
        outputs = build_outputs({"scenario_a": rows}, cfg)
        self.assertIn("scenario_id,lamp_id,lamp_type", outputs["layer_summary_csv"])
        self.assertIn("IE_contacto_spectral", outputs["biological_indices_csv"])
        self.assertIn("fish_sigma_m", outputs["biological_indices_csv"])
        self.assertIn("spectral_weight_blue", outputs["analysis_parameters_csv"])
        self.assertIn("thresholds_W_m2", outputs["analysis_parameters_csv"])

    def test_outputs_preserve_multiple_scenarios(self):
        cfg = self._analysis_config()
        rows_a, _ = summarize_volume_tally(self._volume_tally(1.0), cfg, "omni", {"lamps": []})
        rows_b, _ = summarize_volume_tally(self._volume_tally(2.0), cfg, "tempest", {"lamps": []})
        outputs = build_outputs({"omni": rows_a, "tempest": rows_b}, cfg)
        self.assertEqual(outputs["scenario_ids"], ["omni", "tempest"])
        self.assertIn("omni", outputs["layer_summary_csv"])
        self.assertIn("tempest", outputs["layer_summary_csv"])


if __name__ == "__main__":
    unittest.main()
