'''
imu_parser.py
Parse data from a the IMU sensor WT901C-TTL from Witmotion connected via serial (UART) (internal IMU sensor MPU9250).
'''
import serial
import threading
import time
import math

STALE_TIMEOUT = 0.5  # seconds: consider data stale after this

class IMUParser:
    def __init__(self, serial_port="/dev/serial0", baud_rate=9600, mag_declination=0.0, user_offset=0.0):
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        self.ser = None
        self.running = False
        self.thread = None
        self.lock = threading.Lock()

        # Compass setup
        self.mag_declination = mag_declination  # degrees
        self.user_offset = user_offset          # degrees

        # Shared sensor data
        self.data = {
            "ax": None, "ay": None, "az": None,      # m/s^2
            "wx": None, "wy": None, "wz": None,      # deg/s
            "roll": None, "pitch": None, "yaw": None,# deg
            "mx": None, "my": None, "mz": None,      # raw mag
            "temp": None                             # °C
        }

        # Track last update time per type
        self._last_update = {
            "accel": 0.0,
            "gyro": 0.0,
            "angles": 0.0,
            "mag": 0.0,
            "temp": 0.0
        }

        # For QGC / MAVLink NED body frame
        self.QGC_AXIS_MAP = {
            "roll_sign": -1,   # invert roll
            "pitch_sign": -1,  # invert pitch
            "yaw_sign": -1,    # invert yaw
            "ax_sign": 1,      # accelerometer X
            "ay_sign": 1,      # accelerometer Y
            "az_sign": 1,      # accelerometer Z
            "gx_sign": -1,     # gyro X
            "gy_sign": -1,     # gyro Y
            "gz_sign": 1,      # gyro Z
            "mx_sign": 1,      # magnetometer X
            "my_sign": 1,      # magnetometer Y
            "mz_sign": 1       # magnetometer Z
        }

    def start(self):
        self.ser = serial.Serial(self.serial_port, self.baud_rate, timeout=1)
        self.running = True
        self.thread = threading.Thread(target=self._read_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()
        if self.ser:
            self.ser.close()

    def _to_int16(self, lo, hi):
        val = (hi << 8) | lo
        return val - 0x10000 if val & 0x8000 else val

    def _checksum_ok(self, frame):
        return (sum(frame[:-1]) & 0xFF) == frame[-1]

    def _read_loop(self):
        buf = bytearray()
        while self.running:
            try:
                data = self.ser.read(self.ser.in_waiting or 1)
                if data:
                    buf.extend(data)

                # Process frames
                while len(buf) >= 11:
                    # Find header
                    try:
                        idx = buf.index(0x55)
                    except ValueError:
                        buf.clear()
                        break

                    if idx + 11 > len(buf):
                        break  # wait for full frame

                    frame = buf[idx:idx+11]
                    buf = buf[idx+11:]  # consume frame

                    if not self._checksum_ok(frame):
                        continue

                    pid = frame[1]
                    self._parse_frame(pid, frame[2:10])
            except Exception as e:
                print(f"IMU read error: {e}")
                time.sleep(0.1)

    def _to_uint16(self, lo, hi):
        """Combine two bytes (low, high) into unsigned 16-bit integer."""
        return (hi << 8) | lo

    def _parse_frame(self, pid, payload):
        ts = time.time()
        with self.lock:
            # helper: read temp unsigned, convert to °C
            def parse_temp_from_bytes(lo, hi):
                raw = self._to_uint16(lo, hi)          # unsigned raw
                return raw / 100.0, raw                # return (degC, raw) for logging

            if pid == 0x51:  # Acceleration
                ax = self._to_int16(payload[0], payload[1]) / 32768.0 * 16 * 9.8
                ay = self._to_int16(payload[2], payload[3]) / 32768.0 * 16 * 9.8
                az = self._to_int16(payload[4], payload[5]) / 32768.0 * 16 * 9.8

                temp_c, temp_raw = parse_temp_from_bytes(payload[6], payload[7])

                # sanity check for temp (adjust range if needed)
                if -40.0 <= temp_c <= 85.0:
                    self.data.update({"ax": ax, "ay": ay, "az": az, "temp": temp_c})
                    self._last_update["accel"] = ts
                    self._last_update["temp"] = ts
                else:
                    # log an anomaly and do NOT overwrite last good temp
                    print(f"[IMU WARN] accel packet: temp out-of-range {temp_c:.2f}C (raw={temp_raw}) - ignoring")

            elif pid == 0x52:  # Angular velocity
                wx = self._to_int16(payload[0], payload[1]) / 32768.0 * 2000
                wy = self._to_int16(payload[2], payload[3]) / 32768.0 * 2000
                wz = self._to_int16(payload[4], payload[5]) / 32768.0 * 2000

                temp_c, temp_raw = parse_temp_from_bytes(payload[6], payload[7])

                if -40.0 <= temp_c <= 85.0:
                    self.data.update({"wx": wx, "wy": wy, "wz": wz, "temp": temp_c})
                    self._last_update["gyro"] = ts
                    self._last_update["temp"] = ts
                else:
                    print(f"[IMU WARN] gyro packet: temp out-of-range {temp_c:.2f}C (raw={temp_raw}) - ignoring")
                    # we still update gyro values even if temp is bad:
                    self.data.update({"wx": wx, "wy": wy, "wz": wz})
                    self._last_update["gyro"] = ts

            elif pid == 0x53:  # Angles
                roll = self._to_int16(payload[0], payload[1]) / 32768.0 * 180
                pitch = self._to_int16(payload[2], payload[3]) / 32768.0 * 180
                yaw = self._to_int16(payload[4], payload[5]) / 32768.0 * 180
                self.data.update({"roll": roll, "pitch": pitch, "yaw": yaw})
                self._last_update["angles"] = ts

            elif pid == 0x54:  # Magnetometer
                mx = self._to_int16(payload[0], payload[1])
                my = self._to_int16(payload[2], payload[3])
                mz = self._to_int16(payload[4], payload[5])
                self.data.update({"mx": mx, "my": my, "mz": mz})
                self._last_update["mag"] = ts

    # === Public getters ===
    def get_accel(self, axis_map=None):
        with self.lock:
            if (time.time() - self._last_update["accel"]) > STALE_TIMEOUT:
                return None
            
            ax = self.data.get("ax")
            ay = self.data.get("ay")
            az = self.data.get("az")

            if ax is None or ay is None or az is None:
                return None

            if axis_map:
                ax *= axis_map.get("ax_sign", 1)
                ay *= axis_map.get("ay_sign", 1)
                az *= axis_map.get("az_sign", 1)

            return {"ax": ax, "ay": ay, "az": az}

    def get_gyro(self, axis_map=None):
        with self.lock:
            if (time.time() - self._last_update["gyro"]) > STALE_TIMEOUT:
                return None
            gx = self.data.get("wx")
            gy = self.data.get("wy")
            gz = self.data.get("wz")

            if gx is None or gy is None or gz is None:
                return None

            if axis_map:
                gx *= axis_map.get("gx_sign", 1)
                gy *= axis_map.get("gy_sign", 1)
                gz *= axis_map.get("gz_sign", 1)

            return {"gx": gx, "gy": gy, "gz": gz}

    def get_angles(self, axis_map=None):
        with self.lock:
            if (time.time() - self._last_update["angles"]) > STALE_TIMEOUT:
                return None
            roll = self.data.get("roll")
            pitch = self.data.get("pitch")
            yaw = self.data.get("yaw")
            
            if roll is None or pitch is None or yaw is None:
                return None

            if axis_map:
                roll *= axis_map.get("roll_sign", 1)
                pitch *= axis_map.get("pitch_sign", 1)
                yaw *= axis_map.get("yaw_sign", 1)

            return {"roll": roll, "pitch": pitch, "yaw": yaw}

    def get_mag(self, axis_map=None):
        with self.lock:
            if (time.time() - self._last_update["mag"]) > STALE_TIMEOUT:
                return None
            mx = self.data.get("mx")
            my = self.data.get("my")
            mz = self.data.get("mz")

            if mx is None or my is None or mz is None:
                return None
            
            if axis_map:
                mx *= axis_map.get("mx_sign", 1)
                my *= axis_map.get("my_sign", 1)
                mz *= axis_map.get("mz_sign", 1)

            return {"mx": mx, "my": my, "mz": mz}
    
    def get_mag_heading(self, axis_map=None):
        """
        Returns magnetic compass heading [0,360) degrees from raw mag values, applying declination and user offset.
        axis_map: optional dict to remap axes/signs (default: self.QGC_AXIS_MAP)
        """

        with self.lock:
            if (time.time() - self._last_update["mag"]) > STALE_TIMEOUT:
                return None
            mx = self.data.get("mx")
            my = self.data.get("my")
            mz = self.data.get("mz")
            if mx is None or my is None or mz is None:
                return None
            # Use axis_map if provided, else default
            amap = axis_map if axis_map else self.QGC_AXIS_MAP
            mx *= amap.get("mx_sign", 1)
            my *= amap.get("my_sign", 1)
            # WT901C-TTL: heading = atan2(my, mx) (sensor X forward, Y right)
            heading_rad = math.atan2(my, mx)
            heading_deg = math.degrees(heading_rad)
            # Normalize to [0,360)
            heading_deg = (heading_deg + 360.0) % 360.0
            # Apply declination and user offset
            heading_deg = (heading_deg + self.mag_declination + self.user_offset) % 360.0

            return heading_deg


    def get_temp(self):
        with self.lock:
            if (time.time() - max(self._last_update.get("temp", 0), self._last_update.get("gyro",0), self._last_update.get("accel",0))) > STALE_TIMEOUT:
                return None
            return self.data["temp"]
    
    def measure_update_frequency(self, packet_type="accel", sample_count=100):
        """
        Measures the update frequency (Hz) for a given packet type.
        packet_type: one of "accel", "gyro", "angles", "mag"
        sample_count: number of samples to average
        Returns: estimated frequency in Hz, or None if not enough samples.
        """
        timestamps = []
        last_time = None
        collected = 0

        while collected < sample_count:
            with self.lock:
                t = self._last_update.get(packet_type)
            if t != last_time and t != 0.0:
                timestamps.append(t)
                last_time = t
                collected += 1
            time.sleep(0.001)  # small delay to avoid busy wait

        if len(timestamps) < 2:
            return None
        intervals = [t2 - t1 for t1, t2 in zip(timestamps[:-1], timestamps[1:])]
        avg_interval = sum(intervals) / len(intervals)
        if avg_interval == 0:
            return None
        return 1.0 / avg_interval
        

# === Example usage ===
if __name__ == '__main__':
    IMU = IMUParser(serial_port="/dev/serial0", baud_rate=9600, mag_declination=2.5, user_offset=0.0)
    IMU.start()

    print("Measuring IMU accel update frequency...")
    freq = IMU.measure_update_frequency(packet_type="accel", sample_count=50) # Measured: 10,03 Hz
    print(f"Measured IMU accel frequency: {freq:.2f} Hz")
    time.sleep(2)

    try:
        while True:
            accel = IMU.get_accel()
            angles = IMU.get_angles()
            temp = IMU.get_temp()
            mag_heading = IMU.get_mag_heading()

            if accel and angles and temp and mag_heading is not None:
                print(f"Accel: {{ax:.2f}}, {{ay:.2f}}, {{az:.2f}} | Angles: {{roll:.2f}}, {{pitch:.2f}}, {{yaw:.2f}}, Temp: {{temp:.2f}} °C | Mag Heading: {{mag_heading:.2f}}°".format(
                    ax=accel['ax'], ay=accel['ay'], az=accel['az'],
                    roll=angles['roll'], pitch=angles['pitch'], yaw=angles['yaw'],
                    temp=temp, mag_heading=mag_heading
                ))
            time.sleep(0.05)
    except KeyboardInterrupt:
        IMU.stop()