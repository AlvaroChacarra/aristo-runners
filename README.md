# ARISTO runners

Dashboard estático del reto (26/07/2026–30/08/2026): Strava → GitHub Actions → `data.json` → GitHub Pages. El navegador nunca llama a Strava y el artefacto Pages contiene únicamente `index.html`, `data.json` y `.nojekyll`.

## Dashboard V3 — Performance League

La V3 mantiene la SPA estática y transforma únicamente su capa de presentación:

- `/`: portada deportiva, podium dinámico, clasificación desde el cuarto puesto, bottom-3 dinámico, evolución del club, performance y estado del dato;
- `/?runner=nombre-apellidos`: hero editorial, resumen de rendimiento, progreso, training log observable, hitos y calidad del dato;
- Alvaro López-Chacarra se identifica como creator únicamente mediante `slug=alvaro-lopez-chacarra`; el distintivo no altera ranking, kilómetros ni estado deportivo.

El podium consume dinámicamente los ranks 1–3. La clasificación no los repite y calcula la zona roja como los tres últimos participantes, insertando el corte antes del primero de ellos. La interfaz es mobile-first, con validación explícita entre 320 y 1440 px.

`data.json` conserva `schema_version=2` y el pipeline Strava → Python → GitHub Actions → GitHub Pages no cambia. Los totales combinan checkpoints, incrementos y reconciliaciones auditables del leaderboard cuando una actividad no aparece en el feed de clubes; km/salida, ritmo, desnivel/km, distribución y salidas máximas se calculan exclusivamente con actividades posteriores al checkpoint de seguimiento. La interfaz distingue `last_feed_check`, `last_complete_observation` y `latest_activity_detected_at` para no presentar como actual un total todavía no alineado.

Rollback: revertir el commit de V3 restaura la V2 sin migraciones de datos ni cambios operativos. La rama `v1-stable` conserva además la versión anterior completa.

## Puesta en marcha

### 1. Crear y autorizar la app Strava

1. Abre <https://www.strava.com/settings/api> y crea la app. Tu cuenta debe pertenecer a **ARISTO runners**. Usa `localhost` como **Authorization Callback Domain**.
2. Sustituye `CLIENT_ID` y abre esta URL:

```text
https://www.strava.com/oauth/authorize?client_id=CLIENT_ID&response_type=code&redirect_uri=http://localhost/exchange_token&approval_prompt=force&scope=read
```

3. Autoriza. Aunque `localhost` no cargue, copia de la URL redirigida el valor de `code`.
4. Intercambia el código una sola vez:

```bash
curl -sS -X POST https://www.strava.com/oauth/token \
  -d client_id=CLIENT_ID \
  -d client_secret=CLIENT_SECRET \
  -d code=AUTHORIZATION_CODE \
  -d grant_type=authorization_code
```

Guarda el `refresh_token`; no compartas ni subas la respuesta. El scope mínimo es `read`, que incluye feeds de clubes según [Strava Authentication](https://developers.strava.com/docs/authentication/).

### 2. Crear los tres Secrets

En **Settings → Secrets and variables → Actions → New repository secret**:

```text
STRAVA_CLIENT_ID
STRAVA_CLIENT_SECRET
STRAVA_REFRESH_TOKEN
```

El secret `STRAVA_REFRESH_TOKEN` solo hace bootstrap. Cada ejecución cifra y versiona el token rotado en `state/refresh_token.enc`; el access token solo vive en memoria.

### 3. Ejecutar el spike real

En **Actions → Update Strava and deploy Pages → Run workflow**. Revisa en `state/activity_ledger.json`:

- `field_probe`: presencia real de `id`, fechas y `athlete.id` sin guardar el JSON crudo;
- `strategy=historical_exact`: ID y fecha fiables; se suman solo actividades posteriores al checkpoint del 10/08;
- `strategy=incremental_fingerprint`: falta ID o fecha. La primera ejecución observa hashes sin sumarlos y activa `needs_current_baseline`.

El segundo checkpoint está fijado al **16/08/2026** mediante el HTML **ARISTO runners — Día 22**, establecido como golden source por el organizador. `bootstrap/current_baseline.json` conserva kilómetros, salidas, desnivel y ajuste del solape del 10/08 de forma auditable. La gráfica interpola el intervalo 11–16/08 y lo marca como aproximado.

Si aparecen `unmatched_activities`, consulta `unmatched_athletes` y ajusta los aliases en `config/participants.json`; nunca se asigna una actividad ambigua. Si el feed real solo expone IDs, rellena `athlete_id` tras identificar cada corredor una sola vez.

El feed del club también puede depender de la relación de seguimiento/privacidad entre el atleta autenticado y cada corredor. Si una relación nueva hace visible de golpe el histórico de una persona, **no se suma el bloque completo**: ClubActivity no incluye fechas. Se reconcilian sus hashes en `state/visibility_reconciliations.json`, se ignora lo ya cubierto por checkpoints y solo se conservan como actividades los incrementos contrastados. Ejecuta `python -m scripts.reconcile_visibility` después de revisar el manifiesto; el proceso es idempotente.

Borja y Kept ya están reconciliados contra el checkpoint del 16/08: sus incrementos posteriores proceden de actividades reales del feed y no de ajustes agregados del leaderboard.

### 4. Activar Pages

En **Settings → Pages → Build and deployment → Source**, selecciona **GitHub Actions**. El repositorio privado requiere GitHub Pro/Team/Enterprise; alternativa: hacerlo público. No se cambia la visibilidad automáticamente. El sitio Pages será público aunque el repo sea privado. Véase [GitHub Pages: custom workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

## Operación

El workflow admite ejecución manual y despliega en cada push relevante a `main`. El **31/08** ejecuta una finalización automática cada diez minutos para compensar retrasos del cron y recoger actividades del último día que Strava haga visibles con demora. Para una sincronización operativa inmediata también admite un commit deliberado cuyo mensaje contenga `[strava-sync]`; los demás pushes solo reconstruyen datos y no llaman a Strava. A partir del **01/09/2026** el guard temporal sale antes de leer credenciales o llamar a Strava.

El feed del club no entrega fecha ni ID de actividad. Por ello, `late_observation_end=2026-08-31` define una gracia de cierre estrictamente acotada: un fingerprint nuevo detectado ese día se imputa al **30/08**, conserva `detected_at` real y se marca `date_accuracy=late_observed`. La web declara estas observaciones tardías. Después de la gracia no se incorporan nuevos fingerprints.

Los tests de reconciliación usan el snapshot inmutable del 25/08 y permiten actividades posteriores. Cada ejecución valida además el estado vivo de los 12 corredores: identidades y aliases inequívocos, cero actividades visibles sin asignar, fingerprints únicos, coherencia entre ledger y dashboard y presencia de todos los participantes. Un corredor sin registros posteriores al checkpoint se informa como `NO_POST_CHECKPOINT_RECORD`; no se interpreta automáticamente como una actividad ausente porque el endpoint puede depender de visibilidad y privacidad.

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m scripts.build_data
python -m scripts.validate_live_state
```

Configuración:

- fechas, objetivo, deportes o `club_id` manual: `config/challenge.json`;
- participantes, aliases o IDs: `config/participants.json`;
- checkpoint histórico inmutable: `config/baseline.json`;
- segundo checkpoint condicional: `bootstrap/current_baseline.json`.
- ajustes agregados contrastados con la clasificación de Strava: `state/leaderboard_adjustments.json` (no inventar ritmo, desnivel ni detalle de actividad).
- reconciliaciones por cambios de visibilidad del feed: `state/visibility_reconciliations.json` (hashes únicamente; nunca contiene tokens ni JSON crudo de Strava).

Auditoría: consulta el último run en **Actions**, `generated_at`/`data_through` en `data.json`, `last_successful_update`/`field_probe` en el ledger y `records_added`/`records_total` en el log. Salidas y desnivel se etiquetan como parciales porque el fixture histórico solo contiene kilómetros.

La publicación es transaccional respecto al dato: solo se versionan y despliegan `data.json` y el ledger cuando la validación de los 12 corredores pasa. Si Strava o esa validación fallan, se conserva el último dashboard público válido y únicamente puede persistirse el refresh token rotado.

## Recuperación segura

- API vacía válida: conserva los totales; no inventa actividades.
- Error temporal/JSON inválido: `data.json` válido no se sobrescribe. El token rotado sí se cifra antes de continuar para no perderlo.
- Ejecución repetida: hashes/IDs ya registrados no vuelven a sumar.
- Cambio de `STRAVA_CLIENT_SECRET`: elimina `state/refresh_token.enc`, actualiza los secrets y vuelve a ejecutar para usar el refresh token bootstrap compatible.

Referencia del endpoint: [Strava List Club Activities](https://developers.strava.com/docs/reference/#api-Clubs-getClubActivitiesById).
