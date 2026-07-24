# Replicación óptica del Trial 3 de Porter et al. (2005)

## Alcance

Esta reconstrucción reproduce la exposición lumínica artificial asociada al Trial 3 del informe FRDC 2001/246. No constituye una predicción independiente del 18 % de crecimiento: el repositorio modela transporte de luz, mientras que el informe no publica una función dosis-respuesta que conecte irradiancia con crecimiento, temperatura, consumo de alimento y maduración.

El TM-33-18 aplicado al ensayo está en `uploaded_lamps/PORTER_2005_TRIAL3_SYNTHETIC_400W.xml`. La configuración nominal se entrega como `confgs/porter_2005_trial3_growth18_lit.confg` y, para compatibilidad con el selector actual del simulador, como `confgs/porter_2005_growth18_lit.json`.

## Evidencia experimental

Los métodos generales indican que las fuentes eran “either Aquabeam (Pisces 400 watt) or C&T Lighting (400 watt units)” y se ubicaban “at 5m in a 10m deep cage”. Para Trial 3, el informe especifica “constant additional illumination (4x400 watt submersible lights)”, desde el 28 de mayo hasta el 5 de noviembre de 2002, y que ambos grupos fueron “fed a ration of 2.3% body weight per day”. La población mixta total era de 132.000 peces, peso medio inicial 98 g, dividida en mitades lit y control.

El resultado fotobiológico se resume como 18 % de ventaja de crecimiento durante doce meses y 5–6 semanas de adelanto de cosecha. La sección de resultados publica además “mean weight of 2280±80g compared to 1880±70g”; su contraste directo es 21,28 %, no 18 %. El cálculo exacto del 18 % no puede reconstruirse porque no se publican datos individuales, tamaños muestrales ni la tabla numérica de la serie temporal de la Figura 13.

## Construcción fotométrica

La forma angular se infirió de los 48 lux del Apéndice 3 mediante

\[
E_v(r,z)=B+\frac{I_v(\theta)\cos\theta}{r^2+z^2}\exp[-c\sqrt{r^2+z^2}].
\]

La integral angular se restringió mediante un prior tecnológico de halogenuros metálicos de 400 W circa 2005. Cada fuente nominal tiene 35.502,5 lm, 116,01 W radiantes visibles, 400 W eléctricos, eficiencia radiante 0,29002 y un SPD blanco sintético de 3700 K con líneas de halogenuros. La eficacia fotópica radiométrica es 306,03 lm/W. El ajuste entrega \(c=0{,}28183\ \mathrm{m^{-1}}\), intervalo 90 % 0,21584–0,33612 m⁻¹, y fondo efectivo 32,11 lx. El fondo no se incorporó al Trial 3 porque no representa potencia de las luminarias.

El ajuste contra el apéndice obtiene \(R^2_{\log}=0{,}9045\), MAPE 20,78 % y RMSE multiplicativo ×1,420 en la validación del motor. Esas métricas evalúan la matriz del Apéndice 3, no el crecimiento de Trial 3.

## Geometría nominal

“80m diameter pen” se interpreta como jaula de 80 m de perímetro: radio 12,7324 m, diámetro 25,4648 m y profundidad 10 m. Si se interpretara literalmente como diámetro, el volumen sería aproximadamente 50.265 m³ y la biomasa final iluminada publicada correspondería a sólo 3,0 kg/m³. Con 80 m de perímetro el volumen es 5.093 m³ y la densidad aparente sería 29,5 kg/m³. La segunda escala es más coherente con una jaula comercial, pero no queda demostrada por el informe y se mantiene como incertidumbre estructural.

El plano de instalación no fue publicado. La solución nominal distribuye cuatro lámparas cada 90° sobre un anillo de radio R/2, todas a 5 m. Se analizaron también anillos R/3 y 2R/3. El TM-33 sólo identifica el hemisferio inferior medido en el apéndice; por ello el modelo nominal no asigna emisión sobre las lámparas. El plano z=5 m se omite porque una fuente puntual contenida en el plano produce una singularidad de tally.

## Resultado óptico nominal

La corrida final usa dos millones de rayos, grilla 128×128 y cuatro fuentes: 1.600 W eléctricos, 464,03 W radiantes y 142.010 lm. Durante 161 días de operación continua esto representa 6,182 MWh eléctricos y 1,793 MWh radiantes nominales.

| Profundidad | Media W/m² | Mediana W/m² | Media lx | Cobertura ≥0,017 | Cobertura ≥0,1 | Cobertura ≥1 |
|---:|---:|---:|---:|---:|---:|---:|
| 6 m | 0,561 | 0,0206 | 171,5 | 53,6 % | 24,1 % | 8,6 % |
| 7 m | 0,364 | 0,0651 | 111,4 | 72,0 % | 42,1 % | 13,4 % |
| 8 m | 0,241 | 0,1174 | 73,7 | 83,5 % | 53,0 % | 0,0 % |
| 9 m | 0,161 | 0,1393 | 49,1 | 89,7 % | 58,7 % | 0,0 % |
| 10 m | 0,107 | 0,1167 | 32,8 | 92,7 % | 54,7 % | 0,0 % |

Los umbrales 0,017, 0,1 y 1 W/m² son diagnósticos del simulador y no umbrales de crecimiento validados por Porter. La media disminuye con profundidad, mientras la mediana inicialmente aumenta porque el lóbulo angular alrededor de 40° se abre y cubre una fracción mayor de la jaula. Los máximos cerca de las fuentes dependen del tamaño de celda y son menos transferibles que media, mediana y cobertura.

## Incertidumbre

La incertidumbre óptica combina el intervalo de \(c\) con 25–31 % de eficiencia radiante. En el escenario bajo, la cobertura ≥0,017 W/m² entre 6 y 10 m es 46,1–82,9 %; en el alto es 60,9–99,3 %. El layout modifica la uniformidad sin cambiar sustancialmente la potencia total: R/3 entrega 40,7–74,7 % y 2R/3 entrega 50,6–96,4 %. Interpretar literalmente 80 m como diámetro reduce la cobertura a 5,1–12,3 %, demostrando que la geometría documental domina la incertidumbre del experimento completo.

La incertidumbre Monte Carlo es pequeña frente a las anteriores: al comparar 250.000 con 2.000.000 de rayos, la diferencia máxima de irradiancia media entre 6 y 10 m fue 0,0024 % y la diferencia máxima de cobertura fue 0,21 puntos porcentuales. Esto no elimina el error de modelo; sólo confirma convergencia numérica para la discretización elegida.

La escala absoluta por lámpara tiene un prior de 33–38 klm y 100–124 W visibles. El SPD original, la goniofotometría superior, el fabricante usado en Trial 3, el plano de las cuatro lámparas, la profundidad exacta de esa jaula, las propiedades ópticas durante 161 días y la luz ambiental no fueron publicados. La simulación Beer–Lambert tampoco representa dispersión múltiple, reflexión de red ni comportamiento de los peces.

La inferencia biológica tiene limitaciones todavía mayores: aparentemente existió una jaula por tratamiento, por lo que tratamiento y efecto-jaula no son separables; sólo se describen muestreos de hembras; no se informan n por fecha, datos crudos, mortalidad, consumo real, temperatura diaria ni biomasa ajustada. Por estas razones el campo óptico puede replicarse con incertidumbre cuantificada, pero atribuir causalmente 18 % de crecimiento a una dosis simulada concreta no es identificable con el documento disponible.

## Archivos reproducibles

La tabla planar está en `sensitivity/out/porter_trial3/trial3_depth_summary.csv`; la grilla completa en `trial3_irradiance_grid.csv`; los escenarios en `trial3_uncertainty_scenarios.csv`; y el resumen de supuestos en `trial3_replication_summary.json`. La ejecución se reproduce con `MPLCONFIGDIR=/tmp/porter-trial3-mpl venv/bin/python sensitivity/porter_trial3_replication.py --rays 2000000 --scenario-rays 250000 --bins 128`.
