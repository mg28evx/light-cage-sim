"""Pruebas de integración de /api/photoperiod_target con la óptica del simulador."""

import datetime as dt
import io
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

import ambient_light as al
import app_sim
import sky_forcing

BASE = {
    "lat": -41.598511, "lon": -73.0076,
    "start_date": "2026-04-01", "end_date": "2026-05-31",
    "reference_depth_m": 8, "target_depth_m": 10,
    "ratio": 0.10, "percentile": 50, "cloud_transmittance": 0.6,
    "operation": "24h", "step_minutes": 60,
}
BIO = {"optics_mode": "scattering",
       "optics": {"mc_input_type": "bio", "tss": 3.0, "cdom_a440": 0.3, "chl": 1.5,
                  "g": 0.85, "phase_function": "hg"}}
KD_FIXED = {"optics_mode": "kd_fijo", "kd_list": [0.25],
            "optics": {"atten_coef_type": "kd", "omega": 0.8, "g": 0.85}}
RAS = {"optics_mode": "scattering",
       "optics": {"mc_input_type": "ras_bardsnes", "tss": 5.0, "cdom_a440": 2.0, "chl": 0.0}}
SCALAR_C = {"optics_mode": "scattering",
            "optics": {"mc_input_type": "scalar", "c": 0.6, "omega": 0.8, "g": 0.85}}


def seasonal(weeks, tss=8.0, cdom=0.8, chl=4.0):
    return {"scenario": "turbio",
            "weeks": {str(w): {"tss": tss, "cdom_a440": cdom, "chl": chl} for w in weeks},
            "center": {"name": "Prueba", "lat": -41.6, "lon": -73.0}}


class PhotoperiodEndpointTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = app_sim.app.test_client()

    def post(self, **extra):
        response = self.client.post("/api/photoperiod_target", json={**BASE, **extra})
        return response.status_code, response.get_json()

    def test_every_optics_mode_resolves_a_water_column(self):
        for name, optics in (("bio", BIO), ("kd fijo", KD_FIXED), ("RAS", RAS), ("c escalar", SCALAR_C)):
            code, data = self.post(**optics)
            self.assertEqual(code, 200, msg=name)
            self.assertEqual(data["status"], "ok", msg=name)
            self.assertGreater(data["water"]["kd_par_surface_m_inv"], 0.0, msg=name)
            self.assertEqual(data["water"]["kd_closure_natural"], "lee2005")

    def test_turbid_optics_lowers_the_reference(self):
        clear = {**BIO, "optics": {**BIO["optics"], "tss": 1.0, "cdom_a440": 0.1, "chl": 0.5}}
        turbid = {**BIO, "optics": {**BIO["optics"], "tss": 8.0, "cdom_a440": 0.8, "chl": 4.0}}
        self.assertGreater(self.post(**clear)[1]["reference"]["value_w_m2"],
                           self.post(**turbid)[1]["reference"]["value_w_m2"])

    def test_declared_kd_is_honoured_approximately(self):
        """Kd fijo pasa por la inversión de Kirk y el cierre de Lee: queda cerca."""
        kd = self.post(**KD_FIXED)[1]["water"]["kd_par_surface_m_inv"]
        self.assertAlmostEqual(kd, 0.25, delta=0.03)

    def test_seasonal_profile_changes_the_weeks_it_covers(self):
        base = self.post(**BIO)[1]
        weeks = base["water"]["window_weeks"]
        withs = self.post(**BIO, seasonal=seasonal(weeks))[1]
        self.assertEqual(withs["water"]["window_weeks_with_own_iop"], weeks)
        self.assertIn("perfil estacional", withs["water"]["mode_label"])
        self.assertLess(withs["reference"]["value_w_m2"], base["reference"]["value_w_m2"])

    def test_seasonal_profile_is_ignored_outside_bio_modes(self):
        data = self.post(**KD_FIXED, seasonal=seasonal([14, 15]))[1]
        self.assertEqual(data["water"]["weeks_with_own_iop"], 0)
        self.assertTrue(data["water"]["notes"])

    def test_unreachable_ll_in_24h_is_not_an_error(self):
        code, data = self.post(**BIO, ratio=1.0)
        self.assertEqual(code, 200)
        self.assertIsNone(data["target"]["target_w_m2"])
        self.assertIn("inalcanzable", data["target"]["binding_term"])

    def test_response_has_proposals_and_no_lamp_block(self):
        data = self.post(**BIO)[1]
        self.assertIn("proposals", data)
        self.assertNotIn("lamps", data)

    def test_reversed_window_returns_an_error_message(self):
        code, data = self.post(**BIO, start_date="2026-06-01", end_date="2026-05-01")
        self.assertEqual(code, 500)
        self.assertEqual(data["status"], "error")
        self.assertIn("ventana", data["msg"])

    def test_default_diagnostic_grid_is_unchanged(self):
        """run_simulation sigue recibiendo los ocho puntos espectrales de siempre."""
        diag = app_sim.build_optical_diagnostics(
            {"optics": BIO["optics"]}, "scattering", "bio", "c", 0.0)
        self.assertEqual(diag["wavelength_nm"], [400.0, 450.0, 490.0, 500.0, 550.0, 600.0, 650.0, 700.0])


class PhotoperiodSkyEndpointTests(unittest.TestCase):
    """Fuentes de cielo sin tocar la red: caché con un día real y CSV sintético."""

    FIXTURE = Path(__file__).resolve().parent / "fixtures" / "power_par_2025-06-21.json"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._cache, self._uploads = sky_forcing.CACHE_DIR, app_sim.SKY_UPLOAD_DIR
        self._fetch = sky_forcing.fetch_power_year
        sky_forcing.CACHE_DIR = self.tmp
        app_sim.SKY_UPLOAD_DIR = str(self.tmp / "uploads")
        shutil.copy(self.FIXTURE, self.tmp / "power_par_-41.599_-73.008_2025.json")
        self.client = app_sim.app.test_client()

    def tearDown(self):
        sky_forcing.CACHE_DIR, app_sim.SKY_UPLOAD_DIR = self._cache, self._uploads
        sky_forcing.fetch_power_year = self._fetch
        shutil.rmtree(self.tmp, ignore_errors=True)

    def post(self, **extra):
        body = {**BASE, **BIO, "start_date": "2025-06-21", "end_date": "2025-06-21", **extra}
        response = self.client.post("/api/photoperiod_target", json=body)
        return response.status_code, response.get_json()

    def test_power_from_cache_reports_empirical_cloudiness(self):
        code, data = self.post(sky={"source": "power", "mode": "window"})
        self.assertEqual(code, 200, msg=data)
        self.assertTrue(data["sky"]["observed"])
        self.assertEqual(data["sky"]["days_used"], 1)
        self.assertAlmostEqual(data["sky"]["clear_sky_index"]["p50"], 0.434, delta=0.002)
        self.assertNotIn("used_dates", data["sky"])
        self.assertIsNone(data["settings"]["cloud_transmittance"])

    def test_manual_remains_available_as_fallback(self):
        code, data = self.post(sky={"source": "manual"}, cloud_transmittance=0.7)
        self.assertEqual(code, 200)
        self.assertFalse(data["sky"]["observed"])
        self.assertEqual(data["settings"]["cloud_transmittance"], 0.7)

    def test_network_failure_explains_the_alternatives(self):
        def offline(*args, **kwargs):
            raise OSError("sin conexión")
        sky_forcing.fetch_power_year = offline
        code, data = self.post(start_date="2024-06-21", end_date="2024-06-21",
                               sky={"source": "power", "mode": "window"})
        self.assertEqual(code, 500)
        self.assertIn("NASA POWER", data["msg"])
        self.assertIn("CSV", data["msg"])

    def test_csv_upload_then_use(self):
        rows = ["fecha_hora;radiacion_global;difusa"]
        for day in range(1, 8):
            for h in range(24):
                center = dt.datetime(2024, 5, day, h, 30)
                elev = al.solar_elevation_deg(BASE["lat"], BASE["lon"], center, 0.0)
                g = 0.0 if elev <= 0 else al.clear_sky_broadband_w_m2(elev) * 0.6
                t = center + dt.timedelta(minutes=30) - dt.timedelta(hours=4)
                rows.append(f"{t:%d/%m/%Y %H:%M};{g:.2f};{0.6 * g:.2f}")
        upload = self.client.post(
            "/api/sky_observations/upload",
            data={"file": (io.BytesIO("\n".join(rows).encode()), "estacion.csv"),
                  "lat": str(BASE["lat"]), "lon": str(BASE["lon"])},
            content_type="multipart/form-data").get_json()
        self.assertEqual(upload["status"], "ok", msg=upload)
        self.assertEqual(upload["utc_shift_applied_h"], 3.5)
        code, data = self.post(start_date="2024-05-01", end_date="2024-05-07",
                               sky={"source": "csv", "mode": "window", "csv_path": upload["path"]})
        self.assertEqual(code, 200, msg=data)
        self.assertEqual(data["sky"]["days_used"], 7)

    def test_csv_path_outside_uploads_is_refused(self):
        code, data = self.post(sky={"source": "csv", "csv_path": "/etc/passwd"})
        self.assertEqual(code, 500)
        self.assertEqual(data["status"], "error")


if __name__ == "__main__":
    unittest.main()
