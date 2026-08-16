# ARISTO runners

Dashboard estático del reto (26/07/2026–30/08/2026): Strava → GitHub Actions → `data.json` → GitHub Pages. El navegador nunca llama a Strava y el artefacto Pages contiene únicamente `index.html`, `data.json` y `.nojekyll`.

## Dashboard V2

La V2 mantiene una única SPA estática:

- `/`: KPIs del club, evolución conjunta, ranking e hitos dinámicos;
- `/?runner=nombre-apellidos`: progreso, proyección, contribución, eficiencia observable e hitos individuales.

`data.json` usa `schema_version=2`. Los totales combinan checkpoints e incrementos; km/salida, ritmo, desnivel/km, distribución y salidas máximas se calculan exclusivamente con actividades posteriores al checkpoint de seguimiento. La interfaz distingue `last_feed_check`, `last_complete_observation` y `latest_activity_detected_at` para no presentar como actual un total todavía no alineado.

La rama `v1-stable` conserva la versión anterior completa como rollback.

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

Si pide baseline actual, edita `bootstrap/current_baseline.json`: fija `complete=true`, fecha de captura y los 12 totales actuales. Ejecuta de nuevo inmediatamente. La gráfica interpola el intervalo y lo marca como aproximado.

Si aparecen `unmatched_activities`, consulta `unmatched_athletes` y ajusta los aliases en `config/participants.json`; nunca se asigna una actividad ambigua. Si el feed real solo expone IDs, rellena `athlete_id` tras identificar cada corredor una sola vez.

### 4. Activar Pages

En **Settings → Pages → Build and deployment → Source**, selecciona **GitHub Actions**. El repositorio privado requiere GitHub Pro/Team/Enterprise; alternativa: hacerlo público. No se cambia la visibilidad automáticamente. El sitio Pages será público aunque el repo sea privado. Véase [GitHub Pages: custom workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

## Operación

El workflow corre cada hora (`:17`), admite ejecución manual y despliega en cada push relevante a `main`. A partir del **01/09/2026** el guard temporal sale antes de leer credenciales o llamar a Strava.

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m scripts.build_data
```

Configuración:

- fechas, objetivo, deportes o `club_id` manual: `config/challenge.json`;
- participantes, aliases o IDs: `config/participants.json`;
- checkpoint histórico inmutable: `config/baseline.json`;
- segundo checkpoint condicional: `bootstrap/current_baseline.json`.

Auditoría: consulta el último run en **Actions**, `generated_at`/`data_through` en `data.json` y `last_successful_update`/`field_probe` en el ledger. Salidas y desnivel se etiquetan como parciales porque el fixture histórico solo contiene kilómetros.

## Recuperación segura

- API vacía válida: conserva los totales; no inventa actividades.
- Error temporal/JSON inválido: `data.json` válido no se sobrescribe. El token rotado sí se cifra antes de continuar para no perderlo.
- Ejecución repetida: hashes/IDs ya registrados no vuelven a sumar.
- Cambio de `STRAVA_CLIENT_SECRET`: elimina `state/refresh_token.enc`, actualiza los secrets y vuelve a ejecutar para usar el refresh token bootstrap compatible.

Referencia del endpoint: [Strava List Club Activities](https://developers.strava.com/docs/reference/#api-Clubs-getClubActivitiesById).
