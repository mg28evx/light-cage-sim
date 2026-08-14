# Interfaz bio-óptica relativa para *Caligus*

Esta capa agrega una salida separada del simulador óptico para evaluar índices
relativos de solapamiento vertical pez–copepodito. **No cambia el significado
físico de las salidas existentes**: los mapas y tablas principales siguen
reportando irradiancia simulada según la configuración óptica activa.

## Qué calcula el motor óptico

`simulation_engine.py` simula propagación de luz desde archivos TM-33/IES y
entrega irradiancia radiométrica en `W/m²`. Para TM-33 usa la distribución
angular radiométrica y el SPD espectral del archivo. Para el análisis
bio-óptico se exige SPD real en los TM-33 utilizados.

La ruta volumétrica es *opt-in* mediante `volume_tally`. Usa un estimador por
longitud de trayectoria: acumula `W · ds` dentro de cada celda y divide por el
volumen de celda, entregando una magnitud radiométrica volumétrica en `W/m²`
comparable como irradiancia escalar / *fluence rate* por celda. Esta ruta está
apagada por defecto y no altera los mapas por plano existentes.

## De dónde salen los parámetros ópticos

El campo de luz que alimenta estos índices depende de `a(λ)`, `b(λ)` y `c(λ)`,
que a su vez se derivan de `TSS`, `CDOM a440` y `Chl-a`. El selector **Origen de
parámetros** de la sección de óptica define si esos tres valores se ingresan a
mano, se recuperan por teledetección o provienen de un CSV de medición local.
La procedencia queda registrada por parámetro y se guarda en la configuración.

Las transformaciones intermedias —conversión proxy FNU→TSS, agregación por
semana ISO, cuantiles P25/P50/P75 y el ajuste inverso al `Kd(490)` observado—
están desarrolladas ecuación por ecuación en el panel **Método y ecuaciones** de
la ayuda, y en `documentacion_fisica.tex` (§ presets bio-ópticos desde
teledetección). Conviene revisarlas antes de comparar escenarios: dos corridas
con distinta procedencia de parámetros no son directamente comparables aunque
los tres números se vean parecidos.

## Qué calcula el post-procesamiento biológico

`biooptical_analysis.py` resume la grilla 3D por capas verticales. Sea `i` el
índice de capa, `C_i` la fracción de copepoditos y `F_i` la fracción de peces en
esa capa, y `E_i` la irradiancia representativa de la capa:

| Índice | Definición | Lectura |
| --- | --- | --- |
| `IC` | `Σᵢ Cᵢ·Fᵢ` | Solapamiento vertical puro, sin luz |
| `IE_pez_total` | `Σᵢ Fᵢ·E_total,ᵢ` | Exposición lumínica del pez |
| `IE_contacto_total` | `Σᵢ Cᵢ·Fᵢ·E_total,ᵢ` | Solapamiento ponderado por luz |
| `IE_contacto_spectral` | `Σᵢ Cᵢ·Fᵢ·(w_b·E_azul,ᵢ + w_g·E_verde,ᵢ + w_r·E_rojo,ᵢ)` | Solapamiento ponderado por banda |

Los perfiles `C(z)` y `F(z)` se normalizan para sumar 1 sobre las capas
analizadas:

```text
Σᵢ Cᵢ = 1        Σᵢ Fᵢ = 1
```

Por construcción, los índices son **relativos**: sirven para ordenar escenarios
entre sí, no para estimar probabilidad de infección ni abundancia esperada. Un
`IE_contacto` que duplica al de otro escenario indica el doble de solapamiento
ponderado bajo los supuestos declarados, no el doble de infestación.

## Salidas

La sección **Bio-óptica Caligus** de la interfaz permite:

- activar la salida bio-óptica para la simulación actual;
- configurar capas, resolución horizontal, paso de *tally* y umbrales;
- seleccionar perfiles larvales y de pez;
- guardar configuraciones completas como escenarios *batch*;
- comparar escenarios contra una base de normalización.

El backend devuelve:

- CSV por capas con medias, medianas, P90/P95, máximos, bandas azul/verde/rojo y
  fracciones de volumen sobre umbrales;
- CSV de índices `IC`, `IE_pez`, `IE_contacto` e `IE_contacto_spectral`;
- CSV opcional de celdas 3D;
- gráficos de irradiancia por capa, bandas, mapa de calor escenario-profundidad e
  índice espectral de contacto.

## Supuestos y límites

- La luz se trata como modulador secundario, principalmente vía cambios en `F(z)`.
- Las distribuciones larvales por defecto son escenarios de sensibilidad, no una
  distribución fija universal.
- Los pesos espectrales por defecto (`azul = 1.0`, `verde = 0.7`, `rojo = 0.2`)
  son exploratorios y deben validarse con datos biológicos.
- Los umbrales `0.054`, `0.54`, `5.4` y `8.7 W/m²` son anclas experimentales
  configurables, no límites biológicos universales.
- El modelo no reemplaza salinidad, temperatura, circulación, presión larval
  local ni ventana temporal de siembra.
- Frenzl / Nordtug / Genna se usan como respaldo cualitativo o *proxy*; no se
  implementan como funciones universales de fijación.
- La incertidumbre de los parámetros ópticos se propaga a estos índices sin
  cuantificarse. Un preset satelital con confianza baja produce índices con la
  misma confianza baja, aunque el número resultante se vea preciso.

## Validaciones implementadas

- Capas con rango positivo y sin solapamiento.
- Bandas espectrales no solapadas.
- Umbrales y pesos no negativos.
- `Cᵢ` y `Fᵢ` suman 1.
- Irradiancia finita y no negativa.
- Escenario base de normalización obligatorio cuando se solicita ratio relativo.
