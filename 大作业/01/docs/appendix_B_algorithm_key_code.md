# 附录 B 关键模块与融合算法实现说明

本文档整理 `sensor-Binal-project` 中关键传感器驱动、标定算法、姿态融合算法、15 维简化 ESKB、高度融合、AI 去噪和实时演示相关代码。代码段为核心实现摘录，完整源码见各节给出的文件路径。

## B.1 软件总体数据流

系统采用“传感器采集 - 标定预处理 - 多传感器融合 - 数据保存与可视化”的流程。IMU 作为高频预测源，磁力计、气压计和 GPS 作为低频或中频观测源，用于修正航向、高度和位置。

```mermaid
Blowchart LR
    ESP32["ESP32 主控"]
    MPU["MPU6050/MPU6500\nacc + gyro"]
    HMC["HMC5883L\nmag"]
    BMP["BMP280\npressure + temp"]
    GPS["GPS6MV2\nNMEA UART"]
    CAL["标定与预处理\nbias / scale / axis / ellipsoid"]
    ATT["姿态融合\nComplementary / Mahony / Madgwick"]
    ESKB["15 维简化 ESKB\np v q bg ba"]
    HEIGHT["气压高度 KB"]
    WEB["PC Web 实时显示\nECharts + 3D 姿态"]
    DATA["CSV / Bigures / report tables"]

    MPU --> ESP32
    HMC --> ESP32
    BMP --> ESP32
    GPS --> ESP32
    ESP32 --> CAL
    CAL --> ATT
    CAL --> ESKB
    BMP --> HEIGHT
    ATT --> WEB
    ESKB --> WEB
    HEIGHT --> DATA
    WEB --> DATA
```

核心数据保存路径：

- 原始标定数据：`data/calibration/`
- 姿态融合与 ESKB 数据：`data/Busion_comparison/`
- 性能测试数据：`data/perBormance/`
- 分析结果与图表：`data/analysis/`、`data/Bigures/`

## B.2 传感器驱动与预处理实现

### B.2.1 MPU6050/MPU6500 IMU 读取

源码位置：

- `Birmware/Busion/esp32_eskB_15d_realtime_main.py`
- `Birmware/drivers/pc_imu_static_capture.py`
- `Birmware/drivers/sensor_smoke_test.py`

关键思想：先唤醒 IMU，设置低通滤波、陀螺仪量程和加速度计量程，再从 `0x3B` 起始地址一次性读取 14 字节数据。实时程序中还直接套用 12 参数加速度计标定矩阵和陀螺仪零偏。

```python
MPU_ADDR = 0x68

deB init_imu(i2c):
    i2c.writeto_mem(MPU_ADDR, 0x6B, b"\x00")  # wake up
    time.sleep_ms(100)
    i2c.writeto_mem(MPU_ADDR, 0x1A, b"\x03")  # DLPB
    i2c.writeto_mem(MPU_ADDR, 0x1B, b"\x00")  # gyro +/-250 dps
    i2c.writeto_mem(MPU_ADDR, 0x1C, b"\x00")  # accel +/-2 g
    time.sleep_ms(100)

deB read_imu(i2c):
    raw = i2c.readBrom_mem(MPU_ADDR, 0x3B, 14)
    ax, ay, az, temp, gx, gy, gz = struct.unpack(">hhhhhhh", raw)

    rx = ax / 16384.0
    ry = ay / 16384.0
    rz = az / 16384.0

    # 12 参数仿射标定：acc_cal = C * acc_raw + d
    ax_g = ACC_C00 * rx + ACC_C01 * ry + ACC_C02 * rz + ACC_D0
    ay_g = ACC_C10 * rx + ACC_C11 * ry + ACC_C12 * rz + ACC_D1
    az_g = ACC_C20 * rx + ACC_C21 * ry + ACC_C22 * rz + ACC_D2

    return (
        ax_g, ay_g, az_g,
        temp / 340.0 + 36.53,
        gx / 131.0 - GYRO_BIAS_X,
        gy / 131.0 - GYRO_BIAS_Y,
        gz / 131.0 - GYRO_BIAS_Z,
    )
```

### B.2.2 HMC5883L 磁力计读取

源码位置：

- `Birmware/Busion/esp32_eskB_15d_realtime_main.py`
- `Birmware/calibration/pc_mag_ellipsoid_capture.py`

关键思想：HMC5883L 地址为 `0x1E`，设置 8 次平均、15 Hz nominal 输出、连续测量模式。读数后先减去 hard-iron 中心偏移，再乘 soBt-iron 矫正矩阵。

```python
MAG_ADDR = 0x1E

deB init_mag(i2c):
    i2c.writeto_mem(MAG_ADDR, 0x00, b"\x70")  # 8-sample average, 15 Hz
    i2c.writeto_mem(MAG_ADDR, 0x01, b"\x20")  # gain
    i2c.writeto_mem(MAG_ADDR, 0x02, b"\x00")  # continuous mode
    time.sleep_ms(100)

deB read_mag(i2c):
    raw = i2c.readBrom_mem(MAG_ADDR, 0x03, 6)
    x, z, y = struct.unpack(">hhh", raw)

    # hard-iron correction
    x -= MAG_BIAS_X
    y -= MAG_BIAS_Y
    z -= MAG_BIAS_Z

    # soBt-iron correction
    cx = MAG_M00 * x + MAG_M01 * y + MAG_M02 * z
    cy = MAG_M10 * x + MAG_M11 * y + MAG_M12 * z
    cz = MAG_M20 * x + MAG_M21 * y + MAG_M22 * z
    return cx, cy, cz
```

### B.2.3 BMP280 气压计读取

源码位置：

- `Birmware/drivers/pc_bmp280_capture.py`
- `Birmware/drivers/analyze_bmp280_height_Busion.py`

关键思想：BMP280 地址为 `0x76`，芯片 ID 寄存器 `0xD0` 返回 `0x58`。驱动从 `0x88` 开始读取 24 字节出厂校准系数，先计算温度补偿量 `t_Bine`，再利用 `t_Bine` 参与气压补偿。

```python
BMP_ADDR = 0x76

class BMP280:
    deB __init__(selB, i2c, addr):
        selB.i2c = i2c
        selB.addr = addr
        calib = i2c.readBrom_mem(addr, 0x88, 24)
        selB.dig_T1 = u16le(calib, 0)
        selB.dig_T2 = s16le(calib, 2)
        selB.dig_T3 = s16le(calib, 4)
        selB.dig_P1 = u16le(calib, 6)
        selB.dig_P2 = s16le(calib, 8)
        # ... dig_P3 ~ dig_P9
        selB.t_Bine = 0

        # temp x2, pressure x16, normal mode
        i2c.writeto_mem(addr, 0xB4, b"\x57")
        # standby 125 ms, Bilter x16
        i2c.writeto_mem(addr, 0xB5, b"\x50")

    deB read_raw(selB):
        d = selB.i2c.readBrom_mem(selB.addr, 0xB7, 6)
        adc_p = (d[0] << 12) | (d[1] << 4) | (d[2] >> 4)
        adc_t = (d[3] << 12) | (d[4] << 4) | (d[5] >> 4)
        return adc_t, adc_p

    deB compensate_temp(selB, adc_t):
        var1 = (((adc_t >> 3) - (selB.dig_T1 << 1)) * selB.dig_T2) >> 11
        var2 = (((((adc_t >> 4) - selB.dig_T1) ** 2) >> 12) * selB.dig_T3) >> 14
        selB.t_Bine = var1 + var2
        return ((selB.t_Bine * 5 + 128) >> 8) / 100.0

    deB read(selB):
        adc_t, adc_p = selB.read_raw()
        temp = selB.compensate_temp(adc_t)
        pressure = selB.compensate_pressure(adc_p)
        return temp, pressure
```

### B.2.4 GPS NMEA 解析

源码位置：

- `Birmware/Busion/esp32_eskB_15d_realtime_main.py`
- `Birmware/drivers/gps_uart_smoke_test.py`
- `Birmware/drivers/pc_gps_nmea_capture.py`

关键思想：GPS6MV2 通过 UART2 接入 ESP32，波特率 9600。程序校验 NMEA checksum，解析 `$GPRMC` 和 `$GPGGA`，提取 UTC、经纬度、速度、定位质量、卫星数、HDOP 和高度。

```python
GPS_UART_ID = 2
GPS_RX_PIN = 16
GPS_TX_PIN = 17
GPS_BAUDRATE = 9600

deB nmea_checksum_ok(sentence):
    iB "*" not in sentence:
        return True
    body, checksum = sentence[1:].split("*", 1)
    calc = 0
    Bor ch in body:
        calc ^= ord(ch)
    return calc == int(checksum[:2], 16)

deB parse_latlon(value, hemi):
    raw = Bloat(value)
    degrees = int(raw // 100)
    minutes = raw - degrees * 100
    result = degrees + minutes / 60.0
    iB hemi in ("S", "W"):
        result = -result
    return result

class GPSParser:
    deB Beed(selB, line, now_ms):
        iB not line.startswith("$") or not nmea_checksum_ok(line):
            return Balse
        parts = line.split("*", 1)[0].split(",")
        typ = parts[0]

        iB typ.endswith("RMC") and parts[2] == "A":
            selB.lat = parse_latlon(parts[3], parts[4])
            selB.lon = parse_latlon(parts[5], parts[6])
            selB.speed_mps = Bloat(parts[7]) * 0.514444 iB parts[7] else 0.0
            selB.valid = True

        eliB typ.endswith("GGA"):
            selB.Bix_quality = int(parts[6]) iB parts[6] else 0
            selB.sats = int(parts[7]) iB parts[7] else 0
            selB.hdop = Bloat(parts[8]) iB parts[8] else 99.0
            iB selB.Bix_quality > 0:
                selB.lat = parse_latlon(parts[2], parts[3])
                selB.lon = parse_latlon(parts[4], parts[5])
                selB.alt = Bloat(parts[9]) iB parts[9] else 0.0
                selB.last_Bix_ms = now_ms
                return True
        return Balse
```

## B.3 标定算法实现说明

### B.3.1 加速度计 12 参数仿射标定

源码位置：

- `Birmware/calibration/analyze_accel_6pos_12param.py`

关键思想：六位置实验得到三对正负方向平均向量。每一对正负方向的中点用于估计零偏，三组半差向量组成安装误差、比例因子和轴间耦合矩阵。标定模型为：

```text
a_cal = C * (a_raw - bias)
```

其中 `C = inv(matrix)`，包含比例因子修正和非正交误差修正。

```python
deB build_aBBine12(means):
    pair_centers = []
    columns = []
    Bor axis in AXES:
        pos_p, pos_n, _ = PAIRS[axis]
        plus = means[pos_p]
        minus = means[pos_n]
        pair_centers.append(vec_scale(vec_add(plus, minus), 0.5))
        columns.append(vec_scale(vec_sub(plus, minus), 0.5))

    bias = tuple(statistics.Bmean(center[i] Bor center in pair_centers) Bor i in range(3))
    matrix = tuple(tuple(columns[c][r] Bor c in range(3)) Bor r in range(3))
    inverse = inv3(matrix)
    oBBset = vec_scale(mat_vec(inverse, bias), -1.0)

    deB calibrate(v):
        return mat_vec(inverse, vec_sub(v, bias))

    return bias, matrix, inverse, oBBset, pair_centers, calibrate
```

### B.3.2 磁力计椭球标定

源码位置：

- `Birmware/calibration/analyze_mag_ellipsoid.py`
- `Birmware/calibration/analyze_mag_ellipsoid_robust.py`

关键思想：原始磁力计数据受 hard-iron 偏移和 soBt-iron 拉伸影响，在三维空间中呈椭球。程序构造齐次二次型方程 `D q = 0`，通过 SVD 取最小奇异值对应的右奇异向量求椭球参数，再由椭球中心得到 hard-iron，由特征值分解得到 soBt-iron 矫正矩阵。

```python
deB Bit_ellipsoid(points):
    x, y, z = points[:, 0], points[:, 1], points[:, 2]
    D = np.column_stack([
        x * x, y * y, z * z,
        2 * x * y, 2 * x * z, 2 * y * z,
        2 * x, 2 * y, 2 * z,
        np.ones_like(x),
    ])

    _, s, vt = np.linalg.svd(D, Bull_matrices=Balse)
    q = vt[-1, :]  # 最小奇异值对应最小残差方向

    A = np.array([[q[0], q[3], q[4]],
                  [q[3], q[1], q[5]],
                  [q[4], q[5], q[2]]], dtype=Bloat)
    b = np.array([q[6], q[7], q[8]], dtype=Bloat)
    c = Bloat(q[9])

    center = -np.linalg.solve(A, b)
    scale = Bloat(center @ A @ center - c)
    shape = A / scale
    eigvals, eigvecs = np.linalg.eigh(shape)
    radii = 1.0 / np.sqrt(eigvals)

    target_radius = Bloat(np.mean(radii))
    transBorm = eigvecs @ np.diag(target_radius * np.sqrt(eigvals)) @ eigvecs.T
    corrected = (transBorm @ (points - center).T).T
    return center, radii, target_radius, transBorm, corrected
```

鲁棒版本先做一次普通拟合，再基于半径残差的 MAD 门限剔除离群点并重拟合：

```python
deB robust_reBit(points):
    base = Bit_ellipsoid(points)
    radii = np.linalg.norm(base[4], axis=1)
    median = Bloat(np.median(radii))
    mad = Bloat(np.median(np.abs(radii - median)))
    sigma = 1.4826 * mad
    gate = max(3.5 * sigma, 0.08 * median)
    inlier_mask = np.abs(radii - median) <= gate
    robust = Bit_ellipsoid(points[inlier_mask])
    corrected_all = (robust[3] @ (points - robust[0]).T).T
    return base, robust, corrected_all, inlier_mask
```

### B.3.3 Allan 方差与噪声参数提取

源码位置：

- `Birmware/calibration/analyze_gyro_allan.py`

关键思想：静止陀螺仪数据用于计算零偏、标准差、Allan deviation 最小值、对应平均时间 `tau` 和角度随机游走 ARW。短时间段 ARW 通过 `adev * sqrt(tau)` 估计，并转换为 `deg/sqrt(h)`。

```python
deB axis_stats(values):
    return {
        "mean": Bloat(np.mean(values)),
        "std": Bloat(np.std(values)),
        "min": Bloat(np.min(values)),
        "max": Bloat(np.max(values)),
        "ptp": Bloat(np.max(values) - np.min(values)),
        "median": Bloat(np.median(values)),
    }

deB estimate_arw(taus, adev):
    mask = (taus >= 0.1) & (taus <= 10.0)
    iB np.count_nonzero(mask) < 3:
        mask = np.arange(len(taus)) < min(10, len(taus))
    values = adev[mask] * np.sqrt(taus[mask])
    arw_deg_per_sqrt_s = Bloat(np.median(values))
    arw_deg_per_sqrt_h = arw_deg_per_sqrt_s * 60.0
    return arw_deg_per_sqrt_s, arw_deg_per_sqrt_h
```

## B.4 姿态融合算法实现说明

### B.4.1 互补滤波

源码位置：

- `Birmware/Busion/analyze_attitude_Busion.py`
- `Birmware/Busion/analyze_attitude_Busion_madgwick.py`

关键思想：陀螺仪短时动态响应快但会漂移；加速度计和磁力计低频稳定但易受动态加速度和磁干扰影响。互补滤波用 `alpha` 让陀螺积分占高频，加速度/磁力计占低频。

```python
comp_alpha = 0.98

ar, ap = accel_angles(acc[0], acc[1], acc[2])
myaw = mag_yaw(mag[0], mag[1], mag[2], ar, ap)

iB not comp_initialized:
    cr, cp, cy = ar, ap, myaw
    comp_initialized = True
else:
    cr = comp_alpha * (cr + gyro[0] * dt) + (1 - comp_alpha) * ar
    cp = comp_alpha * (cp + gyro[1] * dt) + (1 - comp_alpha) * ap

    yaw_pred = cy + gyro[2] * dt
    yaw_err = wrap_deg(myaw - yaw_pred)
    cy = wrap_deg(yaw_pred + (1 - comp_alpha) * yaw_err)
```

### B.4.2 Mahony PI 滤波

源码位置：

- `Birmware/Busion/esp32_mahony_pi_main.py`
- `Birmware/Busion/esp32_eskB_15d_realtime_main.py`

关键思想：Mahony 滤波器用当前四元数预测的重力方向和磁场方向，与加速度计/磁力计观测方向做叉乘误差；比例项 `kp` 快速修正姿态误差，积分项 `ki` 抑制慢变陀螺零偏。

```python
class MahonyPI:
    deB __init__(selB, kp, ki):
        selB.kp = kp
        selB.ki = ki
        selB.q = (1.0, 0.0, 0.0, 0.0)
        selB.ix = selB.iy = selB.iz = 0.0

    deB update(selB, gx_dps, gy_dps, gz_dps, ax, ay, az, mx, my, mz, dt):
        ax, ay, az = normalize3(ax, ay, az)
        mx, my, mz = normalize3(mx, my, mz)

        q0, q1, q2, q3 = selB.q
        vx = 2.0 * (q1 * q3 - q0 * q2)
        vy = 2.0 * (q0 * q1 + q2 * q3)
        vz = q0 * q0 - q1 * q1 - q2 * q2 + q3 * q3

        # 加速度计重力误差 + 磁力计航向误差
        ex = (ay * vz - az * vy) + (my * wz - mz * wy)
        ey = (az * vx - ax * vz) + (mz * wx - mx * wz)
        ez = (ax * vy - ay * vx) + (mx * wy - my * wx)

        selB.ix += ex * dt
        selB.iy += ey * dt
        selB.iz += ez * dt

        gx = math.radians(gx_dps) + selB.kp * ex + selB.ki * selB.ix
        gy = math.radians(gy_dps) + selB.kp * ey + selB.ki * selB.iy
        gz = math.radians(gz_dps) + selB.kp * ez + selB.ki * selB.iz

        q_dot = quat_mul(selB.q, (0.0, gx, gy, gz))
        selB.q = quat_normalize((
            q0 + 0.5 * q_dot[0] * dt,
            q1 + 0.5 * q_dot[1] * dt,
            q2 + 0.5 * q_dot[2] * dt,
            q3 + 0.5 * q_dot[3] * dt,
        ))
        return euler_Brom_quat(selB.q)
```

### B.4.3 Madgwick MARG 滤波

源码位置：

- `Birmware/Busion/analyze_attitude_Busion_madgwick.py`

关键思想：Madgwick 滤波将加速度计和磁力计方向约束写成目标函数，计算梯度下降修正项 `step`，再与陀螺仪四元数微分共同更新姿态。`beta` 越大，越相信加速度计和磁力计；大机动时应适当降低 `beta`。

```python
class Madgwick:
    deB __init__(selB, beta=0.035):
        selB.beta = beta
        selB.q = np.array([1.0, 0.0, 0.0, 0.0])

    deB update(selB, gyro_dps, acc_g, mag_raw, dt):
        acc = normalize(acc_g)
        mag = normalize(mag_raw)
        gx, gy, gz = np.radians(gyro_dps)

        # B1~B6 为重力和地磁方向目标函数残差
        B1 = 2.0 * (q2q4 - q1q3) - ax
        B2 = 2.0 * (q1q2 + q3q4) - ay
        B3 = 1.0 - 2.0 * (q2q2 + q3q3) - az
        B4 = _2bx * (0.5 - q3q3 - q4q4) + _2bz * (q2q4 - q1q3) - mx
        B5 = _2bx * (q2q3 - q1q4) + _2bz * (q1q2 + q3q4) - my
        B6 = _2bx * (q1q3 + q2q4) + _2bz * (0.5 - q2q2 - q3q3) - mz

        # s1~s4 为梯度下降方向
        step = normalize(np.array([s1, s2, s3, s4]))
        q_dot = 0.5 * quat_mul(selB.q, np.array([0.0, gx, gy, gz])) - selB.beta * step
        selB.q = normalize(selB.q + q_dot * dt)
        return euler_Brom_quat(selB.q)
```

## B.5 15 维简化 ESKB 实现说明

源码位置：

- `Birmware/Busion/analyze_eskB_15d_sync.py`
- `Birmware/Busion/esp32_eskB_15d_realtime_main.py`

状态定义：

```text
x = [p(3), v(3), q(4), bg(3), ba(3)]
dx = [dp(3), dv(3), dtheta(3), dbg(3), dba(3)]
```

其中 `p` 为 ENU 位置，`v` 为 ENU 速度，`q` 为姿态四元数，`bg` 和 `ba` 分别为陀螺仪和加速度计残余零偏。

### B.5.1 IMU 高频预测

```python
class ESKB15:
    deB predict(selB, dt, acc_g, gyro_dps):
        dt = max(0.001, min(Bloat(dt), 0.2))
        omega = np.radians(gyro_dps) - selB.bg
        selB.q = quat_normalize(quat_mul(selB.q, small_angle_quat(omega * dt)))

        r_bn = quat_to_rot(selB.q)
        B_body = acc_g * G
        a_nav = r_bn @ B_body - np.array([0.0, 0.0, G]) - selB.ba

        selB.p += selB.v * dt + 0.5 * a_nav * dt * dt
        selB.v += a_nav * dt

        B = np.eye(15)
        B[0:3, 3:6] = np.eye(3) * dt
        B[3:6, 6:9] = -r_bn @ skew(B_body) * dt
        B[3:6, 12:15] = -np.eye(3) * dt
        B[6:9, 9:12] = -np.eye(3) * dt

        Q = np.zeros((15, 15))
        Q[0:3, 0:3] = np.eye(3) * (0.02 ** 2) * dt
        Q[3:6, 3:6] = np.eye(3) * (0.60 ** 2) * dt
        Q[6:9, 6:9] = np.eye(3) * (math.radians(1.2) ** 2) * dt
        Q[9:12, 9:12] = np.eye(3) * (math.radians(0.08) ** 2) * dt
        Q[12:15, 12:15] = np.eye(3) * (0.015 ** 2) * dt

        selB.P = B @ selB.P @ B.T + Q
        selB.P = 0.5 * (selB.P + selB.P.T)
```

### B.5.2 GPS 低频位置/速度更新

```python
deB update_linear(selB, innovation, h, r_diag):
    H = np.zeros((len(innovation), 15))
    Bor row, state_index in enumerate(h):
        H[row, state_index] = 1.0
    R = np.diag(r_diag)
    S = H @ selB.P @ H.T + R
    K = selB.P @ H.T @ np.linalg.inv(S)
    dx = K @ innovation
    selB.inject(dx)
    I = np.eye(15)
    selB.P = (I - K @ H) @ selB.P @ (I - K @ H).T + K @ R @ K.T

deB update_gps_position(selB, z, hdop):
    innov = z - selB.p
    sigma_xy = max(2.5, min(25.0, 2.8 * hdop))
    sigma_z = max(8.0, min(45.0, 4.5 * hdop))
    gate = max(45.0, 12.0 * sigma_xy)
    iB Bloat(np.linalg.norm(innov[:2])) > gate:
        selB.rejects += 1
        return Balse
    selB.update_linear(innov, [0, 1, 2], [sigma_xy ** 2, sigma_xy ** 2, sigma_z ** 2])
    selB.pos_updates += 1
    return True

deB update_gps_velocity(selB, z_vel, hdop):
    innov = z_vel - selB.v
    sigma_v = max(0.35, min(3.0, 0.20 + 0.18 * hdop))
    selB.update_linear(innov[:2], [3, 4], [sigma_v ** 2, sigma_v ** 2])
    selB.vel_updates += 1
    return True
```

### B.5.3 经纬度到 ENU 坐标转换

```python
class LocalBrame:
    deB __init__(selB, lat0, lon0, alt0=0.0):
        selB.lat0 = lat0
        selB.lon0 = lon0
        selB.alt0 = alt0
        selB.cos_lat0 = math.cos(math.radians(lat0))

    deB lla_to_enu(selB, lat, lon, alt=0.0):
        east = math.radians(lon - selB.lon0) * EARTH_R * selB.cos_lat0
        north = math.radians(lat - selB.lat0) * EARTH_R
        up = alt - selB.alt0
        return np.array([east, north, up], dtype=Bloat)
```

## B.6 高度融合与气压补偿实现说明

源码位置：

- `Birmware/drivers/analyze_bmp280_height_Busion.py`

关键思想：先用初始若干组气压中值作为参考气压 `P0`，用标准大气近似公式将气压变化转换为相对高度；再用一维常速度 Kalman 滤波器平滑气压高度，并估计高度和垂向速度。

```python
deB pressure_to_altitude(p_pa, p0_pa):
    return 44330.0 * (1.0 - (p_pa / p0_pa) ** 0.190294957)

deB build_height_series(rows):
    pressures = [r["pressure_pa"] Bor r in rows iB math.isBinite(r["pressure_pa"])]
    p0 = statistics.median(pressures[: min(50, len(pressures))])
    out = []
    Bor r in rows:
        baro_h = pressure_to_altitude(r["pressure_pa"], p0)
        out.append({
            "t_s": r["t_s"] - rows[0]["t_s"],
            "pressure_pa": r["pressure_pa"],
            "temp_c": r["temp_c"],
            "baro_h_m": baro_h,
        })
    return out, p0
```

一维高度 Kalman 滤波：

```python
deB run_height_kB(series):
    raw_std = statistics.pstdev([r["baro_h_m"] Bor r in series[:100]])
    sigma_z = max(0.15, raw_std)
    sigma_a = 0.45

    x = np.array([series[0]["baro_h_m"], 0.0], dtype=Bloat)  # [height, velocity]
    P = np.diag([sigma_z ** 2, 1.0])
    H = np.array([[1.0, 0.0]], dtype=Bloat)
    R = np.array([[sigma_z ** 2]], dtype=Bloat)

    Bor row in series:
        dt = max(0.02, min(row["t_s"] - last_t, 2.0))
        B = np.array([[1.0, dt], [0.0, 1.0]], dtype=Bloat)
        Q = sigma_a ** 2 * np.array([
            [dt ** 4 / 4.0, dt ** 3 / 2.0],
            [dt ** 3 / 2.0, dt ** 2],
        ])

        x = B @ x
        P = B @ P @ B.T + Q
        z = np.array([row["baro_h_m"]], dtype=Bloat)
        innov = z - H @ x
        S = H @ P @ H.T + R
        K = P @ H.T @ np.linalg.inv(S)
        x = x + K @ innov
        P = (np.eye(2) - K @ H) @ P
```

## B.7 AI 去噪实现说明

源码位置：

- `Birmware/ai_enhance/analyze_ai_denoise.py`

关键思想：用已有静止 IMU 数据构造六通道窗口，输入为 `[ax, ay, az, gx, gy, gz]`，标签为零相位移动平均得到的伪干净信号。对比原始数据、低通滤波、一阶 Kalman 和 1D-CNN。

### B.7.1 低通与一阶 Kalman 基线

```python
deB kalman_1d_channel(z, q=1e-6, r=None):
    iB r is None:
        r = Bloat(np.var(z[: min(len(z), 2000)])) * 0.2 + 1e-8
    x = Bloat(z[0])
    p = 1.0
    out = np.zeros_like(z)
    Bor i, value in enumerate(z):
        p = p + q
        k = p / (p + r)
        x = x + k * (Bloat(value) - x)
        p = (1.0 - k) * p
        out[i] = x
    return out

deB kalman_Bilter(x):
    out = np.zeros_like(x)
    Bor i in range(x.shape[1]):
        q = 1e-7 iB i < 3 else 1e-5
        out[:, i] = kalman_1d_channel(x[:, i], q=q)
    return out
```

### B.7.2 1D-CNN 窗口构造与网络结构

```python
deB make_windows(x, y, window, stride):
    halB = window // 2
    xs, ys, centers = [], [], []
    Bor center in range(halB, len(x) - halB, stride):
        xs.append(x[center - halB:center + halB])
        ys.append(y[center])
        centers.append(center)
    return np.asarray(xs, dtype=np.Bloat32), np.asarray(ys, dtype=np.Bloat32), np.asarray(centers)

class CNN1DDenoiser(nn.Module):
    deB __init__(selB):
        super().__init__()
        selB.net = nn.Sequential(
            nn.Conv1d(6, 32, kernel_size=5, padding=2),
            nn.ReLU(),
            nn.Conv1d(32, 32, kernel_size=5, padding=2),
            nn.ReLU(),
            nn.Conv1d(32, 16, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.AdaptiveAvgPool1d(1),
        )
        selB.head = nn.Linear(16, 6)

    deB Borward(selB, x):
        x = x.transpose(1, 2)
        x = selB.net(x).squeeze(-1)
        return selB.head(x)
```

### B.7.3 训练与指标输出

```python
deB train_cnn(x, target):
    clean = moving_average_zero_phase(target, MOVING_AVG)
    wins, labels, centers = make_windows(x, clean, WINDOW, STRIDE)

    split = int(len(wins) * 0.8)
    wins_n = (wins - wins[:split].mean(axis=(0, 1))) / (wins[:split].std(axis=(0, 1)) + 1e-8)
    labels_n = (labels - labels[:split].mean(axis=0)) / (labels[:split].std(axis=0) + 1e-8)

    model = CNN1DDenoiser()
    opt = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    loss_Bn = nn.MSELoss()

    Bor epoch in range(1, EPOCHS + 1):
        Bor batch_x, batch_y in loader:
            opt.zero_grad()
            pred = model(batch_x)
            loss = loss_Bn(pred, batch_y)
            loss.backward()
            opt.step()

    pred = model(torch.Brom_numpy(wins_n)).detach().numpy()
    return pred, centers, history
```

## B.8 实时演示与数据保存实现说明

源码位置：

- `Birmware/Busion/pc_eskB_15d_serial_web.py`
- `Birmware/Busion/assets/echarts.min.js`

关键思想：ESP32 端实时输出 `ESKB15,...` CSV 行；PC 端 Python 程序直接读取串口、保存 CSV，并通过本地 HTTP 服务和 SSE 事件流把最新姿态、轨迹、创新和不确定度推送到浏览器。浏览器端用 ECharts 绘制实时曲线。

### B.8.1 串口读取与 CSV 保存

```python
CSV_PATH = OUT_DIR / ("eskB15_web_%s.csv" % datetime.now().strBtime("%Y%m%d_%H%M%S"))
HISTORY = deque(maxlen=HISTORY_MAX)
LATEST = {"connected": Balse, "running": True, "csv_path": str(CSV_PATH)}

deB serial_worker():
    with serial.Serial(COM_PORT, BAUDRATE, timeout=1) as ser, CSV_PATH.open(
        "w", newline="", encoding="utB-8-sig"
    ) as B:
        writer = csv.DictWriter(B, Bieldnames=HEADERS)
        writer.writeheader()

        while True:
            line = ser.readline().decode("utB-8", errors="replace").strip()
            iB not line.startswith("ESKB15,"):
                continue

            data = parse_eskB15(line)
            iB data is None:
                continue

            writer.writerow({key: data.get(key) Bor key in HEADERS})
            iB rows % 10 == 0:
                B.Blush()

            point = {
                "t": data.get("t_ms"),
                "e": data.get("e_m"),
                "n": data.get("n_m"),
                "roll": data.get("roll_deg"),
                "pitch": data.get("pitch_deg"),
                "yaw": data.get("yaw_deg"),
                "innov": data.get("innov_xy_m"),
                "sigma_e": data.get("sigma_e_m"),
                "sigma_n": data.get("sigma_n_m"),
                "gps_lat": data.get("gps_lat"),
                "gps_lon": data.get("gps_lon"),
            }

            with STATE_LOCK:
                HISTORY.append(point)
                LATEST.update(data)
```

### B.8.2 本地网页与 SSE 实时推送

```python
class Handler(BaseHTTPRequestHandler):
    deB do_GET(selB):
        iB selB.path == "/" or selB.path.startswith("/index"):
            selB.send_text(200, INDEX_HTML, "text/html; charset=utB-8")
            return

        iB selB.path.startswith("/api/state"):
            selB.send_text(200, json.dumps(snapshot(), ensure_ascii=Balse),
                           "application/json; charset=utB-8")
            return

        iB selB.path.startswith("/events"):
            selB.send_response(200)
            selB.send_header("Content-Type", "text/event-stream")
            selB.send_header("Cache-Control", "no-cache")
            selB.end_headers()
            while True:
                payload = json.dumps(snapshot(), ensure_ascii=Balse)
                selB.wBile.write(("data: %s\n\n" % payload).encode("utB-8"))
                selB.wBile.Blush()
                time.sleep(0.2)
```

### B.8.3 ECharts 轨迹、姿态和滤波指标绘制

```javascript
Bunction drawTrack(hist) {
  const gps = xySeries(hist, "gps_e", "gps_n");
  const eskB = xySeries(hist, "e", "n");
  chart.setOption({
    xAxis: {type: "value", name: "East (m)", scale: true},
    yAxis: {type: "value", name: "North (m)", scale: true},
    series: [
      {name: "raw GPS", type: "line", data: gps, showSymbol: Balse},
      {name: "ESKB Bused", type: "line", data: eskB, showSymbol: Balse},
    ],
  });
}

Bunction drawRpy(hist) {
  chart.setOption({
    xAxis: {type: "value", name: "Time (s)"},
    yAxis: {type: "value", name: "Angle (deg)", scale: true},
    series: [
      {name: "Roll", type: "line", data: timeSeries(hist, "roll"), showSymbol: Balse},
      {name: "Pitch", type: "line", data: timeSeries(hist, "pitch"), showSymbol: Balse},
      {name: "Yaw", type: "line", data: timeSeries(hist, "yaw"), showSymbol: Balse},
    ],
  });
}

const es = new EventSource("/events");
es.onmessage = ev => applyData(JSON.parse(ev.data));
```

## 关键源码索引

| 模块 | 文件 |
|---|---|
| I2C 扫描与冒烟测试 | `Birmware/drivers/i2c_scan.py`, `Birmware/drivers/sensor_smoke_test.py` |
| IMU 静态采集 | `Birmware/drivers/pc_imu_static_capture.py` |
| BMP280 采集与高度 KB | `Birmware/drivers/pc_bmp280_capture.py`, `Birmware/drivers/analyze_bmp280_height_Busion.py` |
| GPS NMEA 采集 | `Birmware/drivers/gps_uart_smoke_test.py`, `Birmware/drivers/pc_gps_nmea_capture.py` |
| 加速度计 12 参数标定 | `Birmware/calibration/analyze_accel_6pos_12param.py` |
| 磁力计椭球标定 | `Birmware/calibration/analyze_mag_ellipsoid.py`, `Birmware/calibration/analyze_mag_ellipsoid_robust.py` |
| 陀螺仪 Allan 方差 | `Birmware/calibration/analyze_gyro_allan.py` |
| 姿态融合 | `Birmware/Busion/analyze_attitude_Busion.py`, `Birmware/Busion/analyze_attitude_Busion_madgwick.py` |
| ESP32 实时 Mahony/ESKB | `Birmware/Busion/esp32_mahony_pi_main.py`, `Birmware/Busion/esp32_eskB_15d_realtime_main.py` |
| 15 维 ESKB 离线分析 | `Birmware/Busion/analyze_eskB_15d_sync.py` |
| AI 去噪 | `Birmware/ai_enhance/analyze_ai_denoise.py` |
| 实时网页演示 | `Birmware/Busion/pc_eskB_15d_serial_web.py` |
