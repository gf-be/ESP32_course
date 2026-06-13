from __future__ import annotations

import argparse
import csv
from pathlib import Path


def parse_mag_lines(text: str) -> list[list[float]]:
    rows: list[list[float]] = []
    for line in text.splitlines():
        line = line.strip()
        if "MAG," not in line:
            continue
        line = line[line.index("MAG,") :]
        parts = line.split(",")
        if len(parts) < 5:
            continue
        try:
            if len(parts) >= 6:
                # New MicroPython format: MAG,run_id,t,bx,by,bz
                rows.append([float(parts[2]), float(parts[3]), float(parts[4]), float(parts[5])])
            else:
                # Legacy format: MAG,t,bx,by,bz
                rows.append([float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])])
        except ValueError:
            continue
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract MAG CSV rows from ESP-IDF monitor logs.")
    parser.add_argument("input_log", type=Path, help="Serial monitor text log.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("data/mag_raw.csv"),
        help="Output CSV path. Default: data/mag_raw.csv",
    )
    args = parser.parse_args()

    rows = parse_mag_lines(args.input_log.read_text(encoding="utf-8", errors="ignore"))
    args.output.parent.mkdir(parents=True, exist_ok=True)

    with args.output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)

    print(f"Extracted {len(rows)} MAG rows to {args.output}")


if __name__ == "__main__":
    main()
