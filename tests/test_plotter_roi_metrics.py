import unittest

from plotter import _format_roi_stats


PLANE_STATS = {
    'label': 'Area Total',
    'valid': True,
    'avg': 0.039,
    'min': 0.0,
    'max': 2.639,
    'area': 706.9,
    'area_ge_threshold': 0.1,
    'area_ge_thresholds': {'0.017': 0.1, '2.7': 0.1},
    'peak_fine': 57.3,
    'n_lamps_over_max_thr': 0,
}


class PlotterRoiMetricTests(unittest.TestCase):
    def test_plane_metrics_are_independently_selectable(self):
        config = {
            'contour_vals': [0.017, 2.7],
            'roi_plot_metrics': {
                'plane_area': False,
                'plane_avg': False,
                'plane_min': False,
                'plane_max': False,
                'plane_peak': True,
                'plane_stress_lamps': False,
                'plane_threshold': False,
            },
        }
        self.assertEqual(
            _format_roi_stats(PLANE_STATS, config).splitlines(),
            ['ROI plano: Area Total', 'Pico real (malla fina) 57.3 W/m²'],
        )

    def test_all_plane_metrics_include_zero_stress_count(self):
        text = _format_roi_stats(PLANE_STATS, {'contour_vals': [0.017, 2.7]})
        self.assertIn('Área ROI 706.9 m²', text)
        self.assertIn('Prom 0.039 W/m²', text)
        self.assertIn('Min 0.000 W/m²', text)
        self.assertIn('Máx 2.639 W/m²', text)
        self.assertIn('Pico real (malla fina) 57.3 W/m²', text)
        self.assertIn('Lámparas ≥ estrés: 0', text)
        self.assertIn('Área ≥ 0.017: 0.1 m²', text)
        self.assertIn('Área ≥ 2.7: 0.1 m²', text)

    def test_legacy_plane_minmax_setting_controls_both_metrics(self):
        config = {'roi_plot_metrics': {'plane_minmax': False}}
        text = _format_roi_stats(PLANE_STATS, config)
        self.assertNotIn('Min ', text)
        self.assertNotIn('Máx ', text)


if __name__ == '__main__':
    unittest.main()
