import unittest

import numpy as np

from simulation_engine import (
    bio_optical_iop,
    bio_optical_iop_ras_bardsnes,
    build_ff_inverse_cdf,
    c_from_kd,
    ff_backscatter_fraction,
    ff_n_from_backscatter,
    fresnel_transmission,
    hg_backscatter_fraction,
    kd_from_iop,
    ras_tss_from_turbidity,
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

    def test_ras_bardsnes_spectral_shapes_and_scaling(self):
        # La atenuación en RAS crece hacia el azul (inverso al océano) y la forma
        # particulada reproduce la ley de potencia (λ/550)^(-1.8) de la Tabla 4.1.
        wls = np.array([400.0, 440.0, 550.0, 700.0])
        a, b = bio_optical_iop_ras_bardsnes(wls, tss=10.0, cdom_a440=1.0, chl=1.0)
        self.assertTrue(np.all(a > 0.0))
        self.assertTrue(np.all(b >= 0.0))
        # Absorción y dispersión mayores en azul que en rojo.
        self.assertGreater(a[0], a[-1])
        self.assertGreater(b[0], b[-1])
        # Forma particulada a 400/550 nm ≈ 1.774 (potencia -1.8, medido 1.788).
        b400, _b440, b550, _b700 = b
        self.assertAlmostEqual(b400 / b550, (400.0 / 550.0) ** (-1.8), places=6)
        # La dispersión escala linealmente con TSS.
        _a2, b2 = bio_optical_iop_ras_bardsnes(wls, tss=20.0, cdom_a440=1.0, chl=1.0)
        np.testing.assert_allclose(b2, 2.0 * b, rtol=1e-9)
        # Sin TSS, la dispersión es nula y la absorción queda por agua + CDOM.
        a0, b0 = bio_optical_iop_ras_bardsnes(wls, tss=0.0, cdom_a440=1.0, chl=0.0)
        np.testing.assert_allclose(b0, 0.0, atol=1e-12)
        self.assertTrue(np.all(a0 > 0.0))

    def test_ras_turbidity_to_tss_matches_bardsnes_regression(self):
        # TSS = 3.0411·NTU − 0.376 (tanque, Bårdsnes 2020 Fig. 3.2A).
        self.assertAlmostEqual(ras_tss_from_turbidity(5.0), 3.0411 * 5.0 - 0.376, places=6)
        # No devuelve valores negativos para turbidez muy baja.
        self.assertEqual(ras_tss_from_turbidity(0.0), 0.0)
        self.assertIsNone(ras_tss_from_turbidity(None))

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
