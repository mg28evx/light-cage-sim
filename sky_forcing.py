"""Cielo observado para la pestaña de fotoperíodo.

Reemplaza la transmitancia de nubes escrita a mano por irradiancia de
superficie **medida o derivada de satélite**, hora a hora. Dos fuentes:

* **NASA POWER** (CERES SYN1deg, ~1°): PAR horario con cielo real, separado en
  directo horizontal (``ALLSKY_SFC_PAR_DIRH``) y difuso
  (``ALLSKY_SFC_PAR_DIFF``), más el PAR de cielo despejado
  (``CLRSKY_SFC_PAR_TOT``) como diagnóstico. Disponible desde 2001 con unos
  tres meses de rezago; las horas sin dato llegan con ``fill_value = −999``.
  Con PAR directo y difuso observados no hace falta modelo de cielo despejado,
  factor de nubes, modelo de descomposición ni fracción PAR.

* **CSV propio**: sensores del centro, estaciones meteorológicas o
  exportaciones de Explorador Solar. Horario o subhorario. Acepta PAR (W/m² o
  µmol m⁻² s⁻¹), o radiación global de onda corta con difusa opcional.

Convención interna: cada registro es una media sobre un intervalo, fechada en
el **centro** del intervalo y en **UTC** (datetime ingenuo).
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import json
import math
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import numpy as np

import ambient_light as al

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "data" / "sky_cache"

POWER_URL = "https://power.larc.nasa.gov/api/temporal/hourly/point"
POWER_PARAMETERS = ("ALLSKY_SFC_PAR_DIRH", "ALLSKY_SFC_PAR_DIFF", "CLRSKY_SFC_PAR_TOT")
POWER_FIRST_YEAR = 2001

#: Días que se reutiliza la caché de un año todavía incompleto.
PARTIAL_YEAR_CACHE_DAYS = 7

#: µmol de fotones por joule de PAR de luz diurna, para CSV en µmol m⁻² s⁻¹.
UMOL_PER_JOULE_PAR = al.UMOL_PER_JOULE_PAR


# ---------------------------------------------------------------------------
# Serie
# ---------------------------------------------------------------------------

@dataclass
class SkySeries:
    """PAR de superficie observado, hora a hora.

    ``times_utc`` marca el centro de cada intervalo en UTC. ``par_direct_h``
    es el PAR directo sobre plano horizontal y ``par_diffuse`` el difuso de
    cielo, ambos en W/m² medios del intervalo. ``par_clear`` es opcional y
    sólo sirve para diagnosticar la nubosidad.
    """

    times_utc: list
    par_direct_h: np.ndarray
    par_diffuse: np.ndarray
    step_hours: float
    source: str
    par_clear: np.ndarray | None = None
    detail: dict = field(default_factory=dict)

    def __post_init__(self):
        order = np.argsort(np.asarray([t.timestamp() for t in self.times_utc]))
        self.times_utc = [self.times_utc[i] for i in order]
        self.par_direct_h = np.clip(np.asarray(self.par_direct_h, dtype=float)[order], 0.0, None)
        self.par_diffuse = np.clip(np.asarray(self.par_diffuse, dtype=float)[order], 0.0, None)
        if self.par_clear is not None:
            self.par_clear = np.asarray(self.par_clear, dtype=float)[order]

    def __len__(self):
        return len(self.times_utc)

    @property
    def par_total(self) -> np.ndarray:
        return self.par_direct_h + self.par_diffuse

    def local_solar_dates(self, lon_deg: float) -> list:
        """Fecha solar local de cada registro.

        Agrupar por fecha UTC partiría el día en longitudes lejanas de
        Greenwich; la fecha solar local mantiene cada día luminoso entero.
        """
        shift = _dt.timedelta(hours=float(lon_deg) / 15.0)
        return [(t + shift).date() for t in self.times_utc]

    def index_by_date(self, lon_deg: float) -> dict:
        out: dict = {}
        for i, d in enumerate(self.local_solar_dates(lon_deg)):
            out.setdefault(d, []).append(i)
        return out

    def years(self) -> list[int]:
        return sorted({t.year for t in self.times_utc})

    def period(self) -> tuple[str, str] | tuple[None, None]:
        if not self.times_utc:
            return None, None
        return self.times_utc[0].date().isoformat(), self.times_utc[-1].date().isoformat()


def concat(series: list[SkySeries], source: str) -> SkySeries:
    """Une varias series (por ejemplo, un año por solicitud)."""
    series = [s for s in series if len(s)]
    if not series:
        return SkySeries([], np.zeros(0), np.zeros(0), 1.0, source)
    clear = None
    if all(s.par_clear is not None for s in series):
        clear = np.concatenate([s.par_clear for s in series])
    detail = dict(series[0].detail)
    detail["parts"] = len(series)
    return SkySeries(
        times_utc=[t for s in series for t in s.times_utc],
        par_direct_h=np.concatenate([s.par_direct_h for s in series]),
        par_diffuse=np.concatenate([s.par_diffuse for s in series]),
        step_hours=series[0].step_hours,
        source=source,
        par_clear=clear,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# Descomposición y geometría auxiliar
# ---------------------------------------------------------------------------

# La descomposición vive en ambient_light, que también la usa en el modo manual.
extraterrestrial_horizontal_w_m2 = al.extraterrestrial_horizontal_w_m2
erbs_diffuse_fraction = al.erbs_diffuse_fraction


def detect_time_shift_hours(times: list, values: np.ndarray, lat_deg: float, lon_deg: float,
                            candidates: np.ndarray, max_days: int = 40) -> tuple[float, float]:
    """Desfase que mejor alinea una serie con la geometría solar.

    Prueba cada desfase candidato y se queda con el que maximiza la
    correlación entre la serie observada y el seno de la elevación solar. Así
    se resuelven a la vez el huso horario y la convención de la marca de
    tiempo (inicio, centro o fin del intervalo) de un CSV sin metadatos.
    Usa hasta ``max_days`` días repartidos en la serie para acotar el costo.
    Devuelve ``(desfase_h, correlación)``.
    """
    values = np.asarray(values, dtype=float)
    days = sorted({t.date() for t in times})
    if len(days) > max_days:
        keep = set(days[i] for i in np.linspace(0, len(days) - 1, max_days).astype(int))
        idx = [i for i, t in enumerate(times) if t.date() in keep]
    else:
        idx = list(range(len(times)))
    obs = values[idx]
    if obs.size < 12 or np.allclose(obs, obs[0]):
        return 0.0, 0.0
    best, best_r = 0.0, -2.0
    for shift in candidates:
        delta = _dt.timedelta(hours=float(shift))
        model = np.array([max(0.0, math.sin(math.radians(
            al.solar_elevation_deg(lat_deg, lon_deg, times[i] + delta, 0.0)))) for i in idx])
        if np.allclose(model, model[0]):
            continue
        r = float(np.corrcoef(obs, model)[0, 1])
        if r > best_r:
            best, best_r = float(shift), r
    return best, best_r


# ---------------------------------------------------------------------------
# NASA POWER
# ---------------------------------------------------------------------------

def power_url(lat_deg: float, lon_deg: float, start: _dt.date, end: _dt.date) -> str:
    query = {
        "parameters": ",".join(POWER_PARAMETERS),
        "community": "RE",
        "longitude": f"{float(lon_deg):.4f}",
        "latitude": f"{float(lat_deg):.4f}",
        "start": start.strftime("%Y%m%d"),
        "end": end.strftime("%Y%m%d"),
        "format": "JSON",
        "time-standard": "UTC",
    }
    return f"{POWER_URL}?{urlencode(query)}"


def _to_mean_w_m2(values: np.ndarray, units: str) -> np.ndarray:
    """Convierte la unidad declarada por POWER a W/m² medios de la hora."""
    u = units.replace(" ", "").lower()
    if u in ("wh/m^2", "wh/m2", "w-hr/m^2"):
        return values                 # energía horaria: equivale a la media en W/m²
    if u in ("w/m^2", "w/m2"):
        return values
    if u in ("mj/m^2", "mj/m2", "mj/hr"):
        return values * 1e6 / 3600.0
    if u in ("kw-hr/m^2", "kwh/m^2", "kwh/m2"):
        return values * 1000.0
    raise ValueError(f"Unidad de NASA POWER no reconocida: {units!r}")


def parse_power_json(payload: dict) -> SkySeries:
    """Convierte una respuesta horaria de POWER en una serie.

    Descarta las horas en que falta cualquiera de las dos componentes. Las
    claves ``AAAAMMDDHH`` marcan el **inicio** de la hora en UTC.
    """
    params = payload["properties"]["parameter"]
    fill = float(payload["header"].get("fill_value", -999.0))
    units = {k: payload.get("parameters", {}).get(k, {}).get("units", "Wh/m^2")
             for k in params}
    keys = sorted(params["ALLSKY_SFC_PAR_DIRH"])

    def column(name):
        raw = params.get(name)
        if raw is None:
            return None
        arr = np.array([raw.get(k, fill) for k in keys], dtype=float)
        arr[np.isclose(arr, fill)] = np.nan
        return _to_mean_w_m2(arr, units[name])

    direct = column("ALLSKY_SFC_PAR_DIRH")
    diffuse = column("ALLSKY_SFC_PAR_DIFF")
    clear = column("CLRSKY_SFC_PAR_TOT")
    ok = ~(np.isnan(direct) | np.isnan(diffuse))
    times = [_dt.datetime.strptime(k, "%Y%m%d%H") + _dt.timedelta(minutes=30)
             for k, good in zip(keys, ok) if good]
    lon, lat = payload.get("geometry", {}).get("coordinates", [None, None])[:2]
    return SkySeries(
        times_utc=times,
        par_direct_h=direct[ok],
        par_diffuse=diffuse[ok],
        par_clear=None if clear is None else clear[ok],
        step_hours=1.0,
        source="NASA POWER (CERES SYN1deg)",
        detail={"grid_lat": lat, "grid_lon": lon,
                "sources": payload["header"].get("sources"),
                "api_version": payload["header"].get("api", {}).get("version"),
                "hours_requested": len(keys), "hours_valid": int(ok.sum())},
    )


def _power_cache_path(cache_dir: Path, lat: float, lon: float, year: int, partial: bool) -> Path:
    stem = f"power_par_{lat:.3f}_{lon:.3f}_{year}"
    return cache_dir / (f"{stem}_parcial.json" if partial else f"{stem}.json")


def fetch_power_year(lat_deg: float, lon_deg: float, year: int,
                     cache_dir: Path | None = None, timeout: float = 60.0,
                     today: _dt.date | None = None, opener=urlopen) -> SkySeries:
    """Un año de POWER, desde caché o desde la API.

    Los años cerrados se guardan de forma permanente. El año en curso llega
    truncado por el rezago de CERES; se guarda aparte y se renueva cada
    ``PARTIAL_YEAR_CACHE_DAYS`` días.
    """
    today = today or _dt.date.today()
    if year < POWER_FIRST_YEAR or year > today.year:
        raise ValueError(f"NASA POWER horario cubre {POWER_FIRST_YEAR}–{today.year}; se pidió {year}.")
    partial = year >= today.year
    cache_dir = Path(cache_dir) if cache_dir is not None else CACHE_DIR
    path = _power_cache_path(cache_dir, lat_deg, lon_deg, year, partial)
    if path.exists():
        fresh = (not partial) or (time.time() - path.stat().st_mtime < PARTIAL_YEAR_CACHE_DAYS * 86400)
        if fresh:
            series = parse_power_json(json.loads(path.read_text(encoding="utf-8")))
            series.detail["cache"] = str(path)
            return series

    end = _dt.date(year, 12, 31) if not partial else today - _dt.timedelta(days=1)
    url = power_url(lat_deg, lon_deg, _dt.date(year, 1, 1), end)
    with opener(url, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if "properties" not in payload:
        raise RuntimeError(f"NASA POWER no devolvió datos: {str(payload)[:300]}")
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    series = parse_power_json(payload)
    series.detail["cache"] = str(path)
    return series


def load_power(lat_deg: float, lon_deg: float, years: list[int],
               cache_dir: Path | None = None, **kwargs) -> SkySeries:
    """Varios años de POWER unidos en una sola serie."""
    parts = [fetch_power_year(lat_deg, lon_deg, int(y), cache_dir, **kwargs)
             for y in sorted(set(int(y) for y in years))]
    series = concat(parts, "NASA POWER (CERES SYN1deg)")
    series.detail["years_requested"] = sorted(set(int(y) for y in years))
    return series


# ---------------------------------------------------------------------------
# CSV propio
# ---------------------------------------------------------------------------

_TIME_ALIASES = ("timestamp", "datetime", "fecha_hora", "fechahora", "time", "fecha", "date")
_HOUR_ALIASES = ("hora", "hour")
_PART_ALIASES = {"year": ("year", "ano", "anio"), "month": ("month", "mes"),
                 "day": ("day", "dia"), "hour": ("hour", "hora")}
_VALUE_ALIASES = {
    "par_dirh": ("par_dirh", "par_direct", "par_directa", "allsky_sfc_par_dirh"),
    "par_diff": ("par_diff", "par_diffuse", "par_difusa", "allsky_sfc_par_diff"),
    "par_umol": ("par_umol", "ppfd", "par_umol_m2_s", "par_micromol"),
    "par": ("par", "par_w_m2", "par_tot", "par_total", "allsky_sfc_par_tot"),
    "dhi": ("dhi", "diffhor", "difusa", "radiacion_difusa", "rad_difusa", "allsky_sfc_sw_diff", "diff"),
    "ghi": ("ghi", "globhor", "glob", "global", "radiacion_global", "rad_global",
            "radiacion", "sw_dwn", "allsky_sfc_sw_dwn"),
}
_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
                 "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%Y/%m/%d %H:%M", "%Y%m%d%H")


def _normalize(name: str) -> str:
    text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    text = text.strip().lower()
    for ch in " -./()[]{}":
        text = text.replace(ch, "_")
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")


def _find_column(headers: list[str], aliases) -> int | None:
    norm = [_normalize(h) for h in headers]
    for alias in aliases:
        for i, h in enumerate(norm):
            if h == alias:
                return i
    for alias in aliases:
        for i, h in enumerate(norm):
            if h.startswith(alias + "_"):
                return i
    return None


def _parse_time(text: str) -> _dt.datetime:
    text = text.strip()
    try:
        return _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    for fmt in _TIME_FORMATS:
        try:
            return _dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"Fecha no reconocida: {text!r}")


def _parse_number(text: str) -> float:
    text = str(text).strip().replace(",", ".")
    if text in ("", "nan", "na", "null", "-", "--"):
        return float("nan")
    value = float(text)
    return float("nan") if value <= -999.0 else value


def parse_sky_csv(text: str, lat_deg: float, lon_deg: float,
                  utc_offset_h: float | None = None) -> SkySeries:
    """Lee un CSV horario o subhorario de irradiancia de superficie.

    Columnas aceptadas (sin distinguir mayúsculas ni tildes; admiten sufijo
    de unidad, p. ej. ``ghi_w_m2``):

    * tiempo: ``timestamp``/``fecha_hora``/``fecha`` (+ ``hora`` opcional),
      o ``año, mes, día, hora`` por separado;
    * PAR: ``par_dirh`` + ``par_diff`` (ideal), o ``par`` en W/m², o
      ``par_umol``/``ppfd`` en µmol m⁻² s⁻¹;
    * onda corta: ``ghi``/``radiacion_global`` y opcionalmente
      ``dhi``/``difusa``, en W/m² medios.

    Si las fechas traen zona horaria se respetan; si no, se usa
    ``utc_offset_h`` o, en su defecto, el desfase se detecta por correlación
    con la geometría solar. En ambos casos se afina en medias horas para
    absorber la convención de la marca (inicio, centro o fin del intervalo).
    """
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delimiter) if any(c.strip() for c in r)]
    if len(rows) < 3:
        raise ValueError("El CSV no tiene suficientes filas.")
    headers, body = rows[0], rows[1:]

    cols = {key: _find_column(headers, aliases) for key, aliases in _VALUE_ALIASES.items()}
    has_par_split = cols["par_dirh"] is not None and cols["par_diff"] is not None
    if not (has_par_split or cols["par"] is not None or cols["par_umol"] is not None
            or cols["ghi"] is not None):
        raise ValueError("No se encontró una columna de irradiancia: se esperaba PAR "
                         "(par, par_umol, par_dirh + par_diff) o global (ghi, radiacion_global).")

    t_col = _find_column(headers, _TIME_ALIASES)
    h_col = _find_column(headers, _HOUR_ALIASES)
    part_cols = {k: _find_column(headers, v) for k, v in _PART_ALIASES.items()}

    def row_time(r):
        if all(part_cols[k] is not None for k in ("year", "month", "day", "hour")) and t_col is None:
            hour = float(_parse_number(r[part_cols["hour"]]))
            base = _dt.datetime(int(float(r[part_cols["year"]])), int(float(r[part_cols["month"]])),
                                int(float(r[part_cols["day"]])))
            return base + _dt.timedelta(hours=hour)
        if t_col is None:
            raise ValueError("No se encontró la columna de fecha y hora.")
        raw = r[t_col]
        if h_col is not None and h_col != t_col:
            hour_txt = r[h_col].strip()
            if ":" not in hour_txt:
                hour_txt = f"{int(float(hour_txt)):02d}:00"
            raw = f"{raw.strip()} {hour_txt}"
        return _parse_time(raw)

    times, values = [], {k: [] for k in cols if cols[k] is not None}
    for r in body:
        try:
            t = row_time(r)
        except (ValueError, IndexError):
            continue
        rec = {}
        for key in values:
            try:
                rec[key] = _parse_number(r[cols[key]])
            except (ValueError, IndexError):
                rec[key] = float("nan")
        times.append(t)
        for key in values:
            values[key].append(rec[key])
    if len(times) < 12:
        raise ValueError("Muy pocas filas con fecha válida.")

    aware = times[0].tzinfo is not None
    if aware:
        times = [t.astimezone(_dt.timezone.utc).replace(tzinfo=None) for t in times]
    arrays = {k: np.asarray(v, dtype=float) for k, v in values.items()}

    stamps = sorted(t.timestamp() for t in times)
    step_h = float(np.median(np.diff(stamps))) / 3600.0 if len(stamps) > 1 else 1.0
    if step_h >= 20.0:
        raise ValueError("Los datos parecen diarios; se requiere resolución horaria o subhoraria.")

    # Serie de referencia para alinear con el sol: la magnitud total disponible.
    if has_par_split:
        total_ref = np.nan_to_num(arrays["par_dirh"]) + np.nan_to_num(arrays["par_diff"])
    elif "par" in arrays:
        total_ref = np.nan_to_num(arrays["par"])
    elif "par_umol" in arrays:
        total_ref = np.nan_to_num(arrays["par_umol"])
    else:
        total_ref = np.nan_to_num(arrays["ghi"])

    half = np.arange(-1.0, 1.01, 0.5) * max(step_h, 0.5)
    if aware or utc_offset_h is not None:
        base = 0.0 if aware else -float(utc_offset_h)
        shift, r = detect_time_shift_hours(times, total_ref, lat_deg, lon_deg, base + half)
        offset_source = "zona horaria del archivo" if aware else "declarado"
    else:
        coarse, _ = detect_time_shift_hours(times, total_ref, lat_deg, lon_deg,
                                            np.arange(-14.0, 14.01, 1.0))
        shift, r = detect_time_shift_hours(times, total_ref, lat_deg, lon_deg, coarse + half)
        offset_source = "detectado por correlación con la geometría solar"
    times = [t + _dt.timedelta(hours=shift) for t in times]

    # Componentes en PAR
    if has_par_split:
        direct, diffuse = arrays["par_dirh"], arrays["par_diff"]
        basis = "PAR directo y difuso medidos"
    else:
        if "par" in arrays:
            total = arrays["par"]
            basis = "PAR total medido"
        elif "par_umol" in arrays:
            total = arrays["par_umol"] / UMOL_PER_JOULE_PAR
            basis = f"PAR total medido en µmol (÷ {UMOL_PER_JOULE_PAR} µmol/J)"
        else:
            total = arrays["ghi"] * al.PAR_FRACTION_REFERENCE
            basis = f"global de onda corta × {al.PAR_FRACTION_REFERENCE:.3f} (fracción PAR AM1.5G)"
        if "dhi" in arrays and "ghi" in arrays:
            ghi, dhi = arrays["ghi"], arrays["dhi"]
            # Con global nula (noche, bordes del día) la fracción no está
            # definida; se fija en 1 para no descartar la fila, y total = 0.
            with np.errstate(divide="ignore", invalid="ignore"):
                kd = np.where(ghi > 0, np.clip(dhi / ghi, 0.0, 1.0), 1.0)
            kd = np.where(np.isnan(ghi) | np.isnan(dhi), np.nan, kd)
            split = "difusa medida"
        else:
            ghi_equiv = arrays["ghi"] if "ghi" in arrays else total / al.PAR_FRACTION_REFERENCE
            kd = np.empty(len(times))
            for i, t in enumerate(times):
                e0 = extraterrestrial_horizontal_w_m2(t, lat_deg, lon_deg)
                kd[i] = erbs_diffuse_fraction(ghi_equiv[i] / e0) if e0 > 0 else 1.0
            split = "difusa estimada con Erbs et al. (1982)"
        diffuse = total * kd
        direct = total - diffuse
        basis = f"{basis}; {split}"

    ok = ~(np.isnan(direct) | np.isnan(diffuse))
    series = SkySeries(
        times_utc=[t for t, g in zip(times, ok) if g],
        par_direct_h=direct[ok],
        par_diffuse=diffuse[ok],
        step_hours=step_h,
        source="CSV propio",
        detail={"basis": basis, "utc_shift_applied_h": shift, "alignment_r": round(r, 4),
                "offset_source": offset_source, "rows": len(body), "rows_valid": int(ok.sum()),
                "columns": {k: headers[v] for k, v in cols.items() if v is not None}},
    )
    return series


# ---------------------------------------------------------------------------
# Diagnóstico
# ---------------------------------------------------------------------------

def clear_sky_index_summary(series: SkySeries, lon_deg: float,
                            dates: set | None = None) -> dict | None:
    """Razón diaria PAR con cielo real / PAR con cielo despejado.

    Es la «transmitancia de nubes» empírica del sitio. Sólo existe si la
    fuente trae el PAR de cielo despejado (NASA POWER).
    """
    if series.par_clear is None or not len(series):
        return None
    daily_all, daily_clear = {}, {}
    total = series.par_total
    for i, d in enumerate(series.local_solar_dates(lon_deg)):
        if np.isnan(series.par_clear[i]) or (dates is not None and d not in dates):
            continue
        daily_all[d] = daily_all.get(d, 0.0) + total[i]
        daily_clear[d] = daily_clear.get(d, 0.0) + series.par_clear[i]
    ratios = np.array([daily_all[d] / daily_clear[d] for d in daily_all if daily_clear[d] > 0])
    if ratios.size == 0:
        return None
    return {"days": int(ratios.size),
            "p10": float(np.percentile(ratios, 10)),
            "p50": float(np.percentile(ratios, 50)),
            "p90": float(np.percentile(ratios, 90)),
            "mean": float(ratios.mean())}
