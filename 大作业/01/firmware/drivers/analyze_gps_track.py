# -*- coding: utf-8 -*-
"""
Parse GPS NMEA data and generate track visualization.

Input:
  data/gps/gps_nmea_*.txt

Output:
  data/analysis/gps_track_points.csv
  data/analysis/gps_track_summary.csv
  data/figures/gps_track_latlon.png
  data/figures/gps_track_status.png
  data/figures/gps_track_map.html
"""

from pathlib import Path
import csv
import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "gps"
ANALYSIS_DIR = ROOT / "data" / "analysis"
FIG_DIR = ROOT / "data" / "figures"


def latest_nmea_file():
    files = sorted(DATA_DIR.glob("gps_nmea_*.txt"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError("No gps_nmea_*.txt found in %s" % DATA_DIR)
    return files[-1]


def nmea_checksum_ok(sentence):
    if "*" not in sentence:
        return True
    body, checksum = sentence[1:].split("*", 1)
    calc = 0
    for ch in body:
        calc ^= ord(ch)
    try:
        return calc == int(checksum[:2], 16)
    except Exception:
        return False


def parse_latlon(value, hemi):
    if not value:
        return None
    raw = float(value)
    degrees = int(raw // 100)
    minutes = raw - degrees * 100
    result = degrees + minutes / 60.0
    if hemi in ("S", "W"):
        result = -result
    return result


def parse_time_seconds(hhmmss):
    if not hhmmss:
        return None
    hh = int(hhmmss[0:2])
    mm = int(hhmmss[2:4])
    ss = float(hhmmss[4:])
    return hh * 3600 + mm * 60 + ss


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def read_points(path):
    by_time = {}
    nmea_count = 0
    valid_rmc = 0
    valid_gga = 0

    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "," not in line:
                continue
            t_ms_str, sentence = line.split(",", 1)
            if not sentence.startswith("$"):
                continue
            nmea_count += 1
            if not nmea_checksum_ok(sentence):
                continue
            parts = sentence.split("*", 1)[0].split(",")
            typ = parts[0]

            if typ in ("$GPRMC", "$GNRMC") and len(parts) >= 10:
                if parts[2] != "A":
                    continue
                lat = parse_latlon(parts[3], parts[4])
                lon = parse_latlon(parts[5], parts[6])
                if lat is None or lon is None:
                    continue
                utc_s = parse_time_seconds(parts[1])
                key = parts[1]
                point = by_time.setdefault(key, {})
                point.update({
                    "t_ms": int(t_ms_str),
                    "utc_time": parts[1],
                    "utc_seconds": utc_s,
                    "lat": lat,
                    "lon": lon,
                    "speed_knots": float(parts[7]) if parts[7] else 0.0,
                    "course_deg": float(parts[8]) if parts[8] else float("nan"),
                    "date": parts[9],
                    "fix_valid": 1,
                })
                valid_rmc += 1

            if typ in ("$GPGGA", "$GNGGA") and len(parts) >= 10:
                quality = int(parts[6]) if parts[6] else 0
                if quality <= 0:
                    continue
                lat = parse_latlon(parts[2], parts[3])
                lon = parse_latlon(parts[4], parts[5])
                if lat is None or lon is None:
                    continue
                key = parts[1]
                point = by_time.setdefault(key, {})
                point.update({
                    "t_ms": int(t_ms_str),
                    "utc_time": parts[1],
                    "utc_seconds": parse_time_seconds(parts[1]),
                    "lat": lat,
                    "lon": lon,
                    "fix_quality": quality,
                    "satellites": int(parts[7]) if parts[7] else 0,
                    "hdop": float(parts[8]) if parts[8] else float("nan"),
                    "alt_m": float(parts[9]) if parts[9] else float("nan"),
                    "fix_valid": 1,
                })
                valid_gga += 1

    points = []
    for point in by_time.values():
        if "lat" in point and "lon" in point:
            point.setdefault("speed_knots", float("nan"))
            point.setdefault("course_deg", float("nan"))
            point.setdefault("fix_quality", 0)
            point.setdefault("satellites", 0)
            point.setdefault("hdop", float("nan"))
            point.setdefault("alt_m", float("nan"))
            point.setdefault("date", "")
            points.append(point)
    points.sort(key=lambda p: (p.get("t_ms", 0), p.get("utc_time", "")))
    return points, nmea_count, valid_rmc, valid_gga


def compute_summary(points, source_path, nmea_count, valid_rmc, valid_gga):
    distance = 0.0
    for a, b in zip(points[:-1], points[1:]):
        distance += haversine_m(a["lat"], a["lon"], b["lat"], b["lon"])
    duration_s = (points[-1]["t_ms"] - points[0]["t_ms"]) / 1000.0 if len(points) >= 2 else 0.0
    sats = [p["satellites"] for p in points if p.get("satellites", 0) > 0]
    hdop = [p["hdop"] for p in points if not math.isnan(p.get("hdop", float("nan")))]
    alts = [p["alt_m"] for p in points if not math.isnan(p.get("alt_m", float("nan")))]
    return {
        "source_file": source_path.name,
        "nmea_count": nmea_count,
        "valid_points": len(points),
        "valid_rmc": valid_rmc,
        "valid_gga": valid_gga,
        "duration_s": duration_s,
        "track_distance_m": distance,
        "mean_speed_mps": distance / duration_s if duration_s > 0 else 0.0,
        "satellites_mean": sum(sats) / len(sats) if sats else 0.0,
        "satellites_max": max(sats) if sats else 0,
        "hdop_mean": sum(hdop) / len(hdop) if hdop else float("nan"),
        "alt_min_m": min(alts) if alts else float("nan"),
        "alt_max_m": max(alts) if alts else float("nan"),
        "lat_min": min(p["lat"] for p in points),
        "lat_max": max(p["lat"] for p in points),
        "lon_min": min(p["lon"] for p in points),
        "lon_max": max(p["lon"] for p in points),
    }


def save_tables(points, summary):
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    point_path = ANALYSIS_DIR / "gps_track_points.csv"
    headers = ["t_ms", "utc_time", "date", "lat", "lon", "alt_m", "speed_knots", "course_deg", "fix_quality", "satellites", "hdop"]
    with point_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for p in points:
            writer.writerow({h: p.get(h, "") for h in headers})

    summary_path = ANALYSIS_DIR / "gps_track_summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["item", "value", "unit", "note"])
        for key, value in summary.items():
            unit = ""
            if key.endswith("_m"):
                unit = "m"
            elif key.endswith("_s"):
                unit = "s"
            elif key.endswith("_mps"):
                unit = "m/s"
            writer.writerow([key, value, unit, ""])

    return point_path, summary_path


def make_figures(points):
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Arial"]
    plt.rcParams["axes.unicode_minus"] = False

    t = [(p["t_ms"] - points[0]["t_ms"]) / 1000.0 for p in points]
    lat = [p["lat"] for p in points]
    lon = [p["lon"] for p in points]
    sats = [p.get("satellites", 0) for p in points]
    hdop = [p.get("hdop", float("nan")) for p in points]
    alt = [p.get("alt_m", float("nan")) for p in points]

    fig, ax = plt.subplots(figsize=(7.2, 6.2))
    ax.plot(lon, lat, marker="o", markersize=2, linewidth=1.0, color="#2563eb")
    ax.scatter(lon[0], lat[0], color="#16a34a", label="Start", s=45)
    ax.scatter(lon[-1], lat[-1], color="#ef4444", label="End", s=45)
    ax.set_title("GPS outdoor track")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    track_path = FIG_DIR / "gps_track_latlon.png"
    fig.savefig(track_path, dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(3, 1, figsize=(9, 7), sharex=True)
    axes[0].plot(t, sats, color="#2563eb")
    axes[0].set_ylabel("Satellites")
    axes[1].plot(t, hdop, color="#f97316")
    axes[1].set_ylabel("HDOP")
    axes[2].plot(t, alt, color="#16a34a")
    axes[2].set_ylabel("Altitude (m)")
    axes[2].set_xlabel("Time (s)")
    for ax in axes:
        ax.grid(True, alpha=0.25)
    axes[0].set_title("GPS fix quality over time")
    fig.tight_layout()
    status_path = FIG_DIR / "gps_track_status.png"
    fig.savefig(status_path, dpi=180)
    plt.close(fig)

    return track_path, status_path


def make_folium_map(points):
    map_path = FIG_DIR / "gps_track_map.html"
    try:
        import folium
    except Exception:
        center = [sum(p["lat"] for p in points) / len(points), sum(p["lon"] for p in points) / len(points)]
        coords = [[p["lat"], p["lon"]] for p in points]
        html = """<!doctype html><meta charset="utf-8"><title>GPS Track</title>
<h1>GPS Track</h1>
<p>folium is not installed. Track coordinates are embedded below.</p>
<pre>%s</pre>
""" % coords
        map_path.write_text(html, encoding="utf-8")
        return map_path, False

    center = [sum(p["lat"] for p in points) / len(points), sum(p["lon"] for p in points) / len(points)]
    fmap = folium.Map(location=center, zoom_start=18, tiles="OpenStreetMap")
    coords = [(p["lat"], p["lon"]) for p in points]
    folium.PolyLine(coords, color="blue", weight=4, opacity=0.8).add_to(fmap)
    folium.Marker(coords[0], tooltip="Start", icon=folium.Icon(color="green")).add_to(fmap)
    folium.Marker(coords[-1], tooltip="End", icon=folium.Icon(color="red")).add_to(fmap)
    fmap.save(str(map_path))
    return map_path, True


def main():
    path = latest_nmea_file()
    points, nmea_count, valid_rmc, valid_gga = read_points(path)
    if len(points) < 2:
        raise RuntimeError("Not enough valid GPS points. Move outdoors, wait for fix, and capture again.")
    summary = compute_summary(points, path, nmea_count, valid_rmc, valid_gga)
    point_path, summary_path = save_tables(points, summary)
    figs = make_figures(points)
    map_path, folium_ok = make_folium_map(points)

    print("Source:", path)
    print("NMEA sentences:", nmea_count)
    print("Valid points:", len(points))
    print("Duration: %.1f s" % summary["duration_s"])
    print("Track distance: %.1f m" % summary["track_distance_m"])
    print("Mean satellites: %.2f max=%s" % (summary["satellites_mean"], summary["satellites_max"]))
    print("Mean HDOP:", summary["hdop_mean"])
    print("Wrote:", point_path)
    print("Wrote:", summary_path)
    for fig in figs:
        print("Figure:", fig)
    print("Map:", map_path, "folium=" + str(folium_ok))


if __name__ == "__main__":
    main()
