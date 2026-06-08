Software para la simulación de irradiancia según archivos TM-33-18, con parámetros para posición, dimmerizado y rotación de lámparas. 

La instalación se realiza mediante la ejecución de iniciar_simulador.bat, creando un entorno virtual y abriendo la interfaz del simulador en una ventana del navegador.

El software contiene un motor de simulación por ray-tracing, que integra los efectos de refracción, reflexión y atenuación derivados del cambio de medio aire-agua.
Es posible simular estanques y jaulas. Los estanques siguen una lógica de altura desde nivel de piso, y las jaulas siguen una lógica de profundidad desde superficie.
Opción de descarga de gráficos integrada, para evaluaciones rápidas.
Opción de cargar y guardar parámetros.

## Presets bio-ópticos por centro

El módulo `optical_lookup.py` genera presets `claro`, `tipico` y `turbio`
compatibles con el modo `scattering -> bio` del simulador. Puede trabajar con
un CSV de observaciones satelitales/proxy, NOAA CoastWatch ERDDAP sin
credenciales, conectores remotos configurables o, si aun no hay datos, con una
clase de agua conservadora por centro. La interfaz
incluye un asistente dentro del panel bio-óptico para buscar por centro o
coordenadas, elegir fuente/período/buffer y aplicar el preset directamente a
TSS, CDOM, Chl-a y g.

El método operativo `scattering -> bio` corresponde a una parametrización
bio-óptica espectral general basada en absorción y dispersión. Se presenta por
separado de la opción `scattering -> ras_bardsnes`: Bårdsnes (2020) respalda la
influencia de la carga orgánica y las micropartículas sobre la luz en RAS, pero
no entrega coeficientes universales transferibles a cualquier instalación. La
opción RAS queda bloqueada hasta incorporar una calibración propia que relacione
carga orgánica o micropartículas con `c(λ)`, `Kd(λ)` o transmitancia espectral.

La interfaz bio-óptica utiliza un perfil estacional por semana ISO en lugar de
fechas arbitrarias. Para cada semana resume primero cada año completo y luego
combina los años con igual ponderación, evitando que un año con mayor cobertura
satelital domine el resultado. Una semana se marca como útil cuando reúne al
menos cuatro días válidos distribuidos en dos o más años. El endpoint
`/api/optical_weekly_profile` devuelve las 53 semanas, su cobertura, medianas,
rangos intercuartílicos y presets `claro`, `tipico` y `turbio`.

Ejemplo:

```bash
python optical_lookup.py --center pilpilehue --source auto --observations data/optical_observations_example.csv
```

También queda disponible en el backend:

```text
GET /api/optical_presets?center=pilpilehue
GET /api/optical_centers
GET /api/optical_sources/status
```

Columnas soportadas para observaciones: `center_id,date,source,tss,spm,chl,
cdom_a440,cdom_a443,kd490,zsd,quality`. Si `tss` falta se usa `spm`; si falta
`cdom_a440` y existe `cdom_a443`, se convierte con una pendiente CDOM típica;
si falta `kd490` y existe `zsd`, se estima `Kd ~= 1.7/ZSD`.

Los conectores remotos quedan desacoplados en `optical_sources/`. El conector
`noaa_coastwatch.py` descarga datos reales desde ERDDAP publico usando productos
DINEOF globales diarios de `chlor_a` y `kd_490`. Los conectores
`copernicus.py`, `nasa_oceancolor.py` y `sentinel2.py` reportan
disponibilidad/configuración.

Copernicus Marine usa GlobColour global L3 diario de 4 km:

```text
cmems_obs-oc_glo_bgc-plankton_my_l3-multi-4km_P1D
cmems_obs-oc_glo_bgc-transp_my_l3-multi-4km_P1D
cmems_obs-oc_glo_bgc-optics_my_l3-multi-4km_P1D
```

Para períodos recientes cambia automáticamente a las variantes `_nrt_`.
El conector entrega `CHL`, `KD490`, `SPM`, `CDM` y sus incertidumbres
porcentuales cuando estan disponibles.

NASA OceanColor usa las colecciones `VIIRSN_L3m_CHL`,
`VIIRSN_L3m_KD`, `VIIRSN_L3m_IOP`, `PACE_OCI_L3M_CHL`,
`PACE_OCI_L3M_KD` y `PACE_OCI_L3M_IOP`. El conector descarga archivos L3m
diarios de 4 km, extrae `chlor_a`, `Kd_490` y `adg_443`, limita las consultas
interactivas a 14 días y reutiliza archivos en `data/optical_cache/`.

Copernicus es la fuente preferida en modo `auto` porque entrega incertidumbres
porcentuales por variable. NASA OceanColor se puede seleccionar explicitamente
como fuente de contraste; sus archivos L3m usados aqui no incluyen una
incertidumbre porcentual por píxel equivalente.
