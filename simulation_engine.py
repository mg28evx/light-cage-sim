import numpy as np
from scipy.interpolate import RegularGridInterpolator, make_interp_spline
from parsers import TM33Parser, IESParser

try:
    trapz_func = np.trapezoid
except AttributeError:
    trapz_func = np.trapz

def fresnel_transmission(n1, n2, cos_theta_i, cos_theta_t):
    rs = ((n1 * cos_theta_i - n2 * cos_theta_t) / (n1 * cos_theta_i + n2 * cos_theta_t))**2
    rp = ((n1 * cos_theta_t - n2 * cos_theta_i) / (n1 * cos_theta_t + n2 * cos_theta_i))**2
    return 1.0 - 0.5 * (rs + rp)

def normalize(v):
    norm = np.linalg.norm(v, axis=1, keepdims=True)
    return v / (norm + 1e-16)

def rotate_3d(vectors, rx_deg, ry_deg, rz_deg):
    rx = np.radians(rx_deg)
    ry = np.radians(ry_deg)
    rz = np.radians(rz_deg)
    
    cx, sx = np.cos(rx), np.sin(rx)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    
    cy, sy = np.cos(ry), np.sin(ry)
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    
    cz, sz = np.cos(rz), np.sin(rz)
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    
    R = Rz @ Ry @ Rx
    return vectors @ R.T

def sample_henyey_greenstein(D, g):
    N = len(D)
    xi1 = np.random.rand(N)
    xi2 = np.random.rand(N)
    
    if g == 0:
        cos_theta = 1.0 - 2.0 * xi1
    else:
        sqr_term = (1.0 - g**2) / (1.0 - g + 2.0 * g * xi1)
        cos_theta = (1.0 + g**2 - sqr_term**2) / (2.0 * g)
        
    sin_theta = np.sqrt(np.maximum(0.0, 1.0 - cos_theta**2))
    phi = 2.0 * np.pi * xi2
    
    W = normalize(D)
    A = np.where(np.abs(W[:, 0:1]) > 0.9, np.array([0,1,0]), np.array([1,0,0]))
    U = normalize(np.cross(A, W))
    V = np.cross(W, U)
    
    D_new = (U * (sin_theta * np.cos(phi))[:, np.newaxis] + 
             V * (sin_theta * np.sin(phi))[:, np.newaxis] + 
             W * cos_theta[:, np.newaxis])
    return normalize(D_new)

class SimulationEngine:
    def __init__(self):
        self.parsers = {} 
    
    def load_file(self, filename, content_str):
        try:
            if filename.lower().endswith('.ies'):
                parser = IESParser(content_str)
            else:
                parser = TM33Parser(content_str)
            self.parsers[filename] = parser
            return True
        except Exception as e:
            print(f"Error cargando {filename}: {e}")
            return False

    def run(self, config):
        env = config.get('env', {})
        env_type = env.get('type', 'estanque')
        env_shape = env.get('shape', 'circle' if env_type == 'estanque' else 'rect')
        
        raw_x = env.get('x')
        raw_y = env.get('y')
        env_x = float(raw_x) if raw_x is not None else 40.0
        env_y = float(raw_y) if raw_y is not None else 40.0
        
        center_x, center_y = env_x / 2.0, env_y / 2.0
        
        raw_radio = env.get('radio')
        env_radio = float(raw_radio) if raw_radio is not None else env_x / 2.0
        
        raw_n1 = env.get('n1')
        n1 = float(raw_n1) if raw_n1 is not None else 1.0
        
        raw_n2 = env.get('n2')
        n2 = float(raw_n2) if raw_n2 is not None else 1.333
        
        raw_z_int = env.get('z_interface')
        z_interface = 0.0 if env_type == 'jaula' else (float(raw_z_int) if raw_z_int is not None else 3.2)

        optics = config.get('optics', {})
        optics_mode = optics.get('mode', 'kd_fijo')
        kd_fijo = float(optics.get('kd_fijo', 0.2))
        kd_spectral = optics.get('kd_spectral', {}) 
        mc_input_type = optics.get('mc_input_type', 'scalar')
        g_hg = float(optics.get('g', 0.85))
        r_wall = float(optics.get('r_wall', 0.15))

        # --- LECTURA DE PARÁMETROS PINEALES ---
        irradiance_type = config.get('irradiance_type', 'scalar')
        mu_max_deg = float(config.get('mu_max', 85.0))
        cos_mu_max = np.cos(np.radians(mu_max_deg))
        normalize_pineal = config.get('normalize_pineal', True)
        pineal_norm_factor = 0.5 if normalize_pineal else 1.0

        target_depths_input = config.get('target_depths', [2.0])
        n_rays = int(config.get('rays', 50000))
        
        results = {str(d): {'x': [], 'y': [], 'val': [], 'lamp_idx': [], 'wl': []} for d in target_depths_input}

        for i_lamp, lamp in enumerate(config.get('lamps', [])):
            xml_id = lamp['xml']
            if xml_id not in self.parsers: continue
            parser = self.parsers[xml_id]
            
            pos_z = -float(lamp['z']) if env_type == 'jaula' else float(lamp['z'])
            pos = np.array([float(lamp['x']), float(lamp['y']), pos_z])
            dimming = float(lamp['dim'])
            rot_x, rot_y, rot_z = float(lamp.get('rot_x', 0)), float(lamp.get('rot_y', 0)), float(lamp.get('rot_z', 0))

            indices = np.arange(0, n_rays, dtype=float) + 0.5
            phi = np.arccos(1 - 2*indices/n_rays) 
            theta = np.pi * (1 + 5**0.5) * indices 
            lx, ly, lz = np.sin(phi) * np.cos(theta), np.sin(phi) * np.sin(theta), np.cos(phi)
            rays_local = np.column_stack((lx, ly, lz))

            lum, rad = parser.get_intensity(rays_local)
            
            if getattr(parser, 'is_ies', False):
                total_current_power = np.sum(rad) * (4 * np.pi / n_rays)
                user_power = float(lamp.get('power', 600))
                if total_current_power > 0: rad = rad * (user_power / total_current_power)

            mask = rad > 0
            rays_local = rays_local[mask]
            flux_rad = rad[mask] * (4 * np.pi / n_rays) * dimming

            rays_global = rays_local
            if rot_x != 0 or rot_y != 0 or rot_z != 0:
                rays_global = rotate_3d(rays_local, rot_x, rot_y, rot_z)

            spectrum = parser.get_spectrum()
            if not spectrum:
                wls = np.array([400, 500, 600, 700])
                pwrs = np.array([1.0, 1.0, 1.0, 1.0])
            else:
                wls = np.array(sorted(spectrum.keys()))
                pwrs = np.array([spectrum[w] for w in wls])
                
            pdf = pwrs / np.sum(pwrs)
            cdf = np.cumsum(pdf)
            rand_wls = np.random.rand(len(rays_global))
            ray_wls = np.interp(rand_wls, cdf, wls)
            ray_wls = ray_wls[mask]

            if optics_mode == 'scattering':
                if mc_input_type == 'bio':
                    tss_val = float(optics.get('tss', 15.0))
                    a440_val = float(optics.get('cdom_a440', 1.0))
                    wl_ref = np.array([400, 450, 500, 550, 600, 650, 700])
                    b_star_ref = np.array([0.50, 0.42, 0.35, 0.31, 0.28, 0.25, 0.22])
                    aw_ref = np.array([0.01, 0.01, 0.02, 0.06, 0.24, 0.35, 0.65])
                    spline_b = make_interp_spline(wl_ref, b_star_ref, k=2)
                    spline_aw = make_interp_spline(wl_ref, aw_ref, k=2)
                    b_star_ray = np.maximum(spline_b(ray_wls), 0)
                    aw_ray = np.maximum(spline_aw(ray_wls), 0)
                    b_total_ray = b_star_ray * tss_val
                    a_cdom_ray = a440_val * np.exp(-0.015 * (ray_wls - 440))
                    a_total_ray = aw_ray + a_cdom_ray
                    ray_c_all = a_total_ray + b_total_ray
                    ray_omega_all = b_total_ray / (ray_c_all + 1e-9)
                elif mc_input_type == 'json':
                    c_dict = optics.get('c_json', {})
                    omega_dict = optics.get('omega_json', {})
                    c_wls = np.array([float(k) for k in sorted(c_dict.keys())])
                    c_vals = np.array([float(c_dict[k]) for k in sorted(c_dict.keys())])
                    omega_wls = np.array([float(k) for k in sorted(omega_dict.keys())])
                    omega_vals = np.array([float(omega_dict[k]) for k in sorted(omega_dict.keys())])
                    if len(c_wls) == 0: c_wls, c_vals = np.array([500]), np.array([0.5])
                    if len(omega_wls) == 0: omega_wls, omega_vals = np.array([500]), np.array([0.8])
                    ray_c_all = np.interp(ray_wls, c_wls, c_vals)
                    ray_omega_all = np.interp(ray_wls, omega_wls, omega_vals)
                else:
                    c_att = float(optics.get('c', 0.5))
                    omega = float(optics.get('omega', 0.8))
                    ray_c_all = np.full(len(rays_global), c_att)
                    ray_omega_all = np.full(len(rays_global), omega)

            down_mask = rays_global[:, 2] < -1e-6
            v_rays = rays_global[down_mask]
            v_flux = flux_rad[down_mask]
            v_wls = ray_wls[down_mask]
            
            if optics_mode == 'scattering':
                r_c = ray_c_all[down_mask]
                r_omega = ray_omega_all[down_mask]
                
            P_start = np.tile(pos, (len(v_rays), 1))

            if env_type == 'estanque' and pos[2] > z_interface:
                t_int = (z_interface - pos[2]) / v_rays[:, 2]
                P_int = P_start + v_rays * t_int[:, np.newaxis]
                c_ti = -v_rays[:, 2] 
                s2_tt = (n1/n2)**2 * (1.0 - c_ti**2)
                tir_mask = s2_tt <= 1.0
                
                v_rays = v_rays[tir_mask]
                v_flux = v_flux[tir_mask]
                v_wls = v_wls[tir_mask]
                P_start = P_int[tir_mask]
                c_ti = c_ti[tir_mask]
                c_tt = np.sqrt(1.0 - s2_tt[tir_mask])
                
                T_vec = (n1/n2) * v_rays + ((n1/n2) * c_ti - c_tt)[:, np.newaxis] * np.array([0, 0, 1])
                T_fresnel = fresnel_transmission(n1, n2, c_ti, c_tt)
                
                v_rays = normalize(T_vec)
                v_flux = v_flux * T_fresnel * 0.98 

                if optics_mode == 'scattering':
                    r_c = r_c[tir_mask]
                    r_omega = r_omega[tir_mask]

            if len(v_rays) == 0: continue

            if optics_mode == 'kd_fijo':
                for orig_depth in target_depths_input:
                    depth = -float(orig_depth) if env_type == 'jaula' else float(orig_depth)
                    if depth > P_start[0, 2]: continue
                    
                    t = (depth - P_start[:, 2]) / v_rays[:, 2]
                    P_hit = P_start + v_rays * t[:, np.newaxis]
                    
                    d_w = np.linalg.norm(v_rays * t[:, np.newaxis], axis=1)
                    val = v_flux * np.exp(-kd_fijo * d_w)
                    
                    # Ponderación Pineal Exacta (Piecewise Function)
                    if irradiance_type == 'pineal':
                        cos_mu = -v_rays[:, 2] # Coseno del ángulo incidente respecto al cenit (+z)
                        pineal_weight = np.where(cos_mu >= cos_mu_max, pineal_norm_factor * (1.0 + cos_mu), 0.0)
                        val = val * pineal_weight
                        
                    results[str(orig_depth)]['x'].extend(P_hit[:, 0].tolist())
                    results[str(orig_depth)]['y'].extend(P_hit[:, 1].tolist())
                    results[str(orig_depth)]['val'].extend(val.tolist())
                    results[str(orig_depth)]['lamp_idx'].extend(np.full(len(P_hit), i_lamp).tolist())
                    results[str(orig_depth)]['wl'].extend(v_wls.tolist())

            elif optics_mode == 'kd_espectral':
                kd_wls = np.array([float(k) for k in sorted(kd_spectral.keys())])
                kd_vals = np.array([float(kd_spectral[k]) for k in sorted(kd_spectral.keys())])
                if len(kd_wls) == 0: kd_wls, kd_vals = np.array([500]), np.array([0.2])
                
                ray_kd = np.interp(v_wls, kd_wls, kd_vals)
                
                for orig_depth in target_depths_input:
                    depth = -float(orig_depth) if env_type == 'jaula' else float(orig_depth)
                    if depth > P_start[0, 2]: continue
                    
                    t = (depth - P_start[:, 2]) / v_rays[:, 2]
                    P_hit = P_start + v_rays * t[:, np.newaxis]
                    d_w = np.linalg.norm(v_rays * t[:, np.newaxis], axis=1)
                    
                    val = v_flux * np.exp(-ray_kd * d_w)

                    # Ponderación Pineal Exacta (Piecewise Function)
                    if irradiance_type == 'pineal':
                        cos_mu = -v_rays[:, 2]
                        pineal_weight = np.where(cos_mu >= cos_mu_max, pineal_norm_factor * (1.0 + cos_mu), 0.0)
                        val = val * pineal_weight
                    
                    results[str(orig_depth)]['x'].extend(P_hit[:, 0].tolist())
                    results[str(orig_depth)]['y'].extend(P_hit[:, 1].tolist())
                    results[str(orig_depth)]['val'].extend(val.tolist())
                    results[str(orig_depth)]['lamp_idx'].extend(np.full(len(P_hit), i_lamp).tolist())
                    results[str(orig_depth)]['wl'].extend(v_wls.tolist())

            elif optics_mode == 'scattering':
                P_mc = P_start.copy()
                D_mc = v_rays.copy()
                W_mc = v_flux.copy()
                
                max_bounces = 4
                for bounce in range(max_bounces):
                    active = W_mc > 1e-9
                    if not np.any(active): break
                    
                    P, D, W = P_mc[active], D_mc[active], W_mc[active]
                    c_active = r_c[active]
                    omega_active = r_omega[active]
                    wl_active = v_wls[active]
                    
                    t_wall = np.full(len(P), np.inf)
                    if env_type == 'estanque':
                        if env_shape == 'circle':
                            a = D[:,0]**2 + D[:,1]**2
                            b = P[:,0]*D[:,0] + P[:,1]*D[:,1] - center_x*D[:,0] - center_y*D[:,1]
                            c = (P[:,0]-center_x)**2 + (P[:,1]-center_y)**2 - env_radio**2
                            disc = b**2 - a*c
                            valid_disc = disc > 0
                            if np.any(valid_disc):
                                sqrt_disc = np.sqrt(disc[valid_disc])
                                t1 = (-b[valid_disc] + sqrt_disc) / (a[valid_disc] + 1e-9)
                                t2 = (-b[valid_disc] - sqrt_disc) / (a[valid_disc] + 1e-9)
                                t_pos = np.where((t1 > 1e-4) & ((t1 < t2) | (t2 <= 1e-4)), t1, t2)
                                t_wall[valid_disc] = np.where(t_pos > 1e-4, t_pos, np.inf)
                        elif env_shape == 'rect':
                            tx1 = (0 - P[:,0]) / (D[:,0] + 1e-9); tx2 = (env_x - P[:,0]) / (D[:,0] + 1e-9)
                            ty1 = (0 - P[:,1]) / (D[:,1] + 1e-9); ty2 = (env_y - P[:,1]) / (D[:,1] + 1e-9)
                            tx_pos = np.where(tx1 > 1e-4, tx1, np.where(tx2 > 1e-4, tx2, np.inf))
                            ty_pos = np.where(ty1 > 1e-4, ty1, np.where(ty2 > 1e-4, ty2, np.inf))
                            t_wall = np.minimum(tx_pos, ty_pos)

                    t_floor = np.full(len(P), np.inf)
                    going_down = D[:, 2] < 0
                    if np.any(going_down):
                        floor_z = 0.0 if env_type == 'estanque' else -50.0 
                        t_floor[going_down] = (floor_z - P[:,2][going_down]) / D[:,2][going_down]

                    t_bound = np.minimum(t_wall, t_floor)
                    
                    t_scat = -np.log(np.random.rand(len(P))) / (c_active + 1e-9)
                    t_event = np.minimum(t_bound, t_scat)

                    for orig_depth in target_depths_input:
                        d_val = float(orig_depth) if env_type != 'jaula' else -float(orig_depth)
                        z_start = P[:,2]
                        z_end = P[:,2] + t_event * D[:,2]
                        
                        crosses = (z_start - d_val) * (z_end - d_val) < 0
                        if np.any(crosses):
                            tc = (d_val - z_start[crosses]) / (D[:,2][crosses] + 1e-9)
                            Px_c = P[:,0][crosses] + tc * D[:,0][crosses]
                            Py_c = P[:,1][crosses] + tc * D[:,1][crosses]
                            
                            val_cross = W[crosses]

                            # Ponderación Pineal Exacta (Piecewise Function)
                            if irradiance_type == 'pineal':
                                cos_mu = -D[:, 2][crosses]
                                pineal_weight = np.where(cos_mu >= cos_mu_max, pineal_norm_factor * (1.0 + cos_mu), 0.0)
                                val_cross = val_cross * pineal_weight

                            results[str(orig_depth)]['x'].extend(Px_c.tolist())
                            results[str(orig_depth)]['y'].extend(Py_c.tolist())
                            results[str(orig_depth)]['val'].extend(val_cross.tolist())
                            results[str(orig_depth)]['lamp_idx'].extend(np.full(len(Px_c), i_lamp).tolist())
                            results[str(orig_depth)]['wl'].extend(wl_active[crosses].tolist())

                    hit_wall = t_wall < t_scat
                    hit_floor = (t_floor < t_scat) & (t_floor <= t_wall)
                    hit_scat = ~(hit_wall | hit_floor)

                    if np.any(hit_wall):
                        P_hw = P[hit_wall] + t_wall[hit_wall][:, np.newaxis] * D[hit_wall]
                        N = P_hw.copy()
                        if env_shape == 'circle':
                            N[:, 0] -= center_x; N[:, 1] -= center_y
                        else:
                            N[:,0] = np.where(np.abs(P_hw[:,0]) < 1e-3, -1, np.where(np.abs(P_hw[:,0] - env_x) < 1e-3, 1, 0))
                            N[:,1] = np.where(np.abs(P_hw[:,1]) < 1e-3, -1, np.where(np.abs(P_hw[:,1] - env_y) < 1e-3, 1, 0))
                        
                        N[:, 2] = 0
                        N = N / (np.linalg.norm(N, axis=1, keepdims=True) + 1e-9)
                        dot = np.sum(D[hit_wall] * N, axis=1, keepdims=True)
                        D_new = D[hit_wall] - 2 * dot * N
                        
                        P_mc[active.nonzero()[0][hit_wall]] = P_hw
                        D_mc[active.nonzero()[0][hit_wall]] = normalize(D_new)
                        W_mc[active.nonzero()[0][hit_wall]] *= r_wall
                        
                    if np.any(hit_floor):
                        W_mc[active.nonzero()[0][hit_floor]] = 0.0

                    if np.any(hit_scat):
                        P_hs = P[hit_scat] + t_scat[hit_scat][:, np.newaxis] * D[hit_scat]
                        D_new = sample_henyey_greenstein(D[hit_scat], g_hg)
                        
                        P_mc[active.nonzero()[0][hit_scat]] = P_hs
                        D_mc[active.nonzero()[0][hit_scat]] = D_new
                        W_mc[active.nonzero()[0][hit_scat]] *= omega_active[hit_scat]

        return results