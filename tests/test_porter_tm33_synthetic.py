import unittest
import xml.etree.ElementTree as ET
import json

import numpy as np

from sensitivity.porter_tm33_synthetic import (
    CONFIG_PATH,
    GROWTH_CONTROL_CONFIG_PATH,
    GROWTH_LIT_CONFG_PATH,
    GROWTH_LIT_CONFIG_PATH,
    DATA_PATH,
    INPUT_POWER_W,
    LUMINOUS_FLUX_RANGE_LM,
    RADIANT_FLUX_RANGE_W,
    TRIAL_CAGE_RADIUS_M,
    TRIAL_CONFIG_PATH,
    TRIAL3_XML_PATH,
    XML_PATH,
    fit_model,
    forward_components,
    load_measurements,
)


class PorterSyntheticTM33Tests(unittest.TestCase):
    def test_appendix_table_has_expected_geometry(self):
        measurements = load_measurements(DATA_PATH)
        self.assertEqual(len(measurements.observed_lux), 48)
        np.testing.assert_array_equal(np.unique(measurements.horizontal_m), np.arange(1.0, 9.0))
        np.testing.assert_array_equal(np.unique(measurements.vertical_m), np.arange(1.0, 7.0))

    def test_inverse_model_recovers_spatial_pattern(self):
        measurements = load_measurements(DATA_PATH)
        params = fit_model(measurements)
        _, predicted, background = forward_components(
            params, measurements.horizontal_m, measurements.vertical_m
        )
        median_ape = np.median(np.abs(predicted / measurements.observed_lux - 1.0))
        r2_log = 1.0 - np.sum((np.log(predicted) - np.log(measurements.observed_lux)) ** 2) / np.sum(
            (np.log(measurements.observed_lux) - np.mean(np.log(measurements.observed_lux))) ** 2
        )
        self.assertLess(median_ape, 0.25)
        self.assertGreater(r2_log, 0.90)
        self.assertGreater(background, 0.0)

    def test_generated_artifacts_are_parseable(self):
        self.assertTrue(XML_PATH.exists(), "Ejecute sensitivity/porter_tm33_synthetic.py")
        self.assertTrue(CONFIG_PATH.exists(), "Ejecute sensitivity/porter_tm33_synthetic.py")
        root = ET.parse(XML_PATH).getroot()
        self.assertEqual(float(root.findtext(".//InputWattage")), INPUT_POWER_W)
        luminous_flux = float(root.findtext(".//LuminousFlux"))
        radiant_flux = float(root.findtext(".//RadiantFlux"))
        self.assertGreaterEqual(luminous_flux, LUMINOUS_FLUX_RANGE_LM[0])
        self.assertLessEqual(luminous_flux, LUMINOUS_FLUX_RANGE_LM[1])
        self.assertGreaterEqual(radiant_flux, RADIANT_FLUX_RANGE_W[0])
        self.assertLessEqual(radiant_flux, RADIANT_FLUX_RANGE_W[1])
        self.assertEqual(root.findtext(".//Simulation"), "true")

        appendix_config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertAlmostEqual(
            appendix_config["lamps"][0]["efficiency"], radiant_flux / INPUT_POWER_W, places=6
        )

        trial_config = json.loads(TRIAL_CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(trial_config["env"]["shape"], "circle")
        self.assertAlmostEqual(trial_config["env"]["radio"], TRIAL_CAGE_RADIUS_M)
        self.assertEqual(len(trial_config["lamps"]), 8)
        self.assertTrue(all(lamp["z"] == 5.0 for lamp in trial_config["lamps"]))

        growth_lit = json.loads(GROWTH_LIT_CONFIG_PATH.read_text(encoding="utf-8"))
        growth_control = json.loads(GROWTH_CONTROL_CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(len(growth_lit["lamps"]), 4)
        self.assertEqual(len(growth_control["lamps"]), 0)
        self.assertEqual(growth_lit["porter_growth_trial"]["reported_growth_advantage_pct"], 18.0)
        self.assertEqual(growth_lit["porter_growth_trial"]["fish_per_treatment"], 66_000)
        self.assertEqual(growth_lit["porter_growth_trial"]["artificial_light_duration_days"], 161)
        self.assertEqual(growth_lit["lamps"][0]["xml"], TRIAL3_XML_PATH.name)
        self.assertEqual(
            json.loads(GROWTH_LIT_CONFG_PATH.read_text(encoding="utf-8")), growth_lit
        )
        self.assertTrue(TRIAL3_XML_PATH.exists())


if __name__ == "__main__":
    unittest.main()
