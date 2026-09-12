# Enrichment multi-fuente → AI Hunter (energía: O&G / Vaca Muerta / minería San Juan)

Flujo en 3 pasos. Nada escribe en Supabase.

1. `export_tenant.py` — backup crudo por tenant (`<slug>_contacts_<fecha>.csv`) con columnas y orden exactos del API. Muestra 3 filas. Requiere `SUPABASE_URL` y `SUPABASE_SERVICE_ROLE_KEY` en el entorno.
2. Consulta de fuentes por registro según tipo (operadora / proveedor minero / proveedor O&G / contacto). Cada fuente aporta un dict `{columna_original: valor}` y se acumula en `<slug>_results.jsonl` (ver docstring de `consolidate.py`). Solo datos confirmados; lo no confirmado no se escribe.
3. `consolidate.py` — genera `<original>_enriched_<fecha>.csv` con mismas columnas + `fuentes_confirmaron` (JSON por campo: ok / conflicto / missing) y `fecha_enrichment`. Conflicto entre fuentes → campo = `conflicto`, ambos valores y fuentes en `fuentes_confirmaron`. Imprime tabla: 2+ fuentes / 1 fuente / conflicto / sin match / no procesado.

No se commitean datos ni credenciales (`data/`, `*.jsonl`, `.env*` ignorados).
