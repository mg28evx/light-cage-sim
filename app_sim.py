from flask import Flask, render_template, jsonify, request
import os
import json
import re
import numpy as np
from scipy.interpolate import RegularGridInterpolator, make_interp_spline

try:
    trapz_func = np.trapezoid
except AttributeError:
    trapz_func = np.trapz

from simulation_engine import (
    SimulationEngine, bio_optical_iop, bio_optical_iop_ras_bardsnes,
    ras_tss_from_turbidity, c_from_kd, kd_from_iop,
    hg_backscatter_fraction, subsurface_reflectance,
    secchi_preisendorfer, secchi_lee2015, secchi_poole_atkins, kd_lee2005,
    cie_cmf, hue_angle_from_xyz,
)
from optical_lookup import build_optical_presets, build_optical_weekly_profile, load_centers
from optical_sources import get_source_status
import plotter
from biooptical_analysis import (
    analysis_defaults, build_outputs, configure_volume_tally,
    summarize_volume_tally, validate_analysis_config, volume_grid_rows,
)

app = Flask(__name__)
engine = SimulationEngine()

UPLOAD_FOLDER = './uploaded_lamps'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def sanitize_filename(name):
    clean = re.sub(r'[\s\.,\-]+', '_', str(name).lower())
    clean = re.sub(r'_+', '_', clean)
    return clean.strip('_')


def _sorted_numeric_dict_arrays(values_dict, default_wls=None, default_vals=None):
    if values_dict:
        keys = sorted(values_dict.keys(), key=lambda x: float(x))
        return (
            np.array([float(k) for k in keys], dtype=float),
            np.array([float(values_dict[k]) for k in keys], dtype=float),
        )
    return (
        np.array(default_wls if default_wls is not None else [500.0], dtype=float),
        np.array(default_vals if default_vals is not None else [0.0], dtype=float),
    )


def _round_array(values, ndigits=6):
    return [round(float(v), ndigits) for v in np.asarray(values, dtype=float)]


def _active_backscatter_ratio(optics, g_value):
    phase_function = str(optics.get('phase_function', 'hg')).lower()
    if phase_function == 'fournier_forand' and optics.get('bb_ratio') is not None:
        return float(optics.get('bb_ratio'))
    return hg_backscatter_fraction(g_value)


def build_optical_diagnostics(config, optics_mode, mc_input_type, atten_coef_type, kd_val):
    """Build a compact spectral IOP/AOP audit trail for the active optical setup.

    The returned values are diagnostics: they expose the assumptions used to turn
    sparse operational inputs (c, Kd, TSS, CDOM, Chl-a, omega) into the IOPs that
    matter for scalar radiative transfer.
    """
    optics = config.get('optics', {})
    wls = np.array([400.0, 450.0, 490.0, 500.0, 550.0, 600.0, 650.0, 700.0])
    g_value = float(optics.get('g', 0.85))
    omega_default = float(optics.get('omega', 0.8))
    kd_closure = str(optics.get('kd_closure', 'kirk')).lower()
    bb_ratio = _active_backscatter_ratio(optics, g_value)
    inferred_from = "unknown"

    if optics_mode == 'scattering' and mc_input_type == 'bio':
        a, b = bio_optical_iop(
            wls,
            tss=float(optics.get('tss', 15.0)),
            cdom_a440=float(optics.get('cdom_a440', 1.0)),
            chl=float(optics.get('chl', 0.0)),
        )
        c = a + b
        omega = b / (c + 1e-12)
        transport_coef = c
        transport_label = "c(lambda) directo desde a+b"
        inferred_from = "bio_optical_iop"
    elif optics_mode == 'scattering' and mc_input_type == 'json':
        c_wls, c_vals = _sorted_numeric_dict_arrays(
            optics.get('c_json', {}), default_wls=[500.0], default_vals=[0.5]
        )
        o_wls, o_vals = _sorted_numeric_dict_arrays(
            optics.get('omega_json', {}), default_wls=[500.0], default_vals=[omega_default]
        )
        c = np.interp(wls, c_wls, c_vals)
        omega = np.clip(np.interp(wls, o_wls, o_vals), 0.0, 0.999999)
        b = c * omega
        a = c - b
        transport_coef = c
        transport_label = "c(lambda) manual"
        inferred_from = "manual_c_omega"
    elif optics_mode == 'scattering' and mc_input_type == 'ras_bardsnes':
        tss_r = optics.get('tss', None)
        turb_r = optics.get('turbidity_ntu', None)
        if tss_r in (None, '') and turb_r not in (None, ''):
            tss_r = ras_tss_from_turbidity(turb_r)
        tss_r = float(tss_r if tss_r not in (None, '') else 15.0)
        a, b = bio_optical_iop_ras_bardsnes(
            wls,
            tss=tss_r,
            cdom_a440=float(optics.get('cdom_a440', 1.0)),
            chl=float(optics.get('chl', 0.0)),
            bstar_550=float(optics.get('ras_bstar_550', 0.31)),
            omega_p=float(optics.get('ras_omega_p', 0.90)),
            eta_p=float(optics.get('ras_eta_p', 1.8)),
            s_cdom=float(optics.get('ras_s_cdom', 0.0141)),
        )
        c = a + b
        omega = b / (c + 1e-12)
        transport_coef = c
        transport_label = "c(lambda) RAS directo desde a+b"
        inferred_from = "bio_optical_iop_ras_bardsnes"
    elif optics_mode == 'scattering':
        c = np.full_like(wls, float(optics.get('c', kd_val if kd_val else 0.5)))
        omega = np.full_like(wls, omega_default)
        b = c * omega
        a = c - b
        transport_coef = c
        transport_label = "c escalar"
        inferred_from = "scalar_c_omega"
    elif optics_mode == 'kd_espectral':
        k_wls, k_vals = _sorted_numeric_dict_arrays(
            optics.get('kd_spectral', {}), default_wls=[500.0], default_vals=[0.2]
        )
        vals = np.interp(wls, k_wls, k_vals)
        if atten_coef_type == 'kd':
            c, a, b = c_from_kd(vals, omega=omega_default, g=g_value, mu_d=0.85)
            omega = b / (c + 1e-12)
            transport_coef = vals
            transport_label = "Kd(lambda) ingresado; c,a,b inferidos"
            inferred_from = "inverse_kirk_from_kd_spectral"
        else:
            c = vals
            omega = np.full_like(wls, omega_default)
            b = c * omega
            a = c - b
            transport_coef = c
            transport_label = "c(lambda) ingresado; a,b inferidos desde omega"
            inferred_from = "c_spectral_plus_assumed_omega"
    else:
        vals = np.full_like(wls, float(kd_val))
        if atten_coef_type == 'kd':
            c, a, b = c_from_kd(vals, omega=omega_default, g=g_value, mu_d=0.85)
            omega = b / (c + 1e-12)
            transport_coef = vals
            transport_label = "Kd fijo ingresado; c,a,b inferidos"
            inferred_from = "inverse_kirk_from_kd_fixed"
        else:
            c = vals
            omega = np.full_like(wls, omega_default)
            b = c * omega
            a = c - b
            transport_coef = c
            transport_label = "c fijo ingresado; a,b inferidos desde omega"
            inferred_from = "c_fixed_plus_assumed_omega"

    bb = bb_ratio * b
    kd_kirk = kd_from_iop(a, b, g=g_value, mu_d=0.85)
    kd_lee = kd_lee2005(a, bb)
    kd_active = kd_lee if kd_closure == 'lee2005' else kd_kirk

    return {
        "wavelength_nm": _round_array(wls, 1),
        "a_m_inv": _round_array(a),
        "b_m_inv": _round_array(b),
        "c_m_inv": _round_array(c),
        "omega0": _round_array(omega),
        "bb_m_inv": _round_array(bb),
        "bb_ratio": round(float(bb_ratio), 6),
        "kd_kirk_m_inv": _round_array(kd_kirk),
        "kd_lee2005_m_inv": _round_array(kd_lee),
        "kd_active_m_inv": _round_array(kd_active),
        "transport_coefficient": _round_array(transport_coef),
        "transport_label": transport_label,
        "inferred_from": inferred_from,
        "phase_function": str(optics.get('phase_function', 'hg')).lower(),
        "g": round(float(g_value), 6),
        "kd_closure": kd_closure,
        "atten_coef_type": atten_coef_type,
        "model_note": (
            "a,b,c,omega son directos solo en modo bio-optico o manual c/omega; "
            "en modos c/Kd escalares se infieren con omega y g asumidos."
        ),
    }


def _prepare_engine_config_for_bio(config, analysis_config):
    config = json.loads(json.dumps(config))
    if 'optics' not in config:
        config['optics'] = {}
    optics_mode = config.get('optics_mode', config['optics'].get('mode', 'kd_fijo'))
    config['optics']['mode'] = optics_mode
    if optics_mode == 'kd_fijo':
        kd_list = config.get('kd_list') or [config['optics'].get('kd_fijo', 0.2)]
        config['optics']['kd_fijo'] = float(kd_list[0])
    for lamp in config.get('lamps', []):
        req_power = float(lamp.get('power', 0.0))
        lamp['dim'] = 0.0 if req_power <= 0.0 else 1.0
    configure_volume_tally(config, analysis_config)
    return config


def _scenario_id_from_payload(config, fallback='scenario'):
    raw = config.get('bio_analysis', {}).get('scenario_id') or config.get('project_title') or fallback
    return sanitize_filename(raw) or fallback


def _unique_scenario_id(raw_id, existing_ids, fallback):
    base = sanitize_filename(raw_id or fallback) or fallback
    candidate = base
    suffix = 2
    while candidate in existing_ids:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate

@app.route('/')
def index():
    return render_template('simulation.html')

@app.route('/api/upload_lamp', methods=['POST'])
def upload_lamp():
    if 'file' not in request.files: return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '': return jsonify({"error": "No selected file"}), 400

    if file:
        filename = file.filename
        content = file.read().decode('utf-8', errors='ignore')
        success = engine.load_file(filename, content)
        if success:
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            with open(filepath, 'w', encoding='utf-8') as f: f.write(content)
            return jsonify({"status": "ok", "filename": filename, "msg": "Lámpara cargada exitosamente"})
        else:
            return jsonify({"status": "error", "msg": "El archivo no es válido"}), 500

@app.route('/api/get_lamps', methods=['GET'])
def get_lamps():
    if not os.path.exists(UPLOAD_FOLDER): return jsonify({"status": "ok", "lamps": []})
    lamps = [f for f in os.listdir(UPLOAD_FOLDER) if f.lower().endswith('.xml') or f.lower().endswith('.ies')]
    return jsonify({"status": "ok", "lamps": lamps})

@app.route('/api/lamp_profile/<filename>')
def lamp_profile(filename):
    try:
        parser = engine.parsers.get(filename)
        if not parser:
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    engine.load_file(filename, f.read())
                parser = engine.parsers.get(filename)
        
        if not parser: return jsonify({"error": "Lámpara no encontrada en memoria"})
        
        theta_arr = np.linspace(0, 180, 73)
        v_rad = np.radians(theta_arr)
        
        c0 = np.column_stack((np.sin(v_rad), np.zeros_like(v_rad), -np.cos(v_rad)))
        c180 = np.column_stack((-np.sin(v_rad), np.zeros_like(v_rad), -np.cos(v_rad)))
        c90 = np.column_stack((np.zeros_like(v_rad), np.sin(v_rad), -np.cos(v_rad)))
        c270 = np.column_stack((np.zeros_like(v_rad), -np.sin(v_rad), -np.cos(v_rad)))
        
        _, rad0 = parser.get_intensity(c0)
        _, rad180 = parser.get_intensity(c180)
        _, rad90 = parser.get_intensity(c90)
        _, rad270 = parser.get_intensity(c270)
        
        max_rad = max(np.max(rad0), np.max(rad180), np.max(rad90), np.max(rad270))
        if max_rad == 0: max_rad = 1.0
        
        plane_0_180_theta = np.concatenate((theta_arr, -theta_arr[::-1]))
        plane_0_180_rad = np.concatenate((rad0, rad180[::-1])) / max_rad
        plane_90_270_theta = np.concatenate((theta_arr, -theta_arr[::-1]))
        plane_90_270_rad = np.concatenate((rad90, rad270[::-1])) / max_rad

        # --- Grilla 3D para visualización del beam (azimut x polar)
        # Muestreamos en (h, v) con h en [0, 360) y v en [0, 180] (cenit→nadir)
        n_h = 48
        n_v = 49
        h_arr = np.linspace(0, 360, n_h, endpoint=False)
        v_arr = np.linspace(0, 180, n_v)
        H, V = np.meshgrid(h_arr, v_arr, indexing='ij')
        # Convertir a vectores cartesianos: theta = v (polar desde el +z lampara mira -z)
        v_r = np.radians(V.ravel())
        h_r = np.radians(H.ravel())
        sx = np.sin(v_r) * np.cos(h_r)
        sy = np.sin(v_r) * np.sin(h_r)
        sz = -np.cos(v_r)
        sphere_vecs = np.column_stack((sx, sy, sz))
        _, rad_sphere = parser.get_intensity(sphere_vecs)
        rad_sphere = np.array(rad_sphere).reshape(n_h, n_v)
        max_sphere = float(np.max(rad_sphere)) if np.max(rad_sphere) > 0 else 1.0
        rad_sphere_norm = (rad_sphere / max_sphere).tolist()

        elec_pwr = getattr(parser, 'get_electrical_power', lambda: None)()
        rad_pwr = getattr(parser, 'get_radiant_power', lambda: None)()
        eff = 1.0
        if elec_pwr and rad_pwr and elec_pwr > 0:
            eff = rad_pwr / elec_pwr

        return jsonify({
            "c0_180": {"theta": plane_0_180_theta.tolist(), "rad": plane_0_180_rad.tolist()},
            "c90_270": {"theta": plane_90_270_theta.tolist(), "rad": plane_90_270_rad.tolist()},
            "sphere_grid": {
                "h_deg": h_arr.tolist(),
                "v_deg": v_arr.tolist(),
                "rad_norm": rad_sphere_norm,
                "max_rad": max_sphere
            },
            "elec_power": elec_pwr,
            "rad_power": rad_pwr,
            "efficiency": eff
        })
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/api/calc_kd', methods=['POST'])
def calc_kd():
    try:
        data = request.json
        target_x, target_y = float(data['x']), float(data['y'])
        measurements = data['measurements']
        
        pts = [m for m in measurements if abs(m['x'] - target_x) < 0.1 and abs(m['y'] - target_y) < 0.1]
        pts.sort(key=lambda p: float(p['z']))
        
        results = []
        for i in range(len(pts)):
            for j in range(i+1, len(pts)):
                z1, val1 = float(pts[i]['z']), float(pts[i]['val'])
                z2, val2 = float(pts[j]['z']), float(pts[j]['val'])
                if val1 > 0 and val2 > 0 and abs(z2 - z1) > 0.001:
                    kd = (np.log(val1) - np.log(val2)) / abs(z2 - z1)
                    results.append({"z1": z1, "val1": val1, "z2": z2, "val2": val2, "kd": kd})
        return jsonify({"status": "ok", "kds": results})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/api/optical_presets', methods=['GET', 'POST'])
def optical_presets():
    try:
        payload = request.json if request.method == 'POST' else request.args
        result = build_optical_presets(
            center=payload.get('center'),
            lat=payload.get('lat'),
            lon=payload.get('lon'),
            water_class=payload.get('water_class'),
            observations_path=payload.get('observations_path'),
            source=payload.get('source', 'auto'),
            start_date=payload.get('start_date'),
            end_date=payload.get('end_date'),
            buffer_m=float(payload.get('buffer_m', 1000) or 1000),
            fnu_to_tss_slope=payload.get('fnu_to_tss_slope'),
            fnu_to_tss_intercept=payload.get('fnu_to_tss_intercept'),
        )
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/api/optical_centers', methods=['GET'])
def optical_centers():
    try:
        centers_by_key = load_centers()
        centers = {}
        for center in centers_by_key.values():
            centers[center.center_id] = {
                "center_id": center.center_id,
                "name": center.name,
                "lat": center.lat,
                "lon": center.lon,
                "water_class": center.water_class,
                "notes": center.notes,
            }
        return jsonify({"status": "ok", "centers": sorted(centers.values(), key=lambda c: c["name"])})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/api/optical_weekly_profile', methods=['GET', 'POST'])
def optical_weekly_profile():
    try:
        payload = request.json if request.method == 'POST' else request.args
        result = build_optical_weekly_profile(
            center=payload.get('center'),
            lat=payload.get('lat'),
            lon=payload.get('lon'),
            water_class=payload.get('water_class'),
            observations_path=payload.get('observations_path'),
            source=payload.get('source', 'auto'),
            buffer_m=float(payload.get('buffer_m', 1000) or 1000),
            years_back=int(payload.get('years_back', 3) or 3),
            target_year=payload.get('target_year'),
            target_week=payload.get('target_week'),
            fnu_to_tss_slope=payload.get('fnu_to_tss_slope'),
            fnu_to_tss_intercept=payload.get('fnu_to_tss_intercept'),
        )
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/api/optical_sources/status', methods=['GET'])
def optical_sources_status():
    return jsonify({"status": "ok", "sources": get_source_status()})

@app.route('/api/run_simulation', methods=['POST'])
def run_simulation():
    try:
        config = request.json
        env_dict = config.get('env', {})
        
        project_title = config.get('project_title', 'Proyecto Evolux')
        clean_title = sanitize_filename(project_title)
        
        raw_x = env_dict.get('x')
        raw_y = env_dict.get('y')
        raw_z = env_dict.get('z')
        raw_radio = env_dict.get('radio')
        raw_z_int = env_dict.get('z_interface')
        
        env_x = float(raw_x) if raw_x is not None else 40.0
        env_y = float(raw_y) if raw_y is not None else 40.0
        env_z = float(raw_z) if raw_z is not None else 15.0
        env_radio = float(raw_radio) if raw_radio is not None else env_x / 2.0
        z_interface = float(raw_z_int) if raw_z_int is not None else 3.2
        
        center_x, center_y = env_x / 2.0, env_y / 2.0
        env_type = env_dict.get('type', 'estanque')
        env_shape = env_dict.get('shape', 'circle' if env_type == 'estanque' else 'rect')
        
        env_plot_dict = {
            'type': env_type, 'shape': env_shape, 'x': env_x, 'y': env_y,
            'radio': env_radio, 'center_x': center_x, 'center_y': center_y, 'z_interface': z_interface
        }
        
        roi = config.get('roi', {'type': 'global'})
        contour_val = float(config.get('contour_val', 0.017))
        target_depths_requested = sorted([float(d) for d in config.get('target_depths', []) if d is not None], reverse=True)
        
        optics_mode = config.get('optics_mode', 'kd_fijo')
        if 'optics' not in config:
            config['optics'] = {}
        mc_input_type = config['optics'].get('mc_input_type', 'scalar')
        # Tipo de coeficiente para los modos fijo/espectral: 'c' (atenuación de haz)
        # o 'Kd' (atenuación difusa por desplazamiento vertical). Default 'c' por compat.
        atten_coef_type = str(config['optics'].get('atten_coef_type', 'c')).lower()
        config['optics']['atten_coef_type'] = atten_coef_type
        coef_label = 'Kd' if atten_coef_type == 'kd' else 'c'

        if optics_mode == 'kd_fijo':
            kd_val = float(config.get('kd_list', [0.2])[0])
            optics_suffix = f"{coef_label.lower()}fijo_{sanitize_filename(kd_val)}"
            optics_title = f"{coef_label} Fijo: {kd_val} 1/m"
            config['optics']['kd_fijo'] = kd_val
        elif optics_mode == 'kd_espectral':
            kd_val = 0.0
            optics_suffix = f"{coef_label.lower()}_espect"
            optics_title = f"{coef_label} Espectral"
        elif optics_mode == 'scattering':
            if mc_input_type == 'scalar':
                kd_val = float(config['optics'].get('c', 0.5))
                optics_suffix = f"c_{sanitize_filename(kd_val)}"
                optics_title = f"Atenuación Escalar c={kd_val}"
                config['optics']['c'] = kd_val
            elif mc_input_type == 'bio':
                kd_val = 0.0
                tss = config['optics'].get('tss', 15.0)
                cdom = config['optics'].get('cdom_a440', 1.0)
                chl = config['optics'].get('chl', 0.0)
                optics_suffix = f"bio_cdom_{sanitize_filename(cdom)}_tss_{sanitize_filename(tss)}_chl_{sanitize_filename(chl)}"
                optics_title = f"Bio-Óptico Espectral (TSS: {tss}mg/L, CDOM(440): {cdom}, Chl-a: {chl}mg/m³)"
            elif mc_input_type == 'ras_bardsnes':
                kd_val = 0.0
                turb = config['optics'].get('turbidity_ntu', None)
                tss = config['optics'].get('tss', None)
                if tss in (None, '') and turb not in (None, ''):
                    tss = round(max(3.0411 * float(turb) - 0.376, 0.0), 3)
                    config['optics']['tss'] = tss
                if tss in (None, ''):
                    tss = 15.0
                cdom = config['optics'].get('cdom_a440', 1.0)
                optics_suffix = f"ras_bardsnes_tss_{sanitize_filename(tss)}_cdom_{sanitize_filename(cdom)}"
                optics_title = f"RAS Bårdsnes 2020 (TSS: {tss}mg/L, CDOM(440): {cdom})"
            else:
                kd_val = 0.0
                optics_suffix = "scat_json"
                optics_title = "Dispersión Espectral Manual"
        else:
            kd_val = 0.0
            optics_suffix = "default"
            optics_title = "Parámetros por defecto"

        aporte_puntos = config.get('aporte_puntos', [])
        if roi['type'] in ['paralelepipedo', 'cilindro']:
            roi_cz = float(roi.get('cz', 0.0))
            roi_h = float(roi.get('h', 0.0))
            calc_min_z = max(0, roi_cz - roi_h / 2.0)
            calc_max_z = roi_cz + roi_h / 2.0
        else:
            calc_min_z = 0.0
            calc_max_z = z_interface if env_type == 'estanque' else env_z
            
        profile_step = max(float(config.get('profile_step', 0.5)), 1e-6)
        prof_d = np.arange(calc_min_z, calc_max_z + profile_step * 0.5, profile_step)
        prof_d = prof_d[prof_d <= calc_max_z + 1e-9]
        if len(prof_d) == 0 or abs(float(prof_d[-1]) - calc_max_z) > 1e-9:
            prof_d = np.append(prof_d, calc_max_z)
        
        all_depths_set = set(target_depths_requested)
        has_volume_roi = roi['type'] in ['paralelepipedo', 'cilindro']
        if config.get('plot_depth_profile') or has_volume_roi:
            all_depths_set.update(prof_d.tolist())
            
        all_depths_requested = sorted(list(all_depths_set), reverse=True)
        config['target_depths'] = all_depths_requested
        
        for lamp in config.get('lamps', []):
            req_power = float(lamp.get('power', 0.0))
            if req_power <= 0.0: lamp['dim'] = 0.0 
            else: lamp['dim'] = 1.0

        table_data = []
        spectrum_results = {}
        lamps_names = [lamp['xml'] for lamp in config.get('lamps', [])]
        
        if config.get('plot_spectrum_initial'):
            ranges = config.get('spectrum_ranges', {'blue': [400, 499], 'green': [500, 599], 'red': [600, 750]})
            for xml_name in config.get('spectrum_lamps', []):
                parser = engine.parsers.get(xml_name)
                if parser and parser.get_spectrum():
                    wls = np.array(sorted(parser.get_spectrum().keys()))
                    pwrs = np.array([parser.get_spectrum()[w] for w in wls])
                    spectrum_results[f"Espectro Inicial ({xml_name})"] = plotter.plot_initial_spectrum(xml_name, wls, pwrs, ranges)

        optical_diagnostics = build_optical_diagnostics(
            config, optics_mode, mc_input_type, atten_coef_type, kd_val
        )
        kd_res = {
            "depths": {},
            "combined_image": "",
            "comparison_image": "",
            "depth_profile_image": "",
            "env_optics_image": "",
            "aportes": [],
            "depth_table": [],
            "optical_diagnostics": optical_diagnostics,
        }

        config['optics']['mode'] = optics_mode
        bio_analysis_cfg = analysis_defaults(config.get('bio_analysis', {}))
        bio_analysis_enabled = bool(bio_analysis_cfg.get('enabled'))
        if bio_analysis_enabled:
            configure_volume_tally(config, bio_analysis_cfg)
            all_depths_requested = sorted([float(d) for d in config.get('target_depths', all_depths_requested)], reverse=True)

        if config.get('plot_env_optics'):
            wls_env = np.linspace(380, 780, 400)
            kd_env_plot = np.zeros_like(wls_env)

            if optics_mode == 'kd_fijo':
                kd_env_plot = np.full_like(wls_env, kd_val)
                y_label_env = f"{coef_label} Fijo [1/m]"
            elif optics_mode == 'kd_espectral':
                kd_spectral_dict = config['optics'].get('kd_spectral', {})
                if kd_spectral_dict:
                    kd_wls = np.array([float(k) for k in sorted(kd_spectral_dict.keys())])
                    kd_vals = np.array([float(kd_spectral_dict[k]) for k in sorted(kd_spectral_dict.keys())])
                    if len(kd_wls) > 0: kd_env_plot = np.interp(wls_env, kd_wls, kd_vals)
                y_label_env = f"{coef_label} Espectral [1/m]"
            elif optics_mode == 'scattering':
                if mc_input_type == 'scalar':
                    kd_env_plot = np.full_like(wls_env, kd_val)
                    y_label_env = "Atenuación del haz (c) [1/m]"
                elif mc_input_type == 'bio':
                    tss_val = float(config['optics'].get('tss', 15.0))
                    a440_val = float(config['optics'].get('cdom_a440', 1.0))
                    chl_v = float(config['optics'].get('chl', 0.0))
                    a_env, b_env = bio_optical_iop(wls_env, tss=tss_val, cdom_a440=a440_val, chl=chl_v)
                    kd_env_plot = a_env + b_env
                    y_label_env = "Atenuación del haz (c = a+b) [1/m]"
                elif mc_input_type == 'ras_bardsnes':
                    turb_env = config['optics'].get('turbidity_ntu', None)
                    tss_env = config['optics'].get('tss', None)
                    if tss_env in (None, '') and turb_env not in (None, ''):
                        tss_env = ras_tss_from_turbidity(turb_env)
                    tss_env = float(tss_env if tss_env not in (None, '') else 15.0)
                    a440_env = float(config['optics'].get('cdom_a440', 1.0))
                    chl_env = float(config['optics'].get('chl', 0.0))
                    a_env, b_env = bio_optical_iop_ras_bardsnes(
                        wls_env, tss=tss_env, cdom_a440=a440_env, chl=chl_env,
                        bstar_550=float(config['optics'].get('ras_bstar_550', 0.31)),
                        omega_p=float(config['optics'].get('ras_omega_p', 0.90)),
                        eta_p=float(config['optics'].get('ras_eta_p', 1.8)),
                        s_cdom=float(config['optics'].get('ras_s_cdom', 0.0141)),
                    )
                    kd_env_plot = a_env + b_env
                    y_label_env = "Atenuación del haz RAS (c = a+b) [1/m]"
                elif mc_input_type == 'json':
                    c_dict = config['optics'].get('c_json', {})
                    if c_dict:
                        c_wls = np.array([float(k) for k in sorted(c_dict.keys())])
                        c_vals = np.array([float(c_dict[k]) for k in sorted(c_dict.keys())])
                        if len(c_wls) > 0: kd_env_plot = np.interp(wls_env, c_wls, c_vals)
                    y_label_env = "Atenuación del haz (c) [1/m]"

            kd_res["env_optics_image"] = plotter.plot_env_optics(wls_env, kd_env_plot, optics_title, y_label_env)
        
        if config.get('plot_spectrum_normalized'):
            for xml_name in config.get('spectrum_lamps', []):
                parser = engine.parsers.get(xml_name)
                if parser and parser.get_spectrum():
                    wls = np.array(sorted(parser.get_spectrum().keys()))
                    pwrs = np.array([parser.get_spectrum()[w] for w in wls])

                    kd_interp_plot = np.zeros_like(wls)
                    if optics_mode == 'kd_fijo':
                        kd_interp_plot = np.full_like(wls, kd_val)
                    elif optics_mode == 'kd_espectral':
                        kd_dict = config['optics'].get('kd_spectral', {})
                        if kd_dict:
                            k_wls = np.array([float(k) for k in sorted(kd_dict.keys())])
                            k_vals = np.array([float(kd_dict[k]) for k in sorted(kd_dict.keys())])
                            if len(k_wls) > 0: kd_interp_plot = np.interp(wls, k_wls, k_vals)
                    elif optics_mode == 'scattering':
                        if mc_input_type == 'scalar':
                            kd_interp_plot = np.full_like(wls, kd_val)
                        elif mc_input_type == 'bio':
                            tss_v = float(config['optics'].get('tss', 15.0))
                            a44_v = float(config['optics'].get('cdom_a440', 1.0))
                            chl_v = float(config['optics'].get('chl', 0.0))
                            a_ray, b_ray = bio_optical_iop(wls, tss=tss_v, cdom_a440=a44_v, chl=chl_v)
                            kd_interp_plot = a_ray + b_ray
                        elif mc_input_type == 'ras_bardsnes':
                            tss_v = config['optics'].get('tss', None)
                            turb_v = config['optics'].get('turbidity_ntu', None)
                            if tss_v in (None, '') and turb_v not in (None, ''):
                                tss_v = ras_tss_from_turbidity(turb_v)
                            tss_v = float(tss_v if tss_v not in (None, '') else 15.0)
                            a44_v = float(config['optics'].get('cdom_a440', 1.0))
                            chl_v = float(config['optics'].get('chl', 0.0))
                            a_ray, b_ray = bio_optical_iop_ras_bardsnes(
                                wls, tss=tss_v, cdom_a440=a44_v, chl=chl_v,
                                bstar_550=float(config['optics'].get('ras_bstar_550', 0.31)),
                                omega_p=float(config['optics'].get('ras_omega_p', 0.90)),
                                eta_p=float(config['optics'].get('ras_eta_p', 1.8)),
                                s_cdom=float(config['optics'].get('ras_s_cdom', 0.0141)),
                            )
                            kd_interp_plot = a_ray + b_ray
                        elif mc_input_type == 'json':
                            c_dict = config['optics'].get('c_json', {})
                            if c_dict:
                                c_wls = np.array([float(k) for k in sorted(c_dict.keys())])
                                c_vals = np.array([float(c_dict[k]) for k in sorted(c_dict.keys())])
                                if len(c_wls) > 0: kd_interp_plot = np.interp(wls, c_wls, c_vals)

                    lamp_z_ref = 0.0
                    for l_conf in config.get('lamps', []):
                        if l_conf.get('xml') == xml_name:
                            lamp_z_ref = float(l_conf.get('z', 0))
                            break
                            
                    ref_z = lamp_z_ref if env_type == 'estanque' else -lamp_z_ref
                    spectrum_results[f"Atenuación Normalizada ({xml_name})"] = plotter.plot_normalized_shift(xml_name, wls, pwrs, kd_interp_plot, target_depths_requested, ref_z, env_type)

        raw_results = engine.run(config)
        bio_analysis_result = None
        if bio_analysis_enabled:
            if engine.last_volume_tally is None:
                raise ValueError("El tally volumétrico bio-óptico no fue generado.")
            scenario_id = _scenario_id_from_payload(config, clean_title)
            layer_rows, _ = summarize_volume_tally(
                engine.last_volume_tally, bio_analysis_cfg, scenario_id, config,
                scenario_meta=config.get('bio_analysis', {})
            )
            grid_rows = volume_grid_rows(engine.last_volume_tally, scenario_id) if bio_analysis_cfg.get('grid_cells_csv') else []
            bio_analysis_result = build_outputs({scenario_id: layer_rows}, bio_analysis_cfg, grid_rows=grid_rows)
        
        bins = 100
        grid_x = np.linspace(0, env_x, bins)
        grid_y = np.linspace(0, env_y, bins)
        X, Y = np.meshgrid((grid_x[:-1]+grid_x[1:])/2, (grid_y[:-1]+grid_y[1:])/2)
        x_centers, y_centers = (grid_x[:-1] + grid_x[1:]) / 2, (grid_y[:-1] + grid_y[1:]) / 2
        area_bin = (grid_x[1]-grid_x[0]) * (grid_y[1]-grid_y[0])
        label_area_base = "Vol. ROI" if roi['type'] != 'global' else ("Estanque" if env_type == 'estanque' else "Area Total")

        layer_stats = []
        max_irr_all, min_irr_all = -1, 999999
        comp_z, comp_meas, comp_sim = [], [], []
        target_heatmaps = []

        for depth_val in all_depths_requested:
            depth_str = str(depth_val)
            data = None
            for k in raw_results.keys():
                if abs(float(k) - depth_val) < 0.01:
                    data = raw_results[k]
                    break
            
            is_target = any(abs(depth_val - td) < 1e-4 for td in target_depths_requested)

            has_hits = data is not None and bool(data['x'])
            if has_hits:
                pts = np.column_stack((data['x'], data['y']))
                vals_hit = np.array(data['val'])
                lamp_idxs = np.array(data.get('lamp_idx', []))
                wls_hit = np.array(data.get('wl', []))
            else:
                pts = np.empty((0, 2), dtype=float)
                vals_hit = np.array([], dtype=float)
                lamp_idxs = np.array([], dtype=int)
                wls_hit = np.array([], dtype=float)

            sum_val = np.sum(vals_hit)
            if sum_val > 0 and len(wls_hit) > 0:
                L_um = wls_hit / 1000.0
                V_lambda = 1.019 * np.exp(-285.4 * (L_um - 0.559)**2) - 0.092 * np.exp(-1250.0 * (L_um - 0.450)**2)
                V_lambda = np.clip(V_lambda, 0, 1)
                lux_hits = vals_hit * 683.0 * V_lambda
                ppfd_hits = np.where((wls_hit >= 400) & (wls_hit <= 700), vals_hit * wls_hit / 119.626, 0.0)
                
                f_lux = np.sum(lux_hits) / sum_val
                f_ppfd = np.sum(ppfd_hits) / sum_val
            else:
                f_lux = 0.0
                f_ppfd = 0.0

            H, _, _ = np.histogram2d(pts[:,0], pts[:,1], bins=[grid_x, grid_y], weights=vals_hit)
            E = H.T / area_bin

            mask = np.ones_like(E, dtype=bool)
            z_valid = True
            
            if roi['type'] == 'paralelepipedo':
                cx, cy, cz = float(roi.get('cx', 0)), float(roi.get('cy', 0)), float(roi.get('cz', 0))
                l, w, h = float(roi.get('l', 0)), float(roi.get('w', 0)), float(roi.get('h', 0))
                if abs(depth_val - cz) <= h / 2.0:
                    mask = (np.abs(X - cx) <= l / 2.0) & (np.abs(Y - cy) <= w / 2.0)
                else: z_valid = False; mask = np.zeros_like(E, dtype=bool)
            elif roi['type'] == 'cilindro':
                cx, cy, cz = float(roi.get('cx', 0)), float(roi.get('cy', 0)), float(roi.get('cz', 0))
                r_roi, h = float(roi.get('r', 0)), float(roi.get('h', 0))
                if abs(depth_val - cz) <= h / 2.0:
                    mask = ((X - cx)**2 + (Y - cy)**2) <= r_roi**2
                else: z_valid = False; mask = np.zeros_like(E, dtype=bool)
            else: 
                if env_type != 'estanque' and depth_val > env_z: z_valid = False; mask = np.zeros_like(E, dtype=bool)
                elif env_type == 'estanque' and depth_val > z_interface: z_valid = False; mask = np.zeros_like(E, dtype=bool)
                elif env_shape == 'circle': mask = ((X - center_x)**2 + (Y - center_y)**2) <= env_radio**2
                else: mask = np.ones_like(E, dtype=bool)
            
            area_total_layer = np.sum(mask) * area_bin

            # --- Calidad de luz: ángulo de matiz CIE α_E (Lee et al. 2022) ---
            # Tristímulos por celda (3 histogramas ponderados por las CMF) y matiz.
            alpha_e_layer = None
            alpha_e_roi = None
            hue_grid = None
            if len(wls_hit) > 0 and sum_val > 0:
                _xb, _yb, _zb = cie_cmf(wls_hit)
                HX, _, _ = np.histogram2d(pts[:, 0], pts[:, 1], bins=[grid_x, grid_y], weights=vals_hit * _xb)
                HY, _, _ = np.histogram2d(pts[:, 0], pts[:, 1], bins=[grid_x, grid_y], weights=vals_hit * _yb)
                HZ, _, _ = np.histogram2d(pts[:, 0], pts[:, 1], bins=[grid_x, grid_y], weights=vals_hit * _zb)
                Xg, Yg, Zg = HX.T, HY.T, HZ.T
                a_lay, _ = hue_angle_from_xyz(Xg.sum(), Yg.sum(), Zg.sum())
                alpha_e_layer = None if np.isnan(a_lay) else float(a_lay)
                if z_valid and np.any(mask):
                    a_roi, _ = hue_angle_from_xyz(Xg[mask].sum(), Yg[mask].sum(), Zg[mask].sum())
                    alpha_e_roi = None if np.isnan(a_roi) else float(a_roi)
                if config.get('plot_light_quality'):
                    hue_grid, _ = hue_angle_from_xyz(Xg, Yg, Zg)  # malla por celda

            if z_valid and np.any(mask):
                E_roi = E[mask]
                avg_irr, min_irr, max_irr = np.mean(E_roi), np.min(E_roi), np.max(E_roi)
                area_ilum = np.sum(E_roi >= contour_val) * area_bin
                # Cálculo de FLUJO RADIANTE (Potencia en Watts cruzando el plano ROI)
                flux_w = float(np.sum(E_roi) * area_bin)
                max_irr_all = max(max_irr_all, max_irr)
                min_irr_all = min(min_irr_all, min_irr)
            else:
                avg_irr, min_irr, max_irr, area_ilum, flux_w = 0, 0, 0, 0, 0
            
            if z_valid:
                layer_stats.append({
                    'z': depth_val, 'avg': avg_irr, 'area': area_ilum, 'tot': area_total_layer,
                    'f_lux': f_lux, 'f_ppfd': f_ppfd, 'flux_w': flux_w,
                    'alpha_e': alpha_e_roi if alpha_e_roi is not None else alpha_e_layer
                })

            label_area = label_area_base
            roi_stats = {
                "label": label_area,
                "valid": bool(z_valid and np.any(mask)),
                "avg": float(avg_irr),
                "min": float(min_irr),
                "max": float(max_irr),
                "area": float(area_total_layer),
                "area_ge_threshold": float(area_ilum),
                "alpha_e": alpha_e_roi
            }

            if is_target:
                if config.get('plot_depth_summary_table', True):
                    kd_res["depth_table"].append({
                        "z": depth_val,
                        "flux_w": flux_w,
                        "avg_w": avg_irr, "min_w": min_irr, "max_w": max_irr,
                        "avg_lux": avg_irr * f_lux, "min_lux": min_irr * f_lux, "max_lux": max_irr * f_lux,
                        "avg_ppfd": avg_irr * f_ppfd, "min_ppfd": min_irr * f_ppfd, "max_ppfd": max_irr * f_ppfd,
                        "alpha_e": alpha_e_roi if alpha_e_roi is not None else alpha_e_layer
                    })

                pts_at_depth = [p for p in aporte_puntos if abs(float(p['z']) - depth_val) < 0.1]
                if pts_at_depth:
                    interp_tot = RegularGridInterpolator((x_centers, y_centers), H / area_bin, bounds_error=False, fill_value=0)
                    E_lamps_interp = []
                    for i_lamp in range(len(config.get('lamps', []))):
                        mask_i = (lamp_idxs == i_lamp)
                        if np.any(mask_i):
                            H_i, _, _ = np.histogram2d(pts[mask_i,0], pts[mask_i,1], bins=[grid_x, grid_y], weights=vals_hit[mask_i])
                            E_lamps_interp.append(RegularGridInterpolator((x_centers, y_centers), H_i / area_bin, bounds_error=False, fill_value=0))
                        else: E_lamps_interp.append(None)
                            
                    for p in pts_at_depth:
                        tot_val = float(interp_tot((p['x'], p['y'])))
                        lamp_vals = []
                        for i_lamp, interp_i in enumerate(E_lamps_interp):
                            val_i = float(interp_i((p['x'], p['y']))) if interp_i is not None else 0.0
                            pct = (val_i / tot_val * 100) if tot_val > 0 else 0
                            lamp_vals.append({'lamp_idx': i_lamp, 'val': val_i, 'pct': pct})
                        kd_res["aportes"].append({'x': p['x'], 'y': p['y'], 'z': p['z'], 'total': tot_val, 'lamps': lamp_vals})

            if is_target and config.get('compare_measurements') and config.get('compare_x'):
                m_pts = [m for m in config.get('measurements', []) if abs(m['x'] - config['compare_x']) < 0.1 and abs(m['y'] - config['compare_y']) < 0.1 and abs(float(m['z']) - depth_val) < 0.1]
                if m_pts:
                    interp = RegularGridInterpolator((x_centers, y_centers), H / area_bin, bounds_error=False, fill_value=0)
                    sim_val = interp((config['compare_x'], config['compare_y']))
                    avg_meas_val = np.mean([float(m['val']) for m in m_pts])
                    comp_z.append(depth_val); comp_meas.append(avg_meas_val); comp_sim.append(float(sim_val))

            if is_target:
                target_heatmaps.append({
                    "depth_str": depth_str,
                    "depth_val": depth_val,
                    "E": E,
                    "max_irr": max_irr,
                    "avg_irr": avg_irr,
                    "min_irr": min_irr,
                    "area_ilum": area_ilum,
                    "roi_stats": roi_stats,
                    "hue_grid": hue_grid,
                    "alpha_e_roi": alpha_e_roi,
                })
                kd_res["depths"][depth_str] = {
                    "image": "",
                    "grid": E.tolist(),
                    "x_centers": x_centers.tolist(),
                    "y_centers": y_centers.tolist(),
                    "max": float(max_irr),
                    "avg": float(avg_irr),
                    "min": float(min_irr),
                    "area_ilum": float(area_ilum),
                    "roi_stats": roi_stats,
                    "alpha_e": alpha_e_roi,
                    "hue_image": ""
                }

        valid_stats = [s for s in layer_stats if calc_min_z - 1e-3 <= s['z'] <= calc_max_z + 1e-3]
        valid_stats.sort(key=lambda x: x['z']) 
        
        if len(valid_stats) > 1:
            z_arr = np.array([s['z'] for s in valid_stats])
            area_ilum_arr = np.array([s['area'] for s in valid_stats])
            area_tot_arr = np.array([s['tot'] for s in valid_stats])
            avg_irr_arr = np.array([s['avg'] for s in valid_stats])
            avg_lux_arr = np.array([s['avg'] * s['f_lux'] for s in valid_stats])
            avg_ppfd_arr = np.array([s['avg'] * s['f_ppfd'] for s in valid_stats])
            flux_w_arr = np.array([s['flux_w'] for s in valid_stats])

            vol_ilum_total = float(trapz_func(area_ilum_arr, z_arr))
            vol_tot_total = float(trapz_func(area_tot_arr, z_arr))

            vol_pct = (vol_ilum_total / vol_tot_total) * 100 if vol_tot_total > 0 else 0
            avg_all = trapz_func(avg_irr_arr * area_tot_arr, z_arr) / vol_tot_total if vol_tot_total > 0 else 0
            avg_lux_all = trapz_func(avg_lux_arr * area_tot_arr, z_arr) / vol_tot_total if vol_tot_total > 0 else 0
            avg_ppfd_all = trapz_func(avg_ppfd_arr * area_tot_arr, z_arr) / vol_tot_total if vol_tot_total > 0 else 0

            z_diff = z_arr[-1] - z_arr[0]
            avg_flux_w_all = trapz_func(flux_w_arr, z_arr) / z_diff if z_diff > 0 else np.mean(flux_w_arr)
        else:
            vol_ilum_total = float(valid_stats[0]['area']) if len(valid_stats) > 0 else 0.0
            vol_tot_total = float(valid_stats[0]['tot']) if len(valid_stats) > 0 else 0.0
            vol_pct = (valid_stats[0]['area'] / valid_stats[0]['tot']) * 100 if len(valid_stats) > 0 and valid_stats[0]['tot'] > 0 else 0
            avg_all = valid_stats[0]['avg'] if len(valid_stats) > 0 else 0
            avg_lux_all = valid_stats[0]['avg'] * valid_stats[0]['f_lux'] if len(valid_stats) > 0 else 0
            avg_ppfd_all = valid_stats[0]['avg'] * valid_stats[0]['f_ppfd'] if len(valid_stats) > 0 else 0
            avg_flux_w_all = valid_stats[0]['flux_w'] if len(valid_stats) > 0 else 0

        _alpha_vals = [s['alpha_e'] for s in valid_stats if s.get('alpha_e') is not None]
        alpha_e_all = float(np.mean(_alpha_vals)) if _alpha_vals else None

        volumetric_roi_stats = {
            "label": "Vol. ROI" if roi['type'] != 'global' else label_area_base,
            "valid": bool(len(valid_stats) > 0 and vol_tot_total > 0),
            "avg": float(avg_all),
            "min": float(0 if min_irr_all == 999999 else min_irr_all),
            "max": float(max(0, max_irr_all)),
            "volume": float(vol_tot_total),
            "volume_ge_threshold": float(vol_ilum_total),
            "vol_pct": float(vol_pct),
            "alpha_e": alpha_e_all,
            "scope": "volume",
        }

        roi_plot_metrics = config.get('roi_plot_metrics', {}) or {}
        def roi_metric_enabled(key):
            return roi_plot_metrics.get(key, True) is not False

        heatmaps_for_combined = []
        for target_map in target_heatmaps:
            depth_str = target_map["depth_str"]
            layer_roi_stats = target_map["roi_stats"]
            display_roi_stats = volumetric_roi_stats if (
                roi['type'] != 'global' and layer_roi_stats.get("valid")
            ) else layer_roi_stats

            if roi['type'] != 'global':
                if layer_roi_stats.get("valid"):
                    stats_lines = [f"ROI plano Z={target_map['depth_val']} m:"]
                    if roi_metric_enabled('plane_avg'):
                        stats_lines.append(f"Prom plano: {layer_roi_stats['avg']:.4f} W/m²")
                    if roi_metric_enabled('plane_minmax'):
                        stats_lines.append(f"Min: {layer_roi_stats['min']:.4f}")
                        stats_lines.append(f"Max: {layer_roi_stats['max']:.4f}")
                    if roi_metric_enabled('plane_threshold'):
                        stats_lines.append(f"Área >= {contour_val}: {layer_roi_stats['area_ge_threshold']:.1f} m²")
                    stats_text = "\n".join(stats_lines)
                else:
                    stats_text = f"Stats {label_area_base}:\nROI fuera de este plano"
            else:
                stats_text = ""

            hue_image = ""
            if config.get('plot_light_quality') and target_map["hue_grid"] is not None:
                hue_image = plotter.plot_hue_angle_heatmap(
                    target_map["hue_grid"], X, Y, config, env_plot_dict, roi,
                    target_map["depth_val"], target_map["alpha_e_roi"])

            image = plotter.plot_individual_heatmap(
                target_map["E"], X, Y, config, env_plot_dict, contour_val,
                target_map["max_irr"], roi, target_map["depth_val"],
                stats_text, display_roi_stats)
            kd_res["depths"][depth_str]["image"] = image
            kd_res["depths"][depth_str]["display_roi_stats"] = display_roi_stats
            kd_res["depths"][depth_str]["hue_image"] = hue_image
            heatmaps_for_combined.append({
                'E': target_map["E"],
                'max_irr': target_map["max_irr"],
                'depth_val': target_map["depth_val"],
                'roi_stats': display_roi_stats,
                'plane_roi_stats': layer_roi_stats,
            })

        depths_txt = " y ".join([str(d) for d in target_depths_requested])
        kd_res["combined_image"] = plotter.plot_combined_heatmaps(heatmaps_for_combined, X, Y, config, env_plot_dict, contour_val, roi, project_title, depths_txt)

        if config.get('plot_depth_profile') and len(valid_stats) > 0:
            z_vals = [s['z'] for s in valid_stats]
            cum_irr_vals = []
            cum_vol_pct = []
            v_ilum_run, v_tot_run, EA_run = 0.0, 0.0, 0.0
            
            for i in range(len(valid_stats)):
                if i == 0:
                    cum_irr_vals.append(valid_stats[0]['avg'])
                    cum_vol_pct.append((valid_stats[0]['area'] / valid_stats[0]['tot'] * 100) if valid_stats[0]['tot'] > 0 else 0)
                else:
                    dz = abs(valid_stats[i]['z'] - valid_stats[i-1]['z'])
                    dV_ilum = (valid_stats[i-1]['area'] + valid_stats[i]['area']) / 2.0 * dz
                    dV_tot = (valid_stats[i-1]['tot'] + valid_stats[i]['tot']) / 2.0 * dz
                    dEA = ((valid_stats[i-1]['avg'] * valid_stats[i-1]['tot']) + (valid_stats[i]['avg'] * valid_stats[i]['tot'])) / 2.0 * dz
                    v_ilum_run += dV_ilum
                    v_tot_run += dV_tot
                    EA_run += dEA
                    cum_irr_vals.append(EA_run / v_tot_run if v_tot_run > 0 else 0)
                    cum_vol_pct.append((v_ilum_run / v_tot_run * 100) if v_tot_run > 0 else 0)

            irr_vals_plot = [max(val, 1e-4) for val in cum_irr_vals]
            kd_res["depth_profile_image"] = plotter.plot_depth_profile(irr_vals_plot, z_vals, cum_vol_pct, env_type, contour_val, profile_step)

        if config.get('compare_measurements') and len(comp_z) > 0:
            idx_s = np.argsort(comp_z)
            z_arr, m_arr, s_arr = np.array(comp_z)[idx_s], np.array(comp_meas)[idx_s], np.array(comp_sim)[idx_s]
            ss_res, ss_tot = np.sum((m_arr - s_arr)**2), np.sum((m_arr - np.mean(m_arr))**2)
            r2 = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
            rmse = np.sqrt(np.mean((m_arr - s_arr)**2))
            kd_res["comparison_image"] = plotter.plot_comparison(m_arr, s_arr, z_arr, env_type, config['compare_x'], config['compare_y'], r2, rmse)

        min_irr_all = 0 if min_irr_all == 999999 else min_irr_all
        power_eff = sum([float(l.get('power', 0)) for l in config.get('lamps', []) if float(l.get('power', 0)) > 0])
        lamps_str = ", ".join(list(set([l['xml'].replace('.xml','').replace('.ies', '') for l in config.get('lamps', [])])))
        pos_str = " | ".join([f"({l['x']}, {l['y']}, {l['z']})" for l in config.get('lamps', [])])
        
        # ---------------------------------------------------------------
        # Profundidad de disco de Secchi equivalente
        # ---------------------------------------------------------------
        # Se calculan DOS modelos y se devuelven ambos; 'secchi' refleja el
        # seleccionado por config['secchi_model'] ('preisendorfer' por defecto).
        #   - Preisendorfer (1986): Z_SD ≈ 8.69/(c+Kd), teoría clásica acoplada,
        #     dominada por el coeficiente de atenuación de haz c.
        #   - Lee et al. (2015): Z_SD = 1/(2.5·Kd_tr)·ln(|r_T-r_w|/C_t), gobernada
        #     por el Kd MÍNIMO del visible (ventana transparente).
        secchi_model = str(config.get('secchi_model', 'preisendorfer')).lower()
        g_secchi = float(config['optics'].get('g', 0.85))
        omega_secchi = float(config['optics'].get('omega', 0.8))
        mu_d_secchi = 0.85
        WL_VIS_SECCHI = np.linspace(400.0, 700.0, 61)

        # Cierre IOP→Kd: 'kirk' (Gershun/Kirk, por defecto) o 'lee2005'.
        # Fracción de retrodispersión activa B = b_b/b: de la fase FF si está
        # seleccionada (bb_ratio explícito o el equivalente HG), o de HG con g.
        kd_closure = str(config['optics'].get('kd_closure', 'kirk')).lower()
        _phase_fn = str(config['optics'].get('phase_function', 'hg')).lower()
        _bb_ratio = config['optics'].get('bb_ratio', None)
        if _phase_fn == 'fournier_forand':
            B_active = float(_bb_ratio) if _bb_ratio is not None else hg_backscatter_fraction(g_secchi)
        else:
            B_active = hg_backscatter_fraction(g_secchi)

        def _kd_from_iop_active(a, b):
            """Aplica el cierre IOP→Kd elegido (Kirk o Lee 2005), con b_b=B·b."""
            if kd_closure == 'lee2005':
                return kd_lee2005(a, B_active * np.asarray(b, dtype=float))
            return kd_from_iop(a, b, g=g_secchi, mu_d=mu_d_secchi)

        def _sorted_dict_arrays(d):
            keys = sorted(d.keys(), key=lambda x: float(x))
            return (np.array([float(k) for k in keys]),
                    np.array([float(d[k]) for k in keys]))

        def _spectral_kd_c_secchi():
            """Devuelve (Kd, c, a, b) sobre WL_VIS_SECCHI para el modo óptico activo,
            o (None, None, None, None) si no hay información suficiente. Exponer a y b
            permite estimar la retrodispersión b_b=B·b y la reflectancia de fondo r_w
            de forma coherente en el modelo de Secchi de Lee (2015)."""
            kd_from_c = (1.0 - omega_secchi * g_secchi) / mu_d_secchi
            c_from_kd_factor = mu_d_secchi / max(1.0 - omega_secchi * g_secchi, 1e-3)

            def _from_c(c_arr):
                # Descompone c en a y b con el albedo de dispersión simple ω.
                b_arr = omega_secchi * c_arr
                return c_arr - b_arr, b_arr

            if optics_mode == 'kd_fijo':
                base = np.full_like(WL_VIS_SECCHI, kd_val)
                c_arr = base * c_from_kd_factor if atten_coef_type == 'kd' else base
                kd_arr = base if atten_coef_type == 'kd' else base * kd_from_c
                a_arr, b_arr = _from_c(c_arr)
                return kd_arr, c_arr, a_arr, b_arr
            if optics_mode == 'kd_espectral':
                kd_dict = config['optics'].get('kd_spectral', {})
                if kd_dict:
                    kw, kv = _sorted_dict_arrays(kd_dict)
                    vals = np.interp(WL_VIS_SECCHI, kw, kv)
                else:
                    vals = np.full_like(WL_VIS_SECCHI, 0.2)
                c_arr = vals * c_from_kd_factor if atten_coef_type == 'kd' else vals
                kd_arr = vals if atten_coef_type == 'kd' else vals * kd_from_c
                a_arr, b_arr = _from_c(c_arr)
                return kd_arr, c_arr, a_arr, b_arr
            if optics_mode == 'scattering':
                if mc_input_type == 'bio':
                    a, b = bio_optical_iop(
                        WL_VIS_SECCHI,
                        tss=float(config['optics'].get('tss', 15.0)),
                        cdom_a440=float(config['optics'].get('cdom_a440', 1.0)),
                        chl=float(config['optics'].get('chl', 0.0)))
                    return _kd_from_iop_active(a, b), a + b, a, b
                if mc_input_type == 'ras_bardsnes':
                    tss_s = config['optics'].get('tss', None)
                    turb_s = config['optics'].get('turbidity_ntu', None)
                    if tss_s in (None, '') and turb_s not in (None, ''):
                        tss_s = ras_tss_from_turbidity(turb_s)
                    tss_s = float(tss_s if tss_s not in (None, '') else 15.0)
                    a, b = bio_optical_iop_ras_bardsnes(
                        WL_VIS_SECCHI,
                        tss=tss_s,
                        cdom_a440=float(config['optics'].get('cdom_a440', 1.0)),
                        chl=float(config['optics'].get('chl', 0.0)),
                        bstar_550=float(config['optics'].get('ras_bstar_550', 0.31)),
                        omega_p=float(config['optics'].get('ras_omega_p', 0.90)),
                        eta_p=float(config['optics'].get('ras_eta_p', 1.8)),
                        s_cdom=float(config['optics'].get('ras_s_cdom', 0.0141)))
                    return _kd_from_iop_active(a, b), a + b, a, b
                if mc_input_type == 'scalar':
                    c_arr = np.full_like(WL_VIS_SECCHI, kd_val)
                    a_arr, b_arr = _from_c(c_arr)
                    return _kd_from_iop_active(a_arr, b_arr), c_arr, a_arr, b_arr
                if mc_input_type == 'json':
                    c_dict = config['optics'].get('c_json', {})
                    o_dict = config['optics'].get('omega_json', {})
                    if c_dict:
                        cw, cv = _sorted_dict_arrays(c_dict)
                        c_arr = np.interp(WL_VIS_SECCHI, cw, cv)
                    else:
                        c_arr = np.full_like(WL_VIS_SECCHI, 0.5)
                    if o_dict:
                        ow, ov = _sorted_dict_arrays(o_dict)
                        omega_arr = np.interp(WL_VIS_SECCHI, ow, ov)
                    else:
                        omega_arr = np.full_like(WL_VIS_SECCHI, omega_secchi)
                    b_arr = omega_arr * c_arr
                    a_arr = c_arr - b_arr
                    return _kd_from_iop_active(a_arr, b_arr), c_arr, a_arr, b_arr
            return None, None, None, None

        def _r_w_from_iop(a_tr, b_tr):
            """Reflectancia de radiancia de fondo del agua en la ventana transparente,
            estimada vía Gordon R(0-)≈f·b_b/(a+b_b) con b_b=B·b de la fase activa.
            Así la RETRODISPERSIÓN entra al término de contraste del modelo de Lee
            (2015), no sólo al Kd. Válida en todos los modos ópticos."""
            bb_tr = B_active * float(b_tr)
            return subsurface_reflectance(float(a_tr), bb_tr) / np.pi

        secchi_preis = 0.0
        secchi_lee = 0.0
        secchi_poole = 0.0
        kd_spec, c_spec, a_spec, b_spec = _spectral_kd_c_secchi()
        if kd_spec is not None and np.any(np.asarray(kd_spec) > 0):
            kd_spec = np.asarray(kd_spec, dtype=float)
            c_spec = np.asarray(c_spec, dtype=float)
            a_spec = np.asarray(a_spec, dtype=float)
            b_spec = np.asarray(b_spec, dtype=float)
            i_tr = int(np.argmin(kd_spec))           # ventana transparente (Kd mínimo)
            kd_tr = float(kd_spec[i_tr])
            c_tr = float(c_spec[i_tr])
            r_w_tr = _r_w_from_iop(a_spec[i_tr], b_spec[i_tr])
            secchi_lee = secchi_lee2015(kd_tr, r_w=r_w_tr)
            secchi_preis = secchi_preisendorfer(c_tr, kd_tr)
            secchi_poole = secchi_poole_atkins(kd_tr)

        # Preisendorfer acoplado unificado: ambos tipos de coeficiente (c y Kd)
        # usan Z = 8.69/(c + Kd), derivando el coeficiente faltante con el mismo
        # cierre bio-óptico (omega, g, mu_d). Esto garantiza que una misma agua
        # física entregue el MISMO Secchi se ingrese como c o como Kd. La relación
        # clásica de Poole–Atkins (1.7/Kd) se conserva sólo para la INGESTA de
        # datos satelitales (Secchi→Kd) en optical_lookup, no como salida aquí.
        # (El valor coherente ya quedó calculado en el bloque espectral anterior.)

        if secchi_model == 'lee2015':
            secchi_eq = secchi_lee
        elif secchi_model == 'poole_atkins':
            secchi_eq = secchi_poole
        else:
            secchi_eq = secchi_preis

        table_data.append({
            "kd": optics_title, "avg": avg_all, "avg_lux": avg_lux_all, "avg_ppfd": avg_ppfd_all,
            "avg_flux_w": avg_flux_w_all, "max": max_irr_all, "min": min_irr_all,
            "vol_pct": vol_pct, "vol_ilum_m3": vol_ilum_total, "vol_tot_m3": vol_tot_total,
            "power_eff": power_eff, "lamps_str": lamps_str, "pos_str": pos_str,
            "secchi": secchi_eq, "secchi_model": secchi_model,
            "secchi_preisendorfer": secchi_preis, "secchi_lee2015": secchi_lee,
            "secchi_poole_atkins": secchi_poole,
            "alpha_e": alpha_e_all,
        })

        return jsonify({
            "status": "ok", 
            "clean_title": clean_title,
            "depths": [str(d) for d in target_depths_requested],
            "kds": ["default"],
            "results_by_kd": {"default": kd_res},
            "table_data": table_data,
            "optical_diagnostics": optical_diagnostics,
            "spectrums": spectrum_results,
            "lamps_names": lamps_names,
            "scenario_names": {"default": optics_title},
            "file_suffixes": {"default": optics_suffix},
            "bio_analysis": bio_analysis_result
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "msg": str(e)}), 500


@app.route('/api/run_biooptical_batch', methods=['POST'])
def run_biooptical_batch():
    try:
        payload = request.json or {}
        analysis_cfg = validate_analysis_config(payload.get('analysis', {}))
        scenarios = payload.get('scenarios', [])
        if not scenarios:
            return jsonify({"status": "error", "msg": "Agregue al menos un escenario bio-óptico."}), 400

        layer_rows_by_scenario = {}
        grid_rows_all = []
        for idx, scenario in enumerate(scenarios):
            sim_config = scenario.get('config') or {}
            if not sim_config:
                raise ValueError(f"El escenario {idx + 1} no contiene configuración completa.")
            scenario_id = _unique_scenario_id(
                scenario.get('scenario_id') or sim_config.get('project_title'),
                layer_rows_by_scenario,
                f"scenario_{idx + 1}",
            )
            engine_config = _prepare_engine_config_for_bio(sim_config, analysis_cfg)
            engine.run(engine_config)
            if engine.last_volume_tally is None:
                raise ValueError(f"No se generó tally volumétrico para {scenario_id}.")
            scenario_meta = {
                "lamp_id": scenario.get("lamp_id", ""),
                "lamp_type": scenario.get("lamp_type", ""),
                "lamp_depth_m": scenario.get("lamp_depth_m", None),
                "beam_orientation": scenario.get("beam_orientation", ""),
            }
            layer_rows, _ = summarize_volume_tally(
                engine.last_volume_tally, analysis_cfg, scenario_id, engine_config,
                scenario_meta=scenario_meta,
            )
            layer_rows_by_scenario[scenario_id] = layer_rows
            if analysis_cfg.get('grid_cells_csv'):
                grid_rows_all.extend(volume_grid_rows(engine.last_volume_tally, scenario_id))

        result = build_outputs(layer_rows_by_scenario, analysis_cfg, grid_rows=grid_rows_all)
        return jsonify({"status": "ok", "bio_analysis": result})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "msg": str(e)}), 500

if __name__ == '__main__':
    for f in os.listdir(UPLOAD_FOLDER):
        if f.lower().endswith('.xml') or f.lower().endswith('.ies'):
            filepath = os.path.join(UPLOAD_FOLDER, f)
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as file:
                    engine.load_file(f, file.read())
            except Exception: pass
    app.run(debug=False, port=5001)
