import unittest

import numpy as np

from simulation_engine import (
    bio_optical_iop,
    build_ff_inverse_cdf,
    c_from_kd,
    ff_backscatter_fraction,
    ff_n_from_backscatter,
    fresnel_transmission,
    hg_backscatter_fraction,
    kd_from_iop,
    sample_henyey_greenstein,
)


class PhysicsModelTests(unittest.TestCase):
    def test_fresnel_normal_incidence_matches_closed_form(self):
        n_air = 1.0
        n_water = 1.333
        expected_reflectance = ((n_air - n_water) / (n_air + n_water)) ** 2
        transmission = fresnel_transmission(n_air, n_water, 1.0, 1.0)
        self.assertAlmostEqual(transmission, 1.0 - expected_reflectance, places=12)

    def test_kd_to_c_inverse_is_consistent_with_kirk_closure(self):
        kd = np.array([0.12, 0.25, 0.7])
        omega = 0.78
        g = 0.84
        c, a, b = c_from_kd(kd, omega=omega, g=g, mu_d=0.85)
        reconstructed = kd_from_iop(a, b, g=g, mu_d=0.85)
        np.testing.assert_allclose(reconstructed, kd, rtol=1e-12, atol=1e-12)
        np.testing.assert_allclose(a + b, c, rtol=1e-12, atol=1e-12)

    def test_bio_optical_iop_is_positive_and_blue_cdom_absorbs_more(self):
        wls = np.array([400.0, 440.0, 550.0, 700.0])
        a, b = bio_optical_iop(wls, tss=8.0, cdom_a440=1.0, chl=2.0)
        self.assertTrue(np.all(a > 0.0))
        self.assertTrue(np.all(b >= 0.0))
        self.assertGreater(a[0], a[-1])
        self.assertGreater(b[0], b[-1])

    def test_hg_backscatter_limits_and_typical_value(self):
        self.assertAlmostEqual(hg_backscatter_fraction(0.0), 0.5, places=12)
        self.assertGreater(hg_backscatter_fraction(0.85), 0.0)
        self.assertLess(hg_backscatter_fraction(0.85), 0.1)

    def test_fournier_forand_backscatter_solver_hits_target(self):
        target = 0.018
        mu = 3.5
        n_particle = ff_n_from_backscatter(target, mu=mu)
        solved = ff_backscatter_fraction(n_particle, mu)
        self.assertAlmostEqual(solved, target, delta=5e-5)

    def test_fournier_forand_inverse_cdf_is_monotonic_and_normalized(self):
        n_particle = ff_n_from_backscatter(0.018, mu=3.5)
        cdf, theta = build_ff_inverse_cdf(n_particle, 3.5, ngrid=800)
        self.assertAlmostEqual(cdf[0], 0.0, places=12)
        self.assertAlmostEqual(cdf[-1], 1.0, places=12)
        self.assertTrue(np.all(np.diff(cdf) >= -1e-12))
        self.assertTrue(np.all(np.diff(theta) > 0.0))

    def test_henyey_greenstein_sampler_mean_cosine_matches_g(self):
        np.random.seed(42)
        g = 0.72
        directions = np.tile(np.array([[0.0, 0.0, 1.0]]), (50000, 1))
        sampled = sample_henyey_greenstein(directions, g)
        mean_cosine = float(np.mean(sampled[:, 2]))
        self.assertAlmostEqual(mean_cosine, g, delta=0.015)


if __name__ == "__main__":
    unittest.main()
