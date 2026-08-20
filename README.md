# Red Regional · Visor GTFS

Web estática que descarga a diario los GTFS estáticos de las 21 zonas reguladas
(DTPR/MTT), calcula métricas y las muestra en un mapa con perfil de frecuencia y
un tótem de parada con los servicios que pasan por cada `stop_id`.

Todo corre en **GitHub Actions + GitHub Pages**: no hay servidor. Cada día el
workflow baja los feeds, procesa y republica.

## Qué muestra

- **Métricas por zona**: nº de servicios (routes), km de red (largo de trazados
  únicos), paradas, veh-km/día y expediciones por tipo de día.
- **Mapa**: trazados con el `route_color` de cada servicio y paradas. Al pinchar
  una parada aparece un tótem con los servicios (`route_short_name`) y su destino
  (`trip_headsign`), cada uno con su color.
- **Perfil de frecuencia**: salidas de la red por hora, con toggle
  Laboral / Sábado / Domingo. Laboral es el promedio de lunes a viernes.

## Estructura

```
.
├── index.html · app.js · style.css     # la web (Leaflet + Chart.js por CDN)
├── scripts/process_gtfs.py             # descarga + procesa → data/
├── scripts/requirements.txt
├── .github/workflows/update-gtfs.yml   # cron diario + publicación en Pages
└── data/                               # generado por el script (JSON + GeoJSON)
    ├── index.json                      # índice de zonas + resumen
    └── <slug>/ summary.json · routes.geojson · stops.geojson · frequency.json
```

## Puesta en marcha

1. Crea un repo en GitHub y sube estos archivos.
2. En **Settings → Pages → Build and deployment**, elige **Source: GitHub Actions**.
3. Ve a la pestaña **Actions**, corre el workflow *"Actualizar GTFS y publicar"*
   con **Run workflow** (o espera al cron).
4. Al terminar, el sitio queda en `https://<usuario>.github.io/<repo>/`.

El cron está en `0 10 * * *` (UTC ≈ 06–07 h en Chile). Cámbialo en el `.yml`.

## Probar en local

```bash
pip install -r scripts/requirements.txt

# procesar solo una zona con un zip local (sin descargar)
python scripts/process_gtfs.py --local ruta/al/cl-tocopilla.zip --slug tocopilla --name "Tocopilla"

# o una sola zona desde la web
python scripts/process_gtfs.py --only tocopilla

# o todas
python scripts/process_gtfs.py

# servir la web
python -m http.server 8000   # abre http://localhost:8000
```

## Notas técnicas

- Los `stop_id` vienen con espacios en algunos feeds; el script hace `strip()`
  antes de cruzar `stop_times` con `stops`.
- **Km de red** = suma haversine de los shapes únicos. **Veh-km/día** = suma del
  largo del shape de cada expedición activa ese tipo de día (laboral = promedio
  L–V). El tipo de día sale de `calendar.txt`; `calendar_dates.txt` (feriados)
  no altera el perfil típico.
- Los shapes se simplifican (Douglas-Peucker ~4 m) y las coordenadas se redondean
  a 5 decimales para bajar el peso de los GeoJSON.
- Añadir/quitar zonas: edita la lista `ZONES` en `scripts/process_gtfs.py`.
- Si una zona falla la descarga, queda registrada con error en `index.json` y el
  resto se publica igual.
