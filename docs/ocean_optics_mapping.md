# Mapeo fisico Ocean Optics Web Book y ruta predictiva SRTE

## Objetivo

El objetivo fisico del simulador no es solo dibujar mapas de irradiancia, sino
estimar, con la mayor capacidad predictiva posible, cuantas luminarias son
necesarias para alcanzar un umbral biologico de irradiancia bajo condiciones
opticas locales. En terminos de transferencia radiativa, el problema directo es:

1. Caracterizar la fuente luminosa: potencia radiante espectral y distribucion
   angular.
2. Caracterizar el medio: propiedades opticas inherentes, o IOPs, por longitud
   de onda.
3. Resolver transporte radiativo escalar en un dominio de jaula/estanque con
   limites geometricos.
4. Integrar la radiancia o los paquetes de energia sobre planos/sensores para
   obtener irradiancia, lux, PPFD y metricas espectrales.

El Ocean Optics Web Book ordena este marco en radiometria, IOP/AOP, absorcion,
dispersion, superficies, transferencia radiativa y Monte Carlo. El simulador
implementa una version escalar de ese marco, especializada para fuentes
artificiales y geometria de acuicultura.

## Mapeo principal

| Bloque del simulador | Codigo | Contenido Ocean Optics Web Book | Comentario tecnico |
| --- | --- | --- | --- |
| Radiometria y fotometria de fuente | `parsers.py`, `simulation_engine.py` | Light and Radiometry: Units, Geometry, Geometrical Radiometry | La fuente se modela como intensidad radiante angular `I(theta,phi)` normalizada a flujo radiante. |
| Interfaz aire-agua | `fresnel_transmission`, refraccion en `SimulationEngine.run` | Surfaces: Level Sea Surface, Fresnel Equations for Polarization | Se usa Fresnel no polarizado y superficie plana. No se modela oleaje, polarizacion ni Cox-Munk. |
| Atenuacion determinista | modos `kd_fijo`, `kd_espectral` | Inherent and Apparent Optical Properties: K functions | Si el coeficiente se declara como `c`, se aplica por camino real; si se declara `Kd`, se aplica por desplazamiento vertical. |
| Bio-optica | `bio_optical_iop` | Absorption; Optical Constituents: Water, Phytoplankton, CDOM, NAP | Modelo de cuatro componentes: agua pura, CDOM, fitoplancton y TSS como proxy de particulas. |
| Monte Carlo volumetrico | modo `scattering` | Radiative Transfer Theory; Monte Carlo Simulation: Ray Tracing | Se muestrean distancias libres con `-ln(U)/c`, se conserva peso con albedo de scattering y se aplican fases HG/FF. |
| Funcion de fase | HG y Fournier-Forand | Scattering: Henyey-Greenstein, Fournier-Forand | HG es operacional; FF es mas oceanografica porque desacopla retrodispersion de asimetria. |
| Superficies internas | pared lambertiana, suelo absorbente, superficie Fresnel | Surfaces: BRDF, Lambertian BRDFs | Aproximacion de ingenieria. La red de una jaula no esta calibrada como BRDF real. |
| Color, lux y visibilidad | CIE, `V(lambda)`, Secchi equivalente | Photometry and Visibility: Luminosity Functions, Chromaticity, Secchi Disk | Estas son salidas interpretativas. Secchi no controla el transporte Monte Carlo. |
| Datos remotos | `optical_lookup.py`, `optical_sources/` | Remote Sensing; Atmospheric Correction; Reflectances | Los productos satelitales se reducen a proxies de IOP/AOP; no se resuelve correccion atmosferica ni inversion ocean-color dentro del motor. |

## Modelo fisico minimo para prediccion

Para que el SRTE sea predictivo, los insumos opticos no deberian entrar como un
unico `Kd` o una turbidez aislada. La forma minima fisicamente trazable es:

```text
a(lambda) = aw(lambda) + a_cdom(lambda) + a_phy(lambda) + a_nap(lambda)
b(lambda) = b_particles(lambda) + b_water(lambda)
c(lambda) = a(lambda) + b(lambda)
bb(lambda) = B(lambda) * b(lambda)
omega0(lambda) = b(lambda) / c(lambda)
```

El Monte Carlo usa directamente `c(lambda)`, `omega0(lambda)` y una funcion de
fase. Para AOPs derivadas, como `Kd(lambda)` y Secchi equivalente, se necesita
ademas una relacion IOP -> AOP, por ejemplo Kirk/Gershun o Lee et al. 2005.

El modo bio-optico actual cubre una version reducida:

```text
a(lambda) = aw(lambda) + CDOM440 * exp[-S_CDOM(lambda - 440)] + aphy*(lambda) * Chl
b(lambda) = bstar_TSS(lambda) * TSS
c(lambda) = a(lambda) + b(lambda)
omega0(lambda) = b(lambda) / c(lambda)
```

Esta estructura es correcta como esqueleto, pero su poder predictivo depende de
calibrar los coeficientes especificos y sus incertidumbres por zona.

## Ingesta indirecta de datos locales

La ruta indirecta recomendada es jerarquica: usar la fuente de mayor contenido
fisico disponible y degradar con incertidumbre explicita cuando no exista acceso
al sitio.

### Nivel 0: clase de agua y defaults conservadores

Entrada:

- tipo de sitio: fiordo claro, fiordo tipico, fiordo turbio, costa turbia;
- estacion o semana del ano;
- antecedentes operacionales: floraciones, lluvia, descarga fluvial, alimento,
  corrientes, profundidad, cercania a costa.

Uso fisico:

- define priors para `TSS`, `CDOM a440`, `Chl-a`, `g`, `bb/b` y rango de `Kd490`;
- sirve para diseno preliminar y analisis de sensibilidad.

Riesgo:

- no identifica eventos locales de alta absorcion CDOM ni resuspension;
- deberia producir escenarios `claro`, `tipico`, `turbio`, no un valor unico.

### Nivel 1: productos satelitales globales L3

Entrada:

- `Chl-a`, `Kd490`, `SPM`, `CDM/adg443` desde Copernicus, NASA OceanColor o NOAA.

Uso fisico:

- `Chl-a` alimenta absorcion fitoplanctonica;
- `CDM/adg443` alimenta CDOM y detritus, convertido a `a440` con pendiente
  espectral;
- `SPM` o `TSS` proxy alimenta dispersion particulada;
- `Kd490` restringe la magnitud AOP y permite ajustar defaults cuando faltan
  componentes.

Riesgo:

- resolucion espacial de kilometros puede mezclar costa, sombra, sedimento y agua
  fuera de la jaula;
- `Kd490` no reconstruye por si solo `a(lambda)`, `b(lambda)` ni color espectral;
- es AOP dependiente de geometria solar/cielo, no IOP pura.

### Nivel 2: Sentinel-2 con ACOLITE/DSF

Entrada:

- reflectancia de agua corregida atmosfericamente `rhow`;
- turbidez Nechad o producto ACOLITE;
- si se calibra, transformacion turbidez FNU -> TSS/SPM.

Uso fisico:

- mejor resolucion espacial para fiordos y borde costero;
- permite capturar gradientes locales alrededor de centros;
- con calibracion local, `FNU -> TSS -> b(lambda)` puede alimentar directamente el
  Monte Carlo.

Riesgo:

- requiere correccion atmosferica robusta;
- Nechad estima turbidez desde reflectancia roja/NIR y no separa absorcion de
  dispersion;
- FNU no es `b(lambda)`: es respuesta instrumental angular/espectral de luz
  dispersada, sensible a tamano, forma e indice de particulas.

### Nivel 3: mediciones locales puntuales de baja friccion

Aunque el acceso no siempre sea viable, pocas mediciones bien elegidas aumentan
mucho la predictividad:

- Secchi o camara de contraste: restringe transparencia aparente;
- turbidimetro FNU/NTU: restringe dispersion relativa;
- fluorometro Chl-a: restringe absorcion pigmentaria;
- muestras filtradas para TSS/SPM: calibra masa de particulas;
- espectrofotometria de CDOM filtrado: calibra `a_cdom(440)` y `S_CDOM`;
- medicion vertical de irradiancia con la lampara apagada/encendida: calibra
  `Kd(lambda)` y valida el cierre IOP -> AOP.

Uso fisico:

- convierte proxies satelitales en coeficientes opticos locales;
- permite estimar incertidumbre y sesgo por temporada.

### Nivel 4: paquete optico completo

Entrada ideal:

- absorcion `a(lambda)` por AC-S/ACS o equivalente;
- atenuacion de haz `c(lambda)`;
- VSF o retrodispersion `bb(lambda)`;
- PAR/espectral vertical;
- reflectancia de superficie/fondo/red.

Uso fisico:

- parametriza directamente SRTE/Monte Carlo;
- permite validacion predictiva de numero de lamparas.

Riesgo:

- costo/logistica alto; util como campana de calibracion, no como requisito para
  cada sitio.

## Calibraciones prioritarias

### 1. Turbidez FNU -> TSS/SPM

Forma inicial:

```text
TSS = alpha_site * FNU + beta_site
```

Fisica:

- FNU mide luz dispersada por un instrumento a geometria especifica;
- TSS mide masa seca por volumen;
- la pendiente cambia con granulometria, organico/inorganico, color e indice de
  refraccion de particulas.

Recomendacion:

- estimar `alpha_site`, `beta_site` por centro o macrozona;
- guardar incertidumbre y no usar equivalencia 1:1 como calibracion final.

### 2. TSS/SPM -> b(lambda)

Forma inicial:

```text
b_particles(lambda) = bstar(lambda) * TSS
bstar(lambda) = bstar_550 * (lambda / 550)^(-eta_b)
```

Fisica:

- `bstar` es coeficiente especifico de dispersion por masa;
- `eta_b` resume tamano de particula: particulas mas pequenas suelen aumentar la
  pendiente espectral.

Recomendacion:

- calibrar `bstar_550` con mediciones de `c(lambda)` o turbidez + Secchi;
- usar distribuciones por clase de agua cuando no exista medicion local.

### 3. CDOM a440 y pendiente espectral

Forma:

```text
a_cdom(lambda) = a_cdom(440) * exp[-S_CDOM(lambda - 440)]
```

Fisica:

- CDOM absorbe fuerte en azul/violeta;
- `S_CDOM` controla el cambio de color con profundidad;
- lluvia, rios y materia organica pueden cambiar `S_CDOM` estacionalmente.

Recomendacion:

- si solo hay `adg443`, convertir a `a440` pero conservar etiqueta de proxy;
- calibrar `S_CDOM` por macrozona o estacion cuando haya muestras filtradas.

### 4. Chl-a -> absorcion fitoplanctonica

Forma actual:

```text
a_phy(lambda) = aphy_star(lambda) * Chl
```

Fisica:

- `aphy_star` cambia por comunidad, empaque celular, estado fisiologico y
  fotoaclimatacion;
- Chl-a satelital no es una medicion directa de absorcion local bajo jaula.

Recomendacion:

- usar Chl-a principalmente para ajustar absorcion espectral y escenarios de
  floracion;
- no dejar que Chl-a satelital domine si la cobertura es pobre.

### 5. Retrodispersion y funcion de fase

Forma:

```text
bb(lambda) = B(lambda) * b(lambda)
```

Fisica:

- `bb/b` controla cuanta luz vuelve hacia arriba o se difunde lateralmente;
- HG ata `bb/b` a `g`, lo que puede ser restrictivo;
- Fournier-Forand permite desacoplar `bb/b` mediante parametros ligados a
  distribucion de tamanos.

Recomendacion:

- usar Fournier-Forand como modo predictivo preferente;
- calibrar `bb/b` con sensores de backscatter, reflectancia remota o literatura
  por tipo de particula.

## Estrategia predictiva recomendada

1. Ejecutar siempre tres escenarios por sitio: claro, tipico, turbio.
2. Para cada escenario, propagar no solo medianas sino rangos p25-p75 o bandas de
   incertidumbre de `a`, `b`, `c`, `omega0`, `bb/b`, `Kd`.
3. Dimensionar lamparas contra un percentil conservador: por ejemplo, cumplir el
   umbral biologico en escenario tipico y reportar deficit en escenario turbio.
4. Separar datos observados, proxies y defaults en el JSON de salida.
5. Guardar diagnosticos opticos por corrida para auditar por que un sitio exige
   mas o menos potencia.

## Trabajo pendiente para cerrar brecha predictiva

Autonomo:

- exponer diagnosticos IOP/AOP por corrida;
- agregar pruebas fisicas de limites y coherencia;
- documentar explicitamente que fuentes remotas son ingesta de parametros, no
  inversion completa;
- permitir escenarios probabilisticos por percentiles.

Depende de datos/decision:

- calibracion `FNU -> TSS` por macrozona;
- calibracion `TSS -> b(lambda)` y `bb/b`;
- validacion de `S_CDOM` y `aphy_star`;
- criterio biologico final: irradiancia escalar, planar descendente, PPFD,
  fotoperiodo, o una respuesta espectral/pineal calibrada.
