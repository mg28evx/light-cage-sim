"""
Parser de mediciones espectrales OHSP-350 -> tabla por banda.

Cada CSV de measurements/<sitio> contiene metadatos (E lx, CCT, ...) y un espectro
380-780 nm en [mW/m2/nm]. El nombre codifica la posicion del sensor:
    p{x}{y}{z}-{HHMMSS}.csv   con  x,y in {5,10,15,20}  y  z in {8,10,12}

Salida: lista de registros dict con posicion (x,y,z), E(lx), y la irradiancia
integrada por banda espectral en [mW/m2]. Marca ceros como censura izquierda
(bajo el piso del sensor) y devuelve tambien PAR 400-700.
"""
import os
import re
import glob
import json
import numpy as np

# Bandas espectrales de comparacion [nm]. PAR 400-700 se agrega aparte.
BANDS = {
    "blue":  (400.0, 500.0),
    "green": (500.0, 600.0),
    "red":   (600.0, 700.0),
}
PAR_RANGE = (400.0, 700.0)

# Valores permitidos por eje (para desambiguar el parseo del nombre).
_X_VALS = ["20", "15", "10", "5"]
_Y_VALS = ["20", "15", "10", "5"]
_Z_VALS = ["12", "10", "8"]


# Conjuntos de valores por sitio (para desambiguar el parseo del nombre).
_SITE_VALS = {
    "p": (["20", "15", "10", "5"], ["20", "15", "10", "5"], ["12", "10", "8"]),
    "h": (["24", "18", "12", "6"], ["24", "18", "12", "6"], ["10", "8"]),
}


def parse_name(fname):
    """Extrae (x, y, z) enteros de nombres {prefijo}{x}{y}{z}-... Soporta 'p'
    (Punta Iglesia) y 'h' (Hueihue). Devuelve None si falla."""
    base = os.path.basename(fname).split("-")[0]
    if not base or base[0] not in _SITE_VALS:
        return None
    xvals, yvals, zvals = _SITE_VALS[base[0]]
    digits = base[1:]
    for z in zvals:
        if digits.endswith(z):
            xy = digits[: -len(z)]
            for x in xvals:
                if xy.startswith(x):
                    y = xy[len(x):]
                    if y in yvals:
                        return int(x), int(y), int(z)
    return None


def _read_csv(fname):
    """Devuelve (E_lx, wl[nm], spec[mW/m2/nm])."""
    E = None
    wl, spec = [], []
    with open(fname, encoding="latin-1") as fh:
        for line in fh:
            p = line.strip().split(",")
            if not p:
                continue
            if p[0] == "E(lx)":
                try:
                    E = float(p[1])
                except (ValueError, IndexError):
                    pass
            elif re.match(r"^\d{3}$", p[0]) and len(p) >= 2:
                try:
                    wl.append(float(p[0]))
                    spec.append(float(p[1]))
                except ValueError:
                    pass
    return E, np.asarray(wl), np.asarray(spec)


def _integrate(wl, spec, lo, hi):
    m = (wl >= lo) & (wl <= hi)
    if m.sum() < 2:
        return 0.0
    return float(np.trapezoid(spec[m], wl[m]))


def _load_correction_rules(folder):
    """Carga correcciones declarativas locales sin modificar los CSV originales."""
    path = os.path.join(folder, "corrections.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    return payload.get("rules", [])


def _apply_correction_rules(rec, rules):
    """Aplica factores trazables a PAR, bandas y lux, conservando valores crudos."""
    for rule in rules:
        files = set(rule.get("files", []))
        if files and rec["file"] not in files:
            continue
        depth = rule.get("depth_m")
        if depth is not None and not np.isclose(rec["z"], float(depth)):
            continue
        value_w = rec["par"] / 1000.0
        bounds = rule.get("original_range_W_m2", {})
        lo = bounds.get("min_inclusive")
        hi = bounds.get("max_exclusive")
        if lo is not None and value_w < float(lo):
            continue
        if hi is not None and value_w >= float(hi):
            continue
        factor = float(rule.get("factor", 1.0))
        if factor == 1.0:
            continue
        if "raw_par" not in rec:
            rec["raw_E_lx"] = rec.get("E_lx")
            rec["raw_par"] = rec["par"]
            for name in BANDS:
                rec[f"raw_band_{name}"] = rec[f"band_{name}"]
        for name in BANDS:
            rec[f"band_{name}"] *= factor
        if rec.get("E_lx") is not None:
            rec["E_lx"] *= factor
        rec["par"] *= factor
        rec["correction_factor"] = rec.get("correction_factor", 1.0) * factor
        rec.setdefault("correction_ids", []).append(rule.get("id", "unnamed"))
        rec["correction_id"] = "+".join(rec["correction_ids"])
    return rec


def _append_measurement_profiles(recs, folder):
    """Construye perfiles adicionales declarados a partir de capas existentes."""
    path = os.path.join(folder, "measurement_profiles.json")
    if not os.path.exists(path):
        return recs
    with open(path, encoding="utf-8") as fh:
        profiles = json.load(fh).get("profiles", [])
    for profile in profiles:
        source_depths = [float(z) for z in profile["source_depths_m"]]
        weights = np.asarray(profile["weights"], dtype=float)
        weights = weights / weights.sum()
        target_mean = float(profile["target_mean_W_m2"]) * 1000.0
        layers = {
            z: {(r["x"], r["y"]): r for r in recs if np.isclose(r["z"], z)}
            for z in source_depths
        }
        coordinates = set.intersection(*(set(layer) for layer in layers.values()))
        layer_means = {
            z: float(np.mean([layers[z][xy]["par"] for xy in coordinates]))
            for z in source_depths
        }
        for x, y in sorted(coordinates):
            normalized_par = np.asarray([
                layers[z][(x, y)]["par"] / layer_means[z] for z in source_depths
            ])
            rec = {
                "file": f"profile_{profile['id']}_{x:.0f}_{y:.0f}.json",
                "x": float(x),
                "y": float(y),
                "z": float(profile["depth_m"]),
                "par": target_mean * float(np.dot(weights, normalized_par)),
                "source": "profile",
                "profile_id": profile["id"],
            }
            for field in ["E_lx", *(f"band_{name}" for name in BANDS)]:
                values = []
                for z in source_depths:
                    value = layers[z][(x, y)].get(field)
                    values.append(0.0 if value is None else value / layer_means[z])
                rec[field] = target_mean * float(np.dot(weights, values))
            rec["censored"] = rec["par"] <= 0.0
            recs.append(rec)
    return recs


# Factor lux -> PAR [mW/m2 por lx], calibrado sobre los 35 archivos con espectro de
# Punta Iglesia (corr log-log E_lx vs PAR = 0.999; mediana 4.949, 10-90% 4.66-5.31).
# Se usa SOLO para archivos de formato resumen (sin espectro), donde se reconstruye
# el PAR y las bandas a partir de E(lx) y los ratios R/G/B del propio archivo.
LUX_TO_PAR = 4.949


def _read_summary(fn):
    """Lee un CSV de formato RESUMEN (2 lineas: cabecera + datos), sin espectro.
    Devuelve dict con E_lx, PAR reconstruido y bandas via ratios R/G/B, o None."""
    lines = open(fn, encoding="latin-1").read().splitlines()
    if len(lines) < 2:
        return None
    hdr = lines[0].split(","); dat = lines[1].split(",")
    d = dict(zip(hdr, dat))
    def num(key, default=0.0):
        try:
            return float(d.get(key, default))
        except (ValueError, TypeError):
            return default
    E = num("E(lx)")
    par = LUX_TO_PAR * E
    # Fracciones espectrales del propio instrumento (suman ~100).
    fr = {"blue": num("B ratio(%)") / 100.0,
          "green": num("G ratio(%)") / 100.0,
          "red": num("R ratio(%)") / 100.0}
    bands = {name: par * fr[name] for name in BANDS}
    return {"E_lx": E, "par": par, "bands": bands}


def load_measurements(folder):
    """Parsea todos los CSV de `folder` (formato espectral o resumen). Cada registro
    incluye `source` = 'spectrum' (bandas integradas) o 'summary' (bandas reconstruidas
    desde E(lx) y ratios R/G/B)."""
    recs = []
    correction_rules = _load_correction_rules(folder)
    for fn in sorted(glob.glob(os.path.join(folder, "*.csv"))):
        xyz = parse_name(fn)
        if xyz is None:
            continue
        x, y, z = xyz
        first = open(fn, encoding="latin-1").readline()
        wide = len(first.split(",")) > 5
        if wide:
            s = _read_summary(fn)
            if s is None:
                continue
            rec = {"file": os.path.basename(fn), "x": float(x), "y": float(y),
                   "z": float(z), "E_lx": s["E_lx"], "par": s["par"],
                   "source": "summary"}
            for name in BANDS:
                rec[f"band_{name}"] = s["bands"][name]
        else:
            E, wl, spec = _read_csv(fn)
            if wl.size == 0:
                continue
            rec = {"file": os.path.basename(fn), "x": float(x), "y": float(y),
                   "z": float(z), "E_lx": E, "par": _integrate(wl, spec, *PAR_RANGE),
                   "source": "spectrum"}
            for name, (lo, hi) in BANDS.items():
                rec[f"band_{name}"] = _integrate(wl, spec, lo, hi)
        rec = _apply_correction_rules(rec, correction_rules)
        rec["censored"] = rec["par"] <= 0.0
        recs.append(rec)
    return _append_measurement_profiles(recs, folder)


if __name__ == "__main__":
    import sys
    folder = sys.argv[1] if len(sys.argv) > 1 else "../measurements/puntaiglesiaa"
    recs = load_measurements(folder)
    print(f"{len(recs)} mediciones parseadas de {folder}")
    hdr = f"{'x':>3}{'y':>4}{'z':>4} {'PAR':>9} {'blue':>8} {'green':>8} {'red':>8}  cens"
    print(hdr)
    for r in sorted(recs, key=lambda d: (d["x"], d["y"], d["z"])):
        print(f"{r['x']:>3.0f}{r['y']:>4.0f}{r['z']:>4.0f} {r['par']:>9.3f} "
              f"{r['band_blue']:>8.3f} {r['band_green']:>8.3f} {r['band_red']:>8.3f}  "
              f"{'Y' if r['censored'] else ''}")
