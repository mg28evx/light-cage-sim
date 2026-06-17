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
    SimulationEngine, bio_optical_iop, c_from_kd, kd_from_iop,
    hg_backscatter_fraction, subsurface_reflectance,
    secchi_preisendorfer, secchi_lee2015,
)
from optical_lookup import build_optical_presets, build_optical_weekly_profile, load_centers
from optical_sources import get_source_status
import plotter

app = Flask(__name__)
engine = SimulationEngine()

UPLOAD_FOLDER = './uploaded_lamps'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def sanitize_filename(name):
    clean = re.sub(r'[\s\.,\-]+', '_', str(name).lower())
    clean = re.sub(r'_+', '_', clean)
    return clean.strip('_')

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
        if optics_mode == 'scattering' and mc_input_type == 'ras_bardsnes':
            return jsonify({
                'status': 'error',
                'message': (
                    'La calibración empírica RAS basada en Bårdsnes (2020) requiere '
                    'coeficientes propios del sistema antes de simular.'
                )
            }), 400
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
            
        profile_step = float(config.get('profile_step', 0.5))
        prof_d = np.arange(calc_min_z, calc_max_z + profile_step, profile_step)
        
        all_depths_set = set(target_depths_requested)
        if config.get('plot_depth_profile'):
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

        kd_res = {"depths": {}, "combined_image": "", "comparison_image": "", "depth_profile_image": "", "env_optics_image": "", "aportes": [], "depth_table": []}

        config['optics']['mode'] = optics_mode

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
        
        bins = 100
        grid_x = np.linspace(0, env_x, bins)
        grid_y = np.linspace(0, env_y, bins)
        X, Y = np.meshgrid((grid_x[:-1]+grid_x[1:])/2, (grid_y[:-1]+grid_y[1:])/2)
        x_centers, y_centers = (grid_x[:-1] + grid_x[1:]) / 2, (grid_y[:-1] + grid_y[1:]) / 2
        area_bin = (grid_x[1]-grid_x[0]) * (grid_y[1]-grid_y[0])

        layer_stats = []
        max_irr_all, min_irr_all = -1, 999999
        comp_z, comp_meas, comp_sim = [], [], []
        heatmaps_for_combined = []

        for depth_val in all_depths_requested:
            depth_str = str(depth_val)
            data = None
            for k in raw_results.keys():
                if abs(float(k) - depth_val) < 0.01:
                    data = raw_results[k]
                    break
            
            is_target = any(abs(depth_val - td) < 1e-4 for td in target_depths_requested)

            if data is None or not data['x']:
                if is_target:
                    kd_res["depths"][depth_str] = {"image": "", "max": 0, "avg": 0, "area_ilum": 0}
                continue
                
            pts = np.column_stack((data['x'], data['y']))
            vals_hit = np.array(data['val'])
            lamp_idxs = np.array(data.get('lamp_idx', []))
            wls_hit = np.array(data.get('wl', []))

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
                    'f_lux': f_lux, 'f_ppfd': f_ppfd, 'flux_w': flux_w
                })

            label_area = "Vol. ROI" if roi['type'] != 'global' else ("Estanque" if env_type == 'estanque' else "Area Total")
            roi_stats = {
                "label": label_area,
                "valid": bool(z_valid and np.any(mask)),
                "avg": float(avg_irr),
                "min": float(min_irr),
                "max": float(max_irr),
                "area": float(area_total_layer),
                "area_ge_threshold": float(area_ilum)
            }

            if is_target:
                if config.get('plot_depth_summary_table', True):
                    kd_res["depth_table"].append({
                        "z": depth_val,
                        "flux_w": flux_w,
                        "avg_w": avg_irr, "min_w": min_irr, "max_w": max_irr,
                        "avg_lux": avg_irr * f_lux, "min_lux": min_irr * f_lux, "max_lux": max_irr * f_lux,
                        "avg_ppfd": avg_irr * f_ppfd, "min_ppfd": min_irr * f_ppfd, "max_ppfd": max_irr * f_ppfd
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
                stats_text = f"Stats {label_area}:\nProm: {avg_irr:.4f} W/m²\nMin: {min_irr:.4f}\nMax: {max_irr:.4f}\nÁrea >= {contour_val}: {area_ilum:.1f} m²"
                kd_res["depths"][depth_str] = {
                    "image": plotter.plot_individual_heatmap(E, X, Y, config, env_plot_dict, contour_val, max_irr, roi, depth_val, stats_text, roi_stats),
                    "grid": E.tolist(),
                    "x_centers": x_centers.tolist(),
                    "y_centers": y_centers.tolist(),
                    "max": float(max_irr),
                    "avg": float(avg_irr),
                    "min": float(min_irr),
                    "area_ilum": float(area_ilum),
                    "roi_stats": roi_stats
                }
                heatmaps_for_combined.append({'E': E, 'max_irr': max_irr, 'depth_val': depth_val, 'roi_stats': roi_stats})

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

        def _sorted_dict_arrays(d):
            keys = sorted(d.keys(), key=lambda x: float(x))
            return (np.array([float(k) for k in keys]),
                    np.array([float(d[k]) for k in keys]))

        def _spectral_kd_c_secchi():
            """Devuelve (Kd, c) sobre WL_VIS_SECCHI para el modo óptico activo,
            o (None, None) si no hay información suficiente."""
            kd_from_c = (1.0 - omega_secchi * g_secchi) / mu_d_secchi
            c_from_kd_factor = mu_d_secchi / max(1.0 - omega_secchi * g_secchi, 1e-3)
            if optics_mode == 'kd_fijo':
                base = np.full_like(WL_VIS_SECCHI, kd_val)
                if atten_coef_type == 'kd':
                    return base, base * c_from_kd_factor
                return base * kd_from_c, base
            if optics_mode == 'kd_espectral':
                kd_dict = config['optics'].get('kd_spectral', {})
                if kd_dict:
                    kw, kv = _sorted_dict_arrays(kd_dict)
                    vals = np.interp(WL_VIS_SECCHI, kw, kv)
                else:
                    vals = np.full_like(WL_VIS_SECCHI, 0.2)
                if atten_coef_type == 'kd':
                    return vals, vals * c_from_kd_factor
                return vals * kd_from_c, vals
            if optics_mode == 'scattering':
                if mc_input_type == 'bio':
                    a, b = bio_optical_iop(
                        WL_VIS_SECCHI,
                        tss=float(config['optics'].get('tss', 15.0)),
                        cdom_a440=float(config['optics'].get('cdom_a440', 1.0)),
                        chl=float(config['optics'].get('chl', 0.0)))
                    return kd_from_iop(a, b, g=g_secchi, mu_d=mu_d_secchi), a + b
                if mc_input_type == 'scalar':
                    base = np.full_like(WL_VIS_SECCHI, kd_val)
                    return base * kd_from_c, base
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
                    return kd_from_iop(a_arr, b_arr, g=g_secchi, mu_d=mu_d_secchi), c_arr
            return None, None

        def _r_w_transparent(wl_tr):
            """Reflectancia de fondo del agua en la ventana transparente. Si hay
            IOPs (modo bio), se estima vía Gordon con b_b de la fase HG; si no,
            se usa un valor de agua clara por defecto."""
            if optics_mode == 'scattering' and mc_input_type == 'bio':
                a_tr, b_tr = bio_optical_iop(
                    np.array([wl_tr]),
                    tss=float(config['optics'].get('tss', 15.0)),
                    cdom_a440=float(config['optics'].get('cdom_a440', 1.0)),
                    chl=float(config['optics'].get('chl', 0.0)))
                bb_tr = hg_backscatter_fraction(g_secchi) * float(b_tr[0])
                return subsurface_reflectance(float(a_tr[0]), bb_tr) / np.pi
            return 0.02

        secchi_preis = 0.0
        secchi_lee = 0.0
        kd_spec, c_spec = _spectral_kd_c_secchi()
        if kd_spec is not None and np.any(np.asarray(kd_spec) > 0):
            kd_spec = np.asarray(kd_spec, dtype=float)
            c_spec = np.asarray(c_spec, dtype=float)
            i_tr = int(np.argmin(kd_spec))           # ventana transparente (Kd mínimo)
            kd_tr = float(kd_spec[i_tr])
            c_tr = float(c_spec[i_tr])
            wl_tr = float(WL_VIS_SECCHI[i_tr])
            secchi_lee = secchi_lee2015(kd_tr, r_w=_r_w_transparent(wl_tr))
            secchi_preis = secchi_preisendorfer(c_tr, kd_tr)

        # Preisendorfer acoplado unificado: ambos tipos de coeficiente (c y Kd)
        # usan Z = 8.69/(c + Kd), derivando el coeficiente faltante con el mismo
        # cierre bio-óptico (omega, g, mu_d). Esto garantiza que una misma agua
        # física entregue el MISMO Secchi se ingrese como c o como Kd. La relación
        # clásica de Poole–Atkins (1.7/Kd) se conserva sólo para la INGESTA de
        # datos satelitales (Secchi→Kd) en optical_lookup, no como salida aquí.
        # (El valor coherente ya quedó calculado en el bloque espectral anterior.)

        secchi_eq = secchi_lee if secchi_model == 'lee2015' else secchi_preis

        table_data.append({
            "kd": optics_title, "avg": avg_all, "avg_lux": avg_lux_all, "avg_ppfd": avg_ppfd_all,
            "avg_flux_w": avg_flux_w_all, "max": max_irr_all, "min": min_irr_all,
            "vol_pct": vol_pct, "vol_ilum_m3": vol_ilum_total, "vol_tot_m3": vol_tot_total,
            "power_eff": power_eff, "lamps_str": lamps_str, "pos_str": pos_str,
            "secchi": secchi_eq, "secchi_model": secchi_model,
            "secchi_preisendorfer": secchi_preis, "secchi_lee2015": secchi_lee,
        })

        return jsonify({
            "status": "ok", 
            "clean_title": clean_title,
            "depths": [str(d) for d in target_depths_requested],
            "kds": ["default"],
            "results_by_kd": {"default": kd_res},
            "table_data": table_data,
            "spectrums": spectrum_results,
            "lamps_names": lamps_names,
            "scenario_names": {"default": optics_title},
            "file_suffixes": {"default": optics_suffix}
        })

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
