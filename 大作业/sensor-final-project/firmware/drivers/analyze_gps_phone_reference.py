"""
Compare ESP32 offline GPS logs with a phone GNSS GPX reference track.

Inputs:
  ../../data/20260629户外步行.gpx
  data/analysis/gps_track_points_offline_*.csv

Outputs:
  data/analysis/gps_phone_reference_points_20260629.csv
  data/analysis/gps_phone_reference_summary_20260629.csv
  data/analysis/gps_esp32_vs_phone_summary_20260629.csv
  data/figures/gps_esp32_phone_overlay_20260629.png
  data/figures/gps_esp32_phone_error_hist_20260629.png
  data/figures/gps_esp32_phone_overlay_20260629.html
"""

from pathlib import Path
import csv
import math
import statistics
import xml.etree.ElementTree as ET

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[2]
BIG_HOMEWORK = ROOT.parent
PHONE_GPX = BIG_HOMEWORK / "data" / "20260629户外步行.gpx"
ANALYSIS_DIR = ROOT / "data" / "analysis"
FIG_DIR = ROOT / "data" / "figures"
TAG = "20260629"


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


def path_distance(points):
    return sum(
        haversine_m((a["lat"], a["lon"]), (b["lat"], b["lon"]))
        for a, b in zip(points[:-1], points[1:])
    )


def percentile(values, pct):
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * pct))))
    return ordered[index]


def bbox(points):
    lats = [p["lat"] for p in points]
    lons = [p["lon"] for p in points]
    return min(lats), max(lats), min(lons), max(lons)


def bbox_span_m(points):
    lat_min, lat_max, lon_min, lon_max = bbox(points)
    lat_mean = statistics.fmean([p["lat"] for p in points])
    lon_mean = statistics.fmean([p["lon"] for p in points])
    return (
        haversine_m((lat_min, lon_mean), (lat_max, lon_mean)),
        haversine_m((lat_mean, lon_min), (lat_mean, lon_max)),
    )


def read_phone_gpx(path):
    tree = ET.parse(path)
    root = tree.getroot()
    ns = {"gpx": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}

    def findall(name):
        return root.findall(".//gpx:" + name, ns) if ns else root.findall(".//" + name)

    def find_text(name):
        elem = root.find(".//gpx:" + name, ns) if ns else root.find(".//" + name)
        return elem.text.strip() if elem is not None and elem.text else ""

    extension_total_time = find_text("totalTime")
    extension_total_distance = find_text("totalDistance")
    extension_climb = find_text("cumulativeClimb")
    extension_decrease = find_text("cumulativeDecrease")

    points = []
    for index, elem in enumerate(findall("trkpt")):
        lat = float(elem.attrib["lat"])
        lon = float(elem.attrib["lon"])
        ele_elem = elem.find("gpx:ele", ns) if ns else elem.find("ele")
        time_elem = elem.find("gpx:time", ns) if ns else elem.find("time")
        points.append({
            "index": index,
            "lat": lat,
            "lon": lon,
            "ele_m": float(ele_elem.text) if ele_elem is not None and ele_elem.text else float("nan"),
            "gpx_time": time_elem.text if time_elem is not None and time_elem.text else "",
        })

    total_time = float(extension_total_time) if extension_total_time else float("nan")
    if points and not math.isnan(total_time):
        denom = max(1, len(points) - 1)
        for p in points:
            p["elapsed_s"] = total_time * p["index"] / denom
    else:
        for p in points:
            p["elapsed_s"] = float("nan")

    meta = {
        "extension_total_time_s": total_time,
        "extension_total_distance_m": float(extension_total_distance) if extension_total_distance else float("nan"),
        "extension_cumulative_climb_m": float(extension_climb) if extension_climb else float("nan"),
        "extension_cumulative_decrease_m": float(extension_decrease) if extension_decrease else float("nan"),
    }
    return points, meta


def latest_esp32_points_file():
    files = sorted(ANALYSIS_DIR.glob("gps_track_points_offline_*.csv"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError("No gps_track_points_offline_*.csv found in %s" % ANALYSIS_DIR)
    return files[-1]


def read_esp32_points(path):
    points = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                point = {
                    "source_file": row.get("source_file", ""),
                    "file_index": int(float(row.get("file_index", 0) or 0)),
                    "elapsed_ms": int(float(row.get("elapsed_ms", 0) or 0)),
                    "lat": float(row["lat"]),
                    "lon": float(row["lon"]),
                    "alt_m": float(row.get("alt_m", "nan") or "nan"),
                    "speed_knots": float(row.get("speed_knots", "nan") or "nan"),
                    "fix_quality": int(float(row.get("fix_quality", 0) or 0)),
                    "satellites": int(float(row.get("satellites", 0) or 0)),
                    "hdop": float(row.get("hdop", "nan") or "nan"),
                }
            except Exception:
                continue
            points.append(point)
    points.sort(key=lambda p: (p["file_index"], p["elapsed_ms"]))

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
        point["elapsed_s"] = offset + point["elapsed_ms"] / 1000.0
    return points


def nearest_distances(src, ref):
    ref_coords = [(p["lat"], p["lon"]) for p in ref]
    distances = []
    for p in src:
        here = (p["lat"], p["lon"])
        distances.append(min(haversine_m(here, q) for q in ref_coords))
    return distances


def summarize_track(prefix, points, extra=None):
    lat_min, lat_max, lon_min, lon_max = bbox(points)
    ns_span, ew_span = bbox_span_m(points)
    summary = {
        prefix + "_points": len(points),
        prefix + "_raw_distance_m": path_distance(points),
        prefix + "_bbox_ns_m": ns_span,
        prefix + "_bbox_ew_m": ew_span,
        prefix + "_lat_min": lat_min,
        prefix + "_lat_max": lat_max,
        prefix + "_lon_min": lon_min,
        prefix + "_lon_max": lon_max,
    }
    if extra:
        summary.update(extra)
    return summary


def write_points(path, points, headers):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for p in points:
            writer.writerow({h: p.get(h, "") for h in headers})


def write_summary(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["item", "value", "unit", "note"])
        for item, value, unit, note in rows:
            writer.writerow([item, value, unit, note])


def make_overlay_png(phone_points, esp_points, esp_filtered):
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Arial"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(figsize=(8.2, 6.5))
    ax.plot(
        [p["lon"] for p in phone_points],
        [p["lat"] for p in phone_points],
        color="#16a34a",
        linewidth=2.2,
        label="Phone GNSS reference",
    )
    ax.plot(
        [p["lon"] for p in esp_points],
        [p["lat"] for p in esp_points],
        color="#2563eb",
        linewidth=1.0,
        alpha=0.45,
        label="ESP32 GPS raw",
    )
    ax.plot(
        [p["lon"] for p in esp_filtered],
        [p["lat"] for p in esp_filtered],
        color="#ef4444",
        linewidth=1.3,
        alpha=0.85,
        label="ESP32 GPS filtered",
    )
    ax.scatter(phone_points[0]["lon"], phone_points[0]["lat"], color="#15803d", s=50, marker="o", label="Start")
    ax.scatter(phone_points[-1]["lon"], phone_points[-1]["lat"], color="#7f1d1d", s=50, marker="x", label="End")
    ax.set_title("GPS track overlay: ESP32 vs phone GNSS")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best")
    fig.tight_layout()
    out = FIG_DIR / ("gps_esp32_phone_overlay_%s.png" % TAG)
    fig.savefig(out, dpi=180)
    plt.close(fig)
    return out


def make_error_hist_png(raw_dist, filtered_dist):
    fig, ax = plt.subplots(figsize=(8.0, 5.2))
    bins = [0, 2, 5, 10, 15, 20, 30, 50, 80, 120]
    ax.hist(raw_dist, bins=bins, alpha=0.45, color="#2563eb", label="ESP32 raw")
    ax.hist(filtered_dist, bins=bins, alpha=0.65, color="#ef4444", label="ESP32 filtered")
    ax.set_title("Nearest distance to phone GNSS reference")
    ax.set_xlabel("Nearest distance (m)")
    ax.set_ylabel("Point count")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    out = FIG_DIR / ("gps_esp32_phone_error_hist_%s.png" % TAG)
    fig.savefig(out, dpi=180)
    plt.close(fig)
    return out


def make_folium_map(phone_points, esp_points, esp_filtered):
    import folium

    center = [
        statistics.fmean([p["lat"] for p in phone_points]),
        statistics.fmean([p["lon"] for p in phone_points]),
    ]
    fmap = folium.Map(location=center, zoom_start=17, tiles="OpenStreetMap")
    folium.PolyLine(
        [(p["lat"], p["lon"]) for p in phone_points],
        color="green",
        weight=5,
        opacity=0.9,
        tooltip="Phone GNSS reference",
    ).add_to(fmap)
    folium.PolyLine(
        [(p["lat"], p["lon"]) for p in esp_points],
        color="blue",
        weight=3,
        opacity=0.35,
        tooltip="ESP32 GPS raw",
    ).add_to(fmap)
    folium.PolyLine(
        [(p["lat"], p["lon"]) for p in esp_filtered],
        color="red",
        weight=3,
        opacity=0.85,
        tooltip="ESP32 GPS filtered",
    ).add_to(fmap)
    folium.LayerControl().add_to(fmap)
    out = FIG_DIR / ("gps_esp32_phone_overlay_%s.html" % TAG)
    fmap.save(str(out))
    return out


def main():
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    phone_points, phone_meta = read_phone_gpx(PHONE_GPX)
    esp_file = latest_esp32_points_file()
    esp_points = read_esp32_points(esp_file)
    esp_filtered = [p for p in esp_points if p["satellites"] >= 4 and p["hdop"] <= 5.0]

    raw_to_phone = nearest_distances(esp_points, phone_points)
    filtered_to_phone = nearest_distances(esp_filtered, phone_points)
    phone_to_raw = nearest_distances(phone_points, esp_points)
    phone_to_filtered = nearest_distances(phone_points, esp_filtered)

    phone_summary = summarize_track("phone", phone_points, phone_meta)
    esp_summary = summarize_track("esp32_raw", esp_points)
    esp_filtered_summary = summarize_track("esp32_filtered", esp_filtered)

    points_path = ANALYSIS_DIR / ("gps_phone_reference_points_%s.csv" % TAG)
    write_points(points_path, phone_points, ["index", "elapsed_s", "lat", "lon", "ele_m", "gpx_time"])

    phone_summary_path = ANALYSIS_DIR / ("gps_phone_reference_summary_%s.csv" % TAG)
    phone_rows = []
    for key, value in phone_summary.items():
        unit = "m" if key.endswith("_m") else "s" if key.endswith("_s") else ""
        phone_rows.append((key, value, unit, ""))
    write_summary(phone_summary_path, phone_rows)

    comparison_path = ANALYSIS_DIR / ("gps_esp32_vs_phone_summary_%s.csv" % TAG)
    comparison_rows = [
        ("phone_gpx_file", str(PHONE_GPX), "", ""),
        ("esp32_points_file", str(esp_file), "", ""),
        ("phone_points", len(phone_points), "points", ""),
        ("esp32_raw_points", len(esp_points), "points", ""),
        ("esp32_filtered_points", len(esp_filtered), "points", "satellites>=4 and HDOP<=5"),
        ("phone_total_distance_extension", phone_meta["extension_total_distance_m"], "m", "from GPX extensions"),
        ("phone_total_time_extension", phone_meta["extension_total_time_s"], "s", "from GPX extensions"),
        ("phone_raw_distance_from_points", path_distance(phone_points), "m", "polyline distance from GPX points"),
        ("esp32_raw_distance", path_distance(esp_points), "m", ""),
        ("esp32_filtered_distance", path_distance(esp_filtered), "m", ""),
        ("esp32_raw_to_phone_mean", statistics.fmean(raw_to_phone), "m", "nearest distance, ESP32 point to phone path"),
        ("esp32_raw_to_phone_median", statistics.median(raw_to_phone), "m", ""),
        ("esp32_raw_to_phone_p95", percentile(raw_to_phone, 0.95), "m", ""),
        ("esp32_filtered_to_phone_mean", statistics.fmean(filtered_to_phone), "m", "nearest distance, filtered ESP32 point to phone path"),
        ("esp32_filtered_to_phone_median", statistics.median(filtered_to_phone), "m", ""),
        ("esp32_filtered_to_phone_p95", percentile(filtered_to_phone, 0.95), "m", ""),
        ("phone_to_esp32_raw_mean", statistics.fmean(phone_to_raw), "m", "nearest distance, phone point to ESP32 path"),
        ("phone_to_esp32_raw_median", statistics.median(phone_to_raw), "m", ""),
        ("phone_to_esp32_filtered_mean", statistics.fmean(phone_to_filtered), "m", "nearest distance, phone point to filtered ESP32 path"),
        ("phone_to_esp32_filtered_median", statistics.median(phone_to_filtered), "m", ""),
    ]
    for summary in (esp_summary, esp_filtered_summary):
        for key, value in summary.items():
            unit = "m" if key.endswith("_m") else ""
            comparison_rows.append((key, value, unit, ""))
    write_summary(comparison_path, comparison_rows)

    overlay_png = make_overlay_png(phone_points, esp_points, esp_filtered)
    hist_png = make_error_hist_png(raw_to_phone, filtered_to_phone)
    html_map = make_folium_map(phone_points, esp_points, esp_filtered)

    print("Phone GPX:", PHONE_GPX)
    print("ESP32 points:", esp_file)
    print("Phone points:", len(phone_points))
    print("ESP32 raw points:", len(esp_points))
    print("ESP32 filtered points:", len(esp_filtered))
    print("Phone extension distance: %.1f m" % phone_meta["extension_total_distance_m"])
    print("Phone raw polyline distance: %.1f m" % path_distance(phone_points))
    print("ESP32 raw distance: %.1f m" % path_distance(esp_points))
    print("ESP32 filtered distance: %.1f m" % path_distance(esp_filtered))
    print("ESP32 raw nearest-to-phone median/p95: %.2f / %.2f m" % (
        statistics.median(raw_to_phone), percentile(raw_to_phone, 0.95)))
    print("ESP32 filtered nearest-to-phone median/p95: %.2f / %.2f m" % (
        statistics.median(filtered_to_phone), percentile(filtered_to_phone, 0.95)))
    print("Wrote:", points_path)
    print("Wrote:", phone_summary_path)
    print("Wrote:", comparison_path)
    print("Figure:", overlay_png)
    print("Figure:", hist_png)
    print("Map:", html_map)


if __name__ == "__main__":
    main()
