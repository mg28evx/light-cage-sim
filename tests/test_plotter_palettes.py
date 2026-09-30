import unittest

import numpy as np

import plotter
from simulation_engine import cie_cmf


def _xyz_of(wl_nm):
    xb, yb, zb = cie_cmf(np.array([float(wl_nm)]))
    return float(xb[0]), float(yb[0]), float(zb[0])


class IrradiancePaletteTests(unittest.TestCase):
    def test_default_is_cyan(self):
        self.assertEqual(plotter._irradiance_palette({}), 'cyan')
        self.assertEqual(plotter._irradiance_palette({'irradiance_palette': 'xyz'}), 'cyan')

    def test_clasica_is_ylgnbu_r(self):
        self.assertEqual(plotter._irradiance_cmap({'irradiance_palette': 'clasica'}).name, 'YlGnBu_r')

    def test_agua_without_colour_falls_back_to_cyan(self):
        cmap = plotter._irradiance_cmap({'irradiance_palette': 'agua'}, None)
        self.assertEqual(cmap.name, 'evolux_irradiance')

    def test_agua_uses_light_colour(self):
        cmap = plotter._irradiance_cmap({'irradiance_palette': 'agua'}, (0.0, 0.8, 0.2))
        self.assertEqual(cmap.name, 'evolux_water')

    def test_light_colour_follows_wavelength(self):
        blue = plotter.xyz_to_display_rgb(*_xyz_of(455))
        green = plotter.xyz_to_display_rgb(*_xyz_of(540))
        red = plotter.xyz_to_display_rgb(*_xyz_of(640))
        self.assertEqual(int(np.argmax(blue)), 2)
        self.assertEqual(int(np.argmax(green)), 1)
        self.assertEqual(int(np.argmax(red)), 0)

    def test_no_light_gives_none(self):
        self.assertIsNone(plotter.xyz_to_display_rgb(0.0, 0.0, 0.0))
        self.assertIsNone(plotter.xyz_to_display_rgb(float('nan'), 1.0, 1.0))

    def test_ramps_have_monotonic_lightness(self):
        for rgb in [(0.0, 0.3, 1.0), (0.4, 1.0, 0.1), (1.0, 0.9, 0.0), (1.0, 0.2, 0.1)]:
            stops = plotter.water_ramp(rgb)
            L = [plotter._linear_rgb_to_lab(plotter._srgb_decode(s))[0] for s in stops]
            self.assertTrue(all(b > a for a, b in zip(L, L[1:])), (rgb, L))
            for s in stops:
                self.assertTrue(all(0.0 <= v <= 1.0 for v in s))
        L = [plotter._linear_rgb_to_lab(plotter._srgb_decode(np.array(
            [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)])))[0] for h in plotter.SEQ_IRRADIANCE]
        self.assertTrue(all(b > a for a, b in zip(L, L[1:])))


if __name__ == '__main__':
    unittest.main()
