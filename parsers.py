import xml.etree.ElementTree as ET
import numpy as np
from scipy.interpolate import RegularGridInterpolator
import re

class TM33Parser:
    def __init__(self, xml_content):
        self.is_ies = False
        xml_clean = re.sub(r'\sxmlns="[^"]+"', '', xml_content, count=1)
        xml_clean = xml_clean.replace('xsi:', '')
        
        try:
            self.root = ET.fromstring(xml_clean)
            self.lum_interp = self._create_interpolator("./Emitter/LuminousData/LuminousIntensity")
            self.rad_interp = self._create_interpolator("./Emitter/RadiantData/RadiantIntensity")
        except Exception as e:
            print(f"Error XML parsing: {e}")
            self.root = ET.Element("root")
            self.lum_interp = lambda x: np.ones(len(x))
            self.rad_interp = lambda x: np.ones(len(x))

    def _create_interpolator(self, xpath):
        node = self.root.find(xpath)
        if node is None:
            tag = xpath.split('/')[-1]
            for elem in self.root.iter():
                if elem.tag.endswith(tag):
                    node = elem
                    break
        
        if node is None: return lambda x: np.zeros(len(x))

        data, h_set, v_set = [], set(), set()
        for d in node.findall('.//IntData'):
             h = float(d.get('h', 0))
             v = float(d.get('v', 0))
             try: val = float(d.text)
             except: val = 0.0
             data.append((h, v, val))
             h_set.add(h); v_set.add(v)

        if not data: return lambda x: np.zeros(len(x))

        sorted_h, sorted_v = sorted(list(h_set)), sorted(list(v_set))
        grid = np.zeros((len(sorted_h), len(sorted_v)))
        
        h_idx = {val: i for i, val in enumerate(sorted_h)}
        v_idx = {val: i for i, val in enumerate(sorted_v)}

        for h, v, val in data:
            grid[h_idx[h], v_idx[v]] = val

        if 0.0 in h_idx and 360.0 not in h_idx:
            sorted_h.append(360.0)
            grid = np.vstack([grid, grid[0:1, :]])

        return RegularGridInterpolator((sorted_h, sorted_v), grid, bounds_error=False, fill_value=0)

    def get_spectrum(self):
        spectrum = {}
        for tag in ["EmitterSpectral", "SpectralData", "Spectral"]:
            node = self.root.find(f".//{tag}")
            if node is not None:
                for pwr in node.findall(".//PwrData"):
                    try:
                        w = float(pwr.get('w'))
                        val = float(pwr.text)
                        spectrum[w] = val
                    except: pass
                if spectrum: return spectrum
        return spectrum

    def get_intensity(self, vectors):
        vz = np.clip(-vectors[:, 2], -1.0, 1.0) 
        theta_rad = np.arccos(vz)
        v_deg = np.degrees(theta_rad)
        
        phi_rad = np.arctan2(vectors[:, 1], vectors[:, 0])
        h_deg = np.mod(np.degrees(phi_rad), 360)
        
        pts = np.column_stack((h_deg, v_deg))
        return self.lum_interp(pts), self.rad_interp(pts)

class IESParser:
    def __init__(self, content_str):
        self.is_ies = True
        lines = content_str.replace('\r', '\n').split('\n')
        data_lines = []
        in_data = False
        tilt_type = "NONE"
        
        for line in lines:
            line = line.strip()
            if not line: continue
            if line.startswith('TILT='):
                tilt_type = line.split('=')[1].strip()
                in_data = True
                continue
            if in_data:
                data_lines.append(line)
        
        if not in_data:
            for i, line in enumerate(lines):
                if re.match(r'^\s*[\d\.\-]+\s+[\d\.\-]+\s+[\d\.\-]+\s*', line):
                    data_lines = lines[i:]
                    break
        
        tokens = []
        for line in data_lines:
            tokens.extend(line.split())
        
        if not tokens:
            self.lum_interp = lambda x: np.zeros(len(x))
            self.rad_interp = lambda x: np.zeros(len(x))
            return
            
        idx = 0
        if tilt_type == "INCLUDE":
            num_tilt_angles = int(tokens[1])
            idx = 2 + 2 * num_tilt_angles 
            
        self.num_lamps = int(tokens[idx])
        self.lumens = float(tokens[idx+1])
        self.multiplier = float(tokens[idx+2])
        num_v = int(tokens[idx+3])
        num_h = int(tokens[idx+4])
        
        idx += 13 
        v_angles = [float(x) for x in tokens[idx:idx+num_v]]
        idx += num_v
        h_angles = [float(x) for x in tokens[idx:idx+num_h]]
        idx += num_h
        
        candelas = np.zeros((num_h, num_v))
        for i in range(num_h):
            for j in range(num_v):
                candelas[i, j] = float(tokens[idx]) * self.multiplier
                idx += 1
                
        h_angles = np.array(h_angles)
        v_angles = np.array(v_angles)
        
        if len(h_angles) == 1 or h_angles[-1] == 0:
            h_angles = np.array([0.0, 90.0, 180.0, 270.0, 360.0])
            candelas = np.tile(candelas[0, :], (5, 1))
        elif h_angles[-1] == 90:
            h_angles_180 = np.concatenate((h_angles, 180 - h_angles[-2::-1]))
            candelas_180 = np.vstack((candelas, candelas[-2::-1, :]))
            h_angles_full = np.concatenate((h_angles_180, 360 - h_angles_180[-2::-1]))
            candelas_full = np.vstack((candelas_180, candelas_180[-2::-1, :]))
            h_angles, candelas = h_angles_full, candelas_full
        elif h_angles[-1] == 180:
            h_angles_full = np.concatenate((h_angles, 360 - h_angles[-2::-1]))
            candelas_full = np.vstack((candelas, candelas[-2::-1, :]))
            h_angles, candelas = h_angles_full, candelas_full
        elif h_angles[-1] < 360:
            h_angles = np.append(h_angles, 360.0)
            candelas = np.vstack((candelas, candelas[0, :]))
            
        self.lum_interp = RegularGridInterpolator((h_angles, v_angles), candelas, bounds_error=False, fill_value=0)
        self.rad_interp = self.lum_interp

    def get_spectrum(self): 
        return {} 
    
    def get_intensity(self, vectors):
        vz = np.clip(-vectors[:, 2], -1.0, 1.0) 
        theta_rad = np.arccos(vz)
        v_deg = np.degrees(theta_rad)
        phi_rad = np.arctan2(vectors[:, 1], vectors[:, 0])
        h_deg = np.mod(np.degrees(phi_rad), 360)
        pts = np.column_stack((h_deg, v_deg))
        return self.lum_interp(pts), self.rad_interp(pts)