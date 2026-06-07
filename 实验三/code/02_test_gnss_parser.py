"""Step 2: parser unit tests. Run on PC: python 02_test_gnss_parser.py"""

import math

from gnss_nmea import merge_gga_rmc, nmea_checksum_ok, parse_sentence


def with_checksum(body):
    checksum = 0
    for char in body:
        checksum ^= ord(char)
    return "$%s*%02X" % (body, checksum)


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def test_checksum_valid():
    line = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
    assert_true(nmea_checksum_ok(line), "valid checksum should pass")


def test_checksum_invalid():
    line = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*00"
    assert_true(not nmea_checksum_ok(line), "invalid checksum should fail")


def test_parse_gga_valid():
    line = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
    msg, data = parse_sentence(line)
    assert_true(msg == "GGA", "message type should be GGA")
    assert_true(abs(data["lat_deg"] - 48.1173) < 0.001, "latitude conversion")
    assert_true(abs(data["lon_deg"] - 11.5167) < 0.001, "longitude conversion")
    assert_true(data["quality"] == 1, "quality")
    assert_true(data["num_sat"] == 8, "satellite count")
    assert_true(math.isclose(data["hdop"], 0.9, rel_tol=0, abs_tol=0.01), "hdop")
    assert_true(data["valid"] is True, "valid fix")


def test_parse_gga_no_fix():
    line = "$GPGGA,,,,,,0,,,,,,,,*66"
    msg, data = parse_sentence(line)
    assert_true(msg == "GGA", "empty GGA should still parse")
    assert_true(data["valid"] is False, "quality 0 should be invalid")


def test_parse_rmc_valid():
    line = with_checksum("GPRMC,063015.00,A,2603.5234,N,11919.4521,E,0.123,45.6,150624,,,A")
    msg, data = parse_sentence(line)
    assert_true(msg == "RMC", "message type should be RMC")
    assert_true(data["status"] == "A", "status should be valid")
    assert_true(abs(data["lat_deg"] - 26.058723) < 0.001, "rmc latitude")
    assert_true(abs(data["lon_deg"] - 119.324202) < 0.001, "rmc longitude")


def test_merge_gga_rmc():
    gga_line = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
    rmc_line = with_checksum("GPRMC,123519,A,4807.038,N,01131.000,E,1.234,90.0,150624,,,A")
    _, gga = parse_sentence(gga_line)
    _, rmc = parse_sentence(rmc_line)
    merged = merge_gga_rmc(gga, rmc)
    assert_true(merged["quality"] == 1, "merged quality")
    assert_true(merged["sats"] == 8, "merged satellite count")


TESTS = [
    test_checksum_valid,
    test_checksum_invalid,
    test_parse_gga_valid,
    test_parse_gga_no_fix,
    test_parse_rmc_valid,
    test_merge_gga_rmc,
]


def main():
    passed = 0
    for test in TESTS:
        name = test.__name__
        try:
            test()
            print("PASS", name)
            passed += 1
        except AssertionError as exc:
            print("FAIL", name, "-", exc)
    print("summary,%d/%d passed" % (passed, len(TESTS)))
    if passed != len(TESTS):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
