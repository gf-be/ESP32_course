"""
Analyze ESP32 offline GPS logs downloaded from /gps_logs.

Input:
  data/gps/offline_esp32_*/gps_nmea_*.txt

Output:
  data/analysis/gps_track_points_offline_<timestamp>.csv
  data/analysis/gps_track_summary_offline_<timestamp>.csv
  data/figures/gps_track_latlon_offline_<timestamp>.png
  data/figures/gps_track_status_offline_<timestamp>.png
  data/figures/gps_track_map_offline_<timestamp>.html
"""

from pathlib import Path
import csv
import math
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[2]
GPS_DIR = ROOT / "data" / "gps"
ANALYSIS_DIR = ROOT / "data" / "analysis"
FIG_DIR = ROOT / "data" / "figures"


def latest_offline_dir():
    dirs = [p for p in GPS_DIR.glob("offline_esp32_*") if p.is_dir()]
    if not dirs:
        raise FileNotFoundError("No offline_esp32_* directory found in %s" % GPS_DIR)
    return sorted(dirs, key=lambda p: p.stat().st_mtime)[-1]


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
    return int(hhmmss[0:2]) * 3600 + int(hhmmss[2:4]) * 60 + float(hhmmss[4:])


def haversine_m(a, b):
    lat1, lon1 = a
    lat2, lon2 = b
    radius = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(x), math.sqrt(1 - x))


def read_collection(folder):
    points = []
    file_stats = []
    total_nmea = 0
    bad_checksum = 0
    valid_rmc = 0
    valid_gga = 0

    files = sorted(folder.glob("gps_nmea_*.txt"))
    if not files:
        raise FileNotFoundError("No gps_nmea_*.txt found in %s" % folder)

    for file_index, path in enumerate(files):
        by_time = {}
        nmea = 0
        bad = 0
        rmc = 0
        gga = 0
        min_elapsed = None
        max_elapsed = None

        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "," not in line:
                    continue
                elapsed_text, sentence = line.split(",", 1)
                if not sentence.startswith("$"):
                    continue

                nmea += 1
                total_nmea += 1
                try:
                    elapsed_ms = int(elapsed_text)
                except Exception:
                    elapsed_ms = 0
                min_elapsed = elapsed_ms if min_elapsed is None else min(min_elapsed, elapsed_ms)
                max_elapsed = elapsed_ms if max_elapsed is None else max(max_elapsed, elapsed_ms)

                if not nmea_checksum_ok(sentence):
                    bad += 1
                    bad_checksum += 1
                    continue

                parts = sentence.split("*", 1)[0].split(",")
                sentence_type = parts[0]

                if sentence_type.endswith("RMC") and len(parts) >= 10 and parts[2] == "A":
                    lat = parse_latlon(parts[3], parts[4])
                    lon = parse_latlon(parts[5], parts[6])
                    if lat is None or lon is None:
                        continue
                    key = (parts[9], parts[1])
                    point = by_time.setdefault(key, {})
                    point.update({
                        "source_file": path.name,
                        "file_index": file_index,
                        "elapsed_ms": elapsed_ms,
                        "utc_time": parts[1],
                        "date": parts[9],
                        "utc_seconds": parse_time_seconds(parts[1]),
                        "lat": lat,
                        "lon": lon,
                        "speed_knots": float(parts[7]) if parts[7] else float("nan"),
                        "course_deg": float(parts[8]) if parts[8] else float("nan"),
                        "rmc_valid": 1,
                    })
                    rmc += 1
                    valid_rmc += 1

                if sentence_type.endswith("GGA") and len(parts) >= 10:
                    quality = int(parts[6]) if parts[6] else 0
                    if quality <= 0:
                        continue
                    lat = parse_latlon(parts[2], parts[3])
                    lon = parse_latlon(parts[4], parts[5])
                    if lat is None or lon is None:
                        continue
                    matches = [key for key in by_time if key[1] == parts[1]]
                    key = matches[0] if matches else ("", parts[1])
                    point = by_time.setdefault(key, {})
                    point.update({
                        "source_file": path.name,
                        "file_index": file_index,
                        "elapsed_ms": elapsed_ms,
                        "utc_time": parts[1],
                        "utc_seconds": parse_time_seconds(parts[1]),
                        "lat": lat,
                        "lon": lon,
                        "fix_quality": quality,
                        "satellites": int(parts[7]) if parts[7] else 0,
                        "hdop": float(parts[8]) if parts[8] else float("nan"),
                        "alt_m": float(parts[9]) if parts[9] else float("nan"),
                        "gga_valid": 1,
                    })
                    gga += 1
                    valid_gga += 1

        valid_points = [p for p in by_time.values() if "lat" in p and "lon" in p]
        points.extend(valid_points)
        duration_s = (max_elapsed - min_elapsed) / 1000.0 if min_elapsed is not None and max_elapsed is not None else 0.0
        file_stats.append({
            "source_file": path.name,
            "nmea": nmea,
            "bad_checksum": bad,
            "valid_rmc": rmc,
            "valid_gga": gga,
            "valid_points": len(valid_points),
            "duration_s": duration_s,
        })

    points.sort(key=lambda p: (p.get("file_index", 0), p.get("elapsed_ms", 0)))
    return points, file_stats, {
        "total_nmea": total_nmea,
        "bad_checksum": bad_checksum,
        "valid_rmc": valid_rmc,
        "valid_gga": valid_gga,
    }


def compute_summary(points, folder, file_stats, counts):
    segments = [
        haversine_m((a["lat"], a["lon"]), (b["lat"], b["lon"]))
        for a, b in zip(points[:-1], points[1:])
    ]
    duration_s = sum(item["duration_s"] for item in file_stats)
    sats = [p["satellites"] for p in points if p.get("satellites", 0) > 0]
    hdop = [p["hdop"] for p in points if not math.isnan(p.get("hdop", float("nan")))]
    alts = [p["alt_m"] for p in points if not math.isnan(p.get("alt_m", float("nan")))]
    lats = [p["lat"] for p in points]
    lons = [p["lon"] for p in points]
    lat_mean = statistics.fmean(lats)
    lon_mean = statistics.fmean(lons)

    return {
        "source_folder": folder.name,
        "log_files": len(file_stats),
        "usable_log_files": sum(1 for x in file_stats if x["valid_points"] > 0),
        "nmea_count": counts["total_nmea"],
        "bad_checksum": counts["bad_checksum"],
        "valid_points": len(points),
        "valid_rmc": counts["valid_rmc"],
        "valid_gga": counts["valid_gga"],
        "duration_s": duration_s,
        "track_distance_m_raw": sum(segments),
        "mean_speed_mps_raw": sum(segments) / duration_s if duration_s > 0 else 0.0,
        "max_step_m": max(segments) if segments else 0.0,
        "p95_step_m": sorted(segments)[int(0.95 * len(segments))] if segments else 0.0,
        "satellites_mean": statistics.fmean(sats) if sats else 0.0,
        "satellites_min": min(sats) if sats else 0,
        "satellites_max": max(sats) if sats else 0,
        "hdop_mean": statistics.fmean(hdop) if hdop else float("nan"),
        "hdop_min": min(hdop) if hdop else float("nan"),
        "hdop_max": max(hdop) if hdop else float("nan"),
        "alt_min_m": min(alts) if alts else float("nan"),
        "alt_max_m": max(alts) if alts else float("nan"),
        "alt_mean_m": statistics.fmean(alts) if alts else float("nan"),
        "lat_min": min(lats),
        "lat_max": max(lats),
        "lon_min": min(lons),
        "lon_max": max(lons),
        "bbox_ns_m": haversine_m((min(lats), lon_mean), (max(lats), lon_mean)),
        "bbox_ew_m": haversine_m((lat_mean, min(lons)), (lat_mean, max(lons))),
    }


def save_tables(points, file_stats, summary, tag):
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    points_path = ANALYSIS_DIR / ("gps_track_points_offline_%s.csv" % tag)
    summary_path = ANALYSIS_DIR / ("gps_track_summary_offline_%s.csv" % tag)

    point_headers = [
        "source_file", "file_index", "elapsed_ms", "utc_time", "date",
        "lat", "lon", "alt_m", "speed_knots", "course_deg",
        "fix_quality", "satellites", "hdop",
    ]
    with points_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=point_headers)
        writer.writeheader()
        for point in points:
            writer.writerow({key: point.get(key, "") for key in point_headers})

    with summary_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["item", "value", "unit", "note"])
        for item in file_stats:
            writer.writerow(["file_" + item["source_file"], item["valid_points"], "points", "valid GPS points in this log"])
        for key, value in summary.items():
            unit = ""
            if key.endswith("_m") or key.endswith("_m_raw"):
                unit = "m"
            elif key.endswith("_s"):
                unit = "s"
            elif key.endswith("_mps_raw"):
                unit = "m/s"
            writer.writerow([key, value, unit, ""])
    return points_path, summary_path


def make_figures(points, tag):
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Arial"]
    plt.rcParams["axes.unicode_minus"] = False

    elapsed = []
    offset = 0.0
    last_file = None
    last_elapsed = 0.0
    for point in points:
        if last_file is None:
            last_file = point["source_file"]
        if point["source_file"] != last_file:
            offset += last_elapsed
            last_file = point["source_file"]
        last_elapsed = point["elapsed_ms"] / 1000.0
        elapsed.append(offset + point["elapsed_ms"] / 1000.0)

    lat = [p["lat"] for p in points]
    lon = [p["lon"] for p in points]
    sats = [p.get("satellites", 0) for p in points]
    hdop = [p.get("hdop", float("nan")) for p in points]
    alt = [p.get("alt_m", float("nan")) for p in points]

    fig, ax = plt.subplots(figsize=(7.4, 6.2))
    ax.plot(lon, lat, marker="o", markersize=2, linewidth=1.0, color="#2563eb")
    ax.scatter(lon[0], lat[0], color="#16a34a", label="Start", s=50)
    ax.scatter(lon[-1], lat[-1], color="#ef4444", label="End", s=50)
    ax.set_title("GPS outdoor track")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    track_path = FIG_DIR / ("gps_track_latlon_offline_%s.png" % tag)
    fig.savefig(track_path, dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(3, 1, figsize=(9, 7), sharex=True)
    axes[0].plot(elapsed, sats, color="#2563eb")
    axes[0].set_ylabel("Satellites")
    axes[1].plot(elapsed, hdop, color="#f97316")
    axes[1].set_ylabel("HDOP")
    axes[2].plot(elapsed, alt, color="#16a34a")
    axes[2].set_ylabel("Altitude (m)")
    axes[2].set_xlabel("Time (s)")
    for ax in axes:
        ax.grid(True, alpha=0.25)
    axes[0].set_title("GPS fix quality over time")
    fig.tight_layout()
    status_path = FIG_DIR / ("gps_track_status_offline_%s.png" % tag)
    fig.savefig(status_path, dpi=180)
    plt.close(fig)

    return track_path, status_path


def make_folium_map(points, tag):
    import folium

    center = [
        statistics.fmean([p["lat"] for p in points]),
        statistics.fmean([p["lon"] for p in points]),
    ]
    coords = [(p["lat"], p["lon"]) for p in points]
    fmap = folium.Map(location=center, zoom_start=17, tiles="OpenStreetMap")
    folium.PolyLine(coords, color="blue", weight=4, opacity=0.8).add_to(fmap)
    folium.Marker(coords[0], tooltip="Start", icon=folium.Icon(color="green")).add_to(fmap)
    folium.Marker(coords[-1], tooltip="End", icon=folium.Icon(color="red")).add_to(fmap)
    map_path = FIG_DIR / ("gps_track_map_offline_%s.html" % tag)
    fmap.save(str(map_path))
    return map_path


def main():
    folder = latest_offline_dir()
    tag = folder.name.replace("offline_esp32_", "")
    points, file_stats, counts = read_collection(folder)
    if len(points) < 2:
        raise RuntimeError("Not enough valid GPS points in %s" % folder)
    summary = compute_summary(points, folder, file_stats, counts)
    points_path, summary_path = save_tables(points, file_stats, summary, tag)
    track_path, status_path = make_figures(points, tag)
    map_path = make_folium_map(points, tag)

    print("Source:", folder)
    for item in file_stats:
        print("File: {source_file}, nmea={nmea}, valid_points={valid_points}, duration_s={duration_s:.1f}".format(**item))
    print("Valid points:", summary["valid_points"])
    print("Duration: %.1f s" % summary["duration_s"])
    print("Raw track distance: %.1f m" % summary["track_distance_m_raw"])
    print("Mean satellites: %.2f, min=%d, max=%d" % (
        summary["satellites_mean"], summary["satellites_min"], summary["satellites_max"]))
    print("Mean HDOP: %.3f, min=%.2f, max=%.2f" % (
        summary["hdop_mean"], summary["hdop_min"], summary["hdop_max"]))
    print("Wrote:", points_path)
    print("Wrote:", summary_path)
    print("Figure:", track_path)
    print("Figure:", status_path)
    print("Map:", map_path)


if __name__ == "__main__":
    main()
