"""Compare ESP32 GNSS CSV with phone GPX and render an overlay map."""

import argparse
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone

import folium
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def path_length_m(points):
    total = 0.0
    for (lat1, lon1), (lat2, lon2) in zip(points, points[1:]):
        total += haversine_m(lat1, lon1, lat2, lon2)
    return total


def load_gpx(path: Path) -> pd.DataFrame:
    root = ET.fromstring(path.read_text(encoding="utf-8", errors="ignore"))
    rows = []
    for elem in root.iter():
        if elem.tag.endswith("trkpt"):
            lat = float(elem.attrib["lat"])
            lon = float(elem.attrib["lon"])
            ele = None
            time_text = ""
            for child in elem:
                if child.tag.endswith("ele") and child.text:
                    ele = float(child.text)
                elif child.tag.endswith("time") and child.text:
                    time_text = child.text
            rows.append({"lat": lat, "lon": lon, "ele": ele, "time": time_text})
    if not rows:
        raise ValueError("no GPX track points found")
    df = pd.DataFrame(rows)
    df["parsed_time"] = pd.to_datetime(df["time"], errors="coerce", utc=True)
    cutoff = pd.Timestamp(datetime(2020, 1, 1, tzinfo=timezone.utc))
    filtered = df[(df["parsed_time"].isna()) | (df["parsed_time"] >= cutoff)].copy()
    if len(filtered[["lat", "lon"]].drop_duplicates()) >= 2:
        return filtered
    # Some phone apps export the real track geometry with broken 1970 timestamps
    # and append stationary points with correct timestamps. In that case, use
    # the geometry-rich part for spatial comparison and report time sync separately.
    return df.copy()


def nearest_distances(esp_points, phone_points):
    distances = []
    for lat, lon in esp_points:
        best = min(haversine_m(lat, lon, plat, plon) for plat, plon in phone_points)
        distances.append(best)
    return np.array(distances)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--esp", required=True)
    parser.add_argument("--phone", required=True)
    parser.add_argument("--out-dir", default="data")
    parser.add_argument("--assets-dir", default="assets")
    args = parser.parse_args()

    esp_path = Path(args.esp)
    phone_path = Path(args.phone)
    out_dir = Path(args.out_dir)
    assets_dir = Path(args.assets_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    esp_raw = pd.read_csv(esp_path)
    esp = esp_raw[(esp_raw["quality"] > 0) & esp_raw["lat"].notna() & esp_raw["lon"].notna()].copy()
    phone = load_gpx(phone_path)

    esp_points = list(zip(esp["lat"], esp["lon"]))
    phone_points = list(zip(phone["lat"], phone["lon"]))
    distances = nearest_distances(esp_points, phone_points)

    center_lat = float(pd.concat([esp["lat"], phone["lat"]]).mean())
    center_lon = float(pd.concat([esp["lon"], phone["lon"]]).mean())
    m = folium.Map(location=[center_lat, center_lon], zoom_start=17, tiles="OpenStreetMap")

    folium.PolyLine(phone_points, color="#2563eb", weight=4, opacity=0.8, tooltip="Phone GPX").add_to(m)
    folium.PolyLine(esp_points, color="#dc2626", weight=3, opacity=0.85, tooltip="ESP32 GNSS").add_to(m)
    folium.Marker(phone_points[0], popup="Phone start", icon=folium.Icon(color="blue")).add_to(m)
    folium.Marker(phone_points[-1], popup="Phone end", icon=folium.Icon(color="cadetblue")).add_to(m)
    folium.Marker(esp_points[0], popup="ESP32 start", icon=folium.Icon(color="red")).add_to(m)
    folium.Marker(esp_points[-1], popup="ESP32 valid end", icon=folium.Icon(color="orange")).add_to(m)

    for _, row in esp.iterrows():
        color = "green" if row["hdop"] < 1.5 else ("orange" if row["hdop"] < 3 else "red")
        folium.CircleMarker(
            location=(row["lat"], row["lon"]),
            radius=2,
            color=color,
            fill=True,
            fill_opacity=0.55,
            popup="ESP32 sats=%s, HDOP=%.2f" % (row["sats"], row["hdop"]),
        ).add_to(m)

    html_path = out_dir / "esp_phone_overlay.html"
    m.save(str(html_path))

    summary = {
        "esp_samples_raw": int(len(esp_raw)),
        "esp_valid_samples": int(len(esp)),
        "esp_valid_rate_percent": round(100.0 * len(esp) / max(len(esp_raw), 1), 2),
        "esp_avg_hdop": round(float(esp["hdop"].mean()), 3),
        "esp_min_sats": int(esp["sats"].min()),
        "esp_max_sats": int(esp["sats"].max()),
        "phone_samples": int(len(phone)),
        "esp_path_length_m": round(path_length_m(esp_points), 2),
        "phone_path_length_m": round(path_length_m(phone_points), 2),
        "nearest_distance_mean_m": round(float(distances.mean()), 2),
        "nearest_distance_median_m": round(float(np.median(distances)), 2),
        "nearest_distance_p95_m": round(float(np.percentile(distances, 95)), 2),
        "nearest_distance_max_m": round(float(distances.max()), 2),
    }
    summary_path = out_dir / "esp_phone_compare_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    fig, ax = plt.subplots(figsize=(8, 4), dpi=150)
    ax.hist(distances, bins=30, edgecolor="white", color="#dc2626")
    ax.set_xlabel("Nearest distance from ESP32 point to phone track (m)")
    ax.set_ylabel("ESP32 samples")
    ax.set_title("ESP32 vs phone track spatial difference")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(assets_dir / "esp_phone_nearest_distance.png")
    plt.close(fig)

    print("Wrote %s" % html_path)
    print("Wrote %s" % summary_path)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
