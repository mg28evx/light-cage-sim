"""Pruebas del modelo de irradiancia ambiental y objetivo de fotoperíodo.

Las referencias numéricas provienen de tres fuentes:

* geometría solar: valores astronómicos cerrados (fotoperíodo en equinoccio,
  elevación de mediodía en solsticio) que no dependen del modelo;
* óptica: cierres que el modelo espectral debe reproducir exactamente en casos
  límite (agua gris bajo cielo difuso ≡ Beer-Lambert);
* biología: la Tabla 1 y los resultados de Oldham et al. (2023),
  Sci. Rep. 13:2618.
"""

import datetime as dt
import math
import unittest

import numpy as np

import ambient_light as al
from simulation_engine import bio_optical_iop, hg_backscatter_fraction


PUERTO_MONTT_LAT = -41.598511
PUERTO_MONTT_LON = -73.007600
WL = al.REFERENCE_WAVELENGTHS_NM


def bio_iop(tss, cdom, chl, g=0.85):
    """IOP del modo bio-óptico marino, como las entrega build_optical_diagnostics."""
    a, b = bio_optical_iop(WL, tss=tss, cdom_a440=cdom, chl=chl)
    return {"wavelength_nm": WL.tolist(), "a_m_inv": a.tolist(),
            "bb_m_inv": (hg_backscatter_fraction(g) * b).tolist()}


def typical_water():
    return al.WaterColumn(bio_iop(3.0, 0.3, 1.5), label="típica")


def clear_water():
    return al.WaterColumn(bio_iop(1.0, 0.1, 0.5), label="clara")


def turbid_water():
    return al.WaterColumn(bio_iop(8.0, 0.8, 4.0), label="turbia")



class SolarGeometryTests(unittest.TestCase):

    def test_equinox_daylength_is_about_twelve_hours(self):
        """En equinoccio el día dura ~12 h en cualquier latitud.

        Siempre algo más de 12: el cenit de 90,833° incorpora la refracción
        atmosférica y el semidiámetro solar, y ese exceso crece con la latitud
        porque el sol cruza el horizonte más oblicuamente. En el ecuador el
        margen es de minutos; a 55° pasa de veinte.
        """
        for doy in self._equinox_days():
            self.assertAlmostEqual(al.daylength_hours(0.0, doy), 12.12,
                                   delta=0.08, msg=f"ecuador doy={doy}")
            for lat in (-60.0, -41.6, 35.0, 55.0):
                value = al.daylength_hours(lat, doy)
                self.assertGreater(value, 12.0, msg=f"lat={lat} doy={doy}")
                self.assertLess(value, 12.6, msg=f"lat={lat} doy={doy}")

    @staticmethod
    def _equinox_days():
        """Días del año en que la declinación cruza cero, según el modelo.

        Se derivan en vez de fijarse a mano: el equinoccio se desplaza hasta
        dos días entre años, y a latitudes altas el fotoperíodo cambia lo
        bastante rápido como para que esa diferencia importe.
        """
        march = min(range(60, 110), key=lambda n: abs(al.solar_declination_deg(n)))
        september = min(range(240, 290), key=lambda n: abs(al.solar_declination_deg(n)))
        return march, september

    def test_equinox_excess_grows_with_latitude(self):
        """El exceso sobre 12 h en el equinoccio crece con |latitud|."""
        excess = [al.daylength_hours(lat, 80) - 12.0
                  for lat in (0.0, 20.0, 40.0, 55.0)]
        for a, b in zip(excess, excess[1:]):
            self.assertLess(a, b)

    def test_solstice_daylength_at_reloncavi(self):
        """Fotoperíodo en los solsticios para el seno de Reloncaví."""
        winter = al.daylength_hours(PUERTO_MONTT_LAT, 172)   # 21 de junio
        summer = al.daylength_hours(PUERTO_MONTT_LAT, 355)   # 21 de diciembre
        self.assertAlmostEqual(winter, 9.16, delta=0.15)
        self.assertAlmostEqual(summer, 15.19, delta=0.15)
        # Simetría: los dos solsticios suman algo más de 24 h por la refracción.
        self.assertAlmostEqual(winter + summer, 24.35, delta=0.25)

    def test_polar_night_and_midnight_sun(self):
        self.assertEqual(al.daylength_hours(80.0, 355), 0.0)
        self.assertEqual(al.daylength_hours(80.0, 172), 24.0)

    def test_noon_elevation_matches_closed_form(self):
        """Elevación de mediodía solar = 90 − |latitud − declinación|."""
        for doy, month, day in ((172, 6, 21), (355, 12, 21), (80, 3, 21)):
            dec = al.solar_declination_deg(doy)
            expected = 90.0 - abs(PUERTO_MONTT_LAT - dec)
            # Barre el día y toma el máximo: así no hay que resolver a mano la
            # hora del mediodía solar, que depende de longitud y huso.
            best = max(
                al.solar_elevation_deg(
                    PUERTO_MONTT_LAT, PUERTO_MONTT_LON,
                    dt.datetime(2026, month, day, h, m), -4.0)
                for h in range(24) for m in (0, 15, 30, 45))
            self.assertAlmostEqual(best, expected, delta=0.3)

    def test_equation_of_time_stays_within_known_bounds(self):
        values = [al.equation_of_time_minutes(d) for d in range(1, 366)]
        self.assertGreater(min(values), -16.0)
        self.assertLess(max(values), 17.0)

    def test_sun_is_below_horizon_at_local_midnight(self):
        elev = al.solar_elevation_deg(PUERTO_MONTT_LAT, PUERTO_MONTT_LON,
                                      dt.datetime(2026, 6, 21, 0, 0), -4.0)
        self.assertLess(elev, 0.0)


class SurfaceTests(unittest.TestCase):

    def test_clear_sky_is_zero_below_horizon(self):
        self.assertEqual(al.clear_sky_broadband_w_m2(-5.0), 0.0)
        self.assertEqual(al.clear_sky_broadband_w_m2(0.0), 0.0)

    def test_clear_sky_grows_with_elevation(self):
        values = [al.clear_sky_broadband_w_m2(e) for e in (5, 20, 45, 70, 90)]
        self.assertEqual(values, sorted(values))
        # Con el sol en el cenit y τ=0,75 el máximo ronda 1000 W/m².
        self.assertTrue(950.0 < values[-1] < 1100.0)

    def test_fresnel_transmittance_bounds(self):
        """Casi todo entra con el sol alto; con el sol rasante casi nada."""
        self.assertAlmostEqual(al.fresnel_transmittance(90.0), 0.979, delta=0.005)
        self.assertLess(al.fresnel_transmittance(5.0), 0.75)
        self.assertEqual(al.fresnel_transmittance(0.0), 0.0)
        for elev in (10, 30, 60, 90):
            t = al.fresnel_transmittance(elev)
            self.assertTrue(0.0 < t < 1.0)

    def test_fresnel_is_monotonic_in_elevation(self):
        values = [al.fresnel_transmittance(e) for e in (5, 15, 30, 50, 70, 90)]
        self.assertEqual(values, sorted(values))

    def test_refracted_zenith_never_exceeds_critical_angle(self):
        critical = math.degrees(math.asin(1.0 / al.WATER_REFRACTIVE_INDEX))
        for elev in (1, 10, 45, 89):
            self.assertLessEqual(al.refracted_zenith_deg(elev), critical + 1e-9)

    def test_erbs_decomposition_limits(self):
        """Erbs et al. (1982): todo difuso con kt → 0, 0,165 sobre kt = 0,8."""
        self.assertAlmostEqual(al.erbs_diffuse_fraction(0.0), 1.0)
        self.assertAlmostEqual(al.erbs_diffuse_fraction(0.9), 0.165)
        for kt in (0.22, 0.80):   # continuidad en los quiebres
            self.assertAlmostEqual(al.erbs_diffuse_fraction(kt - 1e-6),
                                   al.erbs_diffuse_fraction(kt + 1e-6), delta=0.01)
        for kt in np.linspace(0, 1.2, 25):
            self.assertTrue(0.16 <= al.erbs_diffuse_fraction(kt) <= 1.0)


class AggregationTests(unittest.TestCase):

    def test_percentile_zero_is_the_plain_mean(self):
        values = [1.0, 2.0, 3.0, 4.0, 10.0]
        self.assertAlmostEqual(al.percentile_mean(values, 0.0), float(np.mean(values)))

    def test_percentile_hundred_is_the_maximum(self):
        values = [1.0, 2.0, 3.0, 4.0, 10.0]
        self.assertAlmostEqual(al.percentile_mean(values, 100.0), 10.0)

    def test_percentile_fifty_is_the_mean_of_the_upper_half(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        # mediana 3 -> promedio de {3, 4, 5}
        self.assertAlmostEqual(al.percentile_mean(values, 50.0), 4.0)

    def test_percentile_mean_is_non_decreasing(self):
        rng = np.random.default_rng(20230104)
        values = rng.lognormal(mean=0.0, sigma=0.8, size=400).tolist()
        results = [al.percentile_mean(values, p) for p in range(0, 101, 10)]
        for a, b in zip(results, results[1:]):
            self.assertLessEqual(a, b + 1e-12)

    def test_empty_series_is_zero(self):
        self.assertEqual(al.percentile_mean([], 50.0), 0.0)

    def test_tail_mean_resists_a_single_outlier(self):
        """Promediar la cola no se deja arrastrar por un día atípico."""
        base = [5.0] * 50
        spiked = base + [500.0]
        self.assertLess(al.percentile_mean(spiked, 90.0),
                        max(spiked))


class OldhamRuleTests(unittest.TestCase):
    """Reproduce la lógica de los ocho regímenes de la Tabla 1.

    En los estanques de Oldham no había luz natural: el «día» era el propio
    nivel diurno de la lámpara y la noche una fracción fija de él. Eso es
    exactamente el modo nocturno, donde la referencia no se mezcla con la
    luminaria.
    """

    NIGHT = al.OPERATION_NIGHT_ONLY

    # Intensidad diurna, µmol m⁻² s⁻¹ (Oldham 2023, Tabla 1).
    HIGH_DAY_UMOL = 69.4
    LOW_DAY_UMOL = 1.0

    def _w_m2(self, umol):
        return umol / al.UMOL_PER_JOULE_PAR

    def test_default_threshold_sits_inside_the_measured_band(self):
        """0,016 W/m² debe caer dentro de 0,01–0,1 µmol m⁻² s⁻¹."""
        # El factor depende del espectro: LED azul 450 nm, subacuática 480 nm, PAR diurno.
        for factor in (3.76, 4.03, al.UMOL_PER_JOULE_PAR):
            umol = al.par_w_m2_to_umol(al.DETECTION_THRESHOLD_W_M2, factor)
            self.assertGreater(umol, 0.01)
            self.assertLess(umol, 0.1)
            # Y cerca del 0,05–0,07 de Migaud (2006) y Vera (2010).
            self.assertAlmostEqual(umol, 0.065, delta=0.01)

    def test_low1_falls_below_detection_and_reads_as_darkness(self):
        """Low1 (0,01 µmol nocturnos) no maduró: queda bajo el umbral."""
        result = al.target_irradiance(self._w_m2(self.LOW_DAY_UMOL), 0.01, operation=self.NIGHT)
        self.assertEqual(result["binding_term"], "umbral de detección")
        self.assertLess(result["adaptive_term_w_m2"], result["threshold_w_m2"])

    def test_low10_clears_detection(self):
        """Low10 (0,1 µmol nocturnos) sí produjo maduración."""
        result = al.target_irradiance(self._w_m2(self.LOW_DAY_UMOL), 0.10, operation=self.NIGHT)
        self.assertEqual(result["binding_term"], "razón adaptativa")

    def test_high_treatments_are_all_above_detection(self):
        ref = self._w_m2(self.HIGH_DAY_UMOL)
        for ratio in (0.01, 0.10, 1.00):
            result = al.target_irradiance(ref, ratio, operation=self.NIGHT)
            self.assertEqual(result["binding_term"], "razón adaptativa",
                             msg=f"razón {ratio}")

    def test_darkness_regime_returns_no_binding_term(self):
        result = al.target_irradiance(10.0, 0.0, operation=self.NIGHT)
        self.assertEqual(result["target_w_m2"], al.DETECTION_THRESHOLD_W_M2)
        self.assertIn("oscuridad", result["binding_term"])

    def test_target_never_drops_below_the_threshold(self):
        for ref in (0.0, 1e-6, 0.01, 5.0, 200.0):
            for ratio in (0.0, 0.001, 0.01, 0.1, 1.0):
                result = al.target_irradiance(ref, ratio, operation=self.NIGHT)
                self.assertGreaterEqual(result["target_w_m2"],
                                        al.DETECTION_THRESHOLD_W_M2 - 1e-15)

    def test_target_scales_with_the_ratio_once_above_threshold(self):
        ref = 10.0
        a = al.target_irradiance(ref, 0.01, operation=self.NIGHT)["target_w_m2"]
        b = al.target_irradiance(ref, 0.10, operation=self.NIGHT)["target_w_m2"]
        self.assertAlmostEqual(b / a, 10.0, places=6)


class OperationModeTests(unittest.TestCase):
    """La razón se define sobre la luz total: en 24 h la luminaria suma de día."""

    def test_night_only_is_the_plain_product(self):
        self.assertAlmostEqual(al.adaptive_term(8.0, 0.10, al.OPERATION_NIGHT_ONLY), 0.8)

    def test_24h_is_self_consistent(self):
        """Con E_art = r·E/(1−r), la razón lograda es exactamente r."""
        for e_nat in (0.5, 8.0, 40.0):
            for r in (0.01, 0.10, 0.50, 0.90):
                e_art = al.adaptive_term(e_nat, r, al.OPERATION_24H)
                self.assertAlmostEqual(al.achieved_ratio(e_nat, e_art, al.OPERATION_24H),
                                       r, places=12)

    def test_the_night_formula_undershoots_a_24h_installation(self):
        """El error que motivó el modo: pedir LL con r·E da sólo 50 %."""
        e_art = al.adaptive_term(8.0, 1.0, al.OPERATION_NIGHT_ONLY)
        self.assertAlmostEqual(al.achieved_ratio(8.0, e_art, al.OPERATION_24H), 0.5)
        e_art = al.adaptive_term(8.0, 0.10, al.OPERATION_NIGHT_ONLY)
        self.assertAlmostEqual(al.achieved_ratio(8.0, e_art, al.OPERATION_24H), 1 / 11)

    def test_ll_is_unreachable_with_24h_lamps(self):
        self.assertIsNone(al.adaptive_term(8.0, 1.0, al.OPERATION_24H))
        result = al.target_irradiance(8.0, 1.0, operation=al.OPERATION_24H)
        self.assertIsNone(result["target_w_m2"])
        self.assertIn("inalcanzable", result["binding_term"])

    def test_24h_never_asks_less_than_night_only(self):
        for r in (0.01, 0.10, 0.50):
            self.assertGreater(al.adaptive_term(5.0, r, al.OPERATION_24H),
                               al.adaptive_term(5.0, r, al.OPERATION_NIGHT_ONLY))

    def test_threshold_still_binds_in_dark_water(self):
        result = al.target_irradiance(0.01, 0.10, operation=al.OPERATION_24H)
        self.assertEqual(result["binding_term"], "umbral de detección")
        self.assertEqual(result["target_w_m2"], al.DETECTION_THRESHOLD_W_M2)
        # Si manda el umbral, la razón lograda supera a la pedida.
        self.assertGreater(result["achieved_ratio"], 0.10)

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            al.adaptive_term(5.0, 0.1, "siempre")

    def test_ll_request_in_24h_evaluates_without_crashing(self):
        """Sin objetivo no hay cobertura, pero sí serie y tabla de propuestas."""
        result = al.evaluate(
            lat_deg=-41.6, lon_deg=-73.0, start="2026-06-01", end="2026-06-05",
            reference_depth_m=8.0, target_depth_m=8.0, water=typical_water(), ratio=1.0,
            step_minutes=60, operation=al.OPERATION_24H)
        self.assertIsNone(result["target"]["target_w_m2"])
        self.assertIsNone(result["coverage"])
        self.assertEqual(len(result["profile"]["dates"]), 5)
        self.assertTrue(all(r < 1.0 for r in result["proposals"]["ratios"]))


class SpectralWaterTests(unittest.TestCase):

    def test_reference_spectrum_par_fraction(self):
        """AM1.5G integra 429,8 W/m² en 400–700 nm sobre 1000,4 W/m² totales."""
        self.assertAlmostEqual(al.PAR_FRACTION_REFERENCE, 0.4297, delta=0.0005)

    def test_gray_water_reproduces_beer_lambert(self):
        """Caso límite exacto: Kd uniforme, sin b_b y cielo totalmente difuso."""
        water = al.WaterColumn.from_kd(0.25)
        kw = dict(lat_deg=-41.6, lon_deg=-73.0, start="2026-06-01", end="2026-06-01",
                  water=water, cloud_transmittance=1e-4)
        surface = al.daily_ambient_profile(depth_m=0.0, **kw)["photophase_mean_w_m2"][0]
        deep = al.daily_ambient_profile(depth_m=8.0, **kw)["photophase_mean_w_m2"][0]
        self.assertAlmostEqual(deep / surface, math.exp(-0.25 * 8.0), delta=1e-4)

    def test_low_sun_attenuates_more(self):
        a, bb = al.resample_iop(bio_iop(3.0, 0.3, 1.5))
        self.assertTrue(np.all(al.spectral_kd(a, bb, 70.0) > al.spectral_kd(a, bb, 10.0)))

    def test_zenith_only_acts_on_absorption(self):
        """En el cierre de Lee (2005) el ángulo sólo multiplica al término de a."""
        a = np.zeros(WL.size)
        bb = np.full(WL.size, 0.02)
        np.testing.assert_allclose(al.spectral_kd(a, bb, 0.0), al.spectral_kd(a, bb, 80.0))

    def test_cdom_and_particles_increase_attenuation(self):
        base = al.equivalent_kd_par(bio_iop(3.0, 0.3, 1.5))
        self.assertGreater(al.equivalent_kd_par(bio_iop(3.0, 1.2, 1.5)), base)
        self.assertGreater(al.equivalent_kd_par(bio_iop(9.0, 0.3, 1.5)), base)
        self.assertGreater(al.equivalent_kd_par(bio_iop(3.0, 0.3, 6.0)), base)

    def test_spectral_hardening_lowers_kd_with_depth(self):
        """El agua filtra primero azul y rojo: el Kd de PAR medio baja con z."""
        iop = bio_iop(3.0, 0.3, 1.5)
        self.assertGreater(al.equivalent_kd_par(iop, depth_m=2.0),
                           al.equivalent_kd_par(iop, depth_m=15.0))

    def test_resample_accepts_other_grids_and_rejects_negatives(self):
        coarse = {"wavelength_nm": [700, 400, 550], "a_m_inv": [0.7, 0.1, 0.2],
                  "bb_m_inv": [0.01, 0.01, 0.01]}
        a, bb = al.resample_iop(coarse)
        self.assertEqual(a.size, WL.size)
        self.assertAlmostEqual(a[0], 0.1)
        self.assertAlmostEqual(a[-1], 0.7)
        with self.assertRaises(ValueError):
            al.resample_iop({**coarse, "a_m_inv": [-0.1, 0.1, 0.2]})

    def test_water_column_maps_weeks_to_their_iop(self):
        water = al.WaterColumn(bio_iop(1, 0.1, 0.5), {"23": bio_iop(8, 0.8, 4.0), 30: bio_iop(5, 0.5, 2)})
        self.assertEqual(water.weeks, [23, 30])
        self.assertEqual(water.slot(23), 1)
        self.assertEqual(water.slot(30), 2)
        self.assertEqual(water.slot(10), 0)

    def test_window_keeps_only_daylight_samples(self):
        samples = al._clear_sky_samples(PUERTO_MONTT_LAT, PUERTO_MONTT_LON,
                                        al.window_days("2026-06-21", "2026-06-21"), 0.7, -4.0, 10,
                                        al.WATER_REFRACTIVE_INDEX, 0.75)
        self.assertTrue(np.all(samples["zenith_deg"] < 90.0))
        hours = samples["day_index"].size * 10 / 60.0
        self.assertAlmostEqual(hours, al.daylength_hours(PUERTO_MONTT_LAT, 172), delta=0.4)


class ProfileAndEvaluateTests(unittest.TestCase):

    def _evaluate(self, **kwargs):
        params = dict(
            lat_deg=PUERTO_MONTT_LAT, lon_deg=PUERTO_MONTT_LON,
            start="2026-06-01", end="2026-06-30",
            reference_depth_m=8.0, target_depth_m=8.0,
            water=typical_water(), ratio=0.10, cloud_transmittance=0.7,
            percentile=50.0, step_minutes=60)
        params.update(kwargs)
        return al.evaluate(**params)

    def test_profile_covers_every_day_of_the_window(self):
        profile = al.daily_ambient_profile(
            PUERTO_MONTT_LAT, PUERTO_MONTT_LON, "2026-06-01", "2026-06-30",
            8.0, typical_water(), step_minutes=60)
        self.assertEqual(len(profile["dates"]), 30)
        self.assertEqual(profile["dates"][0], "2026-06-01")
        self.assertEqual(profile["dates"][-1], "2026-06-30")

    def test_daily_max_is_at_least_the_photophase_mean(self):
        profile = al.daily_ambient_profile(
            PUERTO_MONTT_LAT, PUERTO_MONTT_LON, "2026-03-01", "2026-03-20",
            6.0, typical_water(), cloud_transmittance=0.8, step_minutes=30)
        for mean, peak in zip(profile["photophase_mean_w_m2"], profile["daily_max_w_m2"]):
            self.assertLessEqual(mean, peak + 1e-12)

    def test_summer_window_is_brighter_than_winter(self):
        winter = self._evaluate(start="2026-06-01", end="2026-06-30")
        summer = self._evaluate(start="2026-12-01", end="2026-12-30")
        self.assertGreater(summer["reference"]["value_w_m2"], winter["reference"]["value_w_m2"])

    def test_deeper_reference_is_darker(self):
        self.assertGreater(self._evaluate(reference_depth_m=2.0)["reference"]["value_w_m2"],
                           self._evaluate(reference_depth_m=12.0)["reference"]["value_w_m2"])

    def test_turbid_water_lowers_the_reference(self):
        self.assertGreater(self._evaluate(water=clear_water())["reference"]["value_w_m2"],
                           self._evaluate(water=turbid_water())["reference"]["value_w_m2"])

    def test_reference_lies_inside_the_daily_range(self):
        ref = self._evaluate()["reference"]
        self.assertGreaterEqual(ref["value_w_m2"], ref["window_min_w_m2"] - 1e-12)
        self.assertLessEqual(ref["value_w_m2"], ref["window_max_w_m2"] + 1e-12)

    def test_time_zone_does_not_move_the_result(self):
        """El muestreo recorre las 24 h: el huso sólo desplaza el borde del día."""
        a = self._evaluate(tz_offset_h=-5.0)["reference"]["value_w_m2"]
        b = self._evaluate(tz_offset_h=-3.0)["reference"]["value_w_m2"]
        self.assertAlmostEqual(a, b, delta=a * 0.005)

    def test_default_time_zone_comes_from_longitude(self):
        self.assertEqual(al.default_tz_offset(-73.0), -5.0)
        self.assertEqual(al.default_tz_offset(10.0), 1.0)

    def test_reversed_window_is_rejected(self):
        with self.assertRaises(ValueError):
            self._evaluate(start="2026-06-30", end="2026-06-01")

    def test_reports_the_equivalent_kd(self):
        water = self._evaluate()["water"]
        self.assertGreater(water["kd_par_equivalent_m_inv"], 0.0)


class SeasonalWaterTests(unittest.TestCase):

    KW = dict(lat_deg=PUERTO_MONTT_LAT, lon_deg=PUERTO_MONTT_LON,
              start="2026-05-01", end="2026-07-31", reference_depth_m=8.0,
              target_depth_m=8.0, ratio=0.10, step_minutes=60)

    def _weeks(self):
        return sorted({d.isocalendar()[1] for d, _ in al.window_days("2026-05-01", "2026-07-31")})

    def test_weekly_iop_everywhere_equals_that_water(self):
        """Si todas las semanas traen la misma IOP, es como usarla por defecto."""
        turbid = bio_iop(8.0, 0.8, 4.0)
        seasonal = al.WaterColumn(bio_iop(1.0, 0.1, 0.5), {w: turbid for w in self._weeks()})
        a = al.evaluate(water=seasonal, **self.KW)["reference"]["value_w_m2"]
        b = al.evaluate(water=al.WaterColumn(turbid), **self.KW)["reference"]["value_w_m2"]
        self.assertAlmostEqual(a, b, places=10)

    def test_partial_season_lies_between_the_extremes(self):
        weeks = self._weeks()
        half = {w: bio_iop(8.0, 0.8, 4.0) for w in weeks[: len(weeks) // 2]}
        mixed = al.WaterColumn(bio_iop(1.0, 0.1, 0.5), half)
        clear = al.evaluate(water=clear_water(), **self.KW)["reference"]["value_w_m2"]
        turbid = al.evaluate(water=turbid_water(), **self.KW)["reference"]["value_w_m2"]
        value = al.evaluate(water=mixed, **self.KW)["reference"]["value_w_m2"]
        self.assertTrue(turbid < value < clear)

    def test_reports_which_window_weeks_have_their_own_iop(self):
        weeks = self._weeks()
        water = al.WaterColumn(bio_iop(1.0, 0.1, 0.5), {weeks[0]: bio_iop(8, 0.8, 4), 1: bio_iop(8, 0.8, 4)})
        info = al.evaluate(water=water, **self.KW)["water"]
        self.assertEqual(info["window_weeks_with_own_iop"], [weeks[0]])
        self.assertEqual(info["weeks_with_own_iop"], 2)


class ProposalTableTests(unittest.TestCase):

    KW = dict(lat_deg=PUERTO_MONTT_LAT, lon_deg=PUERTO_MONTT_LON,
              start="2026-04-01", end="2026-09-30", reference_depth_m=8.0,
              target_depth_m=12.0, water=typical_water(), ratio=0.25, step_minutes=60)

    def test_table_includes_the_chosen_ratio_and_percentile(self):
        result = al.evaluate(**self.KW)
        table = result["proposals"]
        self.assertEqual(table["ratios"], [0.01, 0.1, 0.25])
        self.assertEqual([r["percentile"] for r in table["rows"]], list(al.PROPOSAL_PERCENTILES))
        row = next(r for r in table["rows"] if r["percentile"] == 50.0)
        cell = next(c for c in row["cells"] if c["ratio"] == 0.25)
        self.assertAlmostEqual(cell["target_w_m2"], result["target"]["target_w_m2"])

    def test_targets_grow_with_percentile_and_ratio(self):
        table = al.evaluate(**self.KW)["proposals"]
        for j in range(len(table["ratios"])):
            column = [row["cells"][j]["target_w_m2"] for row in table["rows"]]
            self.assertEqual(column, sorted(column))
        for row in table["rows"]:
            values = [c["target_w_m2"] for c in row["cells"]]
            self.assertEqual(values, sorted(values))

    def test_coverage_grows_with_percentile_and_reaches_one(self):
        rows = al.evaluate(**self.KW)["proposals"]["rows"]
        fractions = [row["cells"][-1]["fraction_covered"] for row in rows]
        self.assertEqual(fractions, sorted(fractions))
        self.assertAlmostEqual(fractions[-1], 1.0)

    def test_24h_drops_unreachable_ratios_night_keeps_them(self):
        day = al.evaluate(**{**self.KW, "ratio": 1.0, "operation": al.OPERATION_24H})
        night = al.evaluate(**{**self.KW, "ratio": 1.0, "operation": al.OPERATION_NIGHT_ONLY})
        self.assertNotIn(1.0, day["proposals"]["ratios"])
        self.assertIn(1.0, night["proposals"]["ratios"])

    def test_threshold_cells_are_flagged_in_dark_water(self):
        table = al.evaluate(**{**self.KW, "reference_depth_m": 40.0})["proposals"]
        low = table["rows"][0]["cells"][0]
        self.assertEqual(low["binding_term"], "umbral de detección")
        self.assertEqual(low["target_w_m2"], al.DETECTION_THRESHOLD_W_M2)


class CoverageAndVerticalTests(unittest.TestCase):

    KW = dict(lat_deg=PUERTO_MONTT_LAT, lon_deg=PUERTO_MONTT_LON,
              start="2026-04-01", end="2026-09-30",
              reference_depth_m=8.0, target_depth_m=12.0,
              water=typical_water(), ratio=0.10, step_minutes=60)

    def test_daily_target_follows_the_daily_light(self):
        result = al.evaluate(**self.KW)
        means = result["profile"]["photophase_mean_w_m2"]
        targets = result["profile"]["daily_target_w_m2"]
        self.assertEqual(len(targets), len(means))
        self.assertAlmostEqual(targets[int(np.argmax(means))], max(targets))

    def test_maximum_percentile_covers_every_day(self):
        cov = al.evaluate(**{**self.KW, "percentile": 100.0})["coverage"]
        self.assertEqual(cov["days_covered"], cov["days_total"])

    def test_vertical_profile_is_the_exact_statistic_at_each_depth(self):
        """Cada punto del perfil repite la agregación espectral completa."""
        result = al.evaluate(**self.KW)
        for z, value in zip(result["vertical"]["depths_m"][::12],
                            result["vertical"]["ambient_w_m2"][::12]):
            profile = al.daily_ambient_profile(
                PUERTO_MONTT_LAT, PUERTO_MONTT_LON, "2026-04-01", "2026-09-30",
                z, typical_water(), step_minutes=60)
            expected = al.percentile_mean(profile["photophase_mean_w_m2"], 50.0)
            self.assertAlmostEqual(value, expected, delta=max(expected * 1e-9, 1e-15))

    def test_vertical_profile_decreases_with_depth(self):
        vertical = al.evaluate(**self.KW)["vertical"]["ambient_w_m2"]
        for a, b in zip(vertical, vertical[1:]):
            self.assertGreaterEqual(a, b)

    def test_natural_light_at_target_depth_is_reported(self):
        result = al.evaluate(**self.KW)
        self.assertLess(result["reference"]["natural_at_target_w_m2"],
                        result["reference"]["value_w_m2"])


if __name__ == "__main__":
    unittest.main()
