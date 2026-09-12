#!/usr/bin/env python3
"""
Consolidación multi-fuente sobre el CSV original (AI Hunter).

Reglas:
- Mismas columnas y orden que el original. Solo se agregan al final las
  columnas extra permitidas (default: fuentes_confirmaron, fecha_enrichment).
- Nunca sobrescribe el original: escribe <original>_enriched_<YYYYMMDD>.csv.
- Un campo se completa SOLO si al menos una fuente lo devolvió confirmado.
- Si 2+ fuentes devuelven valores distintos (normalizados) para el mismo campo,
  el campo queda con el literal "conflicto" y el detalle (valor + fuente de
  cada uno) va en fuentes_confirmaron. No se promedia ni se elige.
- Si ninguna fuente confirma un campo objetivo, queda como estaba y se lista
  como missing en fuentes_confirmaron.

fuentes_confirmaron es JSON por campo:
  {"email":   {"ok": ["clay","apollo"], "valor": "a@b.com"},
   "cuit":    {"missing": true},                 # vacío en original y sin fuente
   "company": {"sin_confirmar": true},           # el original ya tenía valor; ninguna fuente lo confirmó (se conserva)
   "job_title": {"conflicto": [{"fuente":"clay","valor":"X"},{"fuente":"linkedin","valor":"Y"}]}}

Input de resultados: JSON lines, una por fila original:
  {"row_key": "<id>",
   "tipo": "operadora|proveedor_minero|proveedor_og|contacto",
   "fuentes": {"clay": {"email": "...", "job_title": "..."},
               "afip": {"cuit": "...", "razon_social": "..."},
               "apollo": {...}},
   "fecha_enrichment": "2026-09-12"}
Las claves dentro de cada fuente deben ser nombres de columnas del original.

Uso:
  python3 scripts/clay_enrich/consolidate.py --original data/rda_contacts_20260912.csv \
      --results data/rda_results.jsonl --key id \
      [--extra fuentes_confirmaron,fecha_enrichment] [--targets email,job_title,linkedin_url]
"""
import argparse
import csv
import json
import os
import re
import sys
import unicodedata
from datetime import date

ap = argparse.ArgumentParser()
ap.add_argument("--original", required=True)
ap.add_argument("--results", required=True)
ap.add_argument("--key", default="id")
ap.add_argument("--extra", default="fuentes_confirmaron,fecha_enrichment")
ap.add_argument("--targets", default="",
                help="columnas objetivo a evaluar (vacío = unión de campos que trajeron las fuentes)")
a = ap.parse_args()

EXTRA = [c for c in a.extra.split(",") if c]
COL_FUENTES = EXTRA[0] if EXTRA else "fuentes_confirmaron"
COL_FECHA = EXTRA[1] if len(EXTRA) > 1 else "fecha_enrichment"


def norm(v):
    """Normalización solo para COMPARAR (nunca para escribir)."""
    s = str(v).strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"^https?://(www\.)?", "", s).rstrip("/")
    s = re.sub(r"[^a-z0-9@._-]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def vacio(v):
    return v is None or v == "" or v == [] or v == {}


def cell(v):
    return v if not isinstance(v, (dict, list)) else json.dumps(v, ensure_ascii=False)


with open(a.original, encoding="utf-8-sig", newline="") as f:
    rd = csv.DictReader(f)
    cols = rd.fieldnames
    rows = list(rd)
for c in EXTRA:
    if c in cols:
        sys.exit(f"columna extra '{c}' ya existe en el original; abortando para no romper el esquema")

res = {}
with open(a.results, encoding="utf-8") as f:
    for line in f:
        if line.strip():
            o = json.loads(line)
            res[str(o["row_key"])] = o

stats = {"2+_fuentes": 0, "1_fuente": 0, "conflicto": 0, "sin_match": 0, "no_procesado": 0}
out = []
for r in rows:
    row = dict(r)
    o = res.get(str(r.get(a.key)))
    if not o:
        row[COL_FUENTES] = ""
        row[COL_FECHA] = ""
        stats["no_procesado"] += 1
        out.append(row)
        continue
    fuentes = o.get("fuentes") or {}
    targets = [c for c in a.targets.split(",") if c] or sorted({k for d in fuentes.values() for k in (d or {})})
    detalle = {}
    nivel = "sin_match"
    for c in targets:
        if c not in cols:
            sys.exit(f"results trae campo '{c}' que no existe en el original; no se agregan columnas")
        aportes = [(src, d[c]) for src, d in fuentes.items() if d and not vacio(d.get(c))]
        if not aportes:
            detalle[c] = {"missing": True} if vacio(r.get(c)) or not str(r.get(c)).strip() else {"sin_confirmar": True}
            continue
        distintos = {}
        for src, v in aportes:
            distintos.setdefault(norm(v), []).append((src, v))
        if len(distintos) > 1:
            row[c] = "conflicto"
            detalle[c] = {"conflicto": [{"fuente": s, "valor": cell(v)} for s, v in aportes]}
            nivel = "conflicto"
        else:
            srcs = [s for s, _ in aportes]
            row[c] = cell(aportes[0][1])
            detalle[c] = {"ok": srcs, "valor": cell(aportes[0][1])}
            if nivel != "conflicto":
                nivel = "2+_fuentes" if (len(srcs) >= 2 or nivel == "2+_fuentes") else ("1_fuente" if nivel == "sin_match" else nivel)
    stats[nivel] += 1
    row[COL_FUENTES] = json.dumps(detalle, ensure_ascii=False)
    row[COL_FECHA] = o.get("fecha_enrichment") or date.today().isoformat()
    out.append(row)

base, ext = os.path.splitext(a.original)
dest = f"{base}_enriched_{date.today().strftime('%Y%m%d')}{ext}"
if os.path.exists(dest):
    sys.exit(f"{dest} ya existe; no sobrescribo")
with open(dest, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=cols + EXTRA, lineterminator="\r\n")
    w.writeheader()
    w.writerows(out)
print(f"escrito {dest}")
print("| nivel | N |\n|---|---|")
for k in ("2+_fuentes", "1_fuente", "conflicto", "sin_match", "no_procesado"):
    print(f"| {k} | {stats[k]} |")
