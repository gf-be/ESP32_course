"""Step 3 PC side: receive ESP32 UDP JSON and save track CSV."""

import csv
import json
import socket
from datetime import datetime
from pathlib import Path


UDP_IP = "0.0.0.0"
UDP_PORT = 8080
OUT_DIR = Path(__file__).resolve().parent.parent / "data"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / ("track_%s.csv" % datetime.now().strftime("%Y%m%d_%H%M%S"))

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    print("Listening on UDP %d ..." % UDP_PORT)
    print("Saving to %s" % csv_path)

    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(
            [
                "index",
                "elapsed_ms",
                "time",
                "date",
                "status",
                "quality",
                "lat",
                "lon",
                "alt",
                "sats",
                "hdop",
                "speed_knots",
                "course_deg",
            ]
        )

        try:
            while True:
                data, addr = sock.recvfrom(2048)
                try:
                    msg = json.loads(data.decode("utf-8"))
                except Exception as exc:
                    print("Parse error from %s: %s" % (addr, exc))
                    continue

                writer.writerow(
                    [
                        msg.get("index"),
                        msg.get("elapsed_ms"),
                        msg.get("time"),
                        msg.get("date"),
                        msg.get("status"),
                        msg.get("quality"),
                        msg.get("lat"),
                        msg.get("lon"),
                        msg.get("alt"),
                        msg.get("sats"),
                        msg.get("hdop"),
                        msg.get("speed_knots"),
                        msg.get("course_deg"),
                    ]
                )
                csv_file.flush()
                print(
                    "[%s] %.6f, %.6f | Q=%s sats=%s hdop=%s"
                    % (
                        msg.get("time"),
                        float(msg.get("lat") or 0),
                        float(msg.get("lon") or 0),
                        msg.get("quality"),
                        msg.get("sats"),
                        msg.get("hdop"),
                    )
                )
        except KeyboardInterrupt:
            print("Stopped.")
        finally:
            sock.close()


if __name__ == "__main__":
    main()
