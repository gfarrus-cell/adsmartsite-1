#!/usr/bin/env python3
"""
Paso 1 del enrichment Clay para AI Hunter.

Exporta los contactos de uno o más workspaces (tenants) de Supabase a CSV,
preservando EXACTAMENTE las columnas y el orden que devuelve PostgREST
(= orden físico de la tabla). No transforma valores. Solo lectura.

Uso:
  SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \
  python3 scripts/clay_enrich/export_tenant.py --tenants rda,noa-ai --out data/

  --list-tenants        solo lista slug/name/vertical/is_active y sale
  --limit N             corta a N filas por tenant (piloto)

Salida por tenant:
  <out>/<slug>_contacts_<YYYYMMDD>.csv          (backup crudo, intocable)
  <out>/<slug>_contacts_<YYYYMMDD>.schema.json  (columnas + tipos inferidos)
y muestra las 3 primeras filas por stdout.
"""
import argparse
import csv
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date


def env(name):
    v = os.environ.get(name)
    if not v:
        sys.exit(f"falta variable de entorno {name}")
    return v


def rest(url, key, path, params=None):
    q = ("?" + urllib.parse.urlencode(params, safe="*,.()")) if params else ""
    req = urllib.request.Request(
        url.rstrip("/") + "/rest/v1/" + path + q,
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def paged(url, key, path, params, page=1000):
    out, off = [], 0
    while True:
        rows = rest(url, key, path, {**params, "limit": page, "offset": off})
        out.extend(rows)
        if len(rows) < page:
            return out
        off += page


def cell(v):
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenants", default="", help="slugs separados por coma")
    ap.add_argument("--out", default="data")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--list-tenants", action="store_true")
    a = ap.parse_args()

    url, key = env("SUPABASE_URL"), env("SUPABASE_SERVICE_ROLE_KEY")
    tenants = rest(url, key, "tenants", {"select": "id,slug,name,vertical_type,is_active", "order": "slug"})
    if a.list_tenants or not a.tenants:
        for t in tenants:
            print(f"{t['slug']:<20} {str(t.get('name')):<40} {str(t.get('vertical_type')):<28} active={t.get('is_active')}")
        return
    by_slug = {t["slug"]: t for t in tenants}
    os.makedirs(a.out, exist_ok=True)
    today = date.today().strftime("%Y%m%d")

    for slug in [s.strip() for s in a.tenants.split(",") if s.strip()]:
        t = by_slug.get(slug)
        if not t:
            print(f"[{slug}] tenant no existe", file=sys.stderr)
            continue
        params = {"select": "*", "workspace_id": f"eq.{t['id']}", "order": "created_at.asc"}
        rows = paged(url, key, "contacts", params)
        if a.limit:
            rows = rows[: a.limit]
        if not rows:
            print(f"[{slug}] 0 contactos")
            continue
        cols = list(rows[0].keys())  # orden PostgREST = orden de tabla
        for r in rows[1:]:
            for k in r:
                if k not in cols:
                    cols.append(k)
        base = os.path.join(a.out, f"{slug}_contacts_{today}")
        with open(base + ".csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols, lineterminator="\r\n")
            w.writeheader()
            for r in rows:
                w.writerow({c: cell(r.get(c)) for c in cols})
        types = {c: sorted({type(r.get(c)).__name__ for r in rows if r.get(c) is not None}) for c in cols}
        with open(base + ".schema.json", "w", encoding="utf-8") as f:
            json.dump(
                {"tenant": t, "rows": len(rows), "columns": cols, "types": types,
                 "encoding": "utf-8-sig", "delimiter": ",", "newline": "CRLF"},
                f, ensure_ascii=False, indent=2,
            )
        print(f"\n[{slug}] {len(rows)} filas -> {base}.csv")
        print("columnas:", ", ".join(cols))
        print("primeras 3 filas:")
        for r in rows[:3]:
            print(json.dumps({c: r.get(c) for c in cols}, ensure_ascii=False))


if __name__ == "__main__":
    main()
