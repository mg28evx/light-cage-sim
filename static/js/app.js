window.measurements = [];
window.lastResults = null;
window.lastPayload = null;
window.lampProfiles = {}; 
let lampCount = 0; 
let currentAbortController = null;

const modeConfigs = {
    'estanque': { type: 'estanque', shape: 'circle', radio: 10, z_water: 3.2, env_z: 15.0, depths: '2.0, 1.0', kd_list: '0.20', n1: 1.0, n2: 1.33 },
    'jaula': { type: 'jaula', shape: 'rect', env_x: 30, env_y: 30, z_water: 20.0, env_z: 15.0, depths: '5.0, 10.0, 15.0', kd_list: '0.50', n1: 1.0, n2: 1.33 }
};

let currentSpaceType = 'estanque';

window.togglePreviewMode = window.togglePreviewMode || function togglePreviewModeFallback(mode) {
    const div2d = document.getElementById('heatmap_div_preview');
    const div3d = document.getElementById('scene3d_preview');
    const btn2d = document.getElementById('btn_preview_2d');
    const btn3d = document.getElementById('btn_preview_3d');
    const is3d = mode === '3d';

    if (div2d) div2d.style.display = is3d ? 'none' : 'block';
    if (div3d) {
        div3d.style.display = is3d ? 'block' : 'none';
        if (is3d && !window.scene3dModuleReady) {
            div3d.innerHTML = '<div class="scene3d-loading">Cargando visor 3D...</div>';
            setTimeout(() => {
                if (!window.scene3dModuleReady && div3d.style.display !== 'none') {
                    div3d.innerHTML = '<div class="scene3d-loading scene3d-error">No se pudo inicializar Three.js. Reinicia el servidor y recarga la página.</div>';
                }
            }, 2500);
        }
    }
    if (btn2d) btn2d.classList.toggle('active', !is3d);
    if (btn3d) btn3d.classList.toggle('active', is3d);
};

function showStatusMessage(msg, color="var(--evolux-yellow)") {
    const status = document.getElementById('status-text');
    status.innerText = msg; status.style.color = color;
    setTimeout(() => { status.innerText = "Listo"; status.style.color = "#ccc"; }, 4000);
}

function getLampPrefix(xmlName) {
    let base = xmlName.replace(/\.(xml|ies)$/i, '').trim();
    let parts = base.split(/[\s_\-]+/); 
    let prefix = "";
    if (parts.length > 1) {
        prefix = parts.slice(0, 3).map(p => p.charAt(0).toUpperCase()).join('');
    } else {
        prefix = base.substring(0, 3).toUpperCase();
    }
    return prefix;
}

function updateLampNames() {
    const containers = document.querySelectorAll('.lamp-group-container');
    containers.forEach(container => {
        const model = container.getAttribute('data-model');
        const prefix = getLampPrefix(model);
        const items = container.querySelectorAll('.lamp-item');
        
        const profile = window.lampProfiles[model];
        let extraInfo = '';
        if (profile && profile.elec_power && profile.efficiency) {
            let wpe = (profile.efficiency * 100).toFixed(1);
            extraInfo = ` <span style="font-weight:normal; font-size:11px; color:#1f77b4; margin-left:10px;">[Eficiencia WPE: ${wpe}%]</span>`;
        }

        items.forEach((item, index) => {
            const label = `${prefix}${index + 1}`;
            item.setAttribute('data-label', label);
            const titleEl = item.querySelector('.lamp-title-text');
            if(titleEl) titleEl.innerHTML = `${label} - ${model}${extraInfo}`;
        });
    });
}

function togglePinealParams() {
    const el = document.getElementById('irradiance_type');
    const panel = document.getElementById('pineal_params');
    if (el && panel) {
        panel.style.display = el.value === 'pineal' ? 'block' : 'none';
    }
}

async function fetchLampProfile(xml_name) {
    if (!xml_name) return null;
    
    const applyDataToUI = (data) => {
        document.querySelectorAll('.lamp-item').forEach(item => {
            if (item.querySelector('.lamp-xml').value === xml_name) {
                const effInput = item.querySelector('.lamp-eff');
                if (effInput && data.efficiency) {
                    effInput.value = data.efficiency;
                }
                updateLampEfficiency(item.querySelector('.lamp-power'));
            }
        });
        updateLampNames();
    };

    if (window.lampProfiles[xml_name]) {
        applyDataToUI(window.lampProfiles[xml_name]);
        updateScene();
        return window.lampProfiles[xml_name];
    }
    
    try {
        const res = await fetch('/api/lamp_profile/' + encodeURIComponent(xml_name));
        const data = await res.json();
        if (!data.error) {
            window.lampProfiles[xml_name] = data;
            applyDataToUI(data);
            updateScene();
            return data;
        }
    } catch(e) { console.error("Error trayendo curva polar", e); }
}

// =============================================================================
//  Visualizador de lámparas (polar IES + beam 3D)
// =============================================================================
function ensureLampDiagModal() {
    let modal = document.getElementById('lamp_diag_modal');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'lamp_diag_modal';
    modal.style.cssText = 'display:none; position:fixed; top:0; left:0; width:100vw; height:100vh; background:rgba(0,0,0,0.55); z-index:9999; align-items:center; justify-content:center;';
    modal.innerHTML = `
        <div id="lamp_diag_box" style="background:white; border-radius:8px; width:min(900px,95vw); max-height:92vh; overflow:auto; padding:18px 20px; box-shadow:0 8px 32px rgba(0,0,0,0.4); position:relative;">
            <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:2px solid var(--evolux-yellow); padding-bottom:8px; margin-bottom:12px;">
                <h3 id="lamp_diag_title" style="margin:0; color:#1f1f1f; font-size:15px;">Inspección de lámpara</h3>
                <button type="button" onclick="closeLampDiagnostic()" style="background:#eee; border:1px solid #aaa; border-radius:3px; padding:4px 10px; cursor:pointer; font-weight:bold;">Cerrar ✕</button>
            </div>
            <div style="display:flex; gap:8px; margin-bottom:8px;">
                <button type="button" id="lamp_diag_tab_polar" onclick="switchLampDiagTab('polar')" style="flex:1; padding:6px; cursor:pointer; border:1px solid #aaa; border-radius:3px;">Polar IES (C0/180 y C90/270)</button>
                <button type="button" id="lamp_diag_tab_3d" onclick="switchLampDiagTab('3d')" style="flex:1; padding:6px; cursor:pointer; border:1px solid #aaa; border-radius:3px;">Beam 3D</button>
            </div>
            <div id="lamp_diag_meta" style="font-size:11px; color:#333; margin-bottom:10px;"></div>
            <div id="lamp_diag_polar_plot" style="width:100%; height:520px;"></div>
            <div id="lamp_diag_3d_plot" style="width:100%; height:520px; display:none;"></div>
        </div>`;
    document.body.appendChild(modal);
    modal.addEventListener('click', (e) => { if (e.target === modal) closeLampDiagnostic(); });
    return modal;
}

function closeLampDiagnostic() {
    const m = document.getElementById('lamp_diag_modal');
    if (m) m.style.display = 'none';
}

function switchLampDiagTab(which) {
    const polar = document.getElementById('lamp_diag_polar_plot');
    const beam3 = document.getElementById('lamp_diag_3d_plot');
    const tabP = document.getElementById('lamp_diag_tab_polar');
    const tabB = document.getElementById('lamp_diag_tab_3d');
    if (which === 'polar') {
        polar.style.display = 'block'; beam3.style.display = 'none';
        tabP.style.background = 'var(--evolux-yellow)'; tabP.style.fontWeight = 'bold';
        tabB.style.background = '#fff'; tabB.style.fontWeight = 'normal';
    } else {
        polar.style.display = 'none'; beam3.style.display = 'block';
        tabB.style.background = 'var(--evolux-yellow)'; tabB.style.fontWeight = 'bold';
        tabP.style.background = '#fff'; tabP.style.fontWeight = 'normal';
        // Forzar relayout en caso de que el div estuviera oculto al crear la figura
        try { Plotly.Plots.resize(beam3); } catch(e) {}
    }
}

async function showLampDiagnostic(xml, initialTab) {
    const modal = ensureLampDiagModal();
    document.getElementById('lamp_diag_title').textContent = `Inspección de lámpara: ${xml.replace(/\.(xml|ies)$/i, '')}`;
    modal.style.display = 'flex';

    let profile = window.lampProfiles[xml];
    if (!profile) {
        profile = await fetchLampProfile(xml);
    }
    if (!profile) {
        document.getElementById('lamp_diag_meta').textContent = 'No se pudo cargar el perfil radiométrico de esta lámpara.';
        return;
    }

    const meta = [];
    if (profile.elec_power) meta.push(`Potencia eléctrica: <strong>${Number(profile.elec_power).toFixed(1)} W</strong>`);
    if (profile.rad_power) meta.push(`Flujo radiante: <strong>${Number(profile.rad_power).toFixed(1)} W</strong>`);
    if (profile.efficiency) meta.push(`WPE: <strong>${(profile.efficiency * 100).toFixed(1)}%</strong>`);
    document.getElementById('lamp_diag_meta').innerHTML = meta.join(' · ');

    // --- Curva polar (C0/180 y C90/270) en plotly polar -------------------
    const polarData = [
        {
            type: 'scatterpolar',
            r: profile.c0_180.rad,
            theta: profile.c0_180.theta,
            mode: 'lines', name: 'C0 / C180', line: { color: '#1f77b4', width: 3 }
        },
        {
            type: 'scatterpolar',
            r: profile.c90_270.rad,
            theta: profile.c90_270.theta,
            mode: 'lines', name: 'C90 / C270', line: { color: '#d62728', width: 3, dash: 'dot' }
        }
    ];
    const polarLayout = {
        title: { text: 'Distribución polar normalizada (radiante)', font: { size: 13 } },
        polar: {
            radialaxis: { tickformat: '.1f', range: [0, 1.05], showticklabels: true },
            angularaxis: { tickfont: { size: 10 }, rotation: 90, direction: 'clockwise' }
        },
        margin: { l: 50, r: 50, t: 60, b: 30 },
        showlegend: true
    };
    Plotly.newPlot('lamp_diag_polar_plot', polarData, polarLayout, { responsive: true });

    // --- Beam 3D (superficie sobre esfera normalizada por intensidad) ----
    const sg = profile.sphere_grid;
    if (sg && sg.rad_norm && sg.rad_norm.length) {
        const nH = sg.h_deg.length, nV = sg.v_deg.length;
        // r = intensidad normalizada (0..1) — escala visual
        const X = [], Y = [], Z = [], C = [];
        for (let i = 0; i < nH; i++) {
            const xr = [], yr = [], zr = [], cr = [];
            const phi = sg.h_deg[i] * Math.PI / 180;
            for (let j = 0; j < nV; j++) {
                const theta = sg.v_deg[j] * Math.PI / 180;
                const r = Math.max(sg.rad_norm[i][j], 0.001); // evita degenerate
                xr.push(r * Math.sin(theta) * Math.cos(phi));
                yr.push(r * Math.sin(theta) * Math.sin(phi));
                zr.push(-r * Math.cos(theta));               // lámpara apunta -Z
                cr.push(sg.rad_norm[i][j]);
            }
            X.push(xr); Y.push(yr); Z.push(zr); C.push(cr);
        }
        const beamData = [{
            type: 'surface', x: X, y: Y, z: Z, surfacecolor: C,
            colorscale: 'Hot', cmin: 0, cmax: 1, showscale: true,
            colorbar: { title: 'I(θ,φ) normalizada', thickness: 14 },
            contours: { z: { show: false } }
        }];
        const beamLayout = {
            title: { text: 'Lóbulo radiante 3D (radio ∝ I normalizada)', font: { size: 13 } },
            scene: {
                xaxis: { title: 'X', range: [-1.1, 1.1] },
                yaxis: { title: 'Y', range: [-1.1, 1.1] },
                zaxis: { title: 'Z (−z = abajo)', range: [-1.1, 1.1] },
                aspectmode: 'cube',
                camera: { eye: { x: 1.4, y: 1.4, z: 0.6 } }
            },
            margin: { l: 0, r: 0, t: 40, b: 0 }
        };
        Plotly.newPlot('lamp_diag_3d_plot', beamData, beamLayout, { responsive: true });
    } else {
        document.getElementById('lamp_diag_3d_plot').innerHTML = '<p style="text-align:center; color:#888; padding:30px;">Grilla 3D no disponible para esta lámpara.</p>';
    }

    switchLampDiagTab(initialTab || 'polar');
    return null;
}

function toggleOpticsPanel() {
    const mode = document.getElementById('optics_mode').value;
    document.getElementById('optics_kd_fijo').style.display = mode === 'kd_fijo' ? 'block' : 'none';
    document.getElementById('optics_kd_espectral').style.display = mode === 'kd_espectral' ? 'block' : 'none';
    document.getElementById('optics_scattering').style.display = mode === 'scattering' ? 'block' : 'none';
}

function toggleScatteringMode() {
    const val = document.getElementById('mc_input_type').value;
    document.getElementById('scat_bio').style.display = val === 'bio' ? 'block' : 'none';
    document.getElementById('scat_scalar').style.display = val === 'scalar' ? 'block' : 'none';
    document.getElementById('scat_spectral').style.display = val === 'json' ? 'block' : 'none';
}

function toggleRoiPanel() {
    const type = document.getElementById('roi_type').value;
    document.getElementById('roi_paral_panel').style.display = type === 'paralelepipedo' ? 'block' : 'none';
    document.getElementById('roi_cil_panel').style.display = type === 'cilindro' ? 'block' : 'none';
    updateScene();
}

function toggleShapePanel() {
    const shape = document.getElementById('env_shape').value;
    document.getElementById('shape_circle_inputs').style.display = shape === 'circle' ? 'block' : 'none';
    document.getElementById('shape_rect_inputs').style.display = shape === 'rect' ? 'block' : 'none';
    updateScene();
}

/**
 * Disco Secchi equivalente coherente con el backend:
 *   - Si el coeficiente declarado es Kd (atenuación difusa): Poole-Atkins, Z_SD = 1.7/Kd
 *   - Si el coeficiente declarado es c (atenuación del haz): se estima Kd ≈ c·(1-ω·g)/μ̄_d
 *     con ω=0.8, g=0.85, μ̄_d=0.85 (Gershun/Kirk) y se aplica Preisendorfer
 *     Z_SD ≈ 8.69/(c+Kd).
 */
function computeSecchi(coefVal, coefType) {
    if (!(coefVal > 0)) return 0;
    if ((coefType || 'c').toLowerCase() === 'kd') {
        return 1.7 / coefVal;
    }
    const omega = 0.8, g = 0.85, mu_d = 0.85;
    const kdEst = coefVal * (1.0 - omega * g) / mu_d;
    return 8.69 / (coefVal + kdEst);
}

function updateSecchi() {
    const secchiEl = document.getElementById('secchi_display');
    if (!secchiEl) return;
    const coefType = (document.getElementById('atten_coef_type') || {}).value || 'c';
    const kdRaw = document.getElementById('kd_list').value;
    const kds = kdRaw.split(',').map(v => parseFloat(v.trim())).filter(v => !isNaN(v) && v > 0);
    const secchis = kds.map(kd => computeSecchi(kd, coefType).toFixed(2) + 'm');
    const labelCoef = coefType.toLowerCase() === 'kd' ? 'Kd' : 'c';
    secchiEl.innerHTML = secchis.length ? `Eq. Disco Secchi (${labelCoef}): ${secchis.join(' | ')}` : '';
}

function updateAporteBadge() {
    const input = document.getElementById('aporte_puntos');
    const badge = document.getElementById('aporte_puntos_badge');
    if (!input || !badge) return;
    const raw = input.value.trim();
    if (!raw) { badge.textContent = '0 pts'; badge.style.color = '#888'; return; }
    let n_ok = 0, n_bad = 0;
    raw.split(';').forEach(part => {
        const c = part.split(',');
        if (c.length === 3 && c.every(v => !isNaN(parseFloat(v.trim())))) n_ok++;
        else if (part.trim().length > 0) n_bad++;
    });
    if (n_bad > 0) {
        badge.innerHTML = `<span style="color:#d32f2f;">${n_ok} ok · ${n_bad} mal formado</span>`;
    } else {
        badge.innerHTML = `<span style="color:#2ca02c;">${n_ok} pts ✓</span>`;
    }
}

function updateAttenLabels() {
    const selEl = document.getElementById('atten_coef_type');
    if (!selEl) return;
    const isKd = selEl.value.toLowerCase() === 'kd';
    const labelTxt = isKd ? 'Kd' : 'c';
    const lblFijo = document.getElementById('atten_coef_label_fijo');
    if (lblFijo) lblFijo.innerHTML = `<strong>${labelTxt} (fijo) [1/m]</strong>`;
    const lblEspect = document.getElementById('atten_coef_label_espect');
    if (lblEspect) lblEspect.innerHTML = `<strong>${labelTxt}(λ)</strong> <span class="normal-case">(JSON [nm: ${labelTxt}])</span>`;
}

function updateBioOpticalReference() {
    const tssInput = document.getElementById('scat_tss');
    const cdomInput = document.getElementById('scat_cdom');
    if (!tssInput || !cdomInput) return;

    const tss = parseFloat(tssInput.value) || 0;
    const cdom = parseFloat(cdomInput.value) || 0;

    const b_star = { 400: 0.50, 500: 0.35, 600: 0.28, 700: 0.22 };
    const aw = { 400: 0.01, 500: 0.02, 600: 0.24, 700: 0.65 };

    const calcC = (wl) => {
        const a_cdom = cdom * Math.exp(-0.015 * (wl - 440));
        const b_total = b_star[wl] * tss;
        const a_total = aw[wl] + a_cdom;
        return (a_total + b_total).toFixed(2);
    };

    const refText = `Equivalencia Atenuación (c): 400nm: ${calcC(400)} | 500nm: ${calcC(500)} | 600nm: ${calcC(600)} | 700nm: ${calcC(700)}`;

    let displayDiv = document.getElementById('bio_optics_ref_display');
    if (!displayDiv) {
        displayDiv = document.createElement('div');
        displayDiv.id = 'bio_optics_ref_display';
        displayDiv.style = "font-size:11px; color:#1f77b4; margin-top:8px; font-weight:bold; text-align:center; padding: 4px; border: 1px dashed #1f77b4; border-radius: 4px; background: white;";
        const scatBio = document.getElementById('scat_bio');
        if (scatBio) scatBio.appendChild(displayDiv);
    }
    displayDiv.innerText = refText;
}

function handleMeasurementUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    showStatusMessage("Leyendo archivo...", "white");
    const reader = new FileReader();
    reader.onload = function(e) {
        try {
            const data = new Uint8Array(e.target.result);
            const workbook = XLSX.read(data, {type: 'array'});
            const worksheet = workbook.Sheets[workbook.SheetNames[0]];
            const json = XLSX.utils.sheet_to_json(worksheet, {header: 1, defval: null});
            
            let parsedData = [];
            const pointsValidForKd = {}; 
            let xIdx = -1, yIdx = -1, zIdx = -1, valIdx = -1, startRow = -1;

            for (let i = 0; i < json.length; i++) {
                const row = json[i];
                if (!row || !row.length) continue;
                let tempX = -1, tempY = -1, tempZ = -1, tempVal = -1;
                for (let j = 0; j < row.length; j++) {
                    let cell = String(row[j] || '').toLowerCase().trim();
                    if (cell === 'x') tempX = j;
                    else if (cell === 'y') tempY = j;
                    else if (cell === 'z' || cell === 'profundidad' || cell === 'altura') tempZ = j;
                    else if (cell.includes('w/m') || cell.includes('val') || cell.includes('irr') || cell === 'e') tempVal = j;
                }
                if (tempX !== -1 && tempY !== -1 && tempZ !== -1 && tempVal !== -1) {
                    xIdx = tempX; yIdx = tempY; zIdx = tempZ; valIdx = tempVal; startRow = i + 1; break;
                }
            }

            if (startRow !== -1) {
                for (let i = startRow; i < json.length; i++) {
                    const row = json[i];
                    if (!row || row.length <= Math.max(xIdx, yIdx, zIdx, valIdx)) continue;
                    let x = parseFloat(row[xIdx]), y = parseFloat(row[yIdx]), z = parseFloat(row[zIdx]), val = parseFloat(row[valIdx]);
                    if (!isNaN(x) && !isNaN(y) && !isNaN(z) && !isNaN(val)) {
                        parsedData.push({x, y, z, val});
                        if (val > 0) {
                            const ptKey = `${x},${y}`;
                            if (!pointsValidForKd[ptKey]) pointsValidForKd[ptKey] = 0;
                            pointsValidForKd[ptKey]++;
                        }
                    }
                }
            }

            if (parsedData.length > 0) {
                window.measurements = parsedData;
                document.getElementById('meas_status').innerText = `Cargados ${parsedData.length} puntos.`;
                
                const kdSelector = document.getElementById('meas_point_selector');
                kdSelector.innerHTML = '<option value="">Seleccione coordenada (X,Y)...</option>';
                let addedPoints = 0;
                Object.keys(pointsValidForKd).forEach(pt => {
                    if (pointsValidForKd[pt] >= 2) {
                        kdSelector.innerHTML += `<option value="${pt}">Punto X=${pt.split(',')[0]}, Y=${pt.split(',')[1]}</option>`;
                        addedPoints++;
                    }
                });
                if (addedPoints === 0) kdSelector.innerHTML = '<option value="">Ningún punto con pares válidos (>0 W/m²)</option>';
                updateScene(); showStatusMessage("Archivo listo");
            } else {
                document.getElementById('meas_status').innerText = "Error: Columnas inválidas.";
            }
        } catch (err) { console.error(err); document.getElementById('meas_status').innerText = "Error al procesar."; }
    };
    reader.readAsArrayBuffer(file);
}

function calcKdFromMeasurements() {
    const pt = document.getElementById('meas_point_selector').value;
    if (!pt) { alert("Seleccione un punto válido."); return; }
    const targetX = parseFloat(pt.split(',')[0]);
    const targetY = parseFloat(pt.split(',')[1]);

    fetch('/api/calc_kd', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ x: targetX, y: targetY, measurements: window.measurements })
    }).then(r => r.json()).then(data => {
        if (data.status === 'ok') {
            const resArea = document.getElementById('results_dynamic_area');
            if(!resArea) return;
            let html = `<div class="graph-wrapper result-graph" style="border-top: 4px solid #1f77b4; width: 100%;">
                            <div class="graph-title" style="color:#1f77b4;">Resultados Kd Empírico en (X=${targetX}, Y=${targetY})</div>
                            <div style="display:flex; flex-direction:column; gap:5px; padding:10px;">`;
            if (data.kds.length === 0) { html += `<div>No hay pares válidos.</div>`; } 
            else {
                data.kds.forEach(r => {
                    html += `<div style="background:#f8f9fa; padding:8px; border-radius:4px; border:1px solid #eee;">
                               Z=${r.z1}m ➔ Z=${r.z2}m: <strong>Kd = ${r.kd.toFixed(3)}</strong>
                             </div>`;
                });
            }
            html += `</div></div>`;
            resArea.insertAdjacentHTML('afterbegin', html);
        }
    });
}

function applyModeSettings() {
    const config = modeConfigs[document.getElementById('mode-selector').value] || modeConfigs['estanque'];
    if(config) {
        currentSpaceType = config.type;
        document.getElementById('env_shape').value = config.shape;

        if(config.type === 'estanque') {
            document.getElementById('env_z_container').style.display = 'none';
            document.getElementById('env_radio').value = config.radio;
            
            document.getElementById('z_water_container').style.display = 'block';
            document.getElementById('z_water').value = config.z_water;
            document.getElementById('env_n1_container').style.display = 'block';
            document.getElementById('env_n2_label').innerHTML = '<strong>Índice ref. medio 2</strong> <span class="normal-case">(Agua)</span>';
            document.getElementById('wall_albedo_container').style.display = 'block';
        } else {
            document.getElementById('env_z_container').style.display = 'block';
            document.getElementById('env_x').value = config.env_x;
            document.getElementById('env_y').value = config.env_y;
            document.getElementById('env_z').value = config.env_z;
            
            document.getElementById('z_water_container').style.display = 'none';
            document.getElementById('env_n1_container').style.display = 'none';
            document.getElementById('env_n2_label').innerHTML = '<strong>Índice ref. medio</strong> <span class="normal-case">(Agua)</span>';
            document.getElementById('wall_albedo_container').style.display = 'none';
        }
        
        toggleShapePanel();
        
        document.getElementById('kd_list').value = config.kd_list;
        document.getElementById('target_depths').value = config.depths;
        document.getElementById('env_n1').value = config.n1 || 1.0;
        document.getElementById('env_n2').value = config.n2 || 1.33;
        
        updateSecchi();
        updateGlobalLampControls();
        updateScene(); updateLampLabels();
    }
}

function toggleSpectrumPanel() {
    const show = document.getElementById('plot_spectrum_initial').checked || document.getElementById('plot_spectrum_normalized').checked || document.getElementById('plot_env_optics').checked;
    document.getElementById('spectrum_panel').style.display = show ? 'block' : 'none';
}

function infer3DModelDefaults(xml) {
    const name = String(xml || '').toLowerCase();
    if (name.includes('nexus') || name.includes('slim') || name.includes('fish')) {
        return {shape: 'box', length: 1.25, width: 0.16, height: 0.10};
    }
    if (name.includes('tempest') || name.includes('asteria')) {
        return {shape: 'cylinder', length: 0.55, width: 0.22, height: 0.22};
    }
    return {shape: 'cylinder', length: 0.60, width: 0.25, height: 0.25};
}

function get3DModelSettings() {
    const settings = {};
    document.querySelectorAll('.scene3d-model-row').forEach(row => {
        const xml = row.getAttribute('data-xml');
        settings[xml] = {
            shape: row.querySelector('.scene3d-model-shape').value,
            length: parseFloat(row.querySelector('.scene3d-model-length').value) || 0.6,
            width: parseFloat(row.querySelector('.scene3d-model-width').value) || 0.25,
            height: parseFloat(row.querySelector('.scene3d-model-height').value) || 0.25
        };
    });
    return settings;
}

function get3DRenderSettings() {
    return {
        show_water: document.getElementById('scene3d_show_water') ? document.getElementById('scene3d_show_water').checked : true,
        show_walls: document.getElementById('scene3d_show_walls') ? document.getElementById('scene3d_show_walls').checked : true,
        show_grid: document.getElementById('scene3d_show_grid') ? document.getElementById('scene3d_show_grid').checked : true,
        show_axes: document.getElementById('scene3d_show_axes') ? document.getElementById('scene3d_show_axes').checked : true,
        show_beams: document.getElementById('scene3d_show_beams') ? document.getElementById('scene3d_show_beams').checked : true,
        show_labels: document.getElementById('scene3d_show_labels') ? document.getElementById('scene3d_show_labels').checked : true,
        show_raytrace: document.getElementById('scene3d_show_raytrace') ? document.getElementById('scene3d_show_raytrace').checked : true,
        bio_attenuation: document.getElementById('scene3d_bio_attenuation') ? document.getElementById('scene3d_bio_attenuation').checked : true,
        water_opacity: parseFloat(document.getElementById('scene3d_water_opacity')?.value) || 0.22,
        beam_opacity: parseFloat(document.getElementById('scene3d_beam_opacity')?.value) || 0.28,
        lamp_scale: parseFloat(document.getElementById('scene3d_lamp_scale')?.value) || 1.0,
        exposure: parseFloat(document.getElementById('scene3d_exposure')?.value) || 1.0,
        raytrace_opacity: parseFloat(document.getElementById('scene3d_raytrace_opacity')?.value) || 0.72,
        preset: document.getElementById('scene3d_preset')?.value || 'technical'
    };
}

function open3DSettingsPanel() {
    const buttons = Array.from(document.getElementsByClassName('accordion'));
    const btn = buttons.find(el => el.textContent.includes('VISUALIZACIÓN 3D'));
    if (!btn) {
        showStatusMessage("No se encontró la lámina de Visualización 3D", "red");
        return;
    }
    const panel = btn.nextElementSibling;
    if (panel && !panel.classList.contains('show')) {
        btn.classList.add('active');
        panel.style.display = 'block';
        panel.classList.add('show');
    }
    btn.scrollIntoView({behavior: 'smooth', block: 'center'});
}

function apply3DRenderPreset(preset) {
    const presets = {
        technical: {
            show_water: true, show_walls: true, show_grid: true, show_axes: true,
            show_beams: true, show_labels: true, show_raytrace: true, bio_attenuation: true,
            water_opacity: 0.20, beam_opacity: 0.24, lamp_scale: 1.0, exposure: 1.0, raytrace_opacity: 0.72
        },
        presentation: {
            show_water: true, show_walls: true, show_grid: false, show_axes: false,
            show_beams: true, show_labels: true, show_raytrace: true, bio_attenuation: true,
            water_opacity: 0.32, beam_opacity: 0.38, lamp_scale: 1.2, exposure: 1.25, raytrace_opacity: 0.80
        },
        turbid: {
            show_water: true, show_walls: true, show_grid: false, show_axes: false,
            show_beams: true, show_labels: true, show_raytrace: true, bio_attenuation: true,
            water_opacity: 0.48, beam_opacity: 0.52, lamp_scale: 1.15, exposure: 0.9, raytrace_opacity: 0.85
        },
        wireframe: {
            show_water: false, show_walls: true, show_grid: true, show_axes: true,
            show_beams: false, show_labels: true, show_raytrace: false, bio_attenuation: false,
            water_opacity: 0.1, beam_opacity: 0.1, lamp_scale: 1.0, exposure: 1.0, raytrace_opacity: 0.5
        }
    };
    const cfg = presets[preset] || presets.technical;
    const ids = {
        show_water: 'scene3d_show_water',
        show_walls: 'scene3d_show_walls',
        show_grid: 'scene3d_show_grid',
        show_axes: 'scene3d_show_axes',
        show_beams: 'scene3d_show_beams',
        show_labels: 'scene3d_show_labels',
        show_raytrace: 'scene3d_show_raytrace',
        bio_attenuation: 'scene3d_bio_attenuation'
    };
    Object.entries(ids).forEach(([key, id]) => {
        const el = document.getElementById(id);
        if (el) el.checked = cfg[key];
    });
    const nums = {
        water_opacity: 'scene3d_water_opacity',
        beam_opacity: 'scene3d_beam_opacity',
        lamp_scale: 'scene3d_lamp_scale',
        exposure: 'scene3d_exposure',
        raytrace_opacity: 'scene3d_raytrace_opacity'
    };
    Object.entries(nums).forEach(([key, id]) => {
        const el = document.getElementById(id);
        if (el) el.value = cfg[key];
    });
    const presetEl = document.getElementById('scene3d_preset');
    if (presetEl) presetEl.value = preset;
    updateScene();
}

function setScene3DTransformMode(mode) {
    if (window.scene3dSetTransformMode) window.scene3dSetTransformMode(mode);
    else showStatusMessage("Abra la vista 3D antes de usar el gizmo", "white");
}

function clearScene3DSelection() {
    if (window.scene3dClearSelection) window.scene3dClearSelection();
}

function update3DLampModelControls() {
    const container = document.getElementById('scene3d_lamp_models');
    if (!container) return;

    const uniqueLamps = new Set();
    document.querySelectorAll('.lamp-xml').forEach(input => uniqueLamps.add(input.value));
    const existing = get3DModelSettings();

    if (uniqueLamps.size === 0) {
        container.innerHTML = '<span style="font-size:11px; color:#999;">Agregue lámparas para configurar su geometría 3D.</span>';
        return;
    }

    let html = '';
    uniqueLamps.forEach(xml => {
        const defaults = infer3DModelDefaults(xml);
        const cfg = existing[xml] || defaults;
        html += `
            <div class="scene3d-model-row" data-xml="${xml}">
                <div class="scene3d-model-title">${xml}</div>
                <div class="scene3d-model-controls">
                    <div>
                        <label>Forma</label>
                        <select class="scene3d-model-shape" onchange="updateScene()">
                            <option value="cylinder" ${cfg.shape === 'cylinder' ? 'selected' : ''}>Circular</option>
                            <option value="box" ${cfg.shape === 'box' ? 'selected' : ''}>Paralelepípeda</option>
                        </select>
                    </div>
                    <div>
                        <label>Largo (m)</label>
                        <input type="number" class="scene3d-model-length" value="${cfg.length}" min="0.01" step="0.05" oninput="updateScene()">
                    </div>
                    <div>
                        <label>Ancho/Diam. (m)</label>
                        <input type="number" class="scene3d-model-width" value="${cfg.width}" min="0.01" step="0.05" oninput="updateScene()">
                    </div>
                    <div>
                        <label>Alto (m)</label>
                        <input type="number" class="scene3d-model-height" value="${cfg.height}" min="0.01" step="0.05" oninput="updateScene()">
                    </div>
                </div>
            </div>`;
    });
    container.innerHTML = html;
}

function apply3DSceneSettings(scene3dConfig) {
    if (!scene3dConfig) return;
    const render = scene3dConfig.render || {};
    const checkboxMap = {
        show_water: 'scene3d_show_water',
        show_walls: 'scene3d_show_walls',
        show_grid: 'scene3d_show_grid',
        show_axes: 'scene3d_show_axes',
        show_beams: 'scene3d_show_beams',
        show_labels: 'scene3d_show_labels',
        show_raytrace: 'scene3d_show_raytrace',
        bio_attenuation: 'scene3d_bio_attenuation'
    };
    Object.keys(checkboxMap).forEach(key => {
        if (render[key] !== undefined && document.getElementById(checkboxMap[key])) {
            document.getElementById(checkboxMap[key]).checked = Boolean(render[key]);
        }
    });

    const numericMap = {
        water_opacity: 'scene3d_water_opacity',
        beam_opacity: 'scene3d_beam_opacity',
        lamp_scale: 'scene3d_lamp_scale',
        exposure: 'scene3d_exposure',
        raytrace_opacity: 'scene3d_raytrace_opacity',
        preset: 'scene3d_preset'
    };
    Object.keys(numericMap).forEach(key => {
        if (render[key] !== undefined && document.getElementById(numericMap[key])) {
            document.getElementById(numericMap[key]).value = render[key];
        }
    });

    const models = scene3dConfig.lamp_models || {};
    Object.keys(models).forEach(xml => {
        const row = document.querySelector(`.scene3d-model-row[data-xml="${xml}"]`);
        if (!row) return;
        const cfg = models[xml];
        if (cfg.shape !== undefined) row.querySelector('.scene3d-model-shape').value = cfg.shape;
        if (cfg.length !== undefined) row.querySelector('.scene3d-model-length').value = cfg.length;
        if (cfg.width !== undefined) row.querySelector('.scene3d-model-width').value = cfg.width;
        if (cfg.height !== undefined) row.querySelector('.scene3d-model-height').value = cfg.height;
    });
}

function updateGlobalLampControls() {
    const uniqueLamps = new Set();
    document.querySelectorAll('.lamp-xml').forEach(input => uniqueLamps.add(input.value));
    const container = document.getElementById('global_lamps_container');

    const existing = {};
    container.querySelectorAll('.global-lamp-group').forEach(group => {
        const xml = group.getAttribute('data-xml');
        existing[xml] = {
            power: group.querySelector('.glob-power').value,
            z: group.querySelector('.glob-z').value
        };
    });

    let html = '';
    if (uniqueLamps.size > 0) {
        html += '<div style="font-size: 11px; font-weight: bold; margin-bottom: 5px;">Parámetros Globales por Modelo</div>';
    }
    uniqueLamps.forEach(xml => {
        const pwr = existing[xml] ? existing[xml].power : 600;
        const defZ = existing[xml] ? existing[xml].z : (currentSpaceType === 'estanque' ? parseFloat(document.getElementById('z_water').value) + 0.5 : 2.0);

        html += `
        <div class="global-lamp-group" data-xml="${xml}" style="background:#f4f8fb; padding:8px; border:1px solid #c8d4df; margin-bottom:5px; border-radius:4px;">
            <div style="font-size:11px; font-weight:bold; color:#1f77b4; margin-bottom:4px; text-transform:uppercase;">${xml}</div>
            <div style="display:flex; gap:10px;">
                <div style="flex:1;"><label style="font-size:10px; font-weight:bold; display:block;">Potencia Eléctrica (W)</label><input type="number" class="glob-power" value="${pwr}" oninput="applyGlobal('${xml}', 'power', this.value)" style="padding:4px !important; font-size:11px !important;"></div>
                <div style="flex:1;"><label style="font-size:10px; font-weight:bold; display:block;">Altura Z (m)</label><input type="number" class="glob-z" value="${defZ}" oninput="applyGlobal('${xml}', 'z', this.value)" style="padding:4px !important; font-size:11px !important;"></div>
            </div>
        </div>`;
    });
    container.innerHTML = html;
    updateUniqueLampsForSpectrum();
    update3DLampModelControls();
}

function getGlobalLampSettings() {
    const settings = {};
    document.querySelectorAll('.global-lamp-group').forEach(group => {
        const xml = group.getAttribute('data-xml');
        settings[xml] = {
            power: parseFloat(group.querySelector('.glob-power').value) || 0,
            z: parseFloat(group.querySelector('.glob-z').value) || 0
        };
    });
    return settings;
}

function updateLampEfficiency(input) {
    if (!input) return;
    const item = input.closest('.lamp-item');
    if (!item) return;
    const power = parseFloat(input.value) || 0;
    const effInput = item.querySelector('.lamp-eff');
    const eff = effInput ? parseFloat(effInput.value) || 1.0 : 1.0;
    const rad = power * eff;
    const badge = item.querySelector('.eff-badge');
    if (badge) {
        badge.innerHTML = `Eficiencia WPE: <strong>${(eff*100).toFixed(1)}%</strong> | F. Radiante: <strong style="color:#d62728;">${rad.toFixed(2)} W</strong>`;
    }
}

function applyGlobal(xml, type, value) {
    document.querySelectorAll('.lamp-item').forEach(item => {
        if (item.querySelector('.lamp-xml').value === xml) {
            const input = item.querySelector(type === 'power' ? '.lamp-power' : '.lamp-z');
            if (input.getAttribute('data-manual') !== 'true') {
                input.value = value;
                input.style.opacity = '0.5';
                if (type === 'power') updateLampEfficiency(input);
            }
        }
    });
    updateScene();
}

function removeLampManualOverride(inputElement) {
    inputElement.style.opacity = '1';
    inputElement.setAttribute('data-manual', 'true');
    updateScene();
}

function updateUniqueLampsForSpectrum() {
    const container = document.getElementById('spectrum_lamp_list');
    if (!container) return;
    const uniqueLamps = new Set();
    document.querySelectorAll('.lamp-xml').forEach(input => uniqueLamps.add(input.value));
    const currentlyChecked = new Set();
    container.querySelectorAll('.spectrum-lamp-cb:checked').forEach(cb => currentlyChecked.add(cb.value));
    container.innerHTML = '';
    if(uniqueLamps.size === 0) { container.innerHTML = '<span style="color:#999; font-size:11px;">Agregue lámparas primero</span>'; return; }
    
    uniqueLamps.forEach(lampXml => {
        const isChecked = currentlyChecked.has(lampXml) || currentlyChecked.size === 0 ? 'checked' : '';
        container.innerHTML += `<div style="display: flex; align-items: center; gap: 5px; font-size: 11px; margin-bottom: 3px; cursor: pointer;"><input type="checkbox" class="spectrum-lamp-cb" value="${lampXml}" ${isChecked} style="width:auto;"> <span class="normal-case">${lampXml}</span></div>`;
        if (currentlyChecked.size === 0) currentlyChecked.add(lampXml);
    });
}

function updateLampLabels() {
    const txt = currentSpaceType === 'estanque' ? 'Altura desde fondo (m)' : 'Profundidad Z (m)';
    document.querySelectorAll('.z-label').forEach(lbl => lbl.innerHTML = `<strong>${txt}</strong>`);
    const simLbl = document.getElementById('lbl_target_depths');
    if (simLbl) simLbl.innerHTML = currentSpaceType === 'estanque' ? '<strong>Profundidades a graficar irradiancia</strong> <span class="normal-case">(metros desde el fondo, separadas por coma)</span>' : '<strong>Profundidades a graficar irradiancia</strong> <span class="normal-case">(metros, separadas por coma)</span>';
}

function getSpaceDimensions() {
    const shape = document.getElementById('env_shape').value;
    if (shape === 'circle') {
        const r = parseFloat(document.getElementById('env_radio').value) || 20;
        return { x: r * 2, y: r * 2, shape: 'circle', radius: r };
    } else {
        return { x: parseFloat(document.getElementById('env_x').value) || 40, y: parseFloat(document.getElementById('env_y').value) || 40, shape: 'rect' };
    }
}

function getAxisTicks(maxVal) {
    let labelStep = 1;
    if (maxVal > 50) labelStep = 10;
    else if (maxVal > 20) labelStep = 5;
    else if (maxVal > 10) labelStep = 2;

    let vals = [];
    let texts = [];
    for (let i = -1; i <= Math.ceil(maxVal) + 1; i++) {
        vals.push(i);
        texts.push(i % labelStep === 0 ? i.toString() : '');
    }
    return { vals, texts };
}

function getPlotTraces() {
    const traces = [];
    const dims = getSpaceDimensions();
    const zInterface = parseFloat(document.getElementById('z_water').value) || 0;
    const activeAerial = document.getElementById('toggle_aerial').checked;
    const activeSubmerged = document.getElementById('toggle_submerged').checked;

    const bgSize = 20;
    const zBg = Array(bgSize).fill().map(() => Array(bgSize).fill(0));
    const xBg = Array.from({length: bgSize}, (_, i) => (i / (bgSize-1)) * dims.x);
    const yBg = Array.from({length: bgSize}, (_, i) => (i / (bgSize-1)) * dims.y);
    
    traces.push({
        z: zBg, x: xBg, y: yBg, type: 'heatmap', showscale: false,
        colorscale: [[0, 'rgba(0,0,0,0)'], [1, 'rgba(0,0,0,0)']], hoverinfo: 'none', name: 'Fondo'
    });

    if (dims.shape === 'circle') {
        let cx = dims.x / 2, cy = dims.y / 2, r = dims.radius;
        let bx = [], by = [];
        for(let i=0; i<=100; i++) {
            let angle = i * 2 * Math.PI / 100;
            bx.push(cx + r * Math.cos(angle));
            by.push(cy + r * Math.sin(angle));
        }
        traces.push({x: bx, y: by, mode: 'lines', line: {color: 'rgba(255, 199, 44, 1)', width: 2, dash: 'dash'}, hoverinfo: 'none', showlegend: false, name: 'Límite Estanque'});
    } else {
        traces.push({x: [0, dims.x, dims.x, 0, 0], y: [0, 0, dims.y, dims.y, 0], mode: 'lines', line: {color: 'rgba(255, 199, 44, 1)', width: 2, dash: 'dash'}, hoverinfo: 'none', showlegend: false, name: 'Límite Jaula'});
    }

    let roiType = document.getElementById('roi_type').value;
    if (roiType === 'paralelepipedo') {
        let cx = parseFloat(document.getElementById('roi_p_cx').value) || 0;
        let cy = parseFloat(document.getElementById('roi_p_cy').value) || 0;
        let l = parseFloat(document.getElementById('roi_p_l').value) || 0;
        let w = parseFloat(document.getElementById('roi_p_w').value) || 0;
        traces.push({x: [cx-l/2, cx+l/2, cx+l/2, cx-l/2, cx-l/2], y: [cy-w/2, cy-w/2, cy+w/2, cy+w/2, cy-w/2], mode: 'lines', line: {color: 'rgba(214, 39, 40, 0.8)', width: 2, dash: 'dashdot'}, hoverinfo: 'none', showlegend: false, name: 'ROI'});
    } else if (roiType === 'cilindro') {
        let cx = parseFloat(document.getElementById('roi_c_cx').value) || 0;
        let cy = parseFloat(document.getElementById('roi_c_cy').value) || 0;
        let r = parseFloat(document.getElementById('roi_c_r').value) || 0;
        let bx = [], by = [];
        for(let i=0; i<=50; i++) {
            let angle = i * 2 * Math.PI / 50;
            bx.push(cx + r * Math.cos(angle));
            by.push(cy + r * Math.sin(angle));
        }
        traces.push({x: bx, y: by, mode: 'lines', line: {color: 'rgba(214, 39, 40, 0.8)', width: 2, dash: 'dashdot'}, hoverinfo: 'none', showlegend: false, name: 'ROI'});
    }

    let numSides = parseInt(document.getElementById('poly_sides').value) || 0;
    let polyDist = parseFloat(document.getElementById('poly_dist').value) || 0;
    if (numSides >= 3 && polyDist > 0) {
        let cx = dims.x / 2, cy = dims.y / 2;
        let px = [], py = [];
        for (let i = 0; i <= numSides; i++) {
            let angle = (i * 2 * Math.PI) / numSides - Math.PI / 2; 
            px.push(cx + polyDist * Math.cos(angle));
            py.push(cy + polyDist * Math.sin(angle));
        }
        traces.push({ x: px, y: py, mode: 'lines', line: { color: 'rgba(31, 119, 180, 0.8)', width: 1.5, dash: 'dot' }, hoverinfo: 'none', showlegend: false, name: 'Polígono Ref.' });
    }

    const lampTextX = [], lampTextY = [], lampText = [];
    const aerialX = [], aerialY = [], aerialText = [], aerialOpacity = [];
    const submergedX = [], submergedY = [], submergedText = [], submergedOpacity = [];
    
    document.querySelectorAll('.lamp-item').forEach((item, index) => {
        let x = parseFloat(item.querySelector('.lamp-x').value) || 0;
        let y = parseFloat(item.querySelector('.lamp-y').value) || 0;
        let z = parseFloat(item.querySelector('.lamp-z').value) || 0;
        let rx = parseFloat(item.querySelector('.lamp-rot-x').value) || 0;
        let ry = parseFloat(item.querySelector('.lamp-rot-y').value) || 0;
        let rz = parseFloat(item.querySelector('.lamp-rot-z').value) || 0;
        let xml = item.querySelector('.lamp-xml').value;

        let isAerial = (currentSpaceType === 'estanque' && z > zInterface) || (currentSpaceType === 'jaula' && z < 0);
        const isOn = isAerial ? activeAerial : activeSubmerged;

        let label = item.getAttribute('data-label') || `L${index + 1}`;
        lampTextX.push(x); lampTextY.push(y); lampText.push(isOn ? label : `${label} OFF`);
        if (isAerial) {
            aerialX.push(x); aerialY.push(y); aerialText.push(label); aerialOpacity.push(isOn ? 1.0 : 0.25);
        } else {
            submergedX.push(x); submergedY.push(y); submergedText.push(label); submergedOpacity.push(isOn ? 1.0 : 0.25);
        }

        let profile = window.lampProfiles[xml];
        if (profile) {
            const VISUAL_SCALE = parseFloat(document.getElementById('beam_scale').value) || 8.0; 
            const radX = rx * Math.PI / 180, radY = ry * Math.PI / 180, radZ = rz * Math.PI / 180;
            const cosX = Math.cos(radX), sinX = Math.sin(radX);
            const cosY = Math.cos(radY), sinY = Math.sin(radY);
            const cosZ = Math.cos(radZ), sinZ = Math.sin(radZ);
            
            let polyAlpha = isOn ? 0.8 : 0.25;
            let fillAlpha = isOn ? 0.25 : 0.07;
            let polyColor = isAerial ? `rgba(255, 199, 44, ${polyAlpha})` : `rgba(0, 191, 255, ${polyAlpha})`;
            let polyFill = isAerial ? `rgba(255, 199, 44, ${fillAlpha})` : `rgba(0, 191, 255, ${fillAlpha})`;

            function projectPlane(planeData, isC90) {
                let ptsX = [], ptsY = [];
                for (let i=0; i < planeData.theta.length; i++) {
                    let theta = planeData.theta[i] * Math.PI / 180;
                    let r = planeData.rad[i] * VISUAL_SCALE;
                    let lx = 0, lz = 0, ly = 0; 
                    
                    if (!isC90) {
                        lx = r * Math.sin(theta);
                        lz = -r * Math.cos(theta);
                    } else {
                        ly = r * Math.sin(theta);
                        lz = -r * Math.cos(theta);
                    }

                    let y1 = ly * cosX - lz * sinX;
                    let z1 = ly * sinX + lz * cosX;
                    let x1 = lx * cosY + z1 * sinY;
                    let x2 = x1 * cosZ - y1 * sinZ;
                    let y2 = x1 * sinZ + y1 * cosZ;
                    
                    ptsX.push(x + x2); ptsY.push(y + y2);
                }
                return {x: ptsX, y: ptsY};
            }
            
            let p0 = projectPlane(profile.c0_180, false);
            let p90 = projectPlane(profile.c90_270, true);

            traces.push({
                x: p0.x, y: p0.y, mode: 'lines', fill: 'toself',
                fillcolor: polyFill, line: {color: polyColor, width: 2},
                hoverinfo: 'none', showlegend: false, name: `${label} C0`
            });

            traces.push({
                x: p90.x, y: p90.y, mode: 'lines', fill: 'toself',
                fillcolor: 'rgba(31, 119, 180, 0.1)', line: {color: polyColor, width: 2, dash: 'dot'},
                hoverinfo: 'none', showlegend: false, name: `${label} C90`
            });
        } else {
            fetchLampProfile(xml);
        }
    });

    if (aerialX.length > 0) {
        traces.push({
            x: aerialX, y: aerialY, mode: 'markers', type: 'scatter', name: 'Lámparas aéreas',
            marker: { size: 12, color: '#FFD700', symbol: 'diamond', line: { color: 'black', width: 1.5 }, opacity: aerialOpacity },
            text: aerialText, hovertemplate: '%{text}<br>Aérea<extra></extra>', showlegend: true
        });
    }

    if (submergedX.length > 0) {
        traces.push({
            x: submergedX, y: submergedY, mode: 'markers', type: 'scatter', name: 'Lámparas sumergidas',
            marker: { size: 14, color: '#00BFFF', symbol: 'star', line: { color: 'black', width: 1.5 }, opacity: submergedOpacity },
            text: submergedText, hovertemplate: '%{text}<br>Sumergida<extra></extra>', showlegend: true
        });
    }

    traces.push({ 
        x: lampTextX, y: lampTextY, mode: 'text', type: 'scatter', name: 'Lámparas_Texto', 
        text: lampText, textposition: 'top right', textfont: { color: 'var(--evolux-black)', size: 14, weight: 'bold' }, 
        hoverinfo: 'none', showlegend: false 
    });

    if (window.measurements && window.measurements.length > 0) {
        const measX = [], measY = [];
        window.measurements.forEach(m => { measX.push(m.x); measY.push(m.y); });
        traces.push({ 
            x: measX, y: measY, mode: 'markers', type: 'scatter', name: 'Mediciones', 
            marker: { size: 8, color: '#1f77b4', symbol: 'diamond', line: { color: 'white', width: 1 } }, 
            hoverinfo: 'none', showlegend: false 
        });
    }

    let aporteStr = document.getElementById('aporte_puntos').value;
    if (aporteStr.trim()) {
        let apX=[], apY=[];
        aporteStr.split(';').forEach(part => {
            let c = part.split(',');
            if (c.length === 3 && !isNaN(parseFloat(c[0])) && !isNaN(parseFloat(c[1]))) {
                apX.push(parseFloat(c[0])); apY.push(parseFloat(c[1]));
            }
        });
        if (apX.length > 0) {
            traces.push({ 
                x: apX, y: apY, mode: 'markers+text', type: 'scatter', name: 'Puntos Aporte', 
                text: Array(apX.length).fill('📌'), textposition: 'top center', textfont: {size: 16},
                marker: { size: 10, color: 'magenta', symbol: 'cross', line: { color: 'white', width: 1 } }, 
                hoverinfo: 'none', showlegend: false 
            });
        }
    }

    return traces;
}

function getLayoutWithBoundary() {
    const dims = getSpaceDimensions();
    const xTicks = getAxisTicks(dims.x);
    const yTicks = getAxisTicks(dims.y);

    const layout = { 
        margin: {t: 20, r: 20, l: 40, b: 40}, 
        xaxis: { 
            title: 'Coordenada X (m)', 
            range: [-1, dims.x + 1], 
            tickmode: 'array', 
            tickvals: xTicks.vals, 
            ticktext: xTicks.texts, 
            gridcolor: '#eee'
        }, 
        yaxis: { 
            title: 'Coordenada Y (m)', 
            range: [-1, dims.y + 1], 
            scaleanchor: 'x', 
            scaleratio: 1, 
            tickmode: 'array', 
            tickvals: yTicks.vals, 
            ticktext: yTicks.texts, 
            gridcolor: '#eee'
        }, 
        shapes: [], annotations: []
    };

    const zInterface = parseFloat(document.getElementById('z_water').value) || 0;
    const activeAerial = document.getElementById('toggle_aerial').checked;
    const activeSubmerged = document.getElementById('toggle_submerged').checked;

    document.querySelectorAll('.lamp-item').forEach((item, index) => {
        let x = parseFloat(item.querySelector('.lamp-x').value) || 0;
        let y = parseFloat(item.querySelector('.lamp-y').value) || 0;
        let z = parseFloat(item.querySelector('.lamp-z').value) || 0;
        let rx = parseFloat(item.querySelector('.lamp-rot-x').value) || 0;
        let ry = parseFloat(item.querySelector('.lamp-rot-y').value) || 0;
        
        let isAerial = (currentSpaceType === 'estanque' && z > zInterface) || (currentSpaceType === 'jaula' && z < 0);
        const isOn = isAerial ? activeAerial : activeSubmerged;

        let coreColor = isAerial ? 'var(--evolux-yellow)' : '#00bfff';

        layout.shapes.push({
            type: 'circle',
            x0: x - 0.4, y0: y - 0.4, x1: x + 0.4, y1: y + 0.4,
            fillcolor: coreColor, opacity: isOn ? 1.0 : 0.25, line: { color: 'black', width: 2 }
        });

        if (rx !== 0 || ry !== 0) {
            layout.annotations.push({ x: x, y: y + 1.2, text: `Tilt: ${rx}°, ${ry}°`, showarrow: false, font: {size: 11, color: '#1f77b4', weight: 'bold'} });
        }
    });

    return layout;
}

function updateScene() {
    if (typeof Plotly === 'undefined') {
        if (window.updateScene3D) window.updateScene3D();
        return;
    }
    const layout = getLayoutWithBoundary();
    const traces = getPlotTraces();
    
    Plotly.react('heatmap_div_preview', traces, layout, {
        responsive: true, displaylogo: false, 
        edits: {shapePosition: true} 
    }).then(function(plotDiv){
        
        if (!plotDiv.__clickAttached) {
            plotDiv.on('plotly_click', function(data){
                if(data.points.length > 0){
                    let x = data.points[0].x.toFixed(2);
                    let y = data.points[0].y.toFixed(2);
                    document.getElementById('preview_coords').innerHTML = `📍 Coordenada: <strong>X=${x}, Y=${y}</strong>`;
                }
            });
            plotDiv.__clickAttached = true;
        }

        if (!plotDiv.__dragAttached) {
            plotDiv.on('plotly_relayout', function(eventData){
                let updated = false;
                let lampItems = document.querySelectorAll('.lamp-item');

                for (let key in eventData) {
                    let match = key.match(/shapes\[(\d+)\]\.(x0|x1|y0|y1)/);
                    if (match) {
                        let shapeIdx = parseInt(match[1]);
                        if (shapeIdx >= 0 && shapeIdx < lampItems.length) {
                            let shape = plotDiv.layout.shapes[shapeIdx];
                            let newX = (shape.x0 + shape.x1) / 2;
                            let newY = (shape.y0 + shape.y1) / 2;
                            
                            let inputX = lampItems[shapeIdx].querySelector('.lamp-x');
                            let inputY = lampItems[shapeIdx].querySelector('.lamp-y');
                            let oldX = parseFloat(inputX.value) || 0;
                            let oldY = parseFloat(inputY.value) || 0;
                            
                            if (Math.abs(newX - oldX) > 0.05 || Math.abs(newY - oldY) > 0.05) {
                                inputX.value = newX.toFixed(2);
                                inputY.value = newY.toFixed(2);
                                updated = true;
                            }
                        }
                    }
                }
                if (updated) {
                    setTimeout(() => { updateScene(); }, 150);
                }
            });
            plotDiv.__dragAttached = true;
        }
    });

    if (window.updateScene3D) window.updateScene3D();
}

function loadAvailableLamps() {
    fetch('/api/get_lamps').then(r => r.json()).then(data => {
        if(data.status === 'ok') {
            const sel = document.getElementById('lamp_model_selector');
            sel.innerHTML = ''; 
            if(data.lamps.length === 0) sel.innerHTML = '<option value="">No hay lámparas (suba una)</option>';
            else { data.lamps.forEach(lamp => { const opt = document.createElement('option'); opt.value = lamp; opt.text = lamp; sel.add(opt); }); sel.value = data.lamps[0]; }
        }
    });
}

window.onload = function() {
    applyModeSettings();
    loadAvailableLamps();
    updateAttenLabels();
    updateSecchi();
    updateAporteBadge();
    togglePinealParams();

    const tssInput = document.getElementById('scat_tss');
    const cdomInput = document.getElementById('scat_cdom');
    const chlInput = document.getElementById('scat_chl');
    if (tssInput) tssInput.addEventListener('input', updateBioOpticalReference);
    if (cdomInput) cdomInput.addEventListener('input', updateBioOpticalReference);
    if (chlInput) chlInput.addEventListener('input', updateBioOpticalReference);

    updateBioOpticalReference();
};

function uploadXML(input) {
    const file = input.files[0]; if(!file) return;
    const formData = new FormData(); formData.append('file', file);
    fetch('/api/upload_lamp', { method: 'POST', body: formData }).then(r => r.json()).then(data => {
        if(data.status === 'ok') {
            const sel = document.getElementById('lamp_model_selector');
            if (sel.options[0] && sel.options[0].value === "") sel.remove(0); 
            let exists = Array.from(sel.options).some(opt => opt.value === data.filename);
            if (!exists) { const opt = document.createElement('option'); opt.value = data.filename; opt.text = data.filename; sel.add(opt); }
            sel.value = data.filename; showStatusMessage(`Lámpara guardada: ${data.filename}`);
        } else { alert("Error: " + data.msg); }
        input.value = '';
    });
}

function createLampElement(lampObj) {
    const model = lampObj.xml;
    const containerId = `group-${model.replace(/[^a-zA-Z0-9]/g, '-')}`;
    let groupContainer = document.getElementById(containerId);
    
    if (!groupContainer) {
        const list = document.getElementById('lamp-list');
        groupContainer = document.createElement('div');
        groupContainer.id = containerId;
        groupContainer.className = 'lamp-group-container';
        groupContainer.setAttribute('data-model', model);
        
        const safeModel = model.replace(/'/g, "&#39;").replace(/"/g, '&quot;');
        groupContainer.innerHTML = `
            <div style="background-color: var(--evolux-yellow); color: var(--evolux-black); font-weight: 800; font-size: 11px; padding: 6px 10px; border-bottom: 1px solid #ccc; display: flex; align-items: center; gap: 8px;">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>
                <span style="flex:1;">GRUPO: ${model.replace('.xml', '').replace('.ies', '')}</span>
                <button type="button" title="Ver curva polar IES" onclick="showLampDiagnostic('${safeModel}', 'polar')" style="background:#fff; border:1px solid #555; border-radius:3px; padding:2px 6px; font-size:10px; cursor:pointer; font-weight:700;">📈 Polar</button>
                <button type="button" title="Ver beam 3D" onclick="showLampDiagnostic('${safeModel}', '3d')" style="background:#fff; border:1px solid #555; border-radius:3px; padding:2px 6px; font-size:10px; cursor:pointer; font-weight:700;">🔦 Beam 3D</button>
            </div>
            <div class="lamp-items-wrapper"></div>
        `;
        list.appendChild(groupContainer);
    }

    const wrapper = groupContainer.querySelector('.lamp-items-wrapper');
    
    lampCount++;
    const id = lampCount;
    
    const div = document.createElement('div');
    div.className = 'lamp-item'; 
    div.id = `lamp-${id}`;
    div.style.borderBottom = "1px solid #eee";
    div.style.padding = "10px";
    div.style.position = "relative";
    div.style.background = "white";

    const zLabelText = currentSpaceType === 'estanque' ? 'Altura (m)' : 'Profundidad (m)';

    div.innerHTML = `
        <div class="lamp-title-text" style="font-weight:900; color:#1a252f; margin-bottom:8px; font-size: 12px; display: inline-block; background: #e3f2fd; padding: 3px 8px; border-radius: 4px; border: 1px solid #1f77b4;"></div>
        <button type="button" class="btn-remove" onclick="removeLamp(${id})" style="position: absolute; top: 10px; right: 10px; background: #ffebee; border: 1px solid #ffcdd2; color: #d32f2f; border-radius: 4px; font-weight: bold; cursor: pointer; padding: 2px 6px;">×</button>
        <input type="hidden" class="lamp-xml" value="${model}">
        <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; font-size: 11px;">
            <div><strong>X:</strong> <input type="number" class="lamp-x" value="${lampObj.x}" style="width:100%; padding:5px;" oninput="updateScene()"></div>
            <div><strong>Y:</strong> <input type="number" class="lamp-y" value="${lampObj.y}" style="width:100%; padding:5px;" oninput="updateScene()"></div>
            <div class="z-label-container"><strong>${zLabelText}:</strong> <input type="number" class="lamp-z" value="${lampObj.z}" data-manual="${lampObj.manual_z ? 'true' : 'false'}" style="width:100%; padding:5px; opacity:${lampObj.manual_z ? '1.0' : (lampObj.opacity || '1.0')};" oninput="removeLampManualOverride(this)"></div>
            
            <div style="grid-column: span 3; background:#fffae6; padding: 5px; border-radius: 4px; border: 1px solid var(--evolux-yellow);">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 4px;">
                    <strong>Potencia eléctrica de consumo (W):</strong> 
                    <span class="eff-badge" style="font-size:11px; color:#1f77b4; font-weight:bold;">Flujo Radiante: -- W</span>
                </div>
                <input type="number" class="lamp-power" value="${lampObj.power}" data-manual="${lampObj.manual_power ? 'true' : 'false'}" style="width:100%; padding:5px; opacity:${lampObj.manual_power ? '1.0' : (lampObj.opacity || '1.0')};" oninput="removeLampManualOverride(this); updateLampEfficiency(this)">
                <input type="hidden" class="lamp-eff" value="${lampObj.efficiency || 1.0}">
            </div>
            
            <div><strong>Rot X°:</strong> <input type="number" class="lamp-rot-x" value="${lampObj.rot_x || 0}" style="width:100%; padding:5px;" oninput="updateScene()"></div>
            <div><strong>Rot Y°:</strong> <input type="number" class="lamp-rot-y" value="${lampObj.rot_y || 0}" style="width:100%; padding:5px;" oninput="updateScene()"></div>
            <div><strong>Rot Z°:</strong> <input type="number" class="lamp-rot-z" value="${lampObj.rot_z || 0}" style="width:100%; padding:5px;" oninput="updateScene()"></div>
        </div>
    `;
    wrapper.appendChild(div);
    
    updateLampNames();
    updateGlobalLampControls(); 
    updateLampEfficiency(div.querySelector('.lamp-power'));
    fetchLampProfile(model); 
    updateScene();
}

async function addLamp() {
    try {
        const sel = document.getElementById('lamp_model_selector');
        const model = sel ? sel.value : null;
        if(!model || model === "") { alert("Primero seleccione un modelo de lámpara."); return; }

        let profile = window.lampProfiles[model];
        if (!profile) {
            profile = await fetchLampProfile(model);
        }

        const dims = getSpaceDimensions();
        
        let defaultX = dims.shape === 'circle' ? dims.radius : dims.x / 2;
        let defaultY = dims.shape === 'circle' ? dims.radius : dims.y / 2;
        let defaultZ = currentSpaceType === 'estanque' ? parseFloat(document.getElementById('z_water').value) + 0.5 : 2.0;
        
        let defaultPower = 600;
        let defaultEff = 1.0;

        if (profile) {
            if (profile.elec_power) defaultPower = profile.elec_power;
            if (profile.efficiency) defaultEff = profile.efficiency;
        } else {
            const modelLower = model.toLowerCase();
            if (modelLower.includes('nexus') || modelLower.includes('fish')) defaultPower = 40;
            else if (modelLower.includes('asteria')) defaultPower = 150;
            else if (modelLower.includes('tempest')) defaultPower = 600;
        }

        let defaultRotX = 0;
        let defaultRotY = 0;
        let defaultRotZ = 0;

        const globalGroup = document.querySelector(`.global-lamp-group[data-xml="${model}"]`);
        if (globalGroup) {
            defaultPower = parseFloat(globalGroup.querySelector('.glob-power').value) || defaultPower;
            defaultZ = parseFloat(globalGroup.querySelector('.glob-z').value) || defaultZ;
        }

        const containerId = `group-${model.replace(/[^a-zA-Z0-9]/g, '-')}`;
        const groupContainer = document.getElementById(containerId);
        if (groupContainer) {
            const lastLamp = groupContainer.querySelector('.lamp-item:last-child');
            if (lastLamp) {
                defaultX = parseFloat(lastLamp.querySelector('.lamp-x').value) || defaultX;
                defaultY = parseFloat(lastLamp.querySelector('.lamp-y').value) || defaultY;
                defaultRotX = parseFloat(lastLamp.querySelector('.lamp-rot-x').value) || 0;
                defaultRotY = parseFloat(lastLamp.querySelector('.lamp-rot-y').value) || 0;
                defaultRotZ = parseFloat(lastLamp.querySelector('.lamp-rot-z').value) || 0;
            }
        }

        let initOpacity = globalGroup ? '0.5' : '1.0';

        createLampElement({
            xml: model, x: defaultX, y: defaultY, z: defaultZ, power: defaultPower,
            rot_x: defaultRotX, rot_y: defaultRotY, rot_z: defaultRotZ, opacity: initOpacity,
            efficiency: defaultEff 
        });
    } catch(e) { console.error(e); alert("Error al añadir lámpara."); }
}

function removeLamp(id) { 
    const el = document.getElementById(`lamp-${id}`); 
    if(el) { 
        const wrapper = el.parentElement;
        const group = wrapper.parentElement;
        el.remove(); 
        
        if (wrapper.children.length === 0) {
            group.remove();
        }
        
        updateLampNames();
        updateGlobalLampControls(); 
        updateScene(); 
    } 
}

function parseJsonSafe(id) {
    try {
        const el = document.getElementById(id);
        return el ? JSON.parse(el.value) : {};
    } catch(e) {
        return {};
    }
}

function getPayload(isCompareMode) {
    let depthsArray = document.getElementById('target_depths').value.split(',').map(v => parseFloat(v.trim())).filter(v => !isNaN(v));
    let compare_x = null, compare_y = null;

    if (isCompareMode) {
        const pt = document.getElementById('meas_point_selector').value;
        if (!pt) { alert("Seleccione un punto válido (X, Y)."); return null; }
        compare_x = parseFloat(pt.split(',')[0]); compare_y = parseFloat(pt.split(',')[1]);
        const pointMeas = window.measurements.filter(m => Math.abs(m.x - compare_x) < 0.1 && Math.abs(m.y - compare_y) < 0.1);
        const uniqueZ = [...new Set(pointMeas.map(m => m.z))];
        if (uniqueZ.length === 0) { alert("No hay profundidades para este punto."); return null; }
        depthsArray = uniqueZ;
    } else if (depthsArray.length === 0) { alert("Ingrese alturas a graficar."); return null; }

    let aporteStr = document.getElementById('aporte_puntos').value;
    let aporte_puntos = [];
    if (aporteStr.trim()) {
        let parts = aporteStr.split(';');
        parts.forEach(part => {
            let coords = part.split(',');
            if (coords.length === 3) {
                let x = parseFloat(coords[0]), y = parseFloat(coords[1]), z = parseFloat(coords[2]);
                if (!isNaN(x) && !isNaN(y) && !isNaN(z)) {
                    aporte_puntos.push({x, y, z});
                    if (!depthsArray.includes(z)) depthsArray.push(z); 
                }
            }
        });
    }
    depthsArray.sort((a,b) => currentSpaceType === 'estanque' ? b-a : a-b);

    const activeAerial = document.getElementById('toggle_aerial').checked;
    const activeSubmerged = document.getElementById('toggle_submerged').checked;
    const zInterface = parseFloat(document.getElementById('z_water').value) || 0;

    const lamps = [];
    document.querySelectorAll('.lamp-item').forEach(item => {
        let zVal = parseFloat(item.querySelector('.lamp-z').value) || 0;
        let pwrInputVal = parseFloat(item.querySelector('.lamp-power').value) || 0;
        let pwrVal = pwrInputVal;
        let effVal = parseFloat(item.querySelector('.lamp-eff').value) || 1.0;

        let isAerial = (currentSpaceType === 'estanque' && zVal > zInterface) || (currentSpaceType === 'jaula' && zVal < 0);
        if (isAerial && !activeAerial) pwrVal = 0;
        if (!isAerial && !activeSubmerged) pwrVal = 0;
        const lampZInput = item.querySelector('.lamp-z');
        const lampPowerInput = item.querySelector('.lamp-power');

        lamps.push({
            label: item.getAttribute('data-label'),
            xml: item.querySelector('.lamp-xml').value,
            type: isAerial ? 'aerial' : 'submerged',
            enabled: isAerial ? activeAerial : activeSubmerged,
            x: parseFloat(item.querySelector('.lamp-x').value) || 0, 
            y: parseFloat(item.querySelector('.lamp-y').value) || 0, 
            z: zVal,
            power: pwrVal,
            nominal_power: pwrInputVal,
            efficiency: effVal,
            manual_z: lampZInput ? lampZInput.getAttribute('data-manual') === 'true' : false,
            manual_power: lampPowerInput ? lampPowerInput.getAttribute('data-manual') === 'true' : false,
            rot_x: parseFloat(item.querySelector('.lamp-rot-x').value) || 0, 
            rot_y: parseFloat(item.querySelector('.lamp-rot-y').value) || 0, 
            rot_z: parseFloat(item.querySelector('.lamp-rot-z').value) || 0
        });
    });
    if(lamps.length === 0) { alert("Agregue lámparas."); return null; }

    const spectrum_lamps = [];
    if (document.getElementById('plot_spectrum_initial').checked || document.getElementById('plot_spectrum_normalized').checked || document.getElementById('plot_env_optics').checked) {
        document.querySelectorAll('.spectrum-lamp-cb:checked').forEach(cb => spectrum_lamps.push(cb.value));
    }
    
    let roi = { type: document.getElementById('roi_type').value };
    if (roi.type === 'paralelepipedo') {
        roi.l = parseFloat(document.getElementById('roi_p_l').value) || 0;
        roi.w = parseFloat(document.getElementById('roi_p_w').value) || 0;
        roi.h = parseFloat(document.getElementById('roi_p_h').value) || 0;
        roi.cx = parseFloat(document.getElementById('roi_p_cx').value) || 0;
        roi.cy = parseFloat(document.getElementById('roi_p_cy').value) || 0;
        roi.cz = parseFloat(document.getElementById('roi_p_cz').value) || 0;
    } else if (roi.type === 'cilindro') {
        roi.r = parseFloat(document.getElementById('roi_c_r').value) || 0;
        roi.h = parseFloat(document.getElementById('roi_c_h').value) || 0;
        roi.cx = parseFloat(document.getElementById('roi_c_cx').value) || 0;
        roi.cy = parseFloat(document.getElementById('roi_c_cy').value) || 0;
        roi.cz = parseFloat(document.getElementById('roi_c_cz').value) || 0;
    }

    const dims = getSpaceDimensions();
    const optics_mode = document.getElementById('optics_mode').value;
    const mc_input_type = document.getElementById('mc_input_type').value;
    
    let kdList = [];
    if (optics_mode === 'kd_fijo') {
        kdList = document.getElementById('kd_list').value.split(',').map(v => parseFloat(v.trim())).filter(v => !isNaN(v));
        if (kdList.length === 0) kdList = [0.2];
    } else if (optics_mode === 'scattering') {
        if (mc_input_type === 'scalar') {
            const c_val = parseFloat(document.getElementById('scatter_c').value);
            kdList = isNaN(c_val) ? [0.5] : [c_val];
        } else {
            kdList = [0.0];
        }
    } else {
        kdList = [0.0];
    }

    return {
        project_title: document.getElementById('project_title').value || 'simulacion_evolux',
        lamp_type_toggles: {
            aerial: activeAerial,
            submerged: activeSubmerged
        },
        lamp_globals: getGlobalLampSettings(),
        scene3d: {
            render: get3DRenderSettings(),
            lamp_models: get3DModelSettings()
        },
        env: { 
            type: currentSpaceType, 
            shape: dims.shape,
            radio: dims.shape === 'circle' ? dims.radius : null, 
            x: dims.x, 
            y: dims.y, 
            z: parseFloat(document.getElementById('env_z').value) || 15.0,
            z_interface: parseFloat(document.getElementById('z_water').value) || 3.2,
            n1: parseFloat(document.getElementById('env_n1').value) || 1.0,
            n2: parseFloat(document.getElementById('env_n2').value) || 1.33
        },
        poly: {
            sides: parseInt(document.getElementById('poly_sides').value) || 0,
            dist: parseFloat(document.getElementById('poly_dist').value) || 0
        },
        roi: roi,
        optics_mode: optics_mode,
        optics: {
            kd_fijo: kdList[0],
            kd_spectral: parseJsonSafe('kd_spectral_json'),
            atten_coef_type: (document.getElementById('atten_coef_type') || {}).value || 'c',
            mc_input_type: mc_input_type,
            tss: parseFloat(document.getElementById('scat_tss').value) || 15.0,
            cdom_a440: parseFloat(document.getElementById('scat_cdom').value) || 1.0,
            chl: parseFloat((document.getElementById('scat_chl') || {}).value) || 0.0,
            c: parseFloat(document.getElementById('scatter_c').value) || 0.5,
            omega: parseFloat(document.getElementById('scatter_omega').value) || 0.8,
            g: parseFloat(document.getElementById('scatter_g').value) || 0.85,
            r_wall: parseFloat(document.getElementById('scatter_rwall').value) || 0.15,
            c_json: parseJsonSafe('scatter_c_json'),
            omega_json: parseJsonSafe('scatter_omega_json')
        },
        kd_list: kdList,
        target_depths: depthsArray, 
        rays: parseInt(document.getElementById('rays_count').value) || 50000,
        draw_contour: document.getElementById('draw_contour').checked, 
        contour_val: parseFloat(document.getElementById('contour_val').value) || 0.017,
        color_scale_type: document.getElementById('color_scale_type').value,
        
        irradiance_type: document.getElementById('irradiance_type') ? document.getElementById('irradiance_type').value : 'scalar',
        mu_max: document.getElementById('mu_max') ? parseFloat(document.getElementById('mu_max').value) : 85.0,
        normalize_pineal: document.getElementById('normalize_pineal') ? document.getElementById('normalize_pineal').checked : true,
        
        plot_depth_profile: document.getElementById('plot_depth_profile').checked,
        profile_step: parseFloat(document.getElementById('profile_step').value) || 0.5,
        plot_depth_summary_table: document.getElementById('plot_depth_summary_table') ? document.getElementById('plot_depth_summary_table').checked : true,
        
        plot_env_optics: document.getElementById('plot_env_optics').checked,
        plot_spectrum_initial: document.getElementById('plot_spectrum_initial').checked, 
        plot_spectrum_normalized: document.getElementById('plot_spectrum_normalized').checked, 
        spectrum_lamps: spectrum_lamps,
        spectrum_ranges: { 
            'blue': [parseFloat(document.getElementById('spec_b_min').value) || 400, parseFloat(document.getElementById('spec_b_max').value) || 499], 
            'green': [parseFloat(document.getElementById('spec_g_min').value) || 500, parseFloat(document.getElementById('spec_g_max').value) || 599], 
            'red': [parseFloat(document.getElementById('spec_r_min').value) || 600, parseFloat(document.getElementById('spec_r_max').value) || 750] 
        },
        compare_measurements: isCompareMode, compare_x: compare_x, compare_y: compare_y, measurements: isCompareMode ? window.measurements : [],
        aporte_puntos: aporte_puntos,
        aporte_puntos_raw: document.getElementById('aporte_puntos').value,
        lamps: lamps,
        summary_cols: { 
            lamps: document.getElementById('col_lamps').checked, 
            pos: document.getElementById('col_pos').checked, 
            power: document.getElementById('col_power').checked, 
            vol: document.getElementById('col_vol').checked 
        }
    };
}

function createReportBlob(payload, data) {
    data = data || window.lastResults || {};
    let txt = "=================================================\n";
    txt += "   REPORTE DE SIMULACION DE IRRADIANCIA EVOLUX\n";
    txt += "=================================================\n\n";
    txt += "PROYECTO: " + payload.project_title + "\n";
    txt += "FECHA: " + new Date().toLocaleString() + "\n";
    txt += "ENTORNO: " + (payload.env.type === 'estanque' ? 'Estanque' : 'Jaula') + "\n";
    txt += "FORMA: " + (payload.env.shape === 'circle' ? 'Cilíndrica' : 'Rectangular') + "\n";
    if (payload.env.shape === 'circle') txt += "RADIO: " + payload.env.radio + " m\n";
    else txt += "DIMENSIONES: " + payload.env.x + "x" + payload.env.y + " m\n";
    txt += "PROFUNDIDAD TOTAL Z: " + payload.env.z + " m\n";
    txt += "ALTURA DEL AGUA: " + payload.env.z_interface + " m\n";
    txt += "INDICE REF. MEDIO 1: " + payload.env.n1 + "\n";
    txt += "INDICE REF. MEDIO 2: " + payload.env.n2 + "\n";
    txt += "POLIGONO REF.: " + payload.poly.sides + " vertices, distancia " + payload.poly.dist + " m\n";
    txt += "ROI: " + JSON.stringify(payload.roi) + "\n";
    
    txt += "\n--- MODELADO DE IRRADIANCIA ---\n";
    txt += "METRICA: " + (payload.irradiance_type === 'pineal' ? 'Ponderada (Fisica Pineal)' : 'Escalar (Magnitud Bruta)') + "\n";
    if (payload.irradiance_type === 'pineal') {
        txt += "ANGULO LIMITE (u_max): " + payload.mu_max + " grados\n";
        txt += "NORMALIZACION A 1.0: " + (payload.normalize_pineal ? 'Activada' : 'Desactivada') + "\n";
    }
    
    txt += "\n--- OPTICA ---\n";
    txt += "MODO: " + payload.optics_mode + "\n";
    txt += "TIPO COEFICIENTE: " + (payload.optics.atten_coef_type || 'c') + "\n";
    if (payload.optics_mode === 'scattering') {
         txt += "INPUT: " + payload.optics.mc_input_type + "\n";
         if (payload.optics.mc_input_type === 'bio') {
             txt += "TSS: " + payload.optics.tss + " mg/L\n";
             txt += "CDOM a(440): " + payload.optics.cdom_a440 + " m^-1\n";
             txt += "Chl-a: " + payload.optics.chl + " mg/m^3\n";
         } else if (payload.optics.mc_input_type === 'scalar') {
             txt += "ATENUACION C: " + payload.optics.c + "\n";
             txt += "ALBEDO OMEGA: " + payload.optics.omega + "\n";
         } else {
             txt += "C JSON: " + JSON.stringify(payload.optics.c_json) + "\n";
             txt += "OMEGA JSON: " + JSON.stringify(payload.optics.omega_json) + "\n";
         }
         txt += "FASE g: " + payload.optics.g + "\n";
         txt += "ALBEDO PARED: " + payload.optics.r_wall + "\n";
    } else if (payload.optics_mode === 'kd_fijo') {
         txt += "KD FIJO: " + payload.optics.kd_fijo + "\n";
    } else if (payload.optics_mode === 'kd_espectral') {
         txt += "KD/C ESPECTRAL JSON: " + JSON.stringify(payload.optics.kd_spectral) + "\n";
    }
    
    txt += "\n--- LAMPARAS ---\n";
    txt += "SWITCH AEREAS: " + (payload.lamp_type_toggles && payload.lamp_type_toggles.aerial ? 'ON' : 'OFF') + "\n";
    txt += "SWITCH SUMERGIDAS: " + (payload.lamp_type_toggles && payload.lamp_type_toggles.submerged ? 'ON' : 'OFF') + "\n";
    txt += "PARAMETROS GLOBALES POR MODELO: " + JSON.stringify(payload.lamp_globals || {}) + "\n";
    let activas = 0;
    payload.lamps.forEach((l, i) => {
         if (l.power > 0) activas++;
         let label = l.label || `L${i+1}`;
         txt += `${label}: ${l.xml} | Tipo: ${l.type || '-'} | Estado tipo: ${l.enabled === false ? 'OFF' : 'ON'} | Pos(${l.x}, ${l.y}, ${l.z}) | Rot(${l.rot_x}, ${l.rot_y}, ${l.rot_z})\n`;
         txt += `       └─ Pwr Nominal: ${l.nominal_power !== undefined ? l.nominal_power : l.power}W | Pwr Efectiva: ${l.power}W | Eficiencia WPE: ${(l.efficiency*100).toFixed(1)}% | Pwr Radiante efectiva (Φe): ${(l.power*l.efficiency).toFixed(2)}W\n`;
         txt += `       └─ Override individual: potencia=${l.manual_power ? 'si' : 'no'}, altura=${l.manual_z ? 'si' : 'no'}\n`;
    });
    txt += "TOTAL ACTIVAS: " + activas + "\n";
    
    txt += "\n--- RAY TRACING ---\n";
    txt += "RAYOS POR LÁMPARA: " + payload.rays + "\n";
    txt += "PROFUNDIDADES OBJETIVO: " + payload.target_depths.join(', ') + "\n";
    txt += "ISOCURVA: " + (payload.draw_contour ? 'activada' : 'desactivada') + " >= " + payload.contour_val + " W/m^2\n";
    txt += "ESCALA COLOR: " + payload.color_scale_type + "\n";
    txt += "GRAFICOS ACTIVOS: perfil=" + payload.plot_depth_profile + ", tabla_z=" + payload.plot_depth_summary_table + ", medio=" + payload.plot_env_optics + ", espectro_inicial=" + payload.plot_spectrum_initial + ", color_shift=" + payload.plot_spectrum_normalized + "\n";
    txt += "\n--- VISUALIZACION 3D ---\n";
    txt += "RENDER: " + JSON.stringify(payload.scene3d ? payload.scene3d.render : {}) + "\n";
    txt += "MODELOS FISICOS: " + JSON.stringify(payload.scene3d ? payload.scene3d.lamp_models : {}) + "\n";

    if (data.table_data && Array.isArray(data.table_data) && data.table_data.length > 0) {
        txt += "\n--- RESULTADOS RESUMEN ---\n";
        data.table_data.forEach((row, i) => {
            txt += `ESCENARIO ${i + 1}: ${row.kd}\n`;
            txt += `  Prom W/m2: ${Number(row.avg || 0).toFixed(6)} | Max: ${Number(row.max || 0).toFixed(6)} | Min: ${Number(row.min || 0).toFixed(6)}\n`;
            txt += `  Prom Lux: ${Number(row.avg_lux || 0).toFixed(3)} | Prom PPFD: ${Number(row.avg_ppfd || 0).toFixed(3)} | Flujo prom: ${Number(row.avg_flux_w || 0).toFixed(3)} W\n`;
            txt += `  Vol iluminado: ${Number(row.vol_ilum_m3 || 0).toFixed(3)} m3 / ${Number(row.vol_pct || 0).toFixed(3)}%\n`;
            txt += `  Secchi eq.: ${row.secchi ? Number(row.secchi).toFixed(3) + ' m' : '-'}\n`;
        });
    }

    return new Blob([txt], {type: "text/plain;charset=utf-8"});
}

function runSimulation(isCompareMode = false) {
    const payload = getPayload(isCompareMode);
    if (!payload) return;
    const btn = document.getElementById('btn_run');
    
    btn.innerHTML = "⏳ CALCULANDO..."; btn.disabled = true;

    currentAbortController = new AbortController();

    fetch('/api/run_simulation', { 
        method: 'POST', 
        headers: {'Content-Type': 'application/json'}, 
        body: JSON.stringify(payload),
        signal: currentAbortController.signal
    })
    .then(r => r.json())
    .then(data => {
        btn.innerHTML = "▶ Simular"; btn.disabled = false;
        if(data.status === 'ok') { 
            window.lastResults = data; 
            window.lastPayload = payload;
            try {
                renderResults(data, payload); 
                if (window.updateScene3D) window.updateScene3D();
                showStatusMessage("Simulación completada con éxito"); 
            } catch (renderErr) {
                console.error(renderErr);
                alert("Error en el renderizado de los gráficos:\n" + renderErr.name + ": " + renderErr.message);
            }
        } 
        else { alert("Error en el Servidor:\n" + data.msg); }
    })
    .catch(e => { 
        if(e.name === 'AbortError') {
            showStatusMessage("Simulación cancelada", "red");
        } else {
            console.error("Fetch Error:", e); 
            alert("Error de Conexión/JS en el Navegador:\n" + e.message); 
        }
        btn.innerHTML = "▶ Simular"; 
        btn.disabled = false; 
    });
}

function renderResults(data, payload) {
    const workspace = document.getElementById('results_dynamic_area');
    const dlContainer = document.getElementById('downloads_container');
    
    if (!workspace || !dlContainer) {
        alert("Error Crítico: No se encontraron los contenedores HTML para dibujar los resultados. Asegúrate de haber copiado el archivo simulation.html completamente sin cortar el final.");
        throw new Error("Contenedores HTML faltantes.");
    }
    
    workspace.innerHTML = ''; dlContainer.innerHTML = '';

    if (data.kds && data.results_by_kd) {
        data.kds = data.kds.map(kd => {
            return Object.keys(data.results_by_kd).find(k => parseFloat(k) === parseFloat(kd)) || kd;
        });
    }
    
    if (data.depths && Array.isArray(data.depths)) {
        data.depths.forEach(depth => {
            const rowDiv = document.createElement('div');
            rowDiv.className = 'depth-group result-graph';
            
            let html = `<div class="kd-grid">`;
            
            if (data.kds && Array.isArray(data.kds)) {
                data.kds.forEach(kd => {
                    if (data.results_by_kd && data.results_by_kd[kd] && data.results_by_kd[kd].depths) {
                        const imgData = data.results_by_kd[kd].depths[depth];
                        let scenName = data.scenario_names ? data.scenario_names[kd] : kd;
                        let combinedTitle = currentSpaceType === 'estanque' ? `<div style="font-size:16px;">ALTURA Z = ${depth}m</div> <span style="font-size:12px; color:#555; font-weight:normal; text-transform:none;">ESCENARIO: ${scenName}</span>` : `<div style="font-size:16px;">PROFUNDIDAD Z = ${depth}m</div> <span style="font-size:12px; color:#555; font-weight:normal; text-transform:none;">ESCENARIO: ${scenName}</span>`;
                        
                        if(imgData && imgData.image) {
                            html += `<div class="kd-card">
                                        <div class="kd-card-title">${combinedTitle}</div>
                                        <img src="data:image/png;base64,${imgData.image}">
                                     </div>`;
                        }
                    }
                });
            }
            html += `</div>`;
            rowDiv.innerHTML = html;
            workspace.appendChild(rowDiv);
        });
    }

    let htmlTablas = "";

    let hasAportes = false;
    if(data.kds) { data.kds.forEach(kd => { if(data.results_by_kd[kd] && data.results_by_kd[kd].aportes && data.results_by_kd[kd].aportes.length > 0) hasAportes = true; }); }

    if (hasAportes && data.lamps_names) {
        htmlTablas += `<h4 style="color:#333; margin-bottom:10px; text-transform: uppercase;">Aporte lumínico en puntos específicos</h4>
                       <div style="overflow-x:auto; margin-bottom: 30px;">
                       <table class="summary-table">
                       <tr><th>PUNTO (X,Y,Z)</th><th>PARÁMETROS ÓPTICOS</th><th>TOTAL (W/m²)</th><th>LÁMPARA</th><th>APORTE (W/m² | %)</th></tr>`;
        data.kds.forEach(kd => {
            if(data.results_by_kd[kd] && data.results_by_kd[kd].aportes) {
                data.results_by_kd[kd].aportes.forEach(ap => {
                    let numLamps = ap.lamps.length;
                    let scenName = data.scenario_names ? data.scenario_names[kd] : kd;
                    ap.lamps.forEach((l, idx) => {
                        htmlTablas += `<tr>`;
                        if (idx === 0) {
                            htmlTablas += `<td rowspan="${numLamps}"><strong>${ap.x}, ${ap.y}, ${ap.z}</strong></td>
                                           <td rowspan="${numLamps}">${scenName}</td>
                                           <td rowspan="${numLamps}"><strong>${ap.total.toFixed(3)}</strong></td>`;
                        }
                        let lampName = data.lamps_names[l.lamp_idx] || `Lámpara ${l.lamp_idx + 1}`;
                        let lampConfig = payload.lamps[l.lamp_idx];
                        let label = lampConfig && lampConfig.label ? lampConfig.label : `L${l.lamp_idx + 1}`;
                        htmlTablas += `<td>${label}: ${lampName}</td>
                                       <td>${l.val.toFixed(3)} <strong style="color:#1f77b4;">(${l.pct.toFixed(1)}%)</strong></td>
                                       </tr>`;
                    });
                });
            }
        });
        htmlTablas += `</table></div>`;
    }

    let numLamps = payload.lamps.length;
    let summaryCols = payload.summary_cols;
    
    htmlTablas += `<h4 style="color:#333; margin-bottom:10px; text-transform: uppercase;">Resumen volumétrico de escenarios</h4>
                   <div style="overflow-x:auto;">
                   <table class="summary-table">
                   <tr><th>PARÁMETROS ÓPTICOS</th><th>DISCO SECCHI EQ.</th><th>FLUJO TOTAL (W)</th><th>PROM (W/m²)</th><th>PROM (Lux)</th><th>PROM (μmol)</th><th>MÁX (W/m²)</th><th>MÍN (W/m²)</th>`;
    if (summaryCols.vol !== false) htmlTablas += `<th>VOLUMEN ILUM (m³ / %)</th>`;
    if (summaryCols.lamps) htmlTablas += `<th>LÁMPARA</th>`;
    if (summaryCols.pos) htmlTablas += `<th>POSICIÓN (X,Y,Z)</th>`;
    if (summaryCols.power) htmlTablas += `<th>POTENCIA ELÉCT. (W)</th>`;
    htmlTablas += `</tr>`;

    if (data.table_data && Array.isArray(data.table_data)) {
        data.table_data.forEach(row => {
            let r_avg_flux = row.avg_flux_w !== undefined ? row.avg_flux_w.toFixed(2) : "0.00";
            let r_avg = row.avg !== undefined ? row.avg.toFixed(3) : "0.000";
            let r_avg_lux = row.avg_lux !== undefined ? row.avg_lux.toFixed(1) : "0.0";
            let r_avg_ppfd = row.avg_ppfd !== undefined ? row.avg_ppfd.toFixed(2) : "0.00";
            let r_max = row.max !== undefined ? row.max.toFixed(3) : "0.000";
            let r_min = row.min !== undefined ? row.min.toFixed(3) : "0.000";
            let r_vol = row.vol_pct !== undefined ? row.vol_pct.toFixed(2) : "0.00";
            let r_vol_m3 = row.vol_ilum_m3 !== undefined ? row.vol_ilum_m3.toFixed(2) : "0.00";
            let r_secchi = row.secchi !== undefined && row.secchi > 0 ? row.secchi.toFixed(2) + 'm' : "-";

            let rawKd = row.kd.split(' ')[0];
            let scenName = data.scenario_names ? data.scenario_names[rawKd] : row.kd;

            payload.lamps.forEach((lamp, idx) => {
                htmlTablas += `<tr>`;
                if (idx === 0) {
                    htmlTablas += `<td rowspan="${numLamps}"><strong>${scenName}</strong></td>
                                    <td rowspan="${numLamps}"><strong style="color:#1f77b4;">${r_secchi}</strong></td>
                                    <td rowspan="${numLamps}" style="color:#8c564b; font-weight:bold;">${r_avg_flux}</td>
                                    <td rowspan="${numLamps}">${r_avg}</td>
                                    <td rowspan="${numLamps}" style="color:#ff8c00; font-weight:bold;">${r_avg_lux}</td>
                                    <td rowspan="${numLamps}" style="color:#2ca02c; font-weight:bold;">${r_avg_ppfd}</td>
                                    <td rowspan="${numLamps}">${r_max}</td>
                                    <td rowspan="${numLamps}">${r_min}</td>`;
                    if (summaryCols.vol !== false) {
                        htmlTablas += `<td rowspan="${numLamps}"><strong>${r_vol_m3} m³</strong><br><span style="color:#1f77b4; font-weight:bold;">${r_vol}%</span></td>`;
                    }
                }
                if (summaryCols.lamps) {
                    let lName = lamp.xml.replace('.xml', '').replace('.ies', '');
                    let label = lamp.label || `L${idx + 1}`;
                    htmlTablas += `<td>${label}: ${lName}</td>`;
                }
                if (summaryCols.pos) {
                    htmlTablas += `<td>(${lamp.x}, ${lamp.y}, ${lamp.z})</td>`;
                }
                if (summaryCols.power) {
                    htmlTablas += `<td>${lamp.power}</td>`;
                }
                htmlTablas += `</tr>`;
            });
        });
    }
    htmlTablas += `</table></div>`;

    const tablesWrapper = document.createElement('div');
    tablesWrapper.className = 'graph-wrapper result-graph';
    tablesWrapper.style.width = "100%";
    tablesWrapper.innerHTML = htmlTablas;
    workspace.appendChild(tablesWrapper);
    
    if (data.kds && data.kds.length > 0) {
        data.kds.forEach(kd => {
            if (data.results_by_kd[kd] && data.results_by_kd[kd].depth_table && data.results_by_kd[kd].depth_table.length > 0) {
                let scenName = data.scenario_names ? data.scenario_names[kd] : kd;
                let depthTableHtml = `<h4 style="color:#333; margin-bottom:10px; text-transform: uppercase;">Irradiancia por Profundidad - ${scenName}</h4>
                               <div style="overflow-x:auto; margin-bottom: 20px;">
                               <table class="summary-table">
                               <tr>
                                   <th rowspan="2">Z (m)</th>
                                   <th rowspan="2">Flujo Total (W)</th>
                                   <th colspan="3">Promedio</th>
                                   <th colspan="3">Máximo</th>
                                   <th colspan="3">Mínimo</th>
                               </tr>
                               <tr>
                                   <th>W/m²</th><th>Lux</th><th>μmol/m²/s</th>
                                   <th>W/m²</th><th>Lux</th><th>μmol/m²/s</th>
                                   <th>W/m²</th><th>Lux</th><th>μmol/m²/s</th>
                               </tr>`;
                               
                data.results_by_kd[kd].depth_table.sort((a,b) => currentSpaceType === 'estanque' ? b.z - a.z : a.z - b.z).forEach(row => {
                    depthTableHtml += `<tr>
                                    <td><strong>${row.z}</strong></td>
                                    <td style="color:#8c564b; font-weight:bold;">${row.flux_w.toFixed(2)}</td>
                                    
                                    <td style="color:#d62728; font-weight:bold;">${row.avg_w.toFixed(3)}</td>
                                    <td>${row.avg_lux.toFixed(1)}</td>
                                    <td style="color:#2ca02c; font-weight:bold;">${row.avg_ppfd.toFixed(2)}</td>
                                    
                                    <td style="color:#d62728; font-weight:bold;">${row.max_w.toFixed(3)}</td>
                                    <td>${row.max_lux.toFixed(1)}</td>
                                    <td style="color:#2ca02c; font-weight:bold;">${row.max_ppfd.toFixed(2)}</td>
                                    
                                    <td style="color:#d62728; font-weight:bold;">${row.min_w.toFixed(3)}</td>
                                    <td>${row.min_lux.toFixed(1)}</td>
                                    <td style="color:#2ca02c; font-weight:bold;">${row.min_ppfd.toFixed(2)}</td>
                                  </tr>`;
                });
                depthTableHtml += `</table></div>`;
                
                const tableDiv = document.createElement('div');
                tableDiv.className = 'graph-wrapper result-graph';
                tableDiv.style.width = "100%";
                tableDiv.innerHTML = depthTableHtml;
                workspace.appendChild(tableDiv);
            }
        });
    }

    if (data.kds && data.kds.length > 0) {
        data.kds.forEach(kd => {
            if (data.results_by_kd[kd] && data.results_by_kd[kd].depth_profile_image) {
                const dpDiv = document.createElement('div');
                dpDiv.className = 'graph-wrapper result-graph';
                dpDiv.style.width = "100%";
                dpDiv.innerHTML = `<h4 style="color:#333; margin-bottom:10px; text-transform: uppercase;">PERFIL DE PROFUNDIDAD: ÁREA Y VOLUMEN</h4>
                                   <div style="text-align:center;"><img src="data:image/png;base64,${data.results_by_kd[kd].depth_profile_image}"></div>`;
                workspace.appendChild(dpDiv);
            }
        });
    }

    if (data.kds && data.kds.length > 0) {
        let firstKd = data.kds[0];
        if (data.results_by_kd[firstKd] && data.results_by_kd[firstKd].comparison_image) {
            const compDiv = document.createElement('div');
            compDiv.className = 'graph-wrapper result-graph';
            compDiv.style.width = "100%";
            compDiv.innerHTML = `<h4 style="color:#333; margin-bottom:10px;">ATENUACIÓN: MEDICIÓN VS SIMULACIÓN</h4>
                                 <div style="text-align:center;"><img src="data:image/png;base64,${data.results_by_kd[firstKd].comparison_image}"></div>`;
            workspace.appendChild(compDiv);
        }
    }
    
    if (data.kds && data.kds.length > 0) {
        data.kds.forEach(kd => {
            if (data.results_by_kd[kd] && data.results_by_kd[kd].env_optics_image) {
                const envDiv = document.createElement('div');
                envDiv.className = 'graph-wrapper result-graph';
                envDiv.style.width = "100%";
                envDiv.innerHTML = `<h4 style="color:#333; margin-bottom:10px; text-transform:uppercase;">CARACTERIZACIÓN ÓPTICA DEL MEDIO</h4>
                                     <div style="text-align:center;"><img src="data:image/png;base64,${data.results_by_kd[kd].env_optics_image}"></div>`;
                workspace.appendChild(envDiv);
            }
        });
    }

    if (data.spectrums && typeof data.spectrums === 'object') {
        Object.keys(data.spectrums).forEach(key => {
            const specDiv = document.createElement('div');
            specDiv.className = 'graph-wrapper result-graph';
            specDiv.style.width = "100%";
            specDiv.innerHTML = `<h4 style="color:#333; margin-bottom:10px; text-transform:uppercase;">ANÁLISIS ESPECTRAL</h4>
                                 <div style="text-align:center;"><img src="data:image/png;base64,${data.spectrums[key]}"></div>`;
            workspace.appendChild(specDiv);
        });
    }

    let dlHtml = `<div style="font-weight:bold; font-size:12px; margin-bottom:5px; color:#1a252f;">EXPORTAR RESULTADOS</div>`;
    dlHtml += `<button class="btn-download" onclick="downloadCombined()" title="Descargar vista general">📄 DESCARGAR CONSOLIDADO</button>`;
    if (data.kds && Array.isArray(data.kds)) {
        dlHtml += `<div style="font-weight:bold; font-size:11px; margin:8px 0 2px; color:#555;">MAPAS INDIVIDUALES</div>`;
        data.kds.forEach(kd => {
            const kdRes = data.results_by_kd && data.results_by_kd[kd];
            if (!kdRes || !kdRes.depths) return;
            Object.keys(kdRes.depths).forEach(depth => {
                if (!kdRes.depths[depth] || !kdRes.depths[depth].image) return;
                const label = currentSpaceType === 'estanque' ? `Altura ${depth}m` : `Prof. ${depth}m`;
                dlHtml += `<button class="btn-download" style="background:#555; color:white;" onclick="downloadSingleMap('${encodeURIComponent(kd)}', '${encodeURIComponent(depth)}')">🖼 ${label}</button>`;
            });
        });
    }
    dlHtml += `<button class="btn-download" style="background:#1f77b4;" onclick="downloadAllZip()">⬇ DESCARGAR PAQUETE COMPLETO (ZIP)</button>`;
    dlHtml += `<div style="font-size:10px; color:#888; text-align:center; margin-top:10px;">Las descargas individuales y consolidadas guardan el gráfico junto a su TXT de parámetros. En navegadores sin selector de carpeta, se descarga un ZIP con ambos archivos.</div>`;
    
    dlContainer.innerHTML = dlHtml;
}

function base64PngToBlob(base64Img) {
    return fetch("data:image/png;base64," + base64Img).then(response => response.blob());
}

function textBlobToFileBlob(blob) {
    return blob;
}

async function writeBlobToFile(handle, blob) {
    const writable = await handle.createWritable();
    await writable.write(blob);
    await writable.close();
}

async function downloadZipPair(baseName, imageBase64, payload, data) {
    const zip = new JSZip();
    zip.file(`${baseName}.png`, imageBase64, {base64: true});
    zip.file(`${baseName}_parametros.txt`, createReportBlob(payload, data));
    const content = await zip.generateAsync({type: "blob"});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(content);
    a.download = `${baseName}.zip`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

async function downloadImageWithReport(baseName, imageBase64, payload, data) {
    if (!imageBase64) return;
    payload = payload || window.lastPayload || getPayload(false);
    data = data || window.lastResults;
    if (!payload || !data) return;

    try {
        if (window.showDirectoryPicker) {
            const dirHandle = await window.showDirectoryPicker({
                id: 'export_images',
                mode: 'readwrite',
                startIn: 'downloads'
            });
            const imgHandle = await dirHandle.getFileHandle(`${baseName}.png`, {create: true});
            await writeBlobToFile(imgHandle, await base64PngToBlob(imageBase64));

            const txtHandle = await dirHandle.getFileHandle(`${baseName}_parametros.txt`, {create: true});
            await writeBlobToFile(txtHandle, textBlobToFileBlob(createReportBlob(payload, data)));
            showStatusMessage("Gráfico y parámetros guardados");
            return;
        }

        throw new Error("Directory picker no soportado");
    } catch (e) {
        if (e && e.name === 'AbortError') return;
        await downloadZipPair(baseName, imageBase64, payload, data);
        showStatusMessage("ZIP con gráfico y parámetros descargado");
    }
}

function downloadSingleMap(kdEncoded, depthEncoded) {
    if(!window.lastResults || !window.lastResults.results_by_kd) return;
    const kd = decodeURIComponent(kdEncoded);
    const depth = decodeURIComponent(depthEncoded);
    const kdRes = window.lastResults.results_by_kd[kd];
    if (!kdRes || !kdRes.depths || !kdRes.depths[depth] || !kdRes.depths[depth].image) return;

    const cleanTitle = window.lastResults.clean_title;
    const suffix = window.lastResults.file_suffixes[kd] || kd;
    const dClean = String(depth).replace('.', '_').replace(',', '_');
    downloadImageWithReport(`${cleanTitle}_z${dClean}_${suffix}`, kdRes.depths[depth].image, window.lastPayload, window.lastResults);
}

async function downloadCombined() {
    if(!window.lastResults || !window.lastResults.kds || window.lastResults.kds.length === 0) return;
    const kd = window.lastResults.kds[0];
    const img = window.lastResults.results_by_kd[kd].combined_image;
    if(img) {
        const cleanTitle = window.lastResults.clean_title;
        const suffix = window.lastResults.file_suffixes[kd];
        await downloadImageWithReport(`${cleanTitle}_consolidado_${suffix}`, img, window.lastPayload, window.lastResults);
    }
}

async function downloadAllZip() {
    if(!window.lastResults || !window.lastResults.results_by_kd) return;
    const cleanTitle = window.lastResults.clean_title;
    showStatusMessage("Generando archivo ZIP...", "white");
    
    try {
        const zip = new JSZip();
        
        window.lastResults.kds.forEach(kd => {
            const suffix = window.lastResults.file_suffixes[kd];
            const depths = window.lastResults.results_by_kd[kd].depths;
            if (depths) {
                for (const d of Object.keys(depths)) {
                    const img = depths[d].image;
                    if(img) {
                        let dClean = d.replace('.', '_').replace(',', '_');
                        zip.file(`${cleanTitle}_z${dClean}_${suffix}.png`, img, {base64: true});
                    }
                }
            }
            
            if(window.lastResults.results_by_kd[kd].combined_image) {
                zip.file(`${cleanTitle}_consolidado_${suffix}.png`, window.lastResults.results_by_kd[kd].combined_image, {base64: true});
            }
            
            if(window.lastResults.results_by_kd[kd].depth_profile_image) {
                zip.file(`${cleanTitle}_perfil_vol_${suffix}.png`, window.lastResults.results_by_kd[kd].depth_profile_image, {base64: true});
            }
            
            if(window.lastResults.results_by_kd[kd].env_optics_image) {
                zip.file(`${cleanTitle}_med_optico_${suffix}.png`, window.lastResults.results_by_kd[kd].env_optics_image, {base64: true});
            }
        });

        if (window.lastResults.spectrums) {
            Object.keys(window.lastResults.spectrums).forEach(specKey => {
                let sClean = specKey.toLowerCase().replace(/[\s\.,\-\(\)]+/g, '_').replace(/_+/g, '_');
                zip.file(`${cleanTitle}_${sClean}.png`, window.lastResults.spectrums[specKey], {base64: true});
            });
        }

        const reportBlob = createReportBlob(window.lastPayload || getPayload(false), window.lastResults);
        zip.file(`${cleanTitle}_reporte.txt`, reportBlob);
        
        const content = await zip.generateAsync({type:"blob"});
        const a = document.createElement('a');
        a.href = URL.createObjectURL(content);
        a.download = `${cleanTitle}_resultados.zip`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        
        showStatusMessage("Archivo ZIP descargado correctamente.");
        
    } catch (e) {
        console.error("Error al generar el ZIP:", e);
        alert("Ocurrió un error al intentar comprimir las imágenes. Por favor, revise la consola para más detalles.");
    }
}

async function saveConfiguration() {
    const payload = getPayload(false);
    if(!payload) return;
    
    let cleanTitle = payload.project_title.toLowerCase().replace(/[\s\.,\-]+/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '');
    if (!cleanTitle) cleanTitle = 'simulacion_evolux';
    
    const jsonString = JSON.stringify(payload, null, 4);

    try {
        if (window.showSaveFilePicker) {
            const handle = await window.showSaveFilePicker({
                id: 'config_files',
                suggestedName: `${cleanTitle}_config.json`,
                types: [{ description: 'JSON Config File', accept: {'application/json': ['.json']} }]
            });
            const writable = await handle.createWritable();
            await writable.write(jsonString);
            await writable.close();
            showStatusMessage("Configuración guardada");
        } else {
            let filename = prompt("Ingrese el nombre para el archivo:", `${cleanTitle}_config.json`);
            if (!filename) return; 
            if (!filename.endsWith('.json')) filename += '.json';
            const blob = new Blob([jsonString], { type: "application/json" });
            const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
            a.download = filename; document.body.appendChild(a); a.click(); document.body.removeChild(a);
            showStatusMessage("Configuración guardada");
        }
    } catch (err) {
        console.error(err);
    }
}

async function openConfigurationPicker() {
    if (!window.showOpenFilePicker) {
        document.getElementById('config_input').click();
        return;
    }

    try {
        const [handle] = await window.showOpenFilePicker({
            id: 'config_files',
            startIn: 'documents',
            multiple: false,
            types: [{ description: 'JSON Config File', accept: {'application/json': ['.json']} }]
        });
        const file = await handle.getFile();
        loadConfiguration({target: {files: [file], value: ''}});
    } catch (err) {
        if (err && err.name !== 'AbortError') console.error(err);
    }
}

function loadConfiguration(event) {
    const file = event.target.files[0]; if (!file) return;
    const reader = new FileReader();
    reader.onload = function(e) {
        try {
            const config = JSON.parse(e.target.result);
            
            if(config.project_title !== undefined) {
                document.getElementById('project_title').value = config.project_title;
            }

            if(config.lamp_type_toggles) {
                if (config.lamp_type_toggles.aerial !== undefined) {
                    document.getElementById('toggle_aerial').checked = Boolean(config.lamp_type_toggles.aerial);
                }
                if (config.lamp_type_toggles.submerged !== undefined) {
                    document.getElementById('toggle_submerged').checked = Boolean(config.lamp_type_toggles.submerged);
                }
            }

            if(config.env) {
                document.getElementById('mode-selector').value = config.env.type || 'estanque';
                currentSpaceType = config.env.type || 'estanque';
                document.getElementById('env_shape').value = config.env.shape || (config.env.type === 'estanque' ? 'circle' : 'rect');
                document.getElementById('env_radio').value = config.env.radio || 20;
                document.getElementById('env_x').value = config.env.x || 40;
                document.getElementById('env_y').value = config.env.y || 40;
                document.getElementById('z_water').value = config.env.z_interface || 3.2;
                document.getElementById('env_n1').value = config.env.n1 || 1.0;
                document.getElementById('env_n2').value = config.env.n2 || 1.33;
                document.getElementById('env_z').value = config.env.z || 15.0;
                
                if(currentSpaceType === 'estanque') {
                    document.getElementById('env_z_container').style.display = 'none';
                    document.getElementById('z_water_container').style.display = 'block';
                    document.getElementById('env_n1_container').style.display = 'block';
                    document.getElementById('env_n2_label').innerHTML = '<strong>Índice ref. medio 2</strong> <span class="normal-case">(Agua)</span>';
                    document.getElementById('wall_albedo_container').style.display = 'block';
                } else {
                    document.getElementById('env_z_container').style.display = 'block';
                    document.getElementById('env_x').value = config.env.x || 40;
                    document.getElementById('env_y').value = config.env.y || 40;
                    document.getElementById('env_z').value = config.env.z || 15.0;
                    
                    document.getElementById('z_water_container').style.display = 'none';
                    document.getElementById('env_n1_container').style.display = 'none';
                    document.getElementById('env_n2_label').innerHTML = '<strong>Índice ref. medio</strong> <span class="normal-case">(Agua)</span>';
                    document.getElementById('wall_albedo_container').style.display = 'none';
                }
                toggleShapePanel();
            }
            
            if(config.poly) {
                document.getElementById('poly_sides').value = config.poly.sides || 0;
                document.getElementById('poly_dist').value = config.poly.dist || 0;
            }
            
            if(config.roi) {
                document.getElementById('roi_type').value = config.roi.type || 'global';
                toggleRoiPanel();
                if(config.roi.type === 'paralelepipedo') {
                    document.getElementById('roi_p_l').value = config.roi.l || 10;
                    document.getElementById('roi_p_w').value = config.roi.w || 10;
                    document.getElementById('roi_p_h').value = config.roi.h || 5;
                    document.getElementById('roi_p_cx').value = config.roi.cx || 10;
                    document.getElementById('roi_p_cy').value = config.roi.cy || 10;
                    document.getElementById('roi_p_cz').value = config.roi.cz || 2.5;
                } else if(config.roi.type === 'cilindro') {
                    document.getElementById('roi_c_r').value = config.roi.r || 5;
                    document.getElementById('roi_c_h').value = config.roi.h || 5;
                    document.getElementById('roi_c_cx').value = config.roi.cx || 10;
                    document.getElementById('roi_c_cy').value = config.roi.cy || 10;
                    document.getElementById('roi_c_cz').value = config.roi.cz || 2.5;
                }
            }

            if(config.optics_mode) {
                document.getElementById('optics_mode').value = config.optics_mode;
                toggleOpticsPanel();
            }
            
            if(config.optics) {
                if (config.optics.kd_spectral) document.getElementById('kd_spectral_json').value = JSON.stringify(config.optics.kd_spectral);
                if (config.optics.c) document.getElementById('scatter_c').value = config.optics.c;
                if (config.optics.omega) document.getElementById('scatter_omega').value = config.optics.omega;
                if (config.optics.g) document.getElementById('scatter_g').value = config.optics.g;
                if (config.optics.r_wall) document.getElementById('scatter_rwall').value = config.optics.r_wall;
                
                if (config.optics.mc_input_type) {
                    document.getElementById('mc_input_type').value = config.optics.mc_input_type;
                }
                if (config.optics.tss !== undefined) document.getElementById('scat_tss').value = config.optics.tss;
                if (config.optics.cdom_a440 !== undefined) document.getElementById('scat_cdom').value = config.optics.cdom_a440;
                if (config.optics.chl !== undefined && document.getElementById('scat_chl')) {
                    document.getElementById('scat_chl').value = config.optics.chl;
                }
                if (config.optics.atten_coef_type !== undefined && document.getElementById('atten_coef_type')) {
                    const tval = String(config.optics.atten_coef_type).toLowerCase();
                    document.getElementById('atten_coef_type').value = (tval === 'kd' ? 'Kd' : 'c');
                    updateAttenLabels();
                }

                toggleScatteringMode();

                if (config.optics.c_json) document.getElementById('scatter_c_json').value = JSON.stringify(config.optics.c_json);
                if (config.optics.omega_json) document.getElementById('scatter_omega_json').value = JSON.stringify(config.optics.omega_json);
            }

            if(config.target_depths) document.getElementById('target_depths').value = config.target_depths.join(', ');
            if(config.rays) document.getElementById('rays_count').value = config.rays;
            if(config.kd_list) document.getElementById('kd_list').value = config.kd_list.join(', ');
            if(config.aporte_puntos_raw !== undefined) document.getElementById('aporte_puntos').value = config.aporte_puntos_raw;

            if(config.draw_contour !== undefined) document.getElementById('draw_contour').checked = config.draw_contour;
            if(config.contour_val !== undefined) document.getElementById('contour_val').value = config.contour_val;
            if(config.color_scale_type !== undefined) document.getElementById('color_scale_type').value = config.color_scale_type;
            
            if(config.irradiance_type !== undefined && document.getElementById('irradiance_type')) {
                document.getElementById('irradiance_type').value = config.irradiance_type;
                if(config.mu_max !== undefined && document.getElementById('mu_max')) document.getElementById('mu_max').value = config.mu_max;
                if(config.normalize_pineal !== undefined && document.getElementById('normalize_pineal')) document.getElementById('normalize_pineal').checked = config.normalize_pineal;
                togglePinealParams();
            }
            
            if(config.plot_depth_profile !== undefined) document.getElementById('plot_depth_profile').checked = config.plot_depth_profile;
            if(config.profile_step !== undefined) document.getElementById('profile_step').value = config.profile_step;
            
            if(config.plot_depth_summary_table !== undefined && document.getElementById('plot_depth_summary_table')) {
                document.getElementById('plot_depth_summary_table').checked = config.plot_depth_summary_table;
            }
            
            if(config.plot_env_optics !== undefined) document.getElementById('plot_env_optics').checked = config.plot_env_optics;
            if(config.plot_spectrum_initial !== undefined) document.getElementById('plot_spectrum_initial').checked = config.plot_spectrum_initial;
            if(config.plot_spectrum_normalized !== undefined) document.getElementById('plot_spectrum_normalized').checked = config.plot_spectrum_normalized;

            toggleSpectrumPanel();

            if(config.spectrum_ranges) {
                document.getElementById('spec_b_min').value = config.spectrum_ranges.blue[0];
                document.getElementById('spec_b_max').value = config.spectrum_ranges.blue[1];
                document.getElementById('spec_g_min').value = config.spectrum_ranges.green[0];
                document.getElementById('spec_g_max').value = config.spectrum_ranges.green[1];
                document.getElementById('spec_r_min').value = config.spectrum_ranges.red[0];
                document.getElementById('spec_r_max').value = config.spectrum_ranges.red[1];
            }

            if(config.summary_cols) {
                document.getElementById('col_lamps').checked = config.summary_cols.lamps;
                document.getElementById('col_pos').checked = config.summary_cols.pos;
                document.getElementById('col_power').checked = config.summary_cols.power;
                document.getElementById('col_vol').checked = config.summary_cols.vol;
            }
            
            const container = document.getElementById('lamp-list'); container.innerHTML = ''; lampCount = 0;
            if(config.lamps) {
                config.lamps.forEach(lamp => {
                    createLampElement({
                        xml: lamp.xml, 
                        x: lamp.x, 
                        y: lamp.y, 
                        z: lamp.z,
                        power: lamp.nominal_power !== undefined ? lamp.nominal_power : (lamp.power || 600), 
                        efficiency: lamp.efficiency || 1.0,
                        rot_x: lamp.rot_x || 0, 
                        rot_y: lamp.rot_y || 0, 
                        rot_z: lamp.rot_z || 0,
                        opacity: (lamp.manual_power || lamp.manual_z) ? '1.0' : '0.5',
                        manual_power: lamp.manual_power || false,
                        manual_z: lamp.manual_z || false
                    });
                });
            }
            updateGlobalLampControls();
            if(config.lamp_globals) {
                Object.keys(config.lamp_globals).forEach(xml => {
                    const group = document.querySelector(`.global-lamp-group[data-xml="${xml}"]`);
                    if (!group) return;
                    const settings = config.lamp_globals[xml];
                    if (settings.power !== undefined) group.querySelector('.glob-power').value = settings.power;
                    if (settings.z !== undefined) group.querySelector('.glob-z').value = settings.z;
                    if (settings.power !== undefined) applyGlobal(xml, 'power', settings.power);
                    if (settings.z !== undefined) applyGlobal(xml, 'z', settings.z);
                });
            }
            apply3DSceneSettings(config.scene3d);
            updateSecchi(); updateScene();
            event.target.value = ''; showStatusMessage("Configuración cargada");
        } catch (err) { alert("Error al leer el archivo JSON."); }
    };
    reader.readAsText(file);
}

document.addEventListener("DOMContentLoaded", function() {
    var acc = document.getElementsByClassName("accordion");
    for (var i = 0; i < acc.length; i++) {
        acc[i].addEventListener("click", function() {
            this.classList.toggle("active");
            var panel = this.nextElementSibling;
            if (panel.style.display === "block" || panel.classList.contains("show")) {
                panel.style.display = "none";
                panel.classList.remove("show");
            } else {
                panel.style.display = "block";
                panel.classList.add("show");
            }
            if(panel.classList.contains("show")) {
                setTimeout(updateScene, 100);
            }
        });
    }
});
