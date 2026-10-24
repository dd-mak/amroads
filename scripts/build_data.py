#!/usr/bin/env python3
"""Build Armenia road + railway data from OSM into data/*.geojson + data/meta.json."""
import json, math, os, re, sys, time, datetime, urllib.parse, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent if HERE.name == 'scripts' else HERE

OVP = ["https://overpass-api.de/api/interpreter",
       "https://overpass.kumi.systems/api/interpreter",
       "https://overpass.private.coffee/api/interpreter"]

GROUPS = {
    "roads_t1": (1, ["motorway", "trunk", "primary"]),
    "roads_t2": (2, ["secondary", "tertiary"]),
    "roads_unclassified": (3, ["unclassified"]),
    "roads_residential":  (3, ["residential"]),
    "roads_track":        (3, ["track"]),
    "roads_service":      (3, ["service"]),
    "roads_path":         (3, ["path"]),
}
EXTRA = {"path": ["path", "footway", "cycleway", "pedestrian", "steps", "bridleway"],
         "residential": ["residential", "living_street"],
         "unclassified": ["unclassified", "road"]}
HW = {"living_street": "residential", "road": "unclassified", "footway": "path",
      "cycleway": "path", "pedestrian": "path", "steps": "path", "bridleway": "path"}
PAVED = set("asphalt paved concrete paving_stones sett concrete:plates concrete:lanes "
            "bricks cobblestone chipseal metal".split())

# Full railway taxonomy: active + historical / preserved
RAIL = ["rail", "narrow_gauge", "light_rail", "subway", "tram", "monorail",
        "funicular", "preserved",
        "disused", "abandoned", "razed", "construction"]


def load_config(path=None):
    path = path or next(p for p in (HERE / "config.json", ROOT / "config.json") if p.exists())
    cfg = json.load(open(path, encoding="utf-8"))
    need = {"id", "name", "relation_id", "bounds", "languages",
            "default_lang", "admin", "accent"}
    if need - cfg.keys():
        sys.exit(f"config.json missing: {sorted(need - cfg.keys())}")
    cfg["area"] = f"area(id:{3600000000 + int(cfg['relation_id'])})->.a;"
    return cfg


def km(coords):
    d = 0
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
        p = math.pi / 180
        h = (math.sin((y2 - y1) * p / 2) ** 2 +
             math.cos(y1 * p) * math.cos(y2 * p) * math.sin((x2 - x1) * p / 2) ** 2)
        d += 12742 * math.asin(math.sqrt(h))
    return round(d, 3)


def num(v):
    try:
        return int(re.match(r"\d+", str(v).strip()).group())
    except Exception:
        return None


def road_feature(e, known):
    t = e.get("tags", {})
    c = HW.get(t.get("highway", "").replace("_link", ""),
               t.get("highway", "").replace("_link", ""))
    if c not in known or "geometry" not in e:
        return None
    co = [[round(g["lon"], 5), round(g["lat"], 5)] for g in e["geometry"]]
    if len(co) < 2:
        return None
    su = t.get("surface", "")
    tt = t.get("tracktype", "")
    tg = "na"
    if c == "track":
        tg = "g" + tt[5] if tt in ("grade1", "grade2", "grade3", "grade4", "grade5") else "none"
    ref = t.get("ref", "")
    # Armenian M / H / T classification (Interstate / National / Local)
    am_class = ""
    if ref and len(ref) >= 2 and ref[0] in "MHT" and ref[1].isdigit():
        am_class = ref[0]
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": co},
        "properties": {
            "id": e["id"], "cls": c, "hw": t.get("highway", ""), "tg": tg,
            "name": t.get("name", ""), "ref": ref, "am_class": am_class,
            "surface": su,
            "sc": "unknown" if not su else "paved" if su in PAVED else "unpaved",
            "speed": num(t.get("maxspeed")),
            "lit": "unk" if "lit" not in t else "no" if t["lit"] == "no" else "yes",
            "km": km(co),
            "lanes": num(t.get("lanes")),
            "width": t.get("width", ""),
            "smoothness": t.get("smoothness", ""),
            "bridge": "yes" if t.get("bridge") and t["bridge"] != "no" else "",
            "tunnel": "yes" if t.get("tunnel") and t["tunnel"] != "no" else "",
            "oneway": t.get("oneway", ""),
            "incline": t.get("incline", ""),
        },
    }


def rail_feature(e):
    t = e.get("tags", {})
    rt = t.get("railway", "")
    if rt not in RAIL or "geometry" not in e:
        return None
    co = [[round(g["lon"], 5), round(g["lat"], 5)] for g in e["geometry"]]
    if len(co) < 2:
        return None
    # Normalise gauge -> semantic key
    gauge = t.get("gauge", "")
    gauge_norm = ""
    if gauge:
        g = "".join(ch for ch in gauge.split(";")[0] if ch.isdigit())
        if g:
            gv = int(g)
            if gv in (1520, 1524):
                gauge_norm = "russian"
            elif gv == 1435:
                gauge_norm = "standard"
            elif gv == 1000:
                gauge_norm = "metre"
            elif gv == 750:
                gauge_norm = "narrow750"
            else:
                gauge_norm = str(gv)
    # Normalise electrification
    el = t.get("electrified", "")
    el_norm = "no" if el in ("", "no") else "contact_line" if el in ("contact_line", "yes") else el
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": co},
        "properties": {
            "id": e["id"], "rt": rt,
            "name": t.get("name", ""), "name_en": t.get("name:en", ""),
            "ref": t.get("ref", ""),
            "usage": t.get("usage", ""),          # main / branch / industrial / tourism
            "service": t.get("service", ""),      # yard / siding / spur / crossover
            "gauge": gauge, "gauge_norm": gauge_norm,
            "el": el_norm, "voltage": t.get("voltage", ""), "freq": t.get("frequency", ""),
            "tracks": num(t.get("tracks")),
            "speed": num(t.get("maxspeed")),
            "operator": t.get("operator", ""),
            "bridge": "yes" if t.get("bridge") and t["bridge"] != "no" else "",
            "tunnel": "yes" if t.get("tunnel") and t["tunnel"] != "no" else "",
            "km": km(co),
        },
    }


def overpass(query, tries=8):
    last = None
    for i in range(tries):
        url = OVP[i % len(OVP)]
        try:
            req = urllib.request.Request(
                url,
                data=urllib.parse.urlencode({"data": query}).encode(),
                headers={"User-Agent": "am-roads/1.0 (31 Day OSM Challenge)"})
            j = json.load(urllib.request.urlopen(req, timeout=900))
            if "remark" in j and "error" in j["remark"].lower():
                raise RuntimeError(j["remark"])
            return j["elements"]
        except Exception as ex:
            last = ex
            wait = min(120, 15 * (i + 1))
            print(f"  attempt {i+1}: {ex} — waiting {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise last


def query(area, classes, bbox=None):
    tags = "|".join(x for c in classes
                    for x in ([c, c + "_link"]
                              if c in ("motorway", "trunk", "primary", "secondary", "tertiary")
                              else EXTRA.get(c, [c])))
    geo = f"({','.join(map(str, bbox))})(area.a)" if bbox else "(area.a)"
    return f'[out:json][timeout:900];{area}way["highway"~"^({tags})$"]{geo};out geom tags;'


def rail_query(area, bbox=None):
    tags = "|".join(RAIL)
    geo = f"({','.join(map(str, bbox))})" if bbox else "(area.a)"
    return f'[out:json][timeout:600];{area}way["railway"~"^({tags})$"]{geo};out geom tags;'


def write_geojson(path, feats):
    with open(path, "w") as fh:
        fh.write('{"type":"FeatureCollection","features":[\n' +
                 ",\n".join(json.dumps(f, separators=(",", ":")) for f in feats) +
                 "\n]}")


def fetch_regions(cfg):
    q = (f'[out:json][timeout:120];{cfg["area"]}'
         f'relation["admin_level"="{cfg["admin"]["level"]}"]["boundary"="administrative"](area.a);'
         f'out tags bb;')
    out = []
    for r in overpass(q):
        bb = r.get("bounds")
        if not bb:
            continue
        out.append({
            "id": r["id"],
            "name": r.get("tags", {}).get("name", str(r["id"])),
            "name_en": r.get("tags", {}).get("name:en",
                       r.get("tags", {}).get("name", str(r["id"]))),
            "name_ru": r.get("tags", {}).get("name:ru",
                       r.get("tags", {}).get("name", str(r["id"]))),
            "bbox": [bb["minlat"], bb["minlon"], bb["maxlat"], bb["maxlon"]],
        })
    print(f"  {len(out)} admin regions")
    return out


def write_seo(cfg, updated):
    """sitemap.xml + robots.txt at repo root (set site_url in config.json)."""
    site = cfg.get("site_url", "").rstrip("/") + "/"
    if site == "/":
        return
    u = lambda l: site + ("" if l == cfg["default_lang"] else "?lang=" + l)
    alt = "".join(f'<xhtml:link rel="alternate" hreflang="{l}" href="{u(l)}"/>' for l in cfg["languages"])
    urls = "".join(f"<url><loc>{u(l)}</loc><lastmod>{updated}</lastmod><changefreq>monthly</changefreq>"
                   f"<priority>{1.0 if l == cfg['default_lang'] else 0.8}</priority>{alt}</url>"
                   for l in cfg["languages"])
    (ROOT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:xhtml="http://www.w3.org/1999/xhtml">' + urls + "</urlset>\n", encoding="utf-8")
    (ROOT / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {site}sitemap.xml\n")


def main(out_dir=None):
    cfg = load_config()
    out = Path(out_dir or ROOT / "data")
    out.mkdir(parents=True, exist_ok=True)
    try:
        old = json.load(open(out / "meta.json", encoding="utf-8"))
    except Exception:
        old = {}
    failed = []
    meta = {
        "country": cfg["id"], "name": cfg["name"], "name_local": cfg.get("name_local", cfg["name"]),
        "languages": cfg["languages"], "default_lang": cfg["default_lang"],
        "updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"),
        "files": {"1": [], "2": [], "3": [], "rail": []}, "regions": [], "counts": {},
    }

    def save(name, key, fn):
        path = out / (name + ".geojson")
        print(name)
        try:
            feats = fn()
            feats.sort(key=lambda f: f["properties"]["id"])
            write_geojson(path, feats)
            meta["counts"][name] = len(feats)
            print(f"  {len(feats)} segments, {path.stat().st_size / 1e6:.1f} MB")
        except Exception as ex:
            print(f"  FAILED ({ex})", file=sys.stderr)
            failed.append(name)
            if not path.exists():
                return
            meta["counts"][name] = old.get("counts", {}).get(name, 0)
        meta["files"][key].append(path.name)
        time.sleep(10)

    for name, (tier, classes) in GROUPS.items():
        if tier < 3:
            save(name, str(tier), lambda c=classes: [
                f for e in overpass(query(cfg["area"], c)) if (f := road_feature(e, set(c)))])
    save("railways", "rail", lambda: [f for e in overpass(rail_query(cfg["area"])) if (f := rail_feature(e))])

    # Tier 3: local roads per marz (bbox + area filter; overlap deduped by way id)
    regions = fetch_regions(cfg)
    if not regions:
        sys.exit("No admin regions found")
    t3 = [c for _, (t, cs) in GROUPS.items() if t == 3 for c in cs]
    els = {}
    for r in regions:
        try:
            got = overpass(query(cfg["area"], t3, r["bbox"]))
            els.update({e["id"]: e for e in got})
            print(f"  {r['name']}: {len(got)}")
        except Exception as ex:
            print(f"  {r['name']}: FAILED ({ex})", file=sys.stderr)
            failed.append(r["name"])
        time.sleep(5)

    feats = [f for f in (road_feature(e, set(t3)) for e in els.values()) if f]
    buckets = {r["id"]: [] for r in regions}
    for f in feats:
        x, y = f["geometry"]["coordinates"][0]
        for r in regions:
            s, w, n, e = r["bbox"]
            if w <= x <= e and s <= y <= n:
                buckets[r["id"]].append(f)
                break
    reg_dir = out / "regions"
    reg_dir.mkdir(exist_ok=True)
    listed = set()
    for r in regions:
        fs = sorted(buckets[r["id"]], key=lambda f: f["properties"]["id"])
        if not fs:
            continue
        rel = f"regions/{r['id']}.geojson"
        write_geojson(out / rel, fs)
        listed.add(rel)
        meta["regions"].append({"id": r["id"], "name": r["name"], "name_en": r["name_en"],
                                "name_ru": r["name_ru"], "file": rel, "count": len(fs), "bbox": r["bbox"]})
        meta["files"]["3"].append(rel)
    for p in reg_dir.glob("*.geojson"):          # drop stale region files
        if f"regions/{p.name}" not in listed:
            p.unlink()
    meta["counts"]["local_roads"] = len(feats)

    # Safety net: never publish a broken or shrunken dataset
    for k, v in meta["counts"].items():
        p = old.get("counts", {}).get(k)
        if p and v < 0.8 * p:
            failed.append(f"{k} shrank {p} -> {v}")
    if failed:
        sys.exit("Aborting, meta.json not updated: " + ", ".join(failed))
    json.dump(meta, open(out / "meta.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    write_seo(cfg, meta["updated"])


if __name__ == "__main__":
    main()
