import unittest

import numpy as np

from simulation_engine import SimulationEngine


class _CountingParser:
    def __init__(self):
        self.intensity_calls = 0

    def get_intensity(self, directions):
        self.intensity_calls += 1
        values = np.ones(len(directions), dtype=float)
        return values, values

    def get_spectrum(self):
        return {}


def _empty_tally():
    shape = (3, 3, 3)
    return {
        'env_type': 'jaula',
        'z_interface': 0.0,
        'x_edges_m': np.arange(4.0),
        'y_edges_m': np.arange(4.0),
        'depth_edges_m': np.arange(4.0),
        'path_total': np.zeros(shape, dtype=float),
        'path_bands': {
            'blue': np.zeros(shape, dtype=float),
            'red': np.zeros(shape, dtype=float),
        },
        'bands': {'blue': [400.0, 500.0], 'red': [600.0, 701.0]},
        'valid_mask': np.ones(shape, dtype=bool),
        'step_m': 0.4,
    }


def _scalar_reference(tally, P0, D, distances, weights, wavelengths,
                      attenuation=None, atten_coef_type='c'):
    for i in range(len(P0)):
        n_steps = max(1, int(np.ceil(distances[i] / tally['step_m'])))
        ds = distances[i] / n_steps
        s_mid = (np.arange(n_steps, dtype=float) + 0.5) * ds
        points = P0[i] + D[i] * s_mid[:, np.newaxis]
        sample_weights = np.full(n_steps, weights[i], dtype=float)
        if attenuation is not None:
            if atten_coef_type == 'kd':
                delta_z = np.abs(points[:, 2] - P0[i, 2])
                sample_weights *= np.exp(-attenuation[i] * delta_z)
            else:
                sample_weights *= np.exp(-attenuation[i] * s_mid)
        depth = -points[:, 2]
        ix = np.searchsorted(tally['x_edges_m'], points[:, 0], side='right') - 1
        iy = np.searchsorted(tally['y_edges_m'], points[:, 1], side='right') - 1
        iz = np.searchsorted(tally['depth_edges_m'], depth, side='right') - 1
        valid = ((ix >= 0) & (ix < 3) & (iy >= 0) & (iy < 3) &
                 (iz >= 0) & (iz < 3))
        contribution = sample_weights[valid] * ds
        np.add.at(tally['path_total'], (iz[valid], iy[valid], ix[valid]), contribution)
        for band, (lo, hi) in tally['bands'].items():
            in_band = valid & (wavelengths[i] >= lo) & (wavelengths[i] < hi)
            np.add.at(
                tally['path_bands'][band],
                (iz[in_band], iy[in_band], ix[in_band]),
                sample_weights[in_band] * ds,
            )


class SimulationEngineOptimizationTests(unittest.TestCase):
    def test_vectorized_volume_segments_match_scalar_reference(self):
        P0 = np.array([[0.25, 0.25, -0.25], [1.25, 0.25, -0.75], [2.6, 1.2, -0.2]])
        D = np.array([[2**-0.5, 0.0, -2**-0.5], [0.0, 1.0, -0.25], [-0.8, 0.0, -0.6]])
        D /= np.linalg.norm(D, axis=1, keepdims=True)
        distances = np.array([2.2, 1.1, 2.8])
        weights = np.array([2.0, 0.75, 1.25])
        wavelengths = np.array([450.0, 650.0, 470.0])
        attenuation = np.array([0.2, 0.4, 0.1])

        for coef_type in ('none', 'c', 'kd'):
            with self.subTest(coef_type=coef_type):
                actual = _empty_tally()
                expected = _empty_tally()
                atten = None if coef_type == 'none' else attenuation
                SimulationEngine()._accumulate_volume_segments(
                    actual, P0, D, distances, weights, wavelengths,
                    attenuation=atten, atten_coef_type=coef_type,
                )
                _scalar_reference(
                    expected, P0, D, distances, weights, wavelengths,
                    attenuation=atten, atten_coef_type=coef_type,
                )
                np.testing.assert_allclose(actual['path_total'], expected['path_total'], rtol=0, atol=0)
                for band in expected['bands']:
                    np.testing.assert_allclose(
                        actual['path_bands'][band], expected['path_bands'][band], rtol=0, atol=0
                    )

    def test_shared_lamp_file_interpolates_intensity_once_per_run(self):
        parser = _CountingParser()
        engine = SimulationEngine()
        engine.parsers['fake.xml'] = parser
        lamps = [
            {'xml': 'fake.xml', 'x': 4.0 + i, 'y': 5.0, 'z': 1.0,
             'power': 10.0, 'dim': 1.0, 'efficiency': 1.0}
            for i in range(3)
        ]
        config = {
            'env': {'type': 'jaula', 'shape': 'rect', 'x': 10.0, 'y': 10.0, 'z': 5.0},
            'optics': {'mode': 'kd_fijo', 'kd_fijo': 0.1, 'atten_coef_type': 'c'},
            'target_depths': [2.0],
            'rays': 1000,
            'lamps': lamps,
        }
        result = engine.run(config)
        engine.run(config)
        self.assertEqual(parser.intensity_calls, 1)
        self.assertIsInstance(result['2.0']['x'], list)
        self.assertEqual(len(result['2.0']['lamp_idx']), 1500)

        config['rays'] = 1200
        engine.run(config)
        self.assertEqual(parser.intensity_calls, 2)


if __name__ == '__main__':
    unittest.main()
