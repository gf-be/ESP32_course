# New MPU6500 Complementary Filter Attitude Result

Date: 2026-06-05

This file records Step 7 complementary-filter attitude observations for the new true MPU6500 board.

## Firmware

The firmware was switched from Allan output mode to attitude output mode.

Output format:

```text
ATT,t,roll_deg,pitch_deg,roll_acc_deg,pitch_acc_deg,gx_dps,gy_dps,temp_c
```

The firmware performs an automatic 2 s static zero at startup, then runs a complementary filter:

```text
roll  = 0.98 * roll_gyro  + 0.02 * roll_acc
pitch = 0.98 * pitch_gyro + 0.02 * pitch_acc
```

## Initial Separate Tests

Source files:

- `attitude_level.csv`
- `attitude_x_tilt.csv`
- `attitude_x_tilt_rerun.csv`

The separate tilt files were not used for final validation because opening the serial port can reset the ESP32. If the board is already tilted when the serial port opens, the firmware auto-zero step treats that tilted position as the new zero reference.

## Continuous Sequence

Source file: `attitude_continuous_sequence.csv`

Rows: 1652

Duration: 82.55 s

This continuous record avoids repeated serial-port resets.

### Segment Summary

| Segment | Time window | Roll mean | Roll std | Pitch mean | Pitch std | Note |
|---|---:|---:|---:|---:|---:|---|
| Initial level | 0-20 s | -0.043 deg | 0.196 deg | 0.004 deg | 0.019 deg | Level reference is close to zero |
| Tilt A stable | 30-50 s | 152.204 deg | 0.324 deg | 42.143 deg | 0.547 deg | Pitch follows a clear about-42 deg tilt |
| Return level | 55-70 s | -1.352 deg | 1.042 deg | 0.016 deg | 0.017 deg | Returns close to level |
| Tilt B stable | 75-82.5 s | 56.851 deg | 0.076 deg | 42.725 deg | 0.418 deg | A second stable tilted attitude |

## Assessment

- Horizontal validation passes: roll and pitch are close to zero after auto-zero.
- Tilt validation passes qualitatively: the attitude angles change clearly and remain stable in tilted poses.
- The first tilted pose crosses the current roll-angle convention strongly, so the pitch value is the cleaner 45 deg evidence for that segment.
- The second tilted pose shows stable roll and pitch components, indicating the filter remains stable under another tilted attitude.

## Shake and Return Validation

Source file: `attitude_shake_return_fixed.csv`

Rows: 1132

Duration: 56.55 s

Before this final run, the firmware angle wrapping was fixed so that relative accelerometer angles are wrapped to `[-180 deg, 180 deg]`. Earlier shake files can contain angle jumps near the wrap boundary and should not be used as final evidence.

| Segment | Time window | Roll mean | Roll std | Roll min/max | Pitch mean | Pitch std | Pitch min/max | Note |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Initial level | 0-5 s | 0.321 deg | 0.134 deg | -0.100 / 0.650 deg | -0.007 deg | 0.024 deg | -0.070 / 0.030 deg | Stable level |
| Motion onset | 20-25 s | 4.2 deg | - | -31.4 / 58.8 deg | 2.3 deg | - | -3.9 / 10.9 deg | Visible motion without angle wrap jump |
| Motion peak | 25-30 s | 23.7 deg | - | -11.6 / 71.2 deg | 3.5 deg | - | -5.0 / 12.1 deg | Clear shake/tilt response |
| Return level | 35-56.5 s | about 2.5 deg | low | 1.9 / 3.2 deg in stable bins | about -0.1 deg | low | about -0.1 / 0.0 deg | Returns close to level, no divergence |

Shake validation result: the complementary filter responds to a visible shake/tilt and returns to a stable near-level attitude. There is a small residual roll offset of about 2-3 deg after the motion, but the estimate does not diverge.
