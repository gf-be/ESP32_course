"""Self-written NMEA 0183 parser for experiment 3 (no third-party NMEA library)."""


def nmea_checksum_ok(sentence):
    sentence = sentence.strip()
    if not sentence.startswith("$") or "*" not in sentence:
        return False
    body, checksum_text = sentence[1:].split("*", 1)
    checksum = 0
    for char in body:
        checksum ^= ord(char)
    try:
        expected = int(checksum_text[:2], 16)
    except ValueError:
        return False
    return checksum == expected


def nmea_latlon_to_deg(value, hemi):
    if not value:
        return None
    try:
        raw = float(value)
    except ValueError:
        return None
    degrees = int(raw // 100)
    minutes = raw - degrees * 100
    decimal = degrees + minutes / 60.0
    if hemi in ("S", "W"):
        decimal = -decimal
    return decimal


def parse_gga(fields):
    if len(fields) < 10:
        return None
    quality = int(fields[6]) if fields[6].isdigit() else 0
    return {
        "utc_time": fields[1],
        "lat_deg": nmea_latlon_to_deg(fields[2], fields[3]),
        "lon_deg": nmea_latlon_to_deg(fields[4], fields[5]),
        "quality": quality,
        "num_sat": int(fields[7]) if fields[7].isdigit() else 0,
        "hdop": float(fields[8]) if fields[8] else None,
        "alt_m": float(fields[9]) if fields[9] else None,
        "valid": quality > 0,
    }


def parse_rmc(fields):
    if len(fields) < 10:
        return None
    return {
        "utc_time": fields[1],
        "status": fields[2] or "V",
        "lat_deg": nmea_latlon_to_deg(fields[3], fields[4]),
        "lon_deg": nmea_latlon_to_deg(fields[5], fields[6]),
        "speed_knots": float(fields[7]) if fields[7] else None,
        "course_deg": float(fields[8]) if fields[8] else None,
        "utc_date": fields[9],
        "valid": fields[2] == "A",
    }


def parse_gsa(fields):
    if len(fields) < 18:
        return None
    mode = fields[1]
    fix_type = int(fields[2]) if fields[2].isdigit() else 0
    sats = []
    for sat_id in fields[3:15]:
        if sat_id:
            sats.append(int(sat_id))
    return {
        "mode": mode,
        "fix_type": fix_type,
        "satellites": sats,
        "pdop": float(fields[15]) if fields[15] else None,
        "hdop": float(fields[16]) if fields[16] else None,
        "vdop": float(fields[17]) if fields[17] else None,
    }


def parse_gsv(fields):
    if len(fields) < 4:
        return None
    total_msgs = int(fields[1]) if fields[1].isdigit() else 0
    msg_num = int(fields[2]) if fields[2].isdigit() else 0
    sats_in_view = int(fields[3]) if fields[3].isdigit() else 0
    return {
        "total_msgs": total_msgs,
        "msg_num": msg_num,
        "sats_in_view": sats_in_view,
    }


def parse_sentence(sentence):
    sentence = sentence.strip()
    if not nmea_checksum_ok(sentence):
        return None, None
    body = sentence[1:].split("*", 1)[0]
    fields = body.split(",")
    msg = fields[0][-3:]
    if msg == "GGA":
        return "GGA", parse_gga(fields)
    if msg == "RMC":
        return "RMC", parse_rmc(fields)
    if msg == "GSA":
        return "GSA", parse_gsa(fields)
    if msg == "GSV":
        return "GSV", parse_gsv(fields)
    return msg, None


def merge_gga_rmc(gga, rmc):
    if not gga:
        return None
    return {
        "time": gga.get("utc_time", ""),
        "date": "" if not rmc else rmc.get("utc_date", ""),
        "lat": gga.get("lat_deg"),
        "lon": gga.get("lon_deg"),
        "quality": gga.get("quality", 0),
        "sats": gga.get("num_sat", 0),
        "hdop": gga.get("hdop"),
        "alt": gga.get("alt_m"),
        "speed_knots": None if not rmc else rmc.get("speed_knots"),
        "course_deg": None if not rmc else rmc.get("course_deg"),
        "status": "V" if not rmc else rmc.get("status", "V"),
        "valid": bool(gga.get("valid")),
    }
