#!/usr/bin/env python3
"""Build Armenia road + railway data from OSM into data/*.geojson + data/meta.json."""
import json, math, os, sys, time, datetime, urllib.parse, urllib.request

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


def load_config(path="config.json"):
    cfg = json.load(open(path))
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
        return int(str(v).split()[0])
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
        tg = "g" + tt[5:] if tt[:5] == "grade" and tt[5:] in "12345" else "none"
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
        g = "".join(ch for ch in gauge if ch.isdigit())
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
    geo = f"({','.join(map(str, bbox))})" if bbox else "(area.a)"
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


def main(out_dir="data"):
    cfg = load_config()
    os.makedirs(out_dir, exist_ok=True)
    meta = {
        "country": cfg["id"], "name": cfg["name"],
        "name_local": cfg.get("name_local", cfg["name"]),
        "languages": cfg["languages"], "default_lang": cfg["default_lang"],
        "updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"),
        "files": {"1": [], "2": [], "3": [], "rail": []},
        "regions": [], "counts": {},
    }

    # ------- Tier 1 & 2: national roads -------
    for name, (tier, classes) in GROUPS.items():
        if tier >= 3:
            continue
        path = os.path.join(out_dir, name + ".geojson")
        print(f"{name}: {classes}")
        try:
            feats = [f for f in (road_feature(e, set(classes))
                                 for e in overpass(query(cfg["area"], classes))) if f]
            feats.sort(key=lambda f: f["properties"]["id"])
            write_geojson(path, feats)
            meta["counts"][name] = len(feats)
            meta["files"][str(tier)].append(name + ".geojson")
            print(f"  {len(feats)} segments, {os.path.getsize(path)/1e6:.1f} MB")
        except Exception as ex:
            print(f"  FAILED ({ex})", file=sys.stderr)
            if os.path.exists(path):
                meta["files"][str(tier)].append(name + ".geojson")
        time.sleep(10)

    # ------- Railways -------
    print("railways")
    try:
        feats = [f for f in (rail_feature(e) for e in overpass(rail_query(cfg["area"]))) if f]
        feats.sort(key=lambda f: f["properties"]["id"])
        write_geojson(os.path.join(out_dir, "railways.geojson"), feats)
        meta["counts"]["railways"] = len(feats)
        meta["files"]["rail"].append("railways.geojson")
        print(f"  {len(feats)} segments")
    except Exception as ex:
        print(f"  FAILED ({ex})", file=sys.stderr)
        if os.path.exists(os.path.join(out_dir, "railways.geojson")):
            meta["files"]["rail"].append("railways.geojson")
    time.sleep(10)

    # ------- Marzes -------
    regions = fetch_regions(cfg)
    t3_classes = [c for n, (t, cs) in GROUPS.items() if t == 3 for c in cs]

    # ------- Tier 3: local roads per marz -------
    print("tier 3: local roads")
    els = []
    for r in regions:
        try:
            got = overpass(query(cfg["area"], t3_classes, r["bbox"]))
            els += got
            print(f"  {r['name']}: {len(got)}")
        except Exception as ex:
            print(f"  {r['name']}: FAILED ({ex})", file=sys.stderr)
        time.sleep(5)

    feats = [f for f in (road_feature(e, set(t3_classes)) for e in els) if f]
    buckets = {r["id"]: [] for r in regions}
    for f in feats:
        x, y = f["geometry"]["coordinates"][0]
        for r in regions:
            s, w, n, e = r["bbox"]
            if w <= x <= e and s <= y <= n:
                buckets[r["id"]].append(f)
                break

    reg_dir = os.path.join(out_dir, "regions")
    os.makedirs(reg_dir, exist_ok=True)
    for r in regions:
        fs = buckets[r["id"]]
        if not fs:
            continue
        rel = f"regions/{r['id']}.geojson"
        write_geojson(os.path.join(out_dir, rel), fs)
        meta["regions"].append({
            "id": r["id"], "name": r["name"],
            "name_en": r.get("name_en", r["name"]),
            "name_ru": r.get("name_ru", r["name"]),
            "file": rel, "count": len(fs), "bbox": r["bbox"],
        })
        meta["files"]["3"].append(rel)

    json.dump(meta, open(os.path.join(out_dir, "meta.json"), "w"), indent=1)


if __name__ == "__main__":
    main()