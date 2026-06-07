# New MPU6500 Allan Variance Result

Date: 2026-06-05

Source file: `allan_raw_1h.csv`

Rows: 719946

Sensor duration: 3599.725 s (60.00 min)

Median sample rate: 199.800 Hz

Mean sample rate: 200.000 Hz

Analyzed axis: `gz_dps`

## Key Metrics

- ARW at tau = 1 s: 0.005880 deg/s, treated as 0.005880 deg/sqrt(s)
- ARW converted: 0.045544 deg/sqrt(min)
- ARW converted: 0.352780 deg/sqrt(hr)
- BI minimum ADEV: 0.001145 deg/s at tau = 899.929 s

## Output

- Allan curve: `allan_curve_gz.png`

## Notes

- The manual requests a static recording of at least 1 hour.
- ARW is read from the Allan deviation around tau = 1 s.
- BI is approximated by the minimum Allan deviation in this finite recording.