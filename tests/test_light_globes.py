import unittest

from app_sim import _build_light_globe_result, _configure_light_globe_tally


class LightGlobeTests(unittest.TestCase):
    def test_default_tally_keeps_requested_thresholds_and_per_lamp_mode(self):
        config = {
            'lamps': [{'xml': 'a.xml'}],
            'scene3d': {'render': {
                'show_light_globes': True,
                'light_globe_threshold_W_m2': 0.05,
                'light_globe_resolution_m': 0.5,
            }},
        }
        enabled = _configure_light_globe_tally(
            config, env_x=4.0, env_y=5.0, env_z=3.0,
            z_interface=2.0, env_type='estanque'
        )
        self.assertTrue(enabled)
        self.assertTrue(config['volume_tally']['per_lamp'])
        self.assertEqual(config['volume_tally']['depth_max_m'], 2.0)
        self.assertEqual(
            config['scene3d']['render']['light_globe_thresholds_W_m2'],
            [0.1, 0.05, 0.016],
        )

    def test_volume_is_integrated_separately_for_each_lamp_and_threshold(self):
        tally = {
            'valid_mask': [[[True]], [[True]]],
            'cell_volume_m3': [[[2.0]], [[3.0]]],
            'E_lamps_W_m2': [
                [[[0.2]], [[0.02]]],
                [[[0.05]], [[0.01]]],
            ],
            'x_centers_m': [0.5],
            'y_centers_m': [0.5],
            'depth_centers_m': [0.5, 1.5],
            'x_edges_m': [0.0, 1.0],
            'y_edges_m': [0.0, 1.0],
            'depth_edges_m': [0.0, 1.0, 2.0],
        }
        config = {
            'lamps': [{'label': 'L1'}, {'label': 'L2'}],
            'scene3d': {'render': {'light_globe_threshold_W_m2': 0.1}},
        }
        result = _build_light_globe_result(tally, config)
        self.assertEqual(result['lamps'][0]['volumes_m3']['0.1'], 2.0)
        self.assertEqual(result['lamps'][0]['volumes_m3']['0.016'], 5.0)
        self.assertEqual(result['lamps'][1]['volumes_m3']['0.1'], 0.0)
        self.assertEqual(result['lamps'][1]['volumes_m3']['0.016'], 2.0)


if __name__ == '__main__':
    unittest.main()
