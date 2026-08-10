import time
import math
import serial
import threading
import zmq
from pydantic import ValidationError

import sys
import os
# Add the project root to sys.path to resolve 'src' when running directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# System imports
from src.core.models import ImuMessage, SensorStatusMessage, SensorStatus
from src.core.messaging import Topics, get_zmq_url
from loguru import logger


class WT901Driver:
    def __init__(self, serial_port="/dev/serial0", baud_rate=9600, on_data_callback=None):
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        self.ser = None
        self.running = False
        self.thread = None
        
        # This callback is executed when a 0x53 (Angles) frame arrives
        self.on_data_callback = on_data_callback
        self._error_logged = False  # Suppress repeated read-error log spam

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
                    self._error_logged = False  # Clear on successful read

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
                if not self._error_logged:
                    logger.warning(f"[WT901] Read error: {e}")
                    self._error_logged = True
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
            
            # Since 0x53 is usually the last packet in the 51-52-53-54 burst
            # we trigger the callback to push the full dictionary upwards.
            if self.on_data_callback:
                self.on_data_callback(self.data)

        elif pid == 0x54:  # Magnetometer
            mx = self._to_int16(payload[0], payload[1])
            my = self._to_int16(payload[2], payload[3])
            mz = self._to_int16(payload[4], payload[5])
            self.data.update({"mx": mx, "my": my, "mz": mz})


class ImuNode:
    _RETRY_INTERVAL = 5.0
    _STATUS_TIMEOUT = 5.0
    _STATUS_PUBLISH_INTERVAL = 5.0  # Publish status every 5 seconds for health heartbeat

    def __init__(self, serial_port="/dev/serial0", baud_rate=9600, mag_declination=0.0, user_offset=0.0):
        """
        Connects the WT901 IMU to the internal ZMQ data bus.

        Declination and user offset default to zero because Navigation applies
        them from OffsetsConfig; they only exist for standalone CLI use.
        """
        self.mag_declination = mag_declination
        self.user_offset = user_offset
        self._serial_port = serial_port
        self._baud_rate = baud_rate

        # Connection status tracking
        self._connected = False
        self._last_data_time = 0.0
        self._last_status_publish_time = 0.0
        
        # QGC / MAVLink NED body frame mapping (copied from old parser)
        self.QGC_AXIS_MAP = {
            "mx_sign": 1,      # magnetometer X
            "my_sign": 1,      # magnetometer Y
            "mz_sign": 1       # magnetometer Z
        }

        # ZMQ Context & Socket Setup
        self.context = zmq.Context()
        self.pub_socket = self.context.socket(zmq.PUB)
        
        bus_url = get_zmq_url() # Gets the central IPC/TCP URL
        self.pub_socket.connect(bus_url)
        logger.info(f"[IMU Node] Publisher connected to ZMQ Bus: {bus_url}")

        # Instantiate Driver and register callback
        self._muted = threading.Event()  # Thread-safe mute flag (set = muted)
        self.driver = WT901Driver(
            serial_port=serial_port, 
            baud_rate=baud_rate, 
            on_data_callback=self.publish_imu_data
        )

    @property
    def muted(self) -> bool:
        return self._muted.is_set()

    @muted.setter
    def muted(self, value: bool):
        if value:
            self._muted.set()
        else:
            self._muted.clear()

    def _publish_status(self, status: SensorStatus, message: str = ""):
        try:
            msg = SensorStatusMessage(
                timestamp=time.time(),
                sensor="imu",
                status=status,  # Pass enum directly, not .value
                message=message,
            )
            json_str = msg.model_dump_json()
            self.pub_socket.send_string(f"{Topics.SENSOR_STATUS.value} {json_str}")
            #logger.info(f"[IMU Node] Published status: {status.value} — {message}")
        except Exception as e:
            logger.error(f"[IMU Node] Failed to publish status: {e}", exc_info=True)

    def calculate_mag_heading(self, mx, my):
        """
        Returns magnetic compass heading [0,360) degrees from raw mag values, 
        applying declination and user offset.
        """
        mx_mapped = mx * self.QGC_AXIS_MAP.get("mx_sign", 1)
        my_mapped = my * self.QGC_AXIS_MAP.get("my_sign", 1)
        
        # WT901C-TTL: heading = atan2(my, mx) (sensor X forward, Y right)
        heading_rad = math.atan2(my_mapped, mx_mapped)
        heading_deg = math.degrees(heading_rad)
        
        # Normalize to [0,360)
        heading_deg = (heading_deg + 360.0) % 360.0
        
        # Apply declination and user offset
        heading_deg = (heading_deg + self.mag_declination + self.user_offset) % 360.0
        return heading_deg

    def publish_imu_data(self, raw_data_dict):
        """
        Driver invokes this every time an 'Angles (0x53)' frame is fully parsed.
        """
        if self.muted:
            return  # RT simulation active, skip real sensor publishing
        ts = time.time()
        self._last_data_time = ts
        if not self._connected:
            self._connected = True
            logger.info("[IMU Node] First data received - publishing OK status")
            self._publish_status(SensorStatus.OK, "Receiving data")
        
        # Calculate heading
        m_heading = self.calculate_mag_heading(raw_data_dict["mx"], raw_data_dict["my"])

        try:
            # Map into Pydantic Model
            msg = ImuMessage(
                timestamp=ts,
                roll_raw=raw_data_dict["roll"],
                pitch_raw=raw_data_dict["pitch"],
                yaw_raw=raw_data_dict["yaw"],
                ax_raw=raw_data_dict["ax"],
                ay_raw=raw_data_dict["ay"],
                az_raw=raw_data_dict["az"],
                wx_raw=raw_data_dict["wx"],
                wy_raw=raw_data_dict["wy"],
                wz_raw=raw_data_dict["wz"],
                mx_raw=raw_data_dict["mx"],
                my_raw=raw_data_dict["my"],
                mz_raw=raw_data_dict["mz"],
                temp=raw_data_dict["temp"],
                mag_heading_raw=m_heading
            )
            
            # Serialize
            json_str = msg.model_dump_json()
            
            # Publish!
            # Format: 'topic payload'
            self.pub_socket.send_string(f"{Topics.SENSOR_IMU.value} {json_str}")
            
        except ValidationError as e:
            logger.warning(f"[IMU Node] Data validation error dropping frame: {e}")

    def run(self):
        logger.info("[IMU Node] Starting (with auto-retry)...")
        _start_error_logged = False
        while True:
            # Try to start the driver
            try:
                self.driver.start()
                _start_error_logged = False
                self._connected = False  # Will become True when first data arrives
                self._last_data_time = time.time()
                logger.info(f"[IMU Node] Driver started on {self._serial_port}, waiting for data...")
            except Exception as e:
                self._connected = False
                self._publish_status(SensorStatus.DISCONNECTED, str(e))
                if not _start_error_logged:
                    logger.error(f"[IMU Node] Cannot open {self._serial_port}: {e}. Retrying in {self._RETRY_INTERVAL}s...")
                    _start_error_logged = True
                time.sleep(self._RETRY_INTERVAL)
                # Recreate driver for next attempt
                self.driver = WT901Driver(
                    serial_port=self._serial_port,
                    baud_rate=self._baud_rate,
                    on_data_callback=self.publish_imu_data,
                )
                continue

            # Main loop — monitor health
            try:
                while True:
                    # Periodic status heartbeat (5 seconds)
                    now = time.time()
                    if now - self._last_status_publish_time > self._STATUS_PUBLISH_INTERVAL:
                        if self._connected:
                            self._publish_status(SensorStatus.OK, "Receiving data")
                        else:
                            # Serial port is open but no frames are arriving — this
                            # is an ERROR (cable/wiring/sensor fault), not a
                            # DISCONNECT (which means the bus is unavailable).
                            self._publish_status(SensorStatus.ERROR, "No data from IMU sensor")
                        self._last_status_publish_time = now

                    # Check for data timeout — break to trigger reconnect
                    if self._connected and self._last_data_time > 0:
                        if time.time() - self._last_data_time > self._STATUS_TIMEOUT:
                            self._connected = False
                            self._publish_status(SensorStatus.ERROR, "No data received from IMU (timeout)")
                            logger.warning("[IMU Node] No data timeout — reconnecting...")
                            break
                    time.sleep(0.5)
            except KeyboardInterrupt:
                logger.info("[IMU Node] Keyboard interrupt")
                self.shutdown()
                return
            except Exception as e:
                logger.error(f"[IMU Node] Unexpected error: {e}")
                self._connected = False
                self._publish_status(SensorStatus.ERROR, str(e))

            # Clean up before retry
            self.driver.stop()
            logger.info(f"[IMU Node] Reconnecting in {self._RETRY_INTERVAL}s...")
            time.sleep(self._RETRY_INTERVAL)
            self.driver = WT901Driver(
                serial_port=self._serial_port,
                baud_rate=self._baud_rate,
                on_data_callback=self.publish_imu_data,
            )

    def shutdown(self):
        self.driver.stop()
        self.pub_socket.close()
        self.context.term()
        logger.info("[IMU Node] Shutdown complete.")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description="WT901 IMU Driver - standalone test or ZMQ node")
    parser.add_argument("--mode", choices=["test", "node"], default="test",
                        help="'test' = standalone serial read (no ZMQ), 'node' = full ZMQ publisher")
    parser.add_argument("--port", default="/dev/serial0", help="Serial port (default: /dev/serial0)")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate (default: 9600)")
    parser.add_argument("--declination", type=float, default=2.5, help="Magnetic declination in degrees")
    args = parser.parse_args()

    if args.mode == "node":
        # Full ZMQ publisher mode
        node = ImuNode(serial_port=args.port, baud_rate=args.baud, mag_declination=args.declination)
        node.run()
    else:
        # Standalone test - read and print sensor data (no ZMQ needed)
        received_count = [0]

        def on_data(data):
            received_count[0] += 1
            print(
                f"Accel: {data['ax']:7.2f}, {data['ay']:7.2f}, {data['az']:7.2f} | "
                f"Angles: {data['roll']:7.2f}, {data['pitch']:7.2f}, {data['yaw']:7.2f} | "
                f"Gyro: {data['wx']:7.2f}, {data['wy']:7.2f}, {data['wz']:7.2f} | "
                f"Mag: {data['mx']:6.0f}, {data['my']:6.0f}, {data['mz']:6.0f} | "
                f"Temp: {data['temp']:.2f} °C"
            )

        driver = WT901Driver(args.port, baud_rate=args.baud, on_data_callback=on_data)
        driver.start()
        print(f"[TEST] WT901 driver started on {args.port} @ {args.baud} baud")
        print("[TEST] Waiting for data (Ctrl+C to stop)...\n")

        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            pass

        driver.stop()
        print(f"\n[TEST] Stopped. Total frames received: {received_count[0]}")
