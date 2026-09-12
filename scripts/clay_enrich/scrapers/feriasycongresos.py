#!/usr/bin/env python3
"""
Scraper del calendario de feriasycongresos.com (Argentina).

Salida: data/ferias/feriasycongresos_eventos_<YYYYMMDD>.csv con columnas
  nombre, fecha_inicio, fecha_fin, ciudad, sede, sector, organizador, url, fuente_html
Solo datos publicados textualmente. Campo ausente = vacío.

Estrategia (en orden):
  1. JSON-LD schema.org/Event embebido en la página (lo más confiable).
  2. Fallback heurístico: bloques con link a /evento/ o /eventos/ + fecha.
  3. Siempre guarda el HTML renderizado en data/ferias/raw/ para inspección.

Uso:
  python3 scripts/clay_enrich/scrapers/feriasycongresos.py [--url URL] [--max-pages N] [--headless 1]
Requiere: playwright (Chromium ya instalado en el entorno Claude Code; local: `pip install playwright && playwright install chromium`).
"""
import argparse
import csv
import json
import os
import re
import sys
from datetime import date
from urllib.parse import urljoin

BASE = "https://www.feriasycongresos.com/calendario-de-eventos"
COLS = ["nombre", "fecha_inicio", "fecha_fin", "ciudad", "sede", "sector", "organizador", "url", "fuente_html"]
MESES = "enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre"
RE_FECHA = re.compile(rf"(\d{{1,2}})(?:\s*(?:al|-|–|y)\s*(\d{{1,2}}))?\s+de\s+({MESES})(?:\s+de)?\s+(\d{{4}})", re.I)


def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def from_jsonld(html, page_url):
    out = []
    for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        stack = list(items)
        while stack:
            it = stack.pop()
            if not isinstance(it, dict):
                continue
            if "@graph" in it:
                stack.extend(it["@graph"])
            t = it.get("@type")
            if t == "Event" or (isinstance(t, list) and "Event" in t):
                loc = it.get("location") or {}
                if isinstance(loc, list):
                    loc = loc[0] if loc else {}
                addr = loc.get("address") or {}
                org = it.get("organizer") or {}
                if isinstance(org, list):
                    org = org[0] if org else {}
                out.append({
                    "nombre": norm(it.get("name")),
                    "fecha_inicio": norm(it.get("startDate")),
                    "fecha_fin": norm(it.get("endDate")),
                    "ciudad": norm(addr.get("addressLocality") if isinstance(addr, dict) else addr),
                    "sede": norm(loc.get("name")),
                    "sector": norm(", ".join(it.get("keywords", [])) if isinstance(it.get("keywords"), list) else it.get("keywords")),
                    "organizador": norm(org.get("name") if isinstance(org, dict) else org),
                    "url": urljoin(page_url, it.get("url") or ""),
                    "fuente_html": page_url,
                })
    return out


def from_heuristic(html, page_url):
    """Fallback: cada <a href=*evento*> con texto + fecha cercana en el mismo bloque."""
    out = []
    text = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S | re.I)
    for m in re.finditer(r'<a[^>]+href=["\']([^"\']*(?:evento|ferias?|congreso)[^"\']*)["\'][^>]*>(.*?)</a>', text, re.S | re.I):
        href, inner = m.group(1), norm(re.sub(r"<[^>]+>", " ", m.group(2)))
        if len(inner) < 4:
            continue
        ctx = norm(re.sub(r"<[^>]+>", " ", text[m.end(): m.end() + 600]))
        f = RE_FECHA.search(inner + " " + ctx)
        fi = ff = ""
        if f:
            d1, d2, mes, anio = f.groups()
            fi = f"{d1} {mes} {anio}"
            ff = f"{d2} {mes} {anio}" if d2 else ""
        out.append({"nombre": inner, "fecha_inicio": fi, "fecha_fin": ff, "ciudad": "", "sede": "", "sector": "",
                    "organizador": "", "url": urljoin(page_url, href), "fuente_html": page_url})
    # dedup por url
    seen, ded = set(), []
    for r in out:
        if r["url"] in seen:
            continue
        seen.add(r["url"])
        ded.append(r)
    return ded


def render(url, headless=True):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=headless)
        pg = b.new_page(user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36")
        pg.goto(url, wait_until="networkidle", timeout=60000)
        pg.wait_for_timeout(1500)
        html = pg.content()
        # paginación "siguiente" si existe
        nxt = pg.query_selector("a[rel=next], a.next, li.next a, a:has-text('Siguiente'), a:has-text('siguiente')")
        nxt_url = urljoin(url, nxt.get_attribute("href")) if nxt and nxt.get_attribute("href") else None
        b.close()
        return html, nxt_url


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=BASE)
    ap.add_argument("--max-pages", type=int, default=10)
    ap.add_argument("--headless", type=int, default=1)
    ap.add_argument("--out", default="data/ferias")
    a = ap.parse_args()
    os.makedirs(os.path.join(a.out, "raw"), exist_ok=True)
    today = date.today().strftime("%Y%m%d")

    rows, url, n = [], a.url, 0
    while url and n < a.max_pages:
        n += 1
        html, nxt = render(url, bool(a.headless))
        with open(os.path.join(a.out, "raw", f"feriasycongresos_p{n}_{today}.html"), "w", encoding="utf-8") as f:
            f.write(html)
        got = from_jsonld(html, url)
        modo = "jsonld"
        if not got:
            got = from_heuristic(html, url)
            modo = "heuristico"
        print(f"[p{n}] {url} -> {len(got)} eventos ({modo})", file=sys.stderr)
        rows.extend(got)
        url = nxt if nxt and nxt != url else None

    dest = os.path.join(a.out, f"feriasycongresos_eventos_{today}.csv")
    with open(dest, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLS, lineterminator="\r\n")
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} eventos -> {dest}")
    for r in rows[:3]:
        print(json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    main()
