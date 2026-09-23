"""Pruebas del cielo observado: NASA POWER, CSV propio y su uso en el modelo.

Ninguna prueba toca la red. La descarga de POWER se reemplaza por un abridor
simulado y la caché se alimenta con un día real de la API
(tests/fixtures/power_par_2025-06-21.json, lat −41,5985, lon −73,0076).
"""

import copy
import datetime as dt
import io
import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

import ambient_light as al
import sky_forcing as sf
from simulation_engine import bio_optical_iop, hg_backscatter_fraction

LAT, LON = -41.598511, -73.0076
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "power_par_2025-06-21.json"
WL = al.REFERENCE_WAVELENGTHS_NM


def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def water():
    a, b = bio_optical_iop(WL, tss=3.0, cdom_a440=0.3, chl=1.5)
    return al.WaterColumn({"wavelength_nm": WL.tolist(), "a_m_inv": a.tolist(),
                           "bb_m_inv": (hg_backscatter_fraction(0.85) * b).tolist()})


def synthetic(start, end, ct, hour_offset_min=0):
    """Serie observada generada con el mismo modelo del modo manual."""
    times, dirh, diff = [], [], []
    d = dt.date.fromisoformat(start)
    while d <= dt.date.fromisoformat(end):
        for h in range(24):
            t = dt.datetime(d.year, d.month, d.day, h) + dt.timedelta(minutes=hour_offset_min)
            elev = al.solar_elevation_deg(LAT, LON, t, 0.0)
            par_dir = par_dif = 0.0
            if elev > 0:
                g = al.clear_sky_broadband_w_m2(elev) * ct
                kd = al.erbs_diffuse_fraction(g / al.extraterrestrial_horizontal_w_m2(t, LAT, LON))
                par = g * al.PAR_FRACTION_REFERENCE
                par_dir, par_dif = par * (1 - kd), par * kd
            times.append(t); dirh.append(par_dir); diff.append(par_dif)
        d += dt.timedelta(days=1)
    return sf.SkySeries(times, np.array(dirh), np.array(diff), 1.0, "sintética")


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class PowerParsingTests(unittest.TestCase):

    def test_real_response_is_parsed_and_centered(self):
        series = sf.parse_power_json(payload())
        self.assertEqual(len(series), 24)
        self.assertEqual(series.times_utc[0], dt.datetime(2025, 6, 21, 0, 30))
        self.assertEqual(series.step_hours, 1.0)
        self.assertEqual((series.detail["grid_lat"], series.detail["grid_lon"]), (-41.599, -73.008))

    def test_direct_plus_diffuse_equals_reported_total(self):
        data = payload()
        series = sf.parse_power_json(data)
        total = data["properties"]["parameter"]["ALLSKY_SFC_PAR_TOT"]
        expected = np.array([total[k] for k in sorted(total)])
        np.testing.assert_allclose(series.par_total, expected, atol=0.011)

    def test_overcast_winter_day_is_mostly_diffuse(self):
        series = sf.parse_power_json(payload())
        self.assertGreater(series.par_diffuse.sum() / series.par_total.sum(), 0.8)
        index = sf.clear_sky_index_summary(series, LON)
        self.assertAlmostEqual(index["p50"], 0.434, delta=0.002)

    def test_fill_values_are_dropped(self):
        data = payload()
        data["properties"]["parameter"]["ALLSKY_SFC_PAR_DIFF"]["2025062115"] = -999.0
        series = sf.parse_power_json(data)
        self.assertEqual(len(series), 23)
        self.assertNotIn(dt.datetime(2025, 6, 21, 15, 30), series.times_utc)

    def test_units_are_converted(self):
        data = payload()
        for name in data["parameters"]:
            data["parameters"][name]["units"] = "MJ/m^2"
            for k, v in data["properties"]["parameter"][name].items():
                data["properties"]["parameter"][name][k] = v * 3600.0 / 1e6
        converted = sf.parse_power_json(data)
        np.testing.assert_allclose(converted.par_total, sf.parse_power_json(payload()).par_total, atol=1e-9)
        data["parameters"]["ALLSKY_SFC_PAR_DIRH"]["units"] = "ly/day"
        with self.assertRaises(ValueError):
            sf.parse_power_json(data)


class PowerFetchTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.calls = []

    def opener(self, url, timeout=None):
        self.calls.append(url)
        return FakeResponse(json.dumps(payload()).encode())

    def test_closed_year_is_read_from_cache_without_network(self):
        (self.tmp / "power_par_-41.599_-73.008_2025.json").write_text(FIXTURE.read_text())
        def forbidden(*a, **k):
            raise AssertionError("no debía tocar la red")
        series = sf.fetch_power_year(LAT, LON, 2025, self.tmp, opener=forbidden,
                                     today=dt.date(2026, 9, 23))
        self.assertEqual(len(series), 24)
        self.assertIn("cache", series.detail)

    def test_download_is_cached_for_closed_years(self):
        sf.fetch_power_year(LAT, LON, 2024, self.tmp, opener=self.opener, today=dt.date(2026, 9, 23))
        self.assertTrue((self.tmp / "power_par_-41.599_-73.008_2024.json").exists())
        self.assertIn("start=20240101", self.calls[0])
        self.assertIn("end=20241231", self.calls[0])
        self.assertIn("time-standard=UTC", self.calls[0])
        for name in sf.POWER_PARAMETERS:
            self.assertIn(name, self.calls[0])
        sf.fetch_power_year(LAT, LON, 2024, self.tmp, opener=self.opener, today=dt.date(2026, 9, 23))
        self.assertEqual(len(self.calls), 1)

    def test_current_year_is_cached_apart_and_truncated(self):
        sf.fetch_power_year(LAT, LON, 2026, self.tmp, opener=self.opener, today=dt.date(2026, 9, 23))
        self.assertTrue((self.tmp / "power_par_-41.599_-73.008_2026_parcial.json").exists())
        self.assertIn("end=20260922", self.calls[0])

    def test_years_outside_coverage_are_rejected(self):
        for year in (2000, 2027):
            with self.assertRaises(ValueError):
                sf.fetch_power_year(LAT, LON, year, self.tmp, opener=self.opener,
                                    today=dt.date(2026, 9, 23))

    def test_load_power_requests_each_year_once(self):
        sf.load_power(LAT, LON, [2023, 2021, 2023, 2022], self.tmp, opener=self.opener,
                      today=dt.date(2026, 9, 23))
        self.assertEqual(len(self.calls), 3)


class CsvTests(unittest.TestCase):

    def local_csv(self, header, row, days=6, local_offset_h=-4.0, stamp="end", sep=";"):
        """CSV sintético de estación en hora local, con marca de fin de intervalo."""
        lines = [header]
        for day in range(1, days + 1):
            for h in range(24):
                center = dt.datetime(2024, 5, day, h, 30)
                elev = al.solar_elevation_deg(LAT, LON, center, 0.0)
                g = 0.0 if elev <= 0 else al.clear_sky_broadband_w_m2(elev) * 0.6
                shift = {"end": 30, "start": -30, "center": 0}[stamp]
                t = center + dt.timedelta(minutes=shift) + dt.timedelta(hours=local_offset_h)
                lines.append(row(t, g))
        return "\n".join(lines).replace("\n", "\n") if sep == ";" else "\n".join(lines)

    def test_offset_and_stamp_convention_are_detected(self):
        text = self.local_csv("fecha_hora;radiacion_global (W/m2);difusa",
                              lambda t, g: f"{t:%d/%m/%Y %H:%M};{g:.2f};{0.5 * g:.2f}".replace(".", ","))
        series = sf.parse_sky_csv(text, LAT, LON)
        self.assertEqual(series.detail["utc_shift_applied_h"], 3.5)   # UTC−4 y marca al final
        self.assertGreater(series.detail["alignment_r"], 0.95)
        self.assertEqual(len(series), 6 * 24)
        self.assertIn("difusa medida", series.detail["basis"])
        # global y difusa se escribieron con dos decimales cada una
        np.testing.assert_allclose(series.par_diffuse, series.par_direct_h, atol=0.01)

    def test_declared_offset_is_refined_by_half_hours(self):
        text = self.local_csv("fecha,ghi", lambda t, g: f"{t:%Y-%m-%d %H:%M},{g:.2f}", stamp="start")
        series = sf.parse_sky_csv(text, LAT, LON, utc_offset_h=-4.0)
        self.assertEqual(series.detail["utc_shift_applied_h"], 4.5)
        self.assertEqual(series.detail["offset_source"], "declarado")
        self.assertIn("Erbs", series.detail["basis"])

    def test_timezone_aware_timestamps_are_respected(self):
        text = self.local_csv("timestamp,par_w_m2",
                              lambda t, g: f"{t:%Y-%m-%dT%H:%M:00}-04:00,{0.43 * g:.3f}", stamp="center")
        series = sf.parse_sky_csv(text, LAT, LON)
        self.assertEqual(series.detail["utc_shift_applied_h"], 0.0)
        self.assertEqual(series.detail["offset_source"], "zona horaria del archivo")

    def test_par_in_micromol_is_converted(self):
        text = self.local_csv("fecha_hora,ppfd", lambda t, g: f"{t:%Y-%m-%d %H:%M},{g * 0.43 * 4.57:.3f}",
                              stamp="center", local_offset_h=0.0)
        series = sf.parse_sky_csv(text, LAT, LON, utc_offset_h=0.0)
        noon = int(np.argmax(series.par_total))
        ref = al.clear_sky_broadband_w_m2(al.solar_elevation_deg(LAT, LON, series.times_utc[noon], 0.0)) * 0.6 * 0.43
        self.assertAlmostEqual(series.par_total[noon], ref, delta=0.05)

    def test_measured_par_split_is_used_as_is(self):
        text = self.local_csv("fecha_hora;par_dirh;par_diff",
                              lambda t, g: f"{t:%Y-%m-%d %H:%M};{0.1 * g:.3f};{0.3 * g:.3f}",
                              stamp="center", local_offset_h=0.0)
        series = sf.parse_sky_csv(text, LAT, LON, utc_offset_h=0.0)
        self.assertIn("PAR directo y difuso medidos", series.detail["basis"])
        lit = series.par_total > 0
        np.testing.assert_allclose(series.par_diffuse[lit] / series.par_direct_h[lit], 3.0, rtol=0.02)

    def test_daily_data_and_missing_columns_are_rejected(self):
        daily = "fecha,ghi\n" + "\n".join(f"2024-05-{d:02d},{100 + d}" for d in range(1, 20))
        with self.assertRaises(ValueError):
            sf.parse_sky_csv(daily, LAT, LON)
        with self.assertRaises(ValueError):
            sf.parse_sky_csv("fecha_hora,temperatura\n2024-05-01 10:00,12\n" * 20, LAT, LON)


class ObservedSkyModelTests(unittest.TestCase):

    KW = dict(lat_deg=LAT, lon_deg=LON, start="2026-04-01", end="2026-05-31",
              reference_depth_m=8.0, target_depth_m=10.0, ratio=0.10)

    def test_observed_path_reproduces_the_manual_model_exactly(self):
        """Con datos generados por el modelo manual, ambos caminos coinciden."""
        manual = al.evaluate(water=water(), cloud_transmittance=0.6, tz_offset_h=0.0,
                             step_minutes=60, **self.KW)
        observed = al.evaluate(water=water(), sky=synthetic("2026-04-01", "2026-05-31", 0.6), **self.KW)
        self.assertAlmostEqual(observed["reference"]["value_w_m2"], manual["reference"]["value_w_m2"],
                               places=10)
        self.assertTrue(observed["sky"]["observed"])
        self.assertIsNone(observed["settings"]["cloud_transmittance"])

    def test_real_overcast_day_is_darker_than_the_manual_default(self):
        real = sf.parse_power_json(payload())
        kw = {**self.KW, "start": "2025-06-21", "end": "2025-06-21"}
        observed = al.evaluate(water=water(), sky=real, **kw)["reference"]["value_w_m2"]
        manual = al.evaluate(water=water(), cloud_transmittance=0.7, **kw)["reference"]["value_w_m2"]
        self.assertLess(observed, manual)

    def test_climatology_pools_every_day_year(self):
        series = sf.concat([synthetic(f"{y}-04-01", f"{y}-05-31", ct)
                            for y, ct in ((2021, 0.4), (2022, 0.6), (2023, 0.8))], "sintética")
        result = al.evaluate(water=water(), sky=series, sky_mode=al.SKY_MODE_CLIMATOLOGY,
                             sky_years=[2021, 2022, 2023], **self.KW)
        self.assertEqual(result["sky"]["days_used"], 3 * 61)
        self.assertEqual(result["sky"]["years_used"], [2021, 2022, 2023])
        profile = result["profile"]
        self.assertEqual(len(profile["dates"]), 61)
        self.assertEqual(set(profile["years_per_date"]), {3})
        for lo, mid, hi in zip(profile["photophase_p10_w_m2"], profile["photophase_mean_w_m2"],
                               profile["photophase_p90_w_m2"]):
            self.assertLessEqual(lo, mid)
            self.assertLessEqual(mid, hi)

    def test_percentile_over_pooled_years_spans_the_years(self):
        years = ((2021, 0.4), (2022, 0.6), (2023, 0.8))
        series = sf.concat([synthetic(f"{y}-04-01", f"{y}-05-31", ct) for y, ct in years], "sintética")
        pooled = lambda p: al.evaluate(water=water(), sky=series, sky_mode=al.SKY_MODE_CLIMATOLOGY,
                                       sky_years=[2021, 2022, 2023], percentile=p, **self.KW)
        single = al.evaluate(water=water(), sky=series, **{**self.KW, "start": "2022-04-01",
                                                          "end": "2022-05-31"})
        self.assertLess(pooled(0)["reference"]["value_w_m2"], single["reference"]["value_w_m2"])
        self.assertGreater(pooled(90)["reference"]["value_w_m2"], single["reference"]["value_w_m2"])

    def test_days_without_data_are_excluded_and_reported(self):
        result = al.evaluate(water=water(), sky=synthetic("2026-04-01", "2026-04-30", 0.6), **self.KW)
        self.assertEqual(result["sky"]["days_used"], 30)
        self.assertEqual(result["sky"]["days_missing"], 31)
        self.assertEqual(result["sky"]["missing_first"][0], "2026-05-01")

    def test_no_usable_day_is_an_explicit_error(self):
        with self.assertRaises(ValueError):
            al.evaluate(water=water(), sky=synthetic("2020-01-01", "2020-01-05", 0.6), **self.KW)

    def test_window_crossing_new_year_and_leap_day(self):
        days = al.window_days("2023-12-30", "2024-01-02", al.SKY_MODE_CLIMATOLOGY, [2019, 2020])
        self.assertIn((dt.date(2019, 12, 30), dt.date(2023, 12, 30)), days)
        self.assertIn((dt.date(2020, 1, 2), dt.date(2024, 1, 2)), days)
        leap = al.window_days("2024-02-28", "2024-03-01", al.SKY_MODE_CLIMATOLOGY, [2023, 2024])
        per_year = {y: [d for d, _ in leap if d.year == y] for y in (2023, 2024)}
        self.assertEqual(len(per_year[2023]), 2)          # sin 29 de febrero
        self.assertEqual(len(per_year[2024]), 3)
        self.assertIn(dt.date(2024, 2, 29), per_year[2024])


if __name__ == "__main__":
    unittest.main()
