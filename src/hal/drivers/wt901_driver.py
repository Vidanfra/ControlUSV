import serial
import threading
import time
import math

class WT901Driver:
    def __init__(self, serial_port="/dev/serial0", baud_rate=9600, on_data_callback=None):
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        self.ser = None
        self.running = False
        self.thread = None
        
        # This callback is executed when a 0x53 (Angles) frame arrives
        self.on_data_callback = on_data_callback

        # Shared sensor data accumulator
        self.data = {
            "ax": 0.0, "ay": 0.0, "az": 0.0,    
            "wx": 0.0, "wy": 0.0, "wz": 0.0,      
            "roll": 0.0, "pitch": 0.0, "yaw": 0.0,
            "mx": 0.0, "my": 0.0, "mz": 0.0,      
            "temp": 0.0                             
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

    def _to_uint16(self, lo, hi):
        return (hi << 8) | lo

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
                print(f"WT901 Driver read error: {e}")
                time.sleep(0.1)

    def _parse_frame(self, pid, payload):
        def parse_temp_from_bytes(lo, hi):
            raw = self._to_uint16(lo, hi)
            return raw / 100.0, raw

        if pid == 0x51:  # Acceleration
            ax = self._to_int16(payload[0], payload[1]) / 32768.0 * 16 * 9.8
            ay = self._to_int16(payload[2], payload[3]) / 32768.0 * 16 * 9.8
            az = self._to_int16(payload[4], payload[5]) / 32768.0 * 16 * 9.8

            temp_c, temp_raw = parse_temp_from_bytes(payload[6], payload[7])

            if -40.0 <= temp_c <= 85.0:
                self.data.update({"ax": ax, "ay": ay, "az": az, "temp": temp_c})
            else:
                self.data.update({"ax": ax, "ay": ay, "az": az})

        elif pid == 0x52:  # Angular velocity
            wx = self._to_int16(payload[0], payload[1]) / 32768.0 * 2000
            wy = self._to_int16(payload[2], payload[3]) / 32768.0 * 2000
            wz = self._to_int16(payload[4], payload[5]) / 32768.0 * 2000

            temp_c, temp_raw = parse_temp_from_bytes(payload[6], payload[7])

            if -40.0 <= temp_c <= 85.0:
                self.data.update({"wx": wx, "wy": wy, "wz": wz, "temp": temp_c})
            else:
                self.data.update({"wx": wx, "wy": wy, "wz": wz})

        elif pid == 0x53:  # Angles
            roll = self._to_int16(payload[0], payload[1]) / 32768.0 * 180
            pitch = self._to_int16(payload[2], payload[3]) / 32768.0 * 180
            yaw = self._to_int16(payload[4], payload[5]) / 32768.0 * 180
            self.data.update({"roll": roll, "pitch": pitch, "yaw": yaw})
            
            # Since 0x53 is usually the last packet in the 51-52-53-54 burst (or at least marks a successful attitude calc)
            # we trigger the callback to push the full dictionary upwards.
            if self.on_data_callback:
                self.on_data_callback(self.data)

        elif pid == 0x54:  # Magnetometer
            mx = self._to_int16(payload[0], payload[1])
            my = self._to_int16(payload[2], payload[3])
            mz = self._to_int16(payload[4], payload[5])
            self.data.update({"mx": mx, "my": my, "mz": mz})
