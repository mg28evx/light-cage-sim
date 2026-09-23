"""Irradiancia ambiental y objetivo de fotoperíodo para jaulas de salmón.

Este módulo resuelve la cadena

    geometría solar → cielo → interfaz aire-agua → columna de agua espectral
    → agregación sobre la ventana de cultivo → irradiancia artificial objetivo

y aplica el modelo de interpretación adaptativa del fotoperíodo de Oldham,
Oppedal, Fjelldal & Hansen (2023), *Adaptive photoperiod interpretation
modulates phenological timing in Atlantic salmon*, Sci. Rep. 13:2618,
https://doi.org/10.1038/s41598-023-27583-7

El resultado central de ese trabajo tiene dos partes:

1. **Umbral fijo de detección in vivo.** El salmón del Atlántico no interpreta
   como iluminación nada por debajo de 0,01–0,1 µmol m⁻² s⁻¹ (el grupo Low1,
   con 0,01 µmol m⁻² s⁻¹ nocturnos, no maduró y se comportó como oscuridad
   completa). Trabajos previos sitúan el umbral entre 0,05 y 0,07.

2. **Interpretación adaptativa por encima del umbral.** Superado el umbral, lo
   que el pez lee como «noche» no es un valor absoluto sino una fracción de la
   intensidad diurna reciente: los tratamientos se definieron por la razón
   noche:día (0 %, 1 %, 10 %, 100 %) y la frecuencia de maduración creció con
   esa razón en ambos niveles de intensidad diurna.

De ahí la regla que implementa :func:`target_irradiance`

    E_objetivo(z_obj) = max( E_umbral , término adaptativo )

donde el término adaptativo depende de cómo operan las luminarias. La razón
de Oldham se define sobre la luz **total** que recibe el pez, ``r = E_noche /
E_día``:

* luminarias sólo de noche: el día es la luz natural, ``E_art = r·E_nat``;
* luminarias 24 h (luz continua en jaula): el día percibido es
  ``E_nat + E_art``, y despejando ``E_art = r·E_nat / (1 − r)``.

``E_nat`` resume la historia lumínica reciente del lote a la profundidad de
referencia. En operación 24 h, r = 1 es inalcanzable mientras haya sol.

Advertencia que el propio paper deja explícita: la razón **no** explica por sí
sola la respuesta. Con idéntico 10 % nocturno, el grupo High10 (69,3 µmol de
día) maduró en un 20 % y el Low10 (1,0 µmol de día) sólo en un 6 %. La
intensidad absoluta del día sigue pesando, y la forma exacta de esa
dependencia quedó abierta. La regla es una cota operativa, no una ley de
respuesta.

Medio acuático
--------------
La luz natural se propaga con **las mismas propiedades ópticas inherentes que
usa el trazado de rayos**: ``a(λ)`` y ``b_b(λ)`` resueltos desde la sección
Óptica del simulador (modelo bio-óptico marino, RAS de Bårdsnes, ``c/ω``
manual o Kd declarado, según el modo activo). Por longitud de onda:

* el espectro de superficie es ASTM G173-03 AM1.5 global, 400–700 nm;
* la atenuación difusa sigue el cierre de Lee, Du & Arnone (2005),
  ``Kd(λ, θ) = (1 + 0,005·θ)·a + 4,18·(1 − 0,52·e^(−10,8·a))·b_b``, que es el
  que depende explícitamente del ángulo solar;
* el haz directo entra con el cenit solar del instante y el difuso de cielo
  con un cenit equivalente de 43,3° (Kirk: μ̄₀ ≈ 0,86 bajo cielo cubierto).

La fracción PAR ya no es un parámetro: sale del espectro de referencia.

Cielo
-----
La irradiancia de superficie puede venir **observada** (``sky_forcing``: PAR
horario de NASA POWER o un CSV propio) o, como respaldo, de un cielo
despejado modelado por una transmitancia de nubes constante. Con datos
observados se puede evaluar el año exacto de la ventana o una climatología
multianual, en la que el percentil se toma sobre todos los días-año.

Unidades
--------
Todo el módulo trabaja en **W/m² de irradiancia PAR sobre plano horizontal**,
coherente con el resto del simulador. Oldham midió PAR escalar (esférico) con
un LI-193 en µmol m⁻² s⁻¹; :func:`par_w_m2_to_umol` documenta la conversión
para poder contrastar, pero no se usa en el cálculo.
"""

from __future__ import annotations

import datetime as _dt
import math
from typing import Sequence

import numpy as np

from simulation_engine import kd_lee2005

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

SOLAR_CONSTANT_W_M2 = 1361.0

#: Índice de refracción del agua de mar en el visible.
WATER_REFRACTIVE_INDEX = 1.34

#: Transmitancia de la interfaz aire-agua para radiación difusa de cielo.
DIFFUSE_SURFACE_TRANSMITTANCE = 0.934

#: Cenit en aire equivalente para la luz difusa de cielo. Kirk (1991) da un
#: coseno medio subsuperficial μ̄₀ ≈ 0,859 bajo cielo cubierto, es decir 30,8°
#: bajo el agua; por Snell con n = 1,34 corresponde a 43,3° en aire, que es el
#: argumento que espera el cierre de Lee (2005).
DIFFUSE_EQUIVALENT_ZENITH_DEG = 43.3

#: Umbral fijo de detección in vivo, en W/m² PAR plano. 0,016 W/m² equivale a
#: 0,060–0,073 µmol m⁻² s⁻¹ según el espectro (LED azul a PAR diurno), dentro de
#: la banda 0,01–0,1 de Oldham (2023) y sobre el 0,05–0,07 de Migaud (2006) y
#: Vera (2010). Es el mismo valor que la vista 3D usa para los globos de luz.
DETECTION_THRESHOLD_W_M2 = 0.016

#: Razones noche:día de los tratamientos de Oldham (2023), Tabla 1.
OLDHAM_RATIOS = (0.0, 0.01, 0.10, 1.00)

#: Percentiles y razones con que se arma la tabla de objetivos propuestos.
PROPOSAL_PERCENTILES = (0.0, 25.0, 50.0, 75.0, 90.0, 100.0)
PROPOSAL_RATIOS = (0.01, 0.10)

#: Cenit solar (grados) que define el orto/ocaso aparente, con refracción
#: atmosférica y semidiámetro solar.
SUNRISE_ZENITH_DEG = 90.833

#: µmol de fotones por joule de PAR de luz diurna. Sólo para contraste con la
#: literatura; el módulo no lo usa internamente.
UMOL_PER_JOULE_PAR = 4.57

# ---------------------------------------------------------------------------
# Espectro solar de referencia
# ---------------------------------------------------------------------------

#: Grilla espectral de trabajo: 400–700 nm cada 10 nm.
REFERENCE_WAVELENGTHS_NM = np.arange(400.0, 701.0, 10.0)

#: ASTM G173-03, AM1.5 global (37° de inclinación), promediado en bandas de
#: 10 nm centradas en la grilla (las extremas, de 5 nm, quedan dentro de
#: 400–700). W m⁻² nm⁻¹. Integra 429,8 W/m² en PAR sobre 1000,4 W/m² totales.
_AM15G_W_M2_NM = np.array([
    1.1681, 1.1646, 1.2222, 1.1266, 1.3475, 1.4994, 1.5644, 1.5542, 1.5980,
    1.5109, 1.5433, 1.5588, 1.4892, 1.5317, 1.5340, 1.5416, 1.5126, 1.4927,
    1.5041, 1.4466, 1.4662, 1.4707, 1.4429, 1.4093, 1.4465, 1.4012, 1.3542,
    1.4144, 1.3941, 1.2075, 1.2993,
])
_AM15G_BROADBAND_W_M2 = 1000.4

#: Ancho de banda de cada punto de la grilla (regla del trapecio).
_BAND_WIDTH_NM = np.full(REFERENCE_WAVELENGTHS_NM.size, 10.0)
_BAND_WIDTH_NM[0] = _BAND_WIDTH_NM[-1] = 5.0

#: W/m² de PAR que aporta cada banda por cada W/m² de irradiancia de banda
#: ancha. Suma la fracción PAR del espectro de referencia.
_SPECTRAL_WEIGHTS = _AM15G_W_M2_NM * _BAND_WIDTH_NM / _AM15G_BROADBAND_W_M2

#: Fracción PAR (400–700 nm) de AM1.5G, ≈ 0,430.
PAR_FRACTION_REFERENCE = float(_SPECTRAL_WEIGHTS.sum())

#: Reparto espectral del PAR entre las bandas de la grilla; suma 1. Las
#: muestras se guardan ya en PAR, observado o modelado, y se distribuyen con
#: esta forma para propagarlas por longitud de onda.
_PAR_SHAPE = _SPECTRAL_WEIGHTS / PAR_FRACTION_REFERENCE

# ---------------------------------------------------------------------------
# Cielo
# ---------------------------------------------------------------------------

#: Modos de uso del cielo observado.
SKY_MODE_WINDOW = "window"
SKY_MODE_CLIMATOLOGY = "climatology"

#: Fracción mínima del fotoperíodo que deben cubrir los datos de un día para
#: que entre en la población.
MIN_DAY_COVERAGE = 0.8


# ---------------------------------------------------------------------------
# Geometría solar (algoritmo NOAA)
# ---------------------------------------------------------------------------

def day_of_year(date) -> int:
    """Día del año de un ``date``/``datetime``/cadena ISO."""
    if isinstance(date, str):
        date = _dt.date.fromisoformat(date)
    if isinstance(date, _dt.datetime):
        date = date.date()
    return date.timetuple().tm_yday


def _fractional_year_rad(doy: float, hour: float = 12.0) -> float:
    """Ángulo fraccional del año γ, en radianes (NOAA)."""
    days = 366.0 if doy > 365 else 365.0
    return 2.0 * math.pi / days * (doy - 1.0 + (hour - 12.0) / 24.0)


def equation_of_time_minutes(doy: float, hour: float = 12.0) -> float:
    """Ecuación del tiempo en minutos (serie de Spencer usada por NOAA)."""
    g = _fractional_year_rad(doy, hour)
    return 229.18 * (
        0.000075
        + 0.001868 * math.cos(g)
        - 0.032077 * math.sin(g)
        - 0.014615 * math.cos(2 * g)
        - 0.040849 * math.sin(2 * g)
    )


def solar_declination_deg(doy: float, hour: float = 12.0) -> float:
    """Declinación solar en grados (serie de Spencer usada por NOAA).

    Más precisa que la aproximación de Cooper ``23.45·sin(360/365·(n−81))``,
    que llega a desviarse cerca de medio grado en los equinoccios.
    """
    g = _fractional_year_rad(doy, hour)
    dec = (
        0.006918
        - 0.399912 * math.cos(g)
        + 0.070257 * math.sin(g)
        - 0.006758 * math.cos(2 * g)
        + 0.000907 * math.sin(2 * g)
        - 0.002697 * math.cos(3 * g)
        + 0.001480 * math.sin(3 * g)
    )
    return math.degrees(dec)


def solar_elevation_deg(lat_deg: float, lon_deg: float, when: _dt.datetime,
                        tz_offset_h: float) -> float:
    """Elevación solar en grados para una hora local concreta.

    ``lon_deg`` positiva al este; ``tz_offset_h`` es el desfase del huso
    respecto de UTC (Chile continental en horario de invierno: −4; en horario
    de verano: −3).
    """
    doy = when.timetuple().tm_yday
    hour = when.hour + when.minute / 60.0 + when.second / 3600.0
    eot = equation_of_time_minutes(doy, hour)
    dec = math.radians(solar_declination_deg(doy, hour))
    lat = math.radians(lat_deg)

    # Minutos de desfase entre la hora del reloj y la hora solar verdadera.
    time_offset = eot + 4.0 * lon_deg - 60.0 * tz_offset_h
    true_solar_time = hour * 60.0 + time_offset
    hour_angle = math.radians(true_solar_time / 4.0 - 180.0)

    cos_zenith = (math.sin(lat) * math.sin(dec)
                  + math.cos(lat) * math.cos(dec) * math.cos(hour_angle))
    cos_zenith = max(-1.0, min(1.0, cos_zenith))
    return 90.0 - math.degrees(math.acos(cos_zenith))


def daylength_hours(lat_deg: float, doy: int,
                    zenith_deg: float = SUNRISE_ZENITH_DEG) -> float:
    """Duración del día en horas. Devuelve 0 o 24 en noche/día polar."""
    lat = math.radians(lat_deg)
    dec = math.radians(solar_declination_deg(doy))
    cos_ha = (math.cos(math.radians(zenith_deg))
              / (math.cos(lat) * math.cos(dec)) - math.tan(lat) * math.tan(dec))
    if cos_ha >= 1.0:
        return 0.0
    if cos_ha <= -1.0:
        return 24.0
    return 2.0 * math.degrees(math.acos(cos_ha)) / 15.0


# ---------------------------------------------------------------------------
# Irradiancia en superficie
# ---------------------------------------------------------------------------

def optical_air_mass(zenith_deg: float) -> float:
    """Masa de aire relativa por la fórmula de Kasten & Young (1989)."""
    z = min(zenith_deg, 90.0)
    denom = math.cos(math.radians(z)) + 0.50572 * (96.07995 - z) ** -1.6364
    return 1.0 / max(denom, 1e-6)


def clear_sky_broadband_w_m2(elevation_deg: float,
                             atmospheric_transmittance: float = 0.75) -> float:
    """Irradiancia solar global de banda ancha con cielo despejado, W/m².

    Modelo de Meinel & Meinel: ``I = I0·sin(h)·τ^(m^0.678)``.
    """
    if elevation_deg <= 0.0:
        return 0.0
    m = optical_air_mass(90.0 - elevation_deg)
    tau = atmospheric_transmittance ** (m ** 0.678)
    return SOLAR_CONSTANT_W_M2 * math.sin(math.radians(elevation_deg)) * tau


def extraterrestrial_horizontal_w_m2(when_utc: _dt.datetime, lat_deg: float,
                                     lon_deg: float) -> float:
    """Irradiancia solar extraterrestre sobre plano horizontal, W/m²."""
    elev = solar_elevation_deg(lat_deg, lon_deg, when_utc, 0.0)
    if elev <= 0.0:
        return 0.0
    doy = when_utc.timetuple().tm_yday
    eccentricity = 1.0 + 0.033 * math.cos(2.0 * math.pi * doy / 365.0)
    return SOLAR_CONSTANT_W_M2 * eccentricity * math.sin(math.radians(elev))


def erbs_diffuse_fraction(kt: float) -> float:
    """Fracción difusa horaria según Erbs, Klein & Duffie (1982).

    Correlación empírica entre el índice de claridad ``kt`` (global sobre
    extraterrestre horizontal) y la fracción difusa, ajustada con mediciones
    en cinco estaciones. Se usa cuando la fuente no trae la difusa: en el
    modo manual y en CSV sin columna difusa.
    """
    kt = max(0.0, float(kt))
    if kt <= 0.22:
        return 1.0 - 0.09 * kt
    if kt <= 0.80:
        return 0.9511 - 0.1604 * kt + 4.388 * kt ** 2 - 16.638 * kt ** 3 + 12.336 * kt ** 4
    return 0.165


def fresnel_transmittance(elevation_deg: float,
                          n_water: float = WATER_REFRACTIVE_INDEX) -> float:
    """Transmitancia de Fresnel aire-agua del haz directo, no polarizado."""
    if elevation_deg <= 0.0:
        return 0.0
    theta_i = math.radians(90.0 - elevation_deg)
    sin_t = math.sin(theta_i) / n_water
    if abs(sin_t) >= 1.0:
        return 0.0
    theta_t = math.asin(sin_t)
    ci, ct = math.cos(theta_i), math.cos(theta_t)
    rs = ((ci - n_water * ct) / (ci + n_water * ct)) ** 2
    rp = ((ct - n_water * ci) / (ct + n_water * ci)) ** 2
    return 1.0 - 0.5 * (rs + rp)


def refracted_zenith_deg(elevation_deg: float,
                         n_water: float = WATER_REFRACTIVE_INDEX) -> float:
    """Ángulo cenital del haz directo ya refractado dentro del agua, grados."""
    if elevation_deg <= 0.0:
        return 0.0
    theta_i = math.radians(90.0 - elevation_deg)
    return math.degrees(math.asin(min(1.0, math.sin(theta_i) / n_water)))


# ---------------------------------------------------------------------------
# Columna de agua espectral
# ---------------------------------------------------------------------------

def _as_array(values) -> np.ndarray:
    return np.asarray(values, dtype=float)


def resample_iop(iop: dict) -> tuple[np.ndarray, np.ndarray]:
    """Lleva ``a(λ)`` y ``b_b(λ)`` a la grilla de referencia del módulo.

    ``iop`` tiene la forma que devuelve ``app_sim.build_optical_diagnostics``:
    claves ``wavelength_nm``, ``a_m_inv`` y ``bb_m_inv``. Si ya viene en la
    grilla de referencia la interpolación es la identidad.
    """
    wl = _as_array(iop["wavelength_nm"])
    order = np.argsort(wl)
    a = np.interp(REFERENCE_WAVELENGTHS_NM, wl[order], _as_array(iop["a_m_inv"])[order])
    bb = np.interp(REFERENCE_WAVELENGTHS_NM, wl[order], _as_array(iop["bb_m_inv"])[order])
    if np.any(a < 0) or np.any(bb < 0):
        raise ValueError("Las IOP no pueden ser negativas.")
    return a, bb


def spectral_kd(a: np.ndarray, bb: np.ndarray, zenith_air_deg) -> np.ndarray:
    """Kd(λ) con el cierre de Lee, Du & Arnone (2005) del motor de simulación.

    La dependencia angular afecta sólo al término de absorción; con ``b_b``
    importante, aplicar el factor geométrico al Kd completo sobrestima la
    atenuación con el sol bajo.
    """
    theta = np.clip(_as_array(zenith_air_deg), 0.0, 90.0)
    return kd_lee2005(a, bb, theta_a_deg=theta)


def equivalent_kd_par(iop: dict, zenith_air_deg: float = DIFFUSE_EQUIVALENT_ZENITH_DEG,
                      depth_m: float = 5.0) -> float:
    """Kd de PAR equivalente entre la superficie y ``depth_m``.

    Resume en un número la atenuación espectral para mostrarla o compararla con
    un Secchi. No interviene en el cálculo, que es espectral.
    """
    a, bb = resample_iop(iop)
    kd = spectral_kd(a, bb, zenith_air_deg)
    surface = float(_SPECTRAL_WEIGHTS.sum())
    deep = float((_SPECTRAL_WEIGHTS * np.exp(-kd * depth_m)).sum())
    return math.log(surface / deep) / depth_m


class WaterColumn:
    """Óptica del agua para la ventana de cultivo.

    ``default`` describe el agua cuando no hay dato semanal; ``by_week`` mapea
    semana ISO a IOP propias, para seguir la estacionalidad del perfil
    satelital. Cada entrada tiene la forma de ``build_optical_diagnostics``.
    """

    def __init__(self, default: dict, by_week: dict | None = None, label: str = ""):
        self.label = label
        weekly = {int(w): iop for w, iop in (by_week or {}).items()}
        self.weeks = sorted(weekly)
        pairs = [resample_iop(iop) for iop in [default] + [weekly[w] for w in self.weeks]]
        self.a = np.stack([p[0] for p in pairs])     # (slots, λ)
        self.bb = np.stack([p[1] for p in pairs])
        self._slot_of_week = {w: i + 1 for i, w in enumerate(self.weeks)}
        # El difuso entra siempre con el mismo ángulo equivalente: su Kd sólo
        # depende de la semana, así que se precalcula.
        self.kd_diffuse = spectral_kd(self.a, self.bb, DIFFUSE_EQUIVALENT_ZENITH_DEG)
        self.default_iop = default

    def slot(self, iso_week: int) -> int:
        return self._slot_of_week.get(int(iso_week), 0)

    @classmethod
    def from_kd(cls, kd_par: float) -> "WaterColumn":
        """Agua gris de Kd uniforme, útil para pruebas y comparaciones.

        Construye ``a = Kd/(1 + 0,005·θ_dif)`` con ``b_b = 0``, de modo que el
        difuso atenúe exactamente con ``kd_par``.
        """
        a = float(kd_par) / (1.0 + 0.005 * DIFFUSE_EQUIVALENT_ZENITH_DEG)
        iop = {"wavelength_nm": REFERENCE_WAVELENGTHS_NM.tolist(),
               "a_m_inv": [a] * REFERENCE_WAVELENGTHS_NM.size,
               "bb_m_inv": [0.0] * REFERENCE_WAVELENGTHS_NM.size}
        return cls(iop, label=f"Kd uniforme {kd_par}")


# ---------------------------------------------------------------------------
# Serie temporal sobre la ventana de cultivo
# ---------------------------------------------------------------------------

def _as_date(value) -> _dt.date:
    if isinstance(value, str):
        return _dt.date.fromisoformat(value[:10])
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    raise TypeError(f"Fecha no reconocida: {value!r}")


def default_tz_offset(lon_deg: float) -> float:
    """Huso civil aproximado desde la longitud.

    Las medias de fotofase y los máximos diarios no dependen del huso: el
    muestreo recorre las 24 h del día y sólo se desplaza el borde de la
    jornada. Basta con una aproximación.
    """
    return float(round(float(lon_deg) / 15.0))


def window_days(start, end, mode: str = SKY_MODE_WINDOW,
                years: Sequence[int] | None = None) -> list[tuple[_dt.date, _dt.date]]:
    """Días a evaluar como pares ``(fecha real, fecha de la ventana)``.

    * ``window``: las fechas de la ventana tal cual.
    * ``climatology``: la ventana (mes y día) repetida en cada año pedido; la
      población del percentil pasa a ser todos los días-año, con la
      variabilidad interanual incluida. Una ventana que cruza fin de año se
      desplaza entera. El 29 de febrero se omite en años no bisiestos.
    """
    start_date, end_date = _as_date(start), _as_date(end)
    if end_date < start_date:
        raise ValueError("La ventana de cultivo termina antes de empezar.")
    base = []
    day = start_date
    while day <= end_date:
        base.append(day)
        day += _dt.timedelta(days=1)
    if mode != SKY_MODE_CLIMATOLOGY:
        return [(d, d) for d in base]
    if not years:
        raise ValueError("La climatología necesita al menos un año.")
    out = []
    for year in sorted(set(int(y) for y in years)):
        shift = year - start_date.year
        for d in base:
            try:
                out.append((d.replace(year=d.year + shift), d))
            except ValueError:          # 29 de febrero
                continue
    return out


def _empty_samples(days) -> dict:
    return {"days": days, "day_index": [], "e_direct": [], "e_diffuse": [], "zenith": []}


def _finish(samples: dict, lat_deg: float, valid: list[bool], note: str) -> dict:
    days = samples["days"]
    return {
        "days": days,
        "dates": [d[0].isoformat() for d in days],
        "window_dates": [d[1].isoformat() for d in days],
        "iso_weeks": [d[0].isocalendar()[1] for d in days],
        "daylength_h": [daylength_hours(lat_deg, d[0].timetuple().tm_yday) for d in days],
        "valid": np.asarray(valid, dtype=bool),
        "day_index": np.asarray(samples["day_index"], dtype=int),
        "e_direct": np.asarray(samples["e_direct"], dtype=float),
        "e_diffuse": np.asarray(samples["e_diffuse"], dtype=float),
        "zenith_deg": np.asarray(samples["zenith"], dtype=float),
        "note": note,
    }


def _clear_sky_samples(lat_deg: float, lon_deg: float, days, cloud_transmittance: float,
                       tz_offset_h: float, step_minutes: int, n_water: float,
                       atmospheric_transmittance: float) -> dict:
    """Cielo despejado modelado × transmitancia de nubes constante.

    Es el modo de respaldo cuando no hay datos. La difusa se separa con la
    correlación empírica de Erbs sobre el índice de claridad resultante.
    Todo queda en PAR bajo la superficie.
    """
    step = max(1, int(step_minutes))
    ct = max(0.0, min(1.0, float(cloud_transmittance)))
    s = _empty_samples(days)
    for d_idx, (day, _) in enumerate(days):
        doy = day.timetuple().tm_yday
        ecc = 1.0 + 0.033 * math.cos(2.0 * math.pi * doy / 365.0)
        for m in range(0, 24 * 60, step):
            when = _dt.datetime(day.year, day.month, day.day, m // 60, m % 60)
            elev = solar_elevation_deg(lat_deg, lon_deg, when, tz_offset_h)
            if elev <= 0.0:
                continue
            g = clear_sky_broadband_w_m2(elev, atmospheric_transmittance) * ct
            e0h = SOLAR_CONSTANT_W_M2 * ecc * math.sin(math.radians(elev))
            kd = erbs_diffuse_fraction(g / e0h) if e0h > 0 else 1.0
            par = g * PAR_FRACTION_REFERENCE
            s["day_index"].append(d_idx)
            s["e_direct"].append(par * (1.0 - kd) * fresnel_transmittance(elev, n_water))
            s["e_diffuse"].append(par * kd * DIFFUSE_SURFACE_TRANSMITTANCE)
            s["zenith"].append(90.0 - elev)
    return _finish(s, lat_deg, [True] * len(days),
                   f"cielo despejado modelado × transmitancia {ct:.2f}; difusa por Erbs")


def _observed_samples(sky, lat_deg: float, lon_deg: float, days, n_water: float,
                      min_coverage: float = MIN_DAY_COVERAGE) -> dict:
    """PAR de superficie observado, por instante con sol sobre el horizonte.

    El directo horizontal cruza la interfaz con Fresnel al ángulo solar del
    centro del intervalo; el difuso, con la transmitancia difusa. Un día cuenta
    sólo si los datos cubren al menos ``min_coverage`` de su fotoperíodo; los
    demás se excluyen de la población y se informan.
    """
    by_date = sky.index_by_date(lon_deg)
    step_h = float(getattr(sky, "step_hours", 1.0) or 1.0)
    direct_h = sky.par_direct_h
    diffuse = sky.par_diffuse
    s = _empty_samples(days)
    valid = []
    for d_idx, (day, _) in enumerate(days):
        idx = by_date.get(day, [])
        lit = []
        for i in idx:
            t = sky.times_utc[i]
            elev = solar_elevation_deg(lat_deg, lon_deg, t, 0.0)
            if elev > 0.0:
                lit.append((i, elev))
        covered = len(lit) * step_h
        ok = covered >= min_coverage * daylength_hours(lat_deg, day.timetuple().tm_yday)
        valid.append(ok)
        if not ok:
            continue
        for i, elev in lit:
            s["day_index"].append(d_idx)
            s["e_direct"].append(direct_h[i] * fresnel_transmittance(elev, n_water))
            s["e_diffuse"].append(diffuse[i] * DIFFUSE_SURFACE_TRANSMITTANCE)
            s["zenith"].append(90.0 - elev)
    return _finish(s, lat_deg, valid, f"PAR observado ({getattr(sky, 'source', 'serie')})")


def _prepare(samples: dict, water: WaterColumn) -> dict:
    """Precalcula lo que no depende de la profundidad."""
    slots = np.asarray([water.slot(w) for w in samples["iso_weeks"]], dtype=int)
    sample_slot = slots[samples["day_index"]] if samples["day_index"].size else slots[:0]
    a = water.a[sample_slot]
    bb = water.bb[sample_slot]
    kd_dir = spectral_kd(a, bb, samples["zenith_deg"][:, None])     # (S, λ)
    kd_dif = water.kd_diffuse[sample_slot]                          # (S, λ)
    shape = _PAR_SHAPE[None, :]
    return {
        "n_days": len(samples["days"]),
        "valid": samples["valid"],
        "day_index": samples["day_index"],
        "src_dir": samples["e_direct"][:, None] * shape,              # W/m² por banda
        "src_dif": samples["e_diffuse"][:, None] * shape,
        "kd_dir": kd_dir,
        "kd_dif": kd_dif,
    }


def _par_at_depth(prep: dict, depth_m: float) -> np.ndarray:
    """PAR plana por instante a una profundidad, sumada sobre el espectro."""
    z = max(0.0, float(depth_m))
    field = prep["src_dir"] * np.exp(-prep["kd_dir"] * z) + prep["src_dif"] * np.exp(-prep["kd_dif"] * z)
    return field.sum(axis=1)


def _daily_stats(prep: dict, depth_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Media de fotofase y máximo por día; ``nan`` en los días excluidos."""
    par = _par_at_depth(prep, depth_m)
    n = prep["n_days"]
    idx = prep["day_index"]
    counts = np.bincount(idx, minlength=n)
    sums = np.bincount(idx, weights=par, minlength=n)
    means = np.divide(sums, counts, out=np.zeros(n), where=counts > 0)
    maxima = np.zeros(n)
    if par.size:
        np.maximum.at(maxima, idx, par)
    means[~prep["valid"]] = np.nan
    maxima[~prep["valid"]] = np.nan
    return means, maxima


def _valid(values: np.ndarray) -> list[float]:
    return [float(v) for v in values if not np.isnan(v)]


def _build_samples(lat_deg, lon_deg, days, sky, cloud_transmittance, tz_offset_h,
                   step_minutes, n_water, atmospheric_transmittance):
    if sky is not None:
        return _observed_samples(sky, lat_deg, lon_deg, days, n_water)
    tz = default_tz_offset(lon_deg) if tz_offset_h is None else float(tz_offset_h)
    return _clear_sky_samples(lat_deg, lon_deg, days, cloud_transmittance, tz,
                              step_minutes, n_water, atmospheric_transmittance)


def daily_ambient_profile(lat_deg: float, lon_deg: float, start, end,
                          depth_m: float, water: WaterColumn,
                          cloud_transmittance: float = 0.7,
                          tz_offset_h: float | None = None, step_minutes: int = 30,
                          n_water: float = WATER_REFRACTIVE_INDEX,
                          atmospheric_transmittance: float = 0.75,
                          sky=None) -> dict:
    """Media de fotofase, máximo diario y fotoperíodo, día por día.

    La **media de fotofase** es la población sobre la que luego se agrega: es
    el análogo directo del «día» de intensidad constante que experimentaron los
    peces en Oldham (2023), donde la luz estuvo encendida 12 h a nivel fijo.
    Con ``sky`` se usa el PAR observado; los días sin datos suficientes
    quedan como ``nan``.
    """
    days = window_days(start, end)
    samples = _build_samples(lat_deg, lon_deg, days, sky, cloud_transmittance, tz_offset_h,
                             step_minutes, n_water, atmospheric_transmittance)
    means, maxima = _daily_stats(_prepare(samples, water), depth_m)
    return {
        "dates": samples["dates"],
        "photophase_mean_w_m2": [float(v) for v in means],
        "daily_max_w_m2": [float(v) for v in maxima],
        "daylength_h": samples["daylength_h"],
        "valid": [bool(v) for v in samples["valid"]],
    }


def percentile_mean(values: Sequence[float], percentile: float) -> float:
    """Media de los valores en o sobre el percentil dado.

    Es un estadístico continuo que abarca los tres casos habituales sin
    cambiar de fórmula:

    * ``percentile = 0``   → media de toda la ventana;
    * ``percentile = 50``  → media de la mitad superior;
    * ``percentile → 100`` → tiende al máximo.

    Al promediar la cola en vez de tomar un cuantil suelto, el resultado no
    depende de un único día atípico, que es el riesgo de dimensionar contra el
    máximo.
    """
    arr = np.asarray([v for v in values], dtype=float)
    if arr.size == 0:
        return 0.0
    p = max(0.0, min(100.0, float(percentile)))
    cut = float(np.percentile(arr, p))
    tail = arr[arr >= cut]
    if tail.size == 0:
        return float(arr.max())
    return float(tail.mean())


# ---------------------------------------------------------------------------
# Regla de Oldham (2023)
# ---------------------------------------------------------------------------

#: Modos de operación de las luminarias.
OPERATION_24H = "24h"
OPERATION_NIGHT_ONLY = "night"


def adaptive_term(natural_day_w_m2: float, ratio: float,
                  operation: str = OPERATION_24H) -> float | None:
    """Irradiancia artificial que produce la razón noche:día pedida.

    La razón de Oldham se define sobre la luz **total** que el pez recibe:
    ``r = E_noche / E_día``. Lo que cambia entre modos es qué forma el día.

    * ``night``: las luminarias sólo encienden de noche. El día es la luz
      natural y ``E_art = r · E_nat``.
    * ``24h``: las luminarias quedan encendidas también de día, que es la
      práctica habitual de luz continua en jaulas. El día percibido es
      ``E_nat + E_art`` y la noche ``E_art``; despejando
      ``E_art = r·(E_nat + E_art)`` queda ``E_art = r·E_nat / (1 − r)``.

    En 24 h la razón 1 (LL estricto) es inalcanzable: mientras haya sol, el
    día siempre supera a la noche. Se devuelve ``None``.

    Aplicar la forma ``night`` a una instalación 24 h subdimensiona: con
    r = 10 % logra 9,1 %, y con r = 100 % logra sólo 50 %.
    """
    e_nat = max(0.0, float(natural_day_w_m2))
    r = max(0.0, float(ratio))
    if operation == OPERATION_NIGHT_ONLY:
        return r * e_nat
    if operation != OPERATION_24H:
        raise ValueError(f"Modo de operación desconocido: {operation!r}")
    if r >= 1.0:
        return None
    return r * e_nat / (1.0 - r)


def achieved_ratio(natural_day_w_m2: float, artificial_w_m2: float,
                   operation: str = OPERATION_24H) -> float | None:
    """Razón noche:día que resulta de una irradiancia artificial dada."""
    e_nat = max(0.0, float(natural_day_w_m2))
    e_art = max(0.0, float(artificial_w_m2))
    day = e_nat + e_art if operation == OPERATION_24H else e_nat
    if day <= 0.0:
        return None
    return e_art / day


def target_irradiance(reference_w_m2: float, ratio: float,
                      detection_threshold_w_m2: float = DETECTION_THRESHOLD_W_M2,
                      operation: str = OPERATION_24H) -> dict:
    """Irradiancia artificial objetivo según Oldham et al. (2023).

        E_objetivo = max( E_umbral , término adaptativo )

    El primer término es el umbral fijo de detección: por debajo de él la luz
    artificial no se percibe y el régimen se lee como oscuridad, cualquiera sea
    la razón pedida. El segundo es la interpretación adaptativa; su forma
    depende del modo de operación (ver :func:`adaptive_term`).

    Devuelve también cuál de los dos términos manda, porque la lectura
    biológica cambia: si manda el umbral, el sitio es tan oscuro a esa
    profundidad que basta con superar la detección; si manda la razón, hay que
    competir de verdad contra la luz natural.
    """
    ref = max(0.0, float(reference_w_m2))
    r = max(0.0, float(ratio))
    floor = max(0.0, float(detection_threshold_w_m2))
    adaptive = adaptive_term(ref, r, operation)

    if adaptive is None:
        return {
            "target_w_m2": None,
            "adaptive_term_w_m2": None,
            "threshold_w_m2": floor,
            "binding_term": "inalcanzable (r = 1 con luminarias 24 h)",
            "ratio": r,
            "achieved_ratio": None,
            "reference_w_m2": ref,
            "operation": operation,
        }

    target = max(floor, adaptive)
    if r <= 0.0:
        binding = "ninguno (régimen de oscuridad, r = 0)"
    elif adaptive >= floor:
        binding = "razón adaptativa"
    else:
        binding = "umbral de detección"
    return {
        "target_w_m2": target,
        "adaptive_term_w_m2": adaptive,
        "threshold_w_m2": floor,
        "binding_term": binding,
        "ratio": r,
        "achieved_ratio": achieved_ratio(ref, target, operation),
        "reference_w_m2": ref,
        "operation": operation,
    }


def par_w_m2_to_umol(value_w_m2: float,
                     umol_per_joule: float = UMOL_PER_JOULE_PAR) -> float:
    """Convierte W/m² PAR a µmol m⁻² s⁻¹, sólo para contraste con Oldham.

    El factor depende del espectro: 4,57 µmol/J para PAR de luz diurna,
    ≈4,03 para luz subacuática centrada en 480 nm, ≈3,76 para un LED azul
    de 450 nm. El umbral por defecto, 0,016 W/m², cae entre 0,060 y 0,073
    µmol m⁻² s⁻¹ según cuál se use; en todos los casos dentro de la banda
    0,01–0,1 de Oldham.
    """
    return float(value_w_m2) * float(umol_per_joule)


# ---------------------------------------------------------------------------
# Cobertura y objetivos propuestos
# ---------------------------------------------------------------------------

def daily_targets(daily_means: Sequence[float], ratio: float,
                  detection_threshold_w_m2: float = DETECTION_THRESHOLD_W_M2,
                  operation: str = OPERATION_24H) -> list[float | None]:
    """Objetivo que haría falta cada día para sostener la razón con su luz."""
    floor = max(0.0, float(detection_threshold_w_m2))
    out = []
    for value in daily_means:
        term = adaptive_term(value, ratio, operation)
        out.append(None if term is None else max(floor, term))
    return out


def coverage(single_target_w_m2: float | None, targets: Sequence[float | None],
             dates: Sequence[str] | None = None) -> dict | None:
    """Cuántos días de la ventana sostiene un objetivo único."""
    if single_target_w_m2 is None:
        return None
    labels = list(dates) if dates is not None else [str(i) for i in range(len(targets))]
    valid = [(d, t) for d, t in zip(labels, targets) if t is not None]
    if not valid:
        return None
    covered = sum(1 for _, t in valid if single_target_w_m2 >= t * (1.0 - 1e-9))
    worst_date, worst = max(valid, key=lambda item: item[1])
    mildest_date, mildest = min(valid, key=lambda item: item[1])
    return {
        "days_covered": covered,
        "days_total": len(valid),
        "fraction_covered": covered / len(valid),
        "worst_date": worst_date,
        "worst_target_w_m2": worst,
        "mildest_date": mildest_date,
        "mildest_target_w_m2": mildest,
    }


def proposal_table(daily_means: Sequence[float],
                   percentiles: Sequence[float] = PROPOSAL_PERCENTILES,
                   ratios: Sequence[float] = PROPOSAL_RATIOS,
                   detection_threshold_w_m2: float = DETECTION_THRESHOLD_W_M2,
                   operation: str = OPERATION_24H) -> dict:
    """Objetivos propuestos para cada combinación de percentil y razón.

    Es la salida principal de la pestaña: en vez de un número único, muestra
    cómo cambia el objetivo con las dos decisiones que no son físicas —cuánta
    de la ventana se quiere cubrir y qué razón se persigue— junto con la
    fracción de días que cada combinación sostiene.
    """
    ratio_list = sorted({round(float(r), 6) for r in ratios if float(r) > 0.0})
    per_ratio = {r: daily_targets(daily_means, r, detection_threshold_w_m2, operation)
                 for r in ratio_list}
    rows = []
    for p in percentiles:
        reference = percentile_mean(daily_means, p)
        cells = []
        for r in ratio_list:
            tgt = target_irradiance(reference, r, detection_threshold_w_m2, operation)
            cov = coverage(tgt["target_w_m2"], per_ratio[r])
            cells.append({
                "ratio": r,
                "target_w_m2": tgt["target_w_m2"],
                "binding_term": tgt["binding_term"],
                "fraction_covered": cov["fraction_covered"] if cov else None,
            })
        rows.append({"percentile": float(p), "reference_w_m2": reference, "cells": cells})
    return {"ratios": ratio_list, "rows": rows}


# ---------------------------------------------------------------------------
# Orquestador
# ---------------------------------------------------------------------------

def _by_window_date(window_dates: list[str], values: np.ndarray) -> dict:
    """Agrupa por fecha de la ventana: mediana y banda P10–P90 entre años."""
    order, groups = [], {}
    for d, v in zip(window_dates, values):
        if d not in groups:
            groups[d] = []
            order.append(d)
        if not np.isnan(v):
            groups[d].append(float(v))

    def stat(vals, q):
        return float(np.percentile(vals, q)) if vals else None
    return {
        "dates": order,
        "median": [stat(groups[d], 50) for d in order],
        "p10": [stat(groups[d], 10) for d in order],
        "p90": [stat(groups[d], 90) for d in order],
        "n": [len(groups[d]) for d in order],
    }


def evaluate(lat_deg: float, lon_deg: float, start, end,
             reference_depth_m: float, target_depth_m: float,
             water: WaterColumn, ratio: float,
             cloud_transmittance: float = 0.7,
             percentile: float = 50.0,
             detection_threshold_w_m2: float = DETECTION_THRESHOLD_W_M2,
             tz_offset_h: float | None = None,
             step_minutes: int = 30,
             atmospheric_transmittance: float = 0.75,
             operation: str = OPERATION_24H,
             proposal_percentiles: Sequence[float] = PROPOSAL_PERCENTILES,
             proposal_ratios: Sequence[float] = PROPOSAL_RATIOS,
             sky=None, sky_mode: str = SKY_MODE_WINDOW,
             sky_years: Sequence[int] | None = None) -> dict:
    """Ejecuta la cadena completa y devuelve un resultado serializable.

    ``reference_depth_m`` es la profundidad donde se evalúa la luz natural que
    define la historia lumínica del lote; ``target_depth_m`` es donde debe
    cumplirse la irradiancia artificial. Suelen ser distintas.

    Con ``sky`` (una ``sky_forcing.SkySeries``) la superficie es PAR
    observado; ``sky_mode`` elige entre el año exacto de la ventana y una
    climatología de ``sky_years``. Sin ``sky``, cielo despejado modelado por
    ``cloud_transmittance``.

    Devuelve el objetivo para el percentil y la razón elegidos, el objetivo día
    a día con la cobertura de la ventana, la tabla de objetivos propuestos y el
    perfil vertical exacto del estadístico.
    """
    mode = sky_mode if sky is not None else SKY_MODE_WINDOW
    days = window_days(start, end, mode, sky_years)
    samples = _build_samples(lat_deg, lon_deg, days, sky, cloud_transmittance, tz_offset_h,
                             step_minutes, WATER_REFRACTIVE_INDEX, atmospheric_transmittance)
    prep = _prepare(samples, water)
    valid_mask = samples["valid"]
    if not valid_mask.any():
        raise ValueError("Ningún día de la ventana tiene datos de cielo suficientes. "
                         "Revise el período de la serie observada o use la climatología.")

    means_arr, maxima_arr = _daily_stats(prep, reference_depth_m)
    means = _valid(means_arr)
    labels = [d for d, ok in zip(samples["dates"], valid_mask) if ok]
    reference = percentile_mean(means, percentile)
    target = target_irradiance(reference, ratio, detection_threshold_w_m2, operation)
    per_day = daily_targets(means, ratio, target["threshold_w_m2"], operation)

    # Serie para graficar: por fecha de la ventana, mediana y banda entre años.
    grouped = _by_window_date(samples["window_dates"], means_arr)
    grouped_max = _by_window_date(samples["window_dates"], maxima_arr)
    daylength_by_date = {}
    for wd, dl in zip(samples["window_dates"], samples["daylength_h"]):
        daylength_by_date.setdefault(wd, dl)
    median_targets = daily_targets([np.nan if v is None else v for v in grouped["median"]],
                                   ratio, target["threshold_w_m2"], operation)
    profile = {
        "dates": grouped["dates"],
        "photophase_mean_w_m2": grouped["median"],
        "photophase_p10_w_m2": grouped["p10"],
        "photophase_p90_w_m2": grouped["p90"],
        "years_per_date": grouped["n"],
        "daily_max_w_m2": grouped_max["median"],
        "daylength_h": [daylength_by_date[d] for d in grouped["dates"]],
        "daily_target_w_m2": [None if v is None or np.isnan(v) else t
                              for v, t in zip(grouped["median"], median_targets)],
    }

    # Perfil vertical exacto del estadístico: cada punto repite la agregación
    # completa a esa profundidad, espectralmente y con el cenit de cada instante.
    z_max = max(target_depth_m, reference_depth_m) * 1.5 + 1.0
    depths = np.linspace(0.0, z_max, 60)
    vertical = [percentile_mean(_valid(_daily_stats(prep, z)[0]), percentile) for z in depths]
    natural_at_target = percentile_mean(_valid(_daily_stats(prep, target_depth_m)[0]), percentile)

    z_lo = max(0.0, reference_depth_m - 1.0)
    e_lo = percentile_mean(_valid(_daily_stats(prep, z_lo)[0]), percentile)
    e_hi = percentile_mean(_valid(_daily_stats(prep, z_lo + 2.0)[0]), percentile)
    kd_equivalent = math.log(e_lo / e_hi) / 2.0 if e_lo > 0 and e_hi > 0 else None

    ratios = list(proposal_ratios) + ([ratio] if ratio > 0 else [])
    if operation == OPERATION_24H:
        ratios = [r for r in ratios if r < 1.0]

    missing = [d for d, ok in zip(samples["dates"], valid_mask) if not ok]
    used_years = sorted({int(d[:4]) for d in labels})
    return {
        "profile": profile,
        "reference": {
            "depth_m": float(reference_depth_m),
            "percentile": float(percentile),
            "value_w_m2": reference,
            "window_days": len(means),
            "window_min_w_m2": float(np.min(means)),
            "window_max_w_m2": float(np.max(means)),
            "window_median_w_m2": float(np.median(means)),
            "natural_at_target_w_m2": natural_at_target,
        },
        "target": {**target, "depth_m": float(target_depth_m)},
        "coverage": coverage(target["target_w_m2"], per_day, labels),
        "proposals": proposal_table(means, proposal_percentiles, ratios,
                                    target["threshold_w_m2"], operation),
        "vertical": {
            "depths_m": [float(z) for z in depths],
            "ambient_w_m2": [float(v) for v in vertical],
        },
        "water": {
            "label": water.label,
            "weeks_with_own_iop": len(water.weeks),
            "window_weeks": sorted(set(samples["iso_weeks"])),
            "window_weeks_with_own_iop": sorted(set(samples["iso_weeks"]) & set(water.weeks)),
            "kd_par_equivalent_m_inv": kd_equivalent,
        },
        "sky": {
            "observed": sky is not None,
            "mode": mode,
            "note": samples["note"],
            "days_total": len(days),
            "days_used": len(means),
            "days_missing": len(missing),
            "missing_first": missing[:5],
            "years_used": used_years,
            "used_dates": labels,
        },
        "settings": {
            "cloud_transmittance": None if sky is not None else float(cloud_transmittance),
            "par_fraction": PAR_FRACTION_REFERENCE,
            "step_minutes": int(step_minutes),
            "operation": operation,
        },
    }
