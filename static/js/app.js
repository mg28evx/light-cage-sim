window.measurements = [];
window.lastResults = null;
window.lampProfiles = {}; 
let lampCount = 0; 
let currentAbortController = null;

const modeConfigs = {
    'estanque': { type: 'estanque', shape: 'circle', radio: 10, z_water: 3.2, env_z: 15.0, depths: '2.0, 1.0', kd_list: '0.20', n1: 1.0, n2: 1.33 },
    'jaula': { type: 'jaula', shape: 'rect', env_x: 30, env_y: 30, z_water: 20.0, env_z: 15.0, depths: '5.0, 10.0, 15.0', kd_list: '0.50', n1: 1.0, n2: 1.33 }
};

let currentSpaceType = 'estanque';

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
    if (!xml_name || window.lampProfiles[xml_name]) return;
    try {
        const res = await fetch('/api/lamp_profile/' + encodeURIComponent(xml_name));
        const data = await res.json();
        if (!data.error) {
            window.lampProfiles[xml_name] = data;
            
            document.querySelectorAll('.lamp-item').forEach(item => {
                if (item.querySelector('.lamp-xml').value === xml_name) {
                    const effInput = item.querySelector('.lamp-eff');
                    if (effInput && data.efficiency) {
                        effInput.value = data.efficiency;
                    }
                    const pwrInput = item.querySelector('.lamp-power');
                    if (pwrInput && data.elec_power && pwrInput.getAttribute('data-manual') !== 'true') {
                        pwrInput.value = data.elec_power;
                    }
                    updateLampEfficiency(pwrInput);
                }
            });
            updateLampNames();
            updateScene(); 
        }
    } catch(e) { console.error("Error trayendo curva polar", e); }
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

function updateSecchi() {
    const secchiEl = document.getElementById('secchi_display');
    if (!secchiEl) return;
    const kdRaw = document.getElementById('kd_list').value;
    const kds = kdRaw.split(',').map(v => parseFloat(v.trim())).filter(v => !isNaN(v) && v > 0);
    const secchis = kds.map(kd => (1.7 / kd).toFixed(2) + 'm');
    secchiEl.innerHTML = secchis.length ? `Eq. Disco Secchi: ${secchis.join(' | ')}` : '';
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
        badge.innerHTML = `Flujo Radiante: <strong style="color:#d62728;">${rad.toFixed(2)} W</strong>`;
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

    const lampX = [], lampY = [], lampText = [];
    
    document.querySelectorAll('.lamp-item').forEach((item, index) => {
        let x = parseFloat(item.querySelector('.lamp-x').value) || 0;
        let y = parseFloat(item.querySelector('.lamp-y').value) || 0;
        let z = parseFloat(item.querySelector('.lamp-z').value) || 0;
        let rx = parseFloat(item.querySelector('.lamp-rot-x').value) || 0;
        let ry = parseFloat(item.querySelector('.lamp-rot-y').value) || 0;
        let rz = parseFloat(item.querySelector('.lamp-rot-z').value) || 0;
        let xml = item.querySelector('.lamp-xml').value;

        let isAerial = (currentSpaceType === 'estanque' && z > zInterface) || (currentSpaceType === 'jaula' && z < 0);
        if (isAerial && !activeAerial) return;
        if (!isAerial && !activeSubmerged) return;

        let label = item.getAttribute('data-label') || `L${index + 1}`;
        lampX.push(x); lampY.push(y); lampText.push(label);

        let profile = window.lampProfiles[xml];
        if (profile) {
            const VISUAL_SCALE = parseFloat(document.getElementById('beam_scale').value) || 8.0; 
            const radX = rx * Math.PI / 180, radY = ry * Math.PI / 180, radZ = rz * Math.PI / 180;
            const cosX = Math.cos(radX), sinX = Math.sin(radX);
            const cosY = Math.cos(radY), sinY = Math.sin(radY);
            const cosZ = Math.cos(radZ), sinZ = Math.sin(radZ);
            
            let polyColor = isAerial ? 'rgba(255, 199, 44, 0.8)' : 'rgba(0, 191, 255, 0.8)';
            let polyFill = isAerial ? 'rgba(255, 199, 44, 0.25)' : 'rgba(0, 191, 255, 0.25)';

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

    traces.push({ 
        x: lampX, y: lampY, mode: 'text', type: 'scatter', name: 'Lámparas_Texto', 
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
        if (isAerial && !activeAerial) return;
        if (!isAerial && !activeSubmerged) return;

        let coreColor = isAerial ? 'var(--evolux-yellow)' : '#00bfff';

        layout.shapes.push({
            type: 'circle',
            x0: x - 0.4, y0: y - 0.4, x1: x + 0.4, y1: y + 0.4,
            fillcolor: coreColor, line: { color: 'black', width: 2 }
        });

        if (rx !== 0 || ry !== 0) {
            layout.annotations.push({ x: x, y: y + 1.2, text: `Tilt: ${rx}°, ${ry}°`, showarrow: false, font: {size: 11, color: '#1f77b4', weight: 'bold'} });
        }
    });

    return layout;
}

function updateScene() {
    if (typeof Plotly === 'undefined') return;
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
    updateSecchi(); 
    togglePinealParams(); 

    const tssInput = document.getElementById('scat_tss');
    const cdomInput = document.getElementById('scat_cdom');
    if (tssInput) tssInput.addEventListener('input', updateBioOpticalReference);
    if (cdomInput) cdomInput.addEventListener('input', updateBioOpticalReference);
    
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
        
        groupContainer.innerHTML = `
            <div style="background-color: var(--evolux-yellow); color: var(--evolux-black); font-weight: 800; font-size: 11px; padding: 6px 10px; border-bottom: 1px solid #ccc; display: flex; align-items: center; gap: 8px;">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>
                <span>GRUPO: ${model.replace('.xml', '').replace('.ies', '')}</span>
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
            <div class="z-label-container"><strong>${zLabelText}:</strong> <input type="number" class="lamp-z" value="${lampObj.z}" style="width:100%; padding:5px; opacity:${lampObj.opacity || '1.0'};" oninput="removeLampManualOverride(this)"></div>
            
            <div style="grid-column: span 3; background:#fffae6; padding: 5px; border-radius: 4px; border: 1px solid var(--evolux-yellow);">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 4px;">
                    <strong>Potencia eléctrica de consumo (W):</strong> 
                    <span class="eff-badge" style="font-size:11px; color:#1f77b4; font-weight:bold;">Flujo Radiante: -- W</span>
                </div>
                <input type="number" class="lamp-power" value="${lampObj.power}" style="width:100%; padding:5px; opacity:${lampObj.opacity || '1.0'};" oninput="removeLampManualOverride(this); updateLampEfficiency(this)">
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

function addLamp() {
    try {
        const sel = document.getElementById('lamp_model_selector');
        const model = sel ? sel.value : null;
        if(!model || model === "") { alert("Primero seleccione un modelo de lámpara."); return; }

        const dims = getSpaceDimensions();
        
        let defaultX = dims.shape === 'circle' ? dims.radius : dims.x / 2;
        let defaultY = dims.shape === 'circle' ? dims.radius : dims.y / 2;
        let defaultZ = currentSpaceType === 'estanque' ? parseFloat(document.getElementById('z_water').value) + 0.5 : 2.0;
        
        // Se asume 600W por defecto hasta que la API retorne el valor correcto del XML
        let defaultPower = 600; 

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
            efficiency: 1.0 
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
        let pwrVal = parseFloat(item.querySelector('.lamp-power').value) || 0;
        let effVal = parseFloat(item.querySelector('.lamp-eff').value) || 1.0;

        let isAerial = (currentSpaceType === 'estanque' && zVal > zInterface) || (currentSpaceType === 'jaula' && zVal < 0);
        if (isAerial && !activeAerial) pwrVal = 0;
        if (!isAerial && !activeSubmerged) pwrVal = 0;

        lamps.push({
            label: item.getAttribute('data-label'),
            xml: item.querySelector('.lamp-xml').value,
            x: parseFloat(item.querySelector('.lamp-x').value) || 0, 
            y: parseFloat(item.querySelector('.lamp-y').value) || 0, 
            z: zVal,
            power: pwrVal, 
            efficiency: effVal,
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
            mc_input_type: mc_input_type,
            tss: parseFloat(document.getElementById('scat_tss').value) || 15.0,
            cdom_a440: parseFloat(document.getElementById('scat_cdom').value) || 1.0,
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
    
    txt += "\n--- MODELADO DE IRRADIANCIA ---\n";
    txt += "METRICA: " + (payload.irradiance_type === 'pineal' ? 'Ponderada (Fisica Pineal)' : 'Escalar (Magnitud Bruta)') + "\n";
    if (payload.irradiance_type === 'pineal') {
        txt += "ANGULO LIMITE (u_max): " + payload.mu_max + " grados\n";
        txt += "NORMALIZACION A 1.0: " + (payload.normalize_pineal ? 'Activada' : 'Desactivada') + "\n";
    }
    
    txt += "\n--- OPTICA ---\n";
    txt += "MODO: " + payload.optics_mode + "\n";
    if (payload.optics_mode === 'scattering') {
         txt += "INPUT: " + payload.optics.mc_input_type + "\n";
         if (payload.optics.mc_input_type === 'bio') {
             txt += "TSS: " + payload.optics.tss + " mg/L\n";
             txt += "CDOM a(440): " + payload.optics.cdom_a440 + " m^-1\n";
         } else if (payload.optics.mc_input_type === 'scalar') {
             txt += "ATENUACION C: " + payload.optics.c + "\n";
         }
    } else if (payload.optics_mode === 'kd_fijo') {
         txt += "KD FIJO: " + payload.optics.kd_fijo + "\n";
    }
    
    txt += "\n--- LAMPARAS ---\n";
    let activas = 0;
    payload.lamps.forEach((l, i) => {
         if (l.power > 0) activas++;
         let label = l.label || `L${i+1}`;
         txt += `${label}: ${l.xml} | Pos(${l.x}, ${l.y}, ${l.z}) | Rot(${l.rot_x}, ${l.rot_y}, ${l.rot_z})\n`;
         txt += `       └─ Pwr Eléctrica: ${l.power}W | Eficiencia WPE: ${(l.efficiency*100).toFixed(1)}% | Pwr Radiante (Φe): ${(l.power*l.efficiency).toFixed(2)}W\n`;
    });
    txt += "TOTAL ACTIVAS: " + activas + "\n";
    
    txt += "\n--- RAY TRACING ---\n";
    txt += "RAYOS POR LÁMPARA: " + payload.rays + "\n";
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
            try {
                renderResults(data, payload); 
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
                   <tr><th>PARÁMETROS ÓPTICOS</th><th>DISCO SECCHI EQ.</th><th>FLUJO TOTAL (W)</th><th>PROM (W/m²)</th><th>PROM (Lux)</th><th>PROM (μmol)</th><th>MÁX (W/m²)</th><th>MÍN (W/m²)</th><th>VOLUMEN ILUM (%)</th>`;
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
                                    <td rowspan="${numLamps}">${r_min}</td>
                                    <td rowspan="${numLamps}"><strong>${r_vol}%</strong></td>`;
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
    dlHtml += `<button class="btn-download" style="background:#1f77b4;" onclick="downloadAllZip()">⬇ DESCARGAR PAQUETE COMPLETO (ZIP)</button>`;
    dlHtml += `<div style="font-size:10px; color:#888; text-align:center; margin-top:10px;">Se generará un archivo ZIP comprimido con todos los mapas de irradiancia y el reporte técnico detallado.</div>`;
    
    dlContainer.innerHTML = dlHtml;
}

async function downloadCombined() {
    if(!window.lastResults || !window.lastResults.kds || window.lastResults.kds.length === 0) return;
    const kd = window.lastResults.kds[0];
    const img = window.lastResults.results_by_kd[kd].combined_image;
    if(img) {
        const cleanTitle = window.lastResults.clean_title;
        const suffix = window.lastResults.file_suffixes[kd];
        const filename = `${cleanTitle}_consolidado_${suffix}.png`;
        try {
            if (window.showSaveFilePicker) {
                const handle = await window.showSaveFilePicker({
                    id: 'export_images',
                    suggestedName: filename,
                    types: [{ description: 'PNG Image', accept: {'image/png': ['.png']} }]
                });
                const writable = await handle.createWritable();
                const response = await fetch("data:image/png;base64," + img);
                await writable.write(await response.blob());
                await writable.close();
                showStatusMessage("Gráfico guardado correctamente");
            } else {
                throw new Error("API no soportada");
            }
        } catch (e) {
            if(e.name !== 'AbortError') {
                const a = document.createElement('a');
                a.href = "data:image/png;base64," + img;
                a.download = filename;
                a.click();
            }
        }
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

        const reportBlob = createReportBlob(getPayload(false), window.lastResults);
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

function loadConfiguration(event) {
    const file = event.target.files[0]; if (!file) return;
    const reader = new FileReader();
    reader.onload = function(e) {
        try {
            const config = JSON.parse(e.target.result);
            
            if(config.project_title !== undefined) {
                document.getElementById('project_title').value = config.project_title;
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
                    document.getElementById('env_x').value = config.env_x;
                    document.getElementById('env_y').value = config.env_y;
                    document.getElementById('env_z').value = config.env_z;
                    
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
                        power: lamp.power || 600, 
                        efficiency: lamp.efficiency || 1.0,
                        rot_x: lamp.rot_x || 0, 
                        rot_y: lamp.rot_y || 0, 
                        rot_z: lamp.rot_z || 0,
                        opacity: '0.5'
                    });
                });
            }
            updateGlobalLampControls(); updateSecchi(); updateScene();
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