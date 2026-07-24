#!/usr/bin/env python3
"""Inversión fotométrica del apéndice 3 de Porter et al. (2005).

Genera una fotometría TM-33-18 sintética, configuraciones reproducibles del
simulador y tablas/gráficas con incertidumbre. La escala absoluta se regulariza
con un prior tecnológico para una lámpara de halogenuros metálicos de 400 W
circa 2005 (33--38 klm y 25--31 % de radiación visible). El apéndice no publica
el espectro ni identifica si la unidad medida fue Aquabeam Pisces o C&T.

Modelo directo (sensor sobre un plano horizontal):

    E_v(r,z) = B + I_v(theta) cos(theta) exp(-c d) / d**2

con d=hypot(r,z), theta=atan2(r,z), B como campo difuso/fondo efectivo e I_v
regularizada en log-intensidad. El término c es atenuación de haz por camino,
no Kd; no debe inferirse c directamente desde Secchi sin un cierre óptico.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import numpy as np
from scipy.optimize import least_squares


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "porter_2005_appendix3_lux.csv"
OUT_DIR = ROOT / "sensitivity" / "out" / "porter_2005"
XML_PATH = ROOT / "uploaded_lamps" / "PORTER_2005_SYNTHETIC_400W.xml"
TRIAL3_XML_PATH = ROOT / "uploaded_lamps" / "PORTER_2005_TRIAL3_SYNTHETIC_400W.xml"
CONFIG_PATH = ROOT / "confgs" / "porter_2005_synthetic.json"
TRIAL_CONFIG_PATH = ROOT / "confgs" / "porter_2005_trial2_80m_perimeter.json"
GROWTH_LIT_CONFIG_PATH = ROOT / "confgs" / "porter_2005_growth18_lit.json"
GROWTH_CONTROL_CONFIG_PATH = ROOT / "confgs" / "porter_2005_growth18_control.json"
GROWTH_LIT_CONFG_PATH = ROOT / "confgs" / "porter_2005_trial3_growth18_lit.confg"

KNOTS_DEG = np.arange(0.0, 91.0, 10.0)
BACKGROUND_MAX_LUX = 60.0
REGULARIZATION = 0.70
INPUT_POWER_W = 400.0
LUMINOUS_FLUX_TARGET_LM = 35_500.0
LUMINOUS_FLUX_RANGE_LM = (33_000.0, 38_000.0)
RADIANT_FLUX_TARGET_W = 116.0
RADIANT_FLUX_RANGE_W = (100.0, 124.0)
SPD_CCT_K = 3700.0
FLUX_PRIOR_LOG_SIGMA = 0.01
TRIAL_CAGE_PERIMETER_M = 80.0
TRIAL_CAGE_RADIUS_M = TRIAL_CAGE_PERIMETER_M / (2.0 * math.pi)


@dataclass(frozen=True)
class Measurements:
    horizontal_m: np.ndarray
    vertical_m: np.ndarray
    observed_lux: np.ndarray


def load_measurements(path: Path = DATA_PATH) -> Measurements:
    rows = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rows.append((float(row["horizontal_m"]),
                         float(row["vertical_m"]),
                         float(row["observed_lux"])))
    arr = np.asarray(rows, dtype=float)
    if arr.shape != (48, 3):
        raise ValueError(f"Se esperaban 48 puntos del apéndice 3; recibido {arr.shape}")
    return Measurements(arr[:, 0], arr[:, 1], arr[:, 2])


def _background_from_unconstrained(value: float | np.ndarray) -> np.ndarray:
    value = np.asarray(value, dtype=float)
    return BACKGROUND_MAX_LUX / (1.0 + np.exp(-np.clip(value, -40.0, 40.0)))


def _unconstrained_from_background(background_lux: float) -> float:
    f = np.clip(background_lux / BACKGROUND_MAX_LUX, 1e-8, 1.0 - 1e-8)
    return float(np.log(f / (1.0 - f)))


def luminous_intensity_cd(params: np.ndarray, theta_deg: np.ndarray) -> np.ndarray:
    log_i = np.interp(np.asarray(theta_deg, dtype=float), KNOTS_DEG,
                      np.asarray(params[: len(KNOTS_DEG)], dtype=float))
    return np.exp(log_i)


def forward_components(params: np.ndarray, horizontal_m: np.ndarray,
                       vertical_m: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    r = np.asarray(horizontal_m, dtype=float)
    z = np.asarray(vertical_m, dtype=float)
    distance = np.hypot(r, z)
    theta_deg = np.degrees(np.arctan2(r, z))
    cos_theta = z / distance
    c_beam = float(np.exp(params[-2]))
    background = float(_background_from_unconstrained(params[-1]))
    lamp_lux = (luminous_intensity_cd(params, theta_deg) * cos_theta
                * np.exp(-c_beam * distance) / distance**2)
    return lamp_lux, lamp_lux + background, background


def fit_model(meas: Measurements, initial: np.ndarray | None = None,
              observed_override: np.ndarray | None = None,
              luminous_flux_target_lm: float = LUMINOUS_FLUX_TARGET_LM) -> np.ndarray:
    observed = (meas.observed_lux if observed_override is None
                else np.asarray(observed_override, dtype=float))
    log_observed = np.log(np.maximum(observed, 1e-9))
    if initial is None:
        initial = np.r_[np.linspace(np.log(1.2e4), np.log(1.0e3), len(KNOTS_DEG)),
                        np.log(0.45), _unconstrained_from_background(25.0)]

    def residual(params: np.ndarray) -> np.ndarray:
        _, total, _ = forward_components(params, meas.horizontal_m, meas.vertical_m)
        data_residual = np.log(np.maximum(total, 1e-12)) - log_observed
        curvature = np.diff(params[: len(KNOTS_DEG)], n=2)
        angles, intensity = angular_profile(params)
        flux = integrate_axisymmetric_flux(angles, intensity)
        flux_prior = (
            np.log(max(flux, 1e-12) / luminous_flux_target_lm)
            / FLUX_PRIOR_LOG_SIGMA
        )
        return np.r_[data_residual, REGULARIZATION * curvature, flux_prior]

    lower = np.r_[np.full(len(KNOTS_DEG), np.log(1.0)), np.log(0.02), -8.0]
    upper = np.r_[np.full(len(KNOTS_DEG), np.log(2.0e6)), np.log(2.0), 8.0]
    result = least_squares(
        residual, initial, bounds=(lower, upper), loss="soft_l1",
        f_scale=0.25, max_nfev=4000,
    )
    if not result.success:
        raise RuntimeError(f"La optimización no convergió: {result.message}")
    return result.x


def residual_bootstrap(meas: Measurements, nominal: np.ndarray, n_boot: int,
                       seed: int) -> np.ndarray:
    if n_boot <= 0:
        return nominal[np.newaxis, :]
    _, fitted, _ = forward_components(nominal, meas.horizontal_m, meas.vertical_m)
    log_residual = np.log(meas.observed_lux) - np.log(fitted)
    log_residual -= np.mean(log_residual)
    rng = np.random.default_rng(seed)
    samples = []
    for _ in range(n_boot):
        synthetic = fitted * np.exp(rng.choice(log_residual, size=len(log_residual), replace=True))
        flux_target = rng.uniform(*LUMINOUS_FLUX_RANGE_LM)
        try:
            samples.append(fit_model(
                meas, initial=nominal, observed_override=synthetic,
                luminous_flux_target_lm=flux_target,
            ))
        except RuntimeError:
            continue
    if len(samples) < max(20, n_boot // 2):
        raise RuntimeError(f"Bootstrap inestable: sólo {len(samples)}/{n_boot} ajustes válidos")
    return np.asarray(samples)


def photopic_v_app(wavelength_nm: np.ndarray) -> np.ndarray:
    """Misma aproximación Wyman-Sloan-Shirley usada por app_sim.py."""
    wavelength_um = np.asarray(wavelength_nm, dtype=float) / 1000.0
    v = (1.019 * np.exp(-285.4 * (wavelength_um - 0.559) ** 2)
         - 0.092 * np.exp(-1250.0 * (wavelength_um - 0.450) ** 2))
    return np.clip(v, 0.0, 1.0)


def synthetic_spd() -> tuple[np.ndarray, np.ndarray, float, dict]:
    """SPD blanco de halogenuros metálicos, condicionado por el prior energético.

    Se combina un continuo de Planck a 3700 K con líneas anchas representativas
    de Hg/haluros. La fracción de líneas se resuelve para conservar simultáneamente
    el flujo luminoso y los 116 W radiantes nominales. No pretende reemplazar una
    medición espectroradiométrica de la unidad original.
    """
    wavelengths = np.arange(380.0, 781.0, 5.0)
    trapz = np.trapezoid if hasattr(np, "trapezoid") else np.trapz
    wavelength_m = wavelengths * 1e-9
    c2 = 1.438776877e-2
    continuum = 1.0 / (
        wavelength_m**5 * np.expm1(c2 / (wavelength_m * SPD_CCT_K))
    )
    continuum /= trapz(continuum, wavelengths)

    lines = np.zeros_like(wavelengths)
    for center, weight, sigma_nm in (
        (436.0, 0.12, 5.0),
        (546.0, 0.45, 6.0),
        (578.0, 0.28, 7.0),
        (611.0, 0.15, 8.0),
    ):
        lines += weight * np.exp(-0.5 * ((wavelengths - center) / sigma_nm) ** 2)
    lines /= trapz(lines, wavelengths)

    continuum_ler = 683.0 * trapz(continuum * photopic_v_app(wavelengths), wavelengths)
    lines_ler = 683.0 * trapz(lines * photopic_v_app(wavelengths), wavelengths)
    target_ler = LUMINOUS_FLUX_TARGET_LM / RADIANT_FLUX_TARGET_W
    line_fraction = np.clip(
        (target_ler - continuum_ler) / (lines_ler - continuum_ler), 0.0, 1.0
    )
    power = (1.0 - line_fraction) * continuum + line_fraction * lines
    power /= trapz(power, wavelengths)
    luminous_efficacy = 683.0 * trapz(power * photopic_v_app(wavelengths), wavelengths)
    return wavelengths, power, float(luminous_efficacy), {
        "shape": "3700 K continuum plus metal-halide emission-line surrogate",
        "cct_K": SPD_CCT_K,
        "line_fraction_radiant": float(line_fraction),
        "status": "technology prior; original SPD unavailable",
    }


def spectral_conversion_samples(n: int, seed: int = 5352005) -> np.ndarray:
    """Escenarios de conversión lux/W coherentes con el prior tecnológico."""
    rng = np.random.default_rng(seed)
    luminous_flux = rng.uniform(*LUMINOUS_FLUX_RANGE_LM, size=n)
    radiant_flux = rng.uniform(*RADIANT_FLUX_RANGE_W, size=n)
    return luminous_flux / radiant_flux


def angular_profile(params: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    angles = np.arange(0.0, 181.0, 2.0)
    intensity = np.zeros_like(angles)
    downward = angles < 90.0
    intensity[downward] = luminous_intensity_cd(params, angles[downward])
    return angles, intensity


def integrate_axisymmetric_flux(angles_deg: np.ndarray, intensity: np.ndarray) -> float:
    theta = np.radians(angles_deg)
    trapz = np.trapezoid if hasattr(np, "trapezoid") else np.trapz
    return float(2.0 * np.pi * trapz(intensity * np.sin(theta), theta))


def write_tm33(params: np.ndarray, bootstrap: np.ndarray, path: Path,
               application: str | None = None) -> dict:
    wavelengths, spd, luminous_efficacy, spd_meta = synthetic_spd()
    angles, luminous_intensity = angular_profile(params)
    radiant_intensity = luminous_intensity / luminous_efficacy
    luminous_flux = integrate_axisymmetric_flux(angles, luminous_intensity)
    radiant_flux = luminous_flux / luminous_efficacy
    efficiency = radiant_flux / INPUT_POWER_W
    c_samples = np.exp(bootstrap[:, -2])
    c_lo, c_hi = np.quantile(c_samples, [0.05, 0.95])

    root = ET.Element("IESTM33")
    header = ET.SubElement(root, "Header")
    ET.SubElement(header, "Manufacturer").text = "SYNTHETIC - Porter et al. 2005 inverse reconstruction"
    description = (
        "Synthetic axisymmetric 400 W metal-halide underwater source inferred from Appendix 3 "
        "luxometry and a 33-38 klm historical technology prior; not laboratory gonio-photometry"
    )
    if application:
        description += f"; application: {application}"
    ET.SubElement(header, "Description").text = description
    ET.SubElement(header, "Laboratory").text = "EVOLUX computational reconstruction"
    ET.SubElement(header, "ReportNumber").text = "FRDC 2001/246 Appendix 3"
    ET.SubElement(header, "ReportDate").text = "2005-08"
    ET.SubElement(header, "DocumentCreationDate").text = date.today().isoformat()

    luminaire = ET.SubElement(root, "Luminaire")
    dims = ET.SubElement(luminaire, "Dimensions")
    for tag in ("Length", "Width", "Height"):
        ET.SubElement(dims, tag).text = "0"
    ET.SubElement(luminaire, "Shape").text = "Point_Axisymmetric"
    ET.SubElement(luminaire, "NumEmitter").text = "1"

    emitter = ET.SubElement(root, "Emitter")
    ET.SubElement(emitter, "Quantity").text = "1"
    ET.SubElement(emitter, "InputWattage").text = f"{INPUT_POWER_W:.6f}"
    generation = ET.SubElement(emitter, "DataGeneration")
    ET.SubElement(generation, "Simulation").text = "true"
    lab = ET.SubElement(generation, "Laboratory")
    uncertainty = ET.SubElement(ET.SubElement(lab, "MeasUncertainty"), "Uncertainty")
    uncertainty.text = (
        f"Model-based 90% c interval [{c_lo:.4f}, {c_hi:.4f}] 1/m; "
        "source prior 33-38 klm and 100-124 W visible"
    )
    ET.SubElement(generation, "IntensityScaling").text = "true"
    ET.SubElement(generation, "AngleInterpolation").text = "true"

    luminous_data = ET.SubElement(emitter, "LuminousData")
    luminous_node = ET.SubElement(luminous_data, "LuminousIntensity")
    ET.SubElement(luminous_node, "AbsolutePhotometry").text = "true"
    ET.SubElement(luminous_node, "NumberMeasured").text = str(len(angles))
    ET.SubElement(luminous_node, "NumberHorz").text = "1"
    ET.SubElement(luminous_node, "NumberVert").text = str(len(angles))
    for angle, value in zip(angles, luminous_intensity):
        ET.SubElement(luminous_node, "IntData", h="0", v=f"{angle:.1f}").text = f"{value:.9g}"
    ET.SubElement(luminous_data, "LuminousFlux").text = f"{luminous_flux:.9g}"

    radiant_data = ET.SubElement(emitter, "RadiantData")
    ET.SubElement(radiant_data, "MinWavelength").text = f"{wavelengths.min():.0f}"
    ET.SubElement(radiant_data, "MaxWavelength").text = f"{wavelengths.max():.0f}"
    radiant_node = ET.SubElement(radiant_data, "RadiantIntensity")
    ET.SubElement(radiant_node, "NumberMeasured").text = str(len(angles))
    ET.SubElement(radiant_node, "NumberHorz").text = "1"
    ET.SubElement(radiant_node, "NumberVert").text = str(len(angles))
    for angle, value in zip(angles, radiant_intensity):
        ET.SubElement(radiant_node, "IntData", h="0", v=f"{angle:.1f}").text = f"{value:.9g}"
    ET.SubElement(radiant_data, "RadiantFlux").text = f"{radiant_flux:.9g}"

    spectral_data = ET.SubElement(emitter, "SpectralData")
    spectral = ET.SubElement(spectral_data, "EmitterSpectral")
    ET.SubElement(spectral, "NumberWavelength").text = str(len(wavelengths))
    for wavelength, value in zip(wavelengths, spd):
        ET.SubElement(spectral, "PwrData", w=f"{wavelength:.0f}").text = f"{value:.12g}"

    regulatory = ET.SubElement(emitter, "Regulatory")
    for tag in ("InputWattage", "LuminousIntensity", "LuminousFlux",
                "RadiantIntensity", "RadiantFlux", "SpectralPower"):
        ET.SubElement(regulatory, tag).text = "Synthetic"

    ET.indent(root, space="  ")
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return {
        "luminous_efficacy_lm_per_W": luminous_efficacy,
        "luminous_flux_lm": luminous_flux,
        "radiant_flux_W": radiant_flux,
        "electrical_to_radiant_efficiency": efficiency,
        "electrical_luminous_efficacy_lm_per_W": luminous_flux / INPUT_POWER_W,
        "spd_assumption": spd_meta,
    }


def write_config(params: np.ndarray, bootstrap: np.ndarray, tm33_meta: dict,
                 path: Path) -> None:
    c_beam = float(np.exp(params[-2]))
    background = float(_background_from_unconstrained(params[-1]))
    c_ci = np.quantile(np.exp(bootstrap[:, -2]), [0.05, 0.95]).tolist()
    bg_ci = np.quantile(_background_from_unconstrained(bootstrap[:, -1]), [0.05, 0.95]).tolist()
    config = {
        "project_title": "Porter 2005 Appendix 3 - synthetic reconstruction",
        "env": {"type": "jaula", "shape": "rect", "radio": None,
                "x": 22, "y": 20, "z": 10, "z_interface": 0,
                "n1": 1.0, "n2": 1.33},
        "poly": {"sides": 0, "dist": 0},
        "roi": {"type": "global"},
        "optics_mode": "kd_fijo",
        "optics": {
            "mode": "kd_fijo", "kd_fijo": c_beam, "atten_coef_type": "c",
            "mc_input_type": "scalar", "c": c_beam, "omega": 0.8,
            "g": 0.85, "r_wall": 0.0,
        },
        "kd_list": [c_beam],
        "secchi_model": "lee2015",
        "target_depths": [2, 3, 4, 5, 6, 7],
        "rays": 1000000,
        "grid_bins": 110,
        "source_model": "point",
        "irradiance_type": "scalar",
        "draw_contour": True,
        "contour_vals": [0.017, 0.1, 1.0],
        "color_scale_type": "log",
        "plot_depth_profile": True,
        "plot_depth_summary_table": True,
        "plot_env_optics": True,
        "plot_light_quality": True,
        "plot_spectrum_initial": True,
        "plot_spectrum_normalized": True,
        "spectrum_lamps": [XML_PATH.name],
        "lamps": [{
            "label": "Porter-400W-synthetic", "xml": XML_PATH.name,
            "type": "submerged", "enabled": True,
            "x": 10.0, "y": 10.0, "z": 1.0,
            "power": INPUT_POWER_W, "nominal_power": INPUT_POWER_W,
            "efficiency": tm33_meta["electrical_to_radiant_efficiency"],
            "dim": 1.0, "manual_z": True, "manual_power": True,
            "rot_x": 0.0, "rot_y": 0.0, "rot_z": 0.0,
        }],
        "porter_calibration": {
            "source": "FRDC 2001/246, Appendix 3, page 65",
            "horizontal_measurement_m": [1, 2, 3, 4, 5, 6, 7, 8],
            "vertical_measurement_m_relative_to_lamp": [1, 2, 3, 4, 5, 6],
            "beam_attenuation_c_per_m": c_beam,
            "beam_attenuation_c_90pct_CI_per_m": c_ci,
            "effective_diffuse_background_lux": background,
            "effective_diffuse_background_90pct_CI_lux": bg_ci,
            "source_technology_prior": {
                "type": "400 W broad-white metal halide, circa 2005",
                "luminous_flux_nominal_lm": LUMINOUS_FLUX_TARGET_LM,
                "luminous_flux_range_lm": list(LUMINOUS_FLUX_RANGE_LM),
                "radiant_flux_nominal_W": RADIANT_FLUX_TARGET_W,
                "radiant_flux_range_W": list(RADIANT_FLUX_RANGE_W),
            },
            "spd_assumption": tm33_meta["spd_assumption"],
            "luminous_efficacy_lm_per_W": tm33_meta["luminous_efficacy_lm_per_W"],
            "comparison_rule": "simulated lamp lux + effective diffuse background lux",
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_trial_config(params: np.ndarray, tm33_meta: dict, path: Path) -> None:
    """Escenario Year 2: jaula de 80 m de perímetro y ocho luces a 5 m.

    El informe dice literalmente ``80m diameter``, pero se interpreta como
    perímetro: 80 m de diámetro produciría una biomasa incompatible con la
    densidad de cosecha publicada. La posición radial R/2 es una hipótesis
    explícita porque el documento sólo dice ``spaced equidistant throughout``.
    """
    center = TRIAL_CAGE_RADIUS_M
    lamp_ring_radius = TRIAL_CAGE_RADIUS_M / 2.0
    lamps = []
    for i, phi in enumerate(np.linspace(0.0, 2.0 * np.pi, 8, endpoint=False), start=1):
        lamps.append({
            "label": f"Porter-400W-{i:02d}", "xml": XML_PATH.name,
            "type": "submerged", "enabled": True,
            "x": center + lamp_ring_radius * float(np.cos(phi)),
            "y": center + lamp_ring_radius * float(np.sin(phi)),
            "z": 5.0, "power": INPUT_POWER_W, "nominal_power": INPUT_POWER_W,
            "efficiency": tm33_meta["electrical_to_radiant_efficiency"],
            "dim": 1.0, "manual_z": True, "manual_power": True,
            "rot_x": 0.0, "rot_y": 0.0, "rot_z": 0.0,
        })
    c_beam = float(np.exp(params[-2]))
    config = {
        "project_title": "Porter 2005 Year 2 - 80 m perimeter cage, 8 x 400 W",
        "env": {
            "type": "jaula", "shape": "circle", "radio": TRIAL_CAGE_RADIUS_M,
            "x": 2.0 * TRIAL_CAGE_RADIUS_M, "y": 2.0 * TRIAL_CAGE_RADIUS_M,
            "z": 10.0, "z_interface": 0, "n1": 1.0, "n2": 1.33,
        },
        "poly": {"sides": 0, "dist": 0},
        "roi": {"type": "global"},
        "optics_mode": "kd_fijo",
        "optics": {
            "mode": "kd_fijo", "kd_fijo": c_beam, "atten_coef_type": "c",
            "mc_input_type": "scalar", "c": c_beam,
            "omega": 0.8, "g": 0.85, "r_wall": 0.0,
        },
        "kd_list": [c_beam], "secchi_model": "lee2015",
        "target_depths": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        "rays": 2_000_000, "grid_bins": 128,
        "source_model": "point", "irradiance_type": "scalar",
        "draw_contour": True, "contour_vals": [0.017, 0.1, 1.0],
        "color_scale_type": "log", "plot_depth_profile": True,
        "plot_depth_summary_table": True, "plot_env_optics": True,
        "plot_light_quality": True, "plot_spectrum_initial": True,
        "plot_spectrum_normalized": True, "spectrum_lamps": [XML_PATH.name],
        "lamps": lamps,
        "porter_trial_assumptions": {
            "reported_text": "4, 80m diameter sea cages; 8x400W spaced equidistant at 5m depth",
            "cage_interpretation": "80 m perimeter, not diameter",
            "cage_radius_m": TRIAL_CAGE_RADIUS_M,
            "lamp_layout": "8 lamps on a ring at R/2; layout not published",
            "lamp_depth_m": 5.0,
            "secchi_depth_m": 8.0,
            "effective_background_lux_not_included": float(
                _background_from_unconstrained(params[-1])
            ),
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_growth_trial_configs(params: np.ndarray, tm33_meta: dict,
                               lit_path: Path, control_path: Path,
                               confg_path: Path) -> None:
    """Trial 3: configuración lit/control asociada al crecimiento reportado de 18 %."""
    center = TRIAL_CAGE_RADIUS_M
    lamp_ring_radius = TRIAL_CAGE_RADIUS_M / 2.0
    lamps = []
    for i, phi in enumerate(np.linspace(0.0, 2.0 * np.pi, 4, endpoint=False), start=1):
        lamps.append({
            "label": f"Porter-growth-400W-{i:02d}", "xml": TRIAL3_XML_PATH.name,
            "type": "submerged", "enabled": True,
            "x": center + lamp_ring_radius * float(np.cos(phi)),
            "y": center + lamp_ring_radius * float(np.sin(phi)),
            "z": 5.0, "power": INPUT_POWER_W, "nominal_power": INPUT_POWER_W,
            "efficiency": tm33_meta["electrical_to_radiant_efficiency"],
            "dim": 1.0, "manual_z": True, "manual_power": True,
            "rot_x": 0.0, "rot_y": 0.0, "rot_z": 0.0,
        })

    c_beam = float(np.exp(params[-2]))
    trial_metadata = {
        "source": "FRDC 2001/246, Trial 3, report pages 27-30",
        "objective": "Reproduce artificial-light exposure associated with reported 18% growth advantage",
        "treatment": "lit",
        "population_total_fish": 132_000,
        "fish_per_treatment": 66_000,
        "sex": "mixed",
        "seawater_transfer_date": "2002-05-28",
        "initial_mean_weight_g": 98.0,
        "artificial_light_start_date": "2002-05-28",
        "artificial_light_end_date": "2002-11-05",
        "artificial_light_duration_days": 161,
        "photoperiod": "continuous additional illumination, nominal 24L:0D",
        "feeding_ration_pct_body_weight_per_day": 2.3,
        "reported_growth_evaluation_period_months": 12,
        "reported_growth_advantage_pct": 18.0,
        "reported_harvest_advance_weeks": [5, 6],
        "reported_final_mean_weight_lit_g": 2280.0,
        "reported_final_sem_lit_g": 80.0,
        "reported_final_mean_weight_control_g": 1880.0,
        "reported_final_sem_control_g": 70.0,
        "mean_weight_contrast_pct_from_reported_means": 100.0 * (2280.0 / 1880.0 - 1.0),
        "cage_reported_as": "one 80 m diameter pen",
        "cage_interpretation": "80 m perimeter, not diameter",
        "cage_radius_m": TRIAL_CAGE_RADIUS_M,
        "cage_depth_m": 10.0,
        "lamp_count": 4,
        "lamp_electrical_power_each_W": INPUT_POWER_W,
        "lamp_depth_m": 5.0,
        "lamp_layout": "4 lamps on a ring at R/2; exact layout not published",
        "secchi_depth_m_assumed_from_appendix": 8.0,
        "growth_model_coupling": "metadata only; simulator computes light field, not fish growth",
        "ambient_daylight": "not included in optical run",
        "effective_background_lux_not_included": float(
            _background_from_unconstrained(params[-1])
        ),
    }
    config = {
        "project_title": "Porter 2005 Trial 3 - 18% growth - lit treatment",
        "env": {
            "type": "jaula", "shape": "circle", "radio": TRIAL_CAGE_RADIUS_M,
            "x": 2.0 * TRIAL_CAGE_RADIUS_M, "y": 2.0 * TRIAL_CAGE_RADIUS_M,
            "z": 10.0, "z_interface": 0, "n1": 1.0, "n2": 1.33,
        },
        "poly": {"sides": 0, "dist": 0},
        "roi": {"type": "global"},
        "optics_mode": "kd_fijo",
        "optics": {
            "mode": "kd_fijo", "kd_fijo": c_beam, "atten_coef_type": "c",
            "mc_input_type": "scalar", "c": c_beam,
            "omega": 0.8, "g": 0.85, "r_wall": 0.0,
        },
        "kd_list": [c_beam], "secchi_model": "lee2015",
        "target_depths": [1, 2, 3, 4, 6, 7, 8, 9, 10],
        "rays": 2_000_000, "grid_bins": 128,
        "source_model": "point", "irradiance_type": "scalar",
        "draw_contour": True, "contour_vals": [0.017, 0.1, 1.0],
        "color_scale_type": "log", "plot_depth_profile": True,
        "plot_depth_summary_table": True, "plot_env_optics": True,
        "plot_light_quality": True, "plot_spectrum_initial": True,
        "plot_spectrum_normalized": True, "spectrum_lamps": [TRIAL3_XML_PATH.name],
        "lamps": lamps,
        "porter_growth_trial": trial_metadata,
        "replication_limits": {
            "depth_5m_omitted": "point-source plane intersects emitters; planar tally is singular",
            "upward_photometry": "not measured in Appendix 3; synthetic profile is lower-hemisphere only",
            "ambient_light": "not simulated",
            "growth_response": "18% is observed metadata, not an optical-model prediction",
        },
    }
    lit_path.parent.mkdir(parents=True, exist_ok=True)
    lit_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    confg_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    control = json.loads(json.dumps(config))
    control["project_title"] = "Porter 2005 Trial 3 - 18% growth - ambient control"
    control["lamps"] = []
    control["porter_growth_trial"]["treatment"] = "ambient control"
    control["porter_growth_trial"]["photoperiod"] = "ambient photoperiod; no artificial lamps"
    control_path.write_text(
        json.dumps(control, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def prediction_ensemble(bootstrap: np.ndarray, meas: Measurements) -> tuple[np.ndarray, np.ndarray]:
    lamp, total = [], []
    for params in bootstrap:
        lamp_i, total_i, _ = forward_components(params, meas.horizontal_m, meas.vertical_m)
        lamp.append(lamp_i)
        total.append(total_i)
    return np.asarray(lamp), np.asarray(total)


def predictive_total_ensemble(bootstrap: np.ndarray, meas: Measurements,
                              nominal: np.ndarray, seed: int = 2462005) -> np.ndarray:
    """Predicción posterior aproximada = incertidumbre paramétrica + discrepancia."""
    _, nominal_total, _ = forward_components(
        nominal, meas.horizontal_m, meas.vertical_m
    )
    residual = np.log(meas.observed_lux) - np.log(nominal_total)
    residual -= np.mean(residual)
    _, boot_total = prediction_ensemble(bootstrap, meas)
    rng = np.random.default_rng(seed)
    discrepancy = rng.choice(residual, size=boot_total.shape, replace=True)
    return boot_total * np.exp(discrepancy)


def write_results(meas: Measurements, params: np.ndarray, bootstrap: np.ndarray,
                  tm33_meta: dict, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    lamp, total, background = forward_components(params, meas.horizontal_m, meas.vertical_m)
    boot_lamp, boot_total = prediction_ensemble(bootstrap, meas)
    predictive_total = predictive_total_ensemble(bootstrap, meas, params)
    lamp_q = np.quantile(boot_lamp, [0.05, 0.50, 0.95], axis=0)
    total_q = np.quantile(predictive_total, [0.05, 0.50, 0.95], axis=0)
    efficacy = tm33_meta["luminous_efficacy_lm_per_W"]
    efficacy_samples = spectral_conversion_samples(len(bootstrap))
    predictive_irradiance = predictive_total / efficacy_samples[:, np.newaxis]
    irradiance_q = np.quantile(predictive_irradiance, [0.05, 0.95], axis=0)
    fields = [
        "horizontal_m", "vertical_m", "observed_lux", "simulated_lamp_lux",
        "simulated_total_lux", "total_lux_p05", "total_lux_p50", "total_lux_p95",
        "observed_equivalent_irradiance_W_m2", "lamp_irradiance_W_m2",
        "total_equivalent_irradiance_W_m2",
        "irradiance_p05_W_m2", "irradiance_p95_W_m2", "relative_error_pct",
    ]
    with (out_dir / "porter_simulated_measurements.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for i in range(len(meas.observed_lux)):
            writer.writerow({
                "horizontal_m": f"{meas.horizontal_m[i]:.0f}",
                "vertical_m": f"{meas.vertical_m[i]:.0f}",
                "observed_lux": f"{meas.observed_lux[i]:.6g}",
                "simulated_lamp_lux": f"{lamp[i]:.8g}",
                "simulated_total_lux": f"{total[i]:.8g}",
                "total_lux_p05": f"{total_q[0, i]:.8g}",
                "total_lux_p50": f"{total_q[1, i]:.8g}",
                "total_lux_p95": f"{total_q[2, i]:.8g}",
                "observed_equivalent_irradiance_W_m2": f"{meas.observed_lux[i] / efficacy:.8g}",
                "lamp_irradiance_W_m2": f"{lamp[i] / efficacy:.8g}",
                "total_equivalent_irradiance_W_m2": f"{total[i] / efficacy:.8g}",
                "irradiance_p05_W_m2": f"{irradiance_q[0, i]:.8g}",
                "irradiance_p95_W_m2": f"{irradiance_q[1, i]:.8g}",
                "relative_error_pct": f"{100.0 * (total[i] / meas.observed_lux[i] - 1.0):.6g}",
            })

    residual_log = np.log(total) - np.log(meas.observed_lux)
    coverage90 = float(np.mean((meas.observed_lux >= total_q[0]) & (meas.observed_lux <= total_q[2])))
    obs_over_sim = meas.observed_lux / total
    summary = {
        "n_measurements": len(meas.observed_lux),
        "beam_attenuation_c_per_m": float(np.exp(params[-2])),
        "beam_attenuation_c_90pct_CI_per_m": np.quantile(np.exp(bootstrap[:, -2]), [0.05, 0.95]).tolist(),
        "effective_diffuse_background_lux": background,
        "effective_diffuse_background_90pct_CI_lux": np.quantile(
            _background_from_unconstrained(bootstrap[:, -1]), [0.05, 0.95]).tolist(),
        "log_RMSE": float(np.sqrt(np.mean(residual_log**2))),
        "multiplicative_RMSE_factor": float(np.exp(np.sqrt(np.mean(residual_log**2)))),
        "median_absolute_percentage_error_pct": float(np.median(np.abs(total / meas.observed_lux - 1.0)) * 100.0),
        "R2_log": float(1.0 - np.sum(residual_log**2) / np.sum((np.log(meas.observed_lux) - np.mean(np.log(meas.observed_lux)))**2)),
        "predictive_90pct_pointwise_coverage": coverage90,
        "observed_over_simulated_90pct_range": np.quantile(obs_over_sim, [0.05, 0.95]).tolist(),
        "luminous_efficacy_scenario_90pct_range_lm_per_W": np.quantile(
            efficacy_samples, [0.05, 0.95]
        ).tolist(),
        **tm33_meta,
    }
    (out_dir / "porter_fit_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return summary


def write_plots(meas: Measurements, params: np.ndarray, bootstrap: np.ndarray,
                out_dir: Path) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(out_dir / ".mplconfig"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm, TwoSlopeNorm

    _, total, _ = forward_components(params, meas.horizontal_m, meas.vertical_m)
    boot_lamp, boot_total = prediction_ensemble(bootstrap, meas)
    predictive_total = predictive_total_ensemble(bootstrap, meas, params)
    del boot_lamp
    obs_grid = meas.observed_lux.reshape(6, 8)
    sim_grid = total.reshape(6, 8)
    error_grid = 100.0 * (sim_grid / obs_grid - 1.0)
    vmin = min(obs_grid.min(), sim_grid.min())
    vmax = max(obs_grid.max(), sim_grid.max())

    fig, axes = plt.subplots(2, 2, figsize=(12, 9), constrained_layout=True)
    extent = [0.5, 8.5, 6.5, 0.5]
    for ax, grid, title in ((axes[0, 0], obs_grid, "Porter 2005: observado"),
                            (axes[0, 1], sim_grid, "Modelo: lámpara + fondo efectivo")):
        im = ax.imshow(grid, extent=extent, aspect="auto", cmap="viridis",
                       norm=LogNorm(vmin=vmin, vmax=vmax))
        fig.colorbar(im, ax=ax, label="Iluminancia [lx]")
        ax.set_title(title)
        ax.set_xlabel("Distancia horizontal [m]")
        ax.set_ylabel("Distancia vertical [m]")
    lim = max(100.0, float(np.nanpercentile(np.abs(error_grid), 95)))
    im = axes[1, 0].imshow(error_grid, extent=extent, aspect="auto", cmap="coolwarm",
                           norm=TwoSlopeNorm(vmin=-lim, vcenter=0.0, vmax=lim))
    fig.colorbar(im, ax=axes[1, 0], label="Error relativo [%]")
    axes[1, 0].set_title("Residuo espacial")
    axes[1, 0].set_xlabel("Distancia horizontal [m]")
    axes[1, 0].set_ylabel("Distancia vertical [m]")

    theta = np.linspace(0.0, 90.0, 361)
    profile = luminous_intensity_cd(params, theta)
    profile_boot = np.asarray([luminous_intensity_cd(p, theta) for p in bootstrap])
    q05, q95 = np.quantile(profile_boot, [0.05, 0.95], axis=0)
    axes[1, 1].fill_between(theta, q05, q95, color="#8ecae6", alpha=0.55,
                            label="IC bootstrap 90%")
    axes[1, 1].plot(theta, profile, color="#023047", lw=2.2, label="TM-33 sintético")
    axes[1, 1].set_yscale("log")
    axes[1, 1].set_xlabel("Ángulo desde el nadir de la lámpara [°]")
    axes[1, 1].set_ylabel("Intensidad luminosa [cd]")
    axes[1, 1].set_title("Distribución angular inferida")
    axes[1, 1].grid(True, which="both", ls=":", alpha=0.45)
    axes[1, 1].legend()
    fig.suptitle("Reconstrucción fotométrica del apéndice 3 (48 puntos)", fontsize=15, weight="bold")
    fig.savefig(out_dir / "porter_fit_diagnostics.png", dpi=180)
    plt.close(fig)

    predicted_q = np.quantile(predictive_total, [0.05, 0.95], axis=0)
    order = np.argsort(meas.observed_lux)
    fig, ax = plt.subplots(figsize=(7.2, 6.4), constrained_layout=True)
    ax.errorbar(meas.observed_lux[order], total[order],
                yerr=np.vstack([total[order] - predicted_q[0, order],
                                predicted_q[1, order] - total[order]]),
                fmt="o", ms=5, alpha=0.8, color="#0077b6", ecolor="#90e0ef", capsize=2)
    lo = min(meas.observed_lux.min(), total.min()) * 0.8
    hi = max(meas.observed_lux.max(), total.max()) * 1.2
    ax.plot([lo, hi], [lo, hi], "--", color="#d62828", label="1:1")
    ax.set(xscale="log", yscale="log", xlim=(lo, hi), ylim=(lo, hi),
           xlabel="Porter observado [lx]", ylabel="Simulación [lx]",
           title="Validación punto a punto e intervalo bootstrap 90%")
    ax.grid(True, which="both", ls=":", alpha=0.45)
    ax.legend()
    fig.savefig(out_dir / "porter_observed_vs_simulated.png", dpi=180)
    plt.close(fig)


def validate_tm33_with_parser(path: Path) -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from parsers import TM33Parser
    parser = TM33Parser(path.read_text(encoding="utf-8"))
    downward = np.array([[0.0, 0.0, -1.0], [2**-0.5, 0.0, -2**-0.5]])
    lum, rad = parser.get_intensity(downward)
    if not (np.all(np.isfinite(lum)) and np.all(lum > 0.0)
            and np.all(np.isfinite(rad)) and np.all(rad > 0.0)):
        raise RuntimeError("El parser local no pudo leer la intensidad sintética")
    if parser.get_electrical_power() != INPUT_POWER_W or not parser.get_spectrum():
        raise RuntimeError("El parser local no recuperó potencia/SPD del TM-33")


def run_engine_validation(meas: Measurements, params: np.ndarray, tm33_meta: dict,
                          rays: int, cell_width_m: float = 1.0) -> dict:
    """Ejecuta SimulationEngine y muestrea celdas centradas en los 48 receptores."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from simulation_engine import SimulationEngine

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config["rays"] = int(rays)
    config["optics"]["mode"] = config["optics_mode"]
    engine = SimulationEngine()
    engine.load_file(XML_PATH.name, XML_PATH.read_text(encoding="utf-8"))
    np.random.seed(2005246)
    result = engine.run(config)

    lamp_x = float(config["lamps"][0]["x"])
    lamp_y = float(config["lamps"][0]["y"])
    lamp_depth = float(config["lamps"][0]["z"])
    background = float(_background_from_unconstrained(params[-1]))
    area = cell_width_m**2
    engine_lamp_lux = np.zeros(len(meas.observed_lux), dtype=float)
    for i, (horizontal, vertical) in enumerate(zip(meas.horizontal_m, meas.vertical_m)):
        depth = lamp_depth + vertical
        layer = result[str(int(depth))]
        x = np.asarray(layer["x"], dtype=float)
        y = np.asarray(layer["y"], dtype=float)
        values = np.asarray(layer["val"], dtype=float)
        wavelengths = np.asarray(layer["wl"], dtype=float)
        receiver_x = lamp_x + horizontal
        receiver_y = lamp_y
        half = cell_width_m / 2.0
        inside = ((x >= receiver_x - half) & (x < receiver_x + half)
                  & (y >= receiver_y - half) & (y < receiver_y + half))
        engine_lamp_lux[i] = np.sum(
            values[inside] * 683.0 * photopic_v_app(wavelengths[inside])
        ) / area

    total = engine_lamp_lux + background
    residual_log = np.log(np.maximum(total, 1e-12)) - np.log(meas.observed_lux)
    fields = ["horizontal_m", "vertical_m", "observed_lux",
              "observed_equivalent_irradiance_W_m2", "engine_lamp_lux",
              "engine_total_lux", "engine_lamp_irradiance_W_m2",
              "engine_total_equivalent_irradiance_W_m2", "relative_error_pct"]
    with (OUT_DIR / "porter_engine_validation.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for i in range(len(total)):
            writer.writerow({
                "horizontal_m": f"{meas.horizontal_m[i]:.0f}",
                "vertical_m": f"{meas.vertical_m[i]:.0f}",
                "observed_lux": f"{meas.observed_lux[i]:.8g}",
                "observed_equivalent_irradiance_W_m2": f"{meas.observed_lux[i] / tm33_meta['luminous_efficacy_lm_per_W']:.8g}",
                "engine_lamp_lux": f"{engine_lamp_lux[i]:.8g}",
                "engine_total_lux": f"{total[i]:.8g}",
                "engine_lamp_irradiance_W_m2": f"{engine_lamp_lux[i] / tm33_meta['luminous_efficacy_lm_per_W']:.8g}",
                "engine_total_equivalent_irradiance_W_m2": f"{total[i] / tm33_meta['luminous_efficacy_lm_per_W']:.8g}",
                "relative_error_pct": f"{100.0 * (total[i] / meas.observed_lux[i] - 1.0):.8g}",
            })
    return {
        "engine_rays": int(rays),
        "engine_receiver_cell_width_m": cell_width_m,
        "engine_log_RMSE": float(np.sqrt(np.mean(residual_log**2))),
        "engine_multiplicative_RMSE_factor": float(np.exp(np.sqrt(np.mean(residual_log**2)))),
        "engine_median_absolute_percentage_error_pct": float(
            np.median(np.abs(total / meas.observed_lux - 1.0)) * 100.0
        ),
        "engine_R2_log": float(
            1.0 - np.sum(residual_log**2)
            / np.sum((np.log(meas.observed_lux) - np.mean(np.log(meas.observed_lux)))**2)
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", type=int, default=300,
                        help="Número de réplicas de bootstrap residual (default: 300)")
    parser.add_argument("--seed", type=int, default=2005246)
    parser.add_argument("--no-plots", action="store_true")
    parser.add_argument("--engine-rays", type=int, default=0,
                        help="Si es >0, valida con SimulationEngine y celdas de 1 m")
    args = parser.parse_args()

    meas = load_measurements()
    params = fit_model(meas)
    bootstrap = residual_bootstrap(meas, params, args.bootstrap, args.seed)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT_DIR / "porter_bootstrap.npz", params=params, bootstrap=bootstrap,
                        knots_deg=KNOTS_DEG)
    tm33_meta = write_tm33(params, bootstrap, XML_PATH)
    validate_tm33_with_parser(XML_PATH)
    trial3_meta = write_tm33(
        params, bootstrap, TRIAL3_XML_PATH,
        application="Porter et al. 2005 Trial 3 growth treatment",
    )
    validate_tm33_with_parser(TRIAL3_XML_PATH)
    write_config(params, bootstrap, tm33_meta, CONFIG_PATH)
    write_trial_config(params, tm33_meta, TRIAL_CONFIG_PATH)
    write_growth_trial_configs(
        params, trial3_meta, GROWTH_LIT_CONFIG_PATH, GROWTH_CONTROL_CONFIG_PATH,
        GROWTH_LIT_CONFG_PATH,
    )
    summary = write_results(meas, params, bootstrap, tm33_meta, OUT_DIR)
    if args.engine_rays > 0:
        summary.update(run_engine_validation(meas, params, tm33_meta, args.engine_rays))
        (OUT_DIR / "porter_fit_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    if not args.no_plots:
        write_plots(meas, params, bootstrap, OUT_DIR)

    print(json.dumps({"tm33": str(XML_PATH), "config": str(CONFIG_PATH),
                      "trial_config": str(TRIAL_CONFIG_PATH),
                      "growth_lit_config": str(GROWTH_LIT_CONFIG_PATH),
                      "growth_control_config": str(GROWTH_CONTROL_CONFIG_PATH),
                      "growth_lit_confg": str(GROWTH_LIT_CONFG_PATH),
                      "trial3_tm33": str(TRIAL3_XML_PATH),
                      "results": str(OUT_DIR / "porter_simulated_measurements.csv"),
                      "summary": summary}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
