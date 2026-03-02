"""
gnss_um982.py
UM982 Dual-Antenna GNSS driver for the USV pub/sub architecture.
Reads NMEA sentences (GGA, THS, VTG, ZDA) via serial, forwards RTCM
corrections from an NTRIP caster, and publishes GNSSData on the ZMQ bus.
"""
import socket
import base64
import serial
import threading
import time
import json
import zmq
import pynmea2
from pydantic import ValidationError
from loguru import logger

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.core.models import GNSSData, CommandType, SensorStatusMessage, SensorStatus
from src.core.messaging import Topics, get_zmq_url


class UM982Driver:
    """
    Low-level NMEA serial reader + NTRIP RTCM forwarder for the UM982 receiver.
    Parses GGA, THS, VTG, ZDA sentences and fires a callback with the latest data dict.
    """

    def __init__(
        self,
        serial_port: str = "/dev/gnss_um982",
        baud_rate: int = 115200,
        ntrip_caster: str = "",
        ntrip_port: int = 2101,
        mountpoint: str = "",
        username: str = "",
        password: str = "",
        command_freq: float = 1.0,
        timeout: float = 1.0,
        on_data_callback=None,
    ):
        self.serial_port_name = serial_port
        self.baud_rate = baud_rate
        self.timeout = timeout
        self.ntrip_caster = ntrip_caster
        self.ntrip_port = ntrip_port
        self.mountpoint = mountpoint
        self.username = username
        self.password = password
        self.command_freq = command_freq
        self.on_data_callback = on_data_callback

        self.ser = None
        self.ntrip_sock = None
        self.running = False
        self._reader_thread = None
        self._rtcm_thread = None

        # Accumulated parsed data (updated per-sentence, callback fired on GGA)
        self.data = {
            "lat": 0.0,
            "lon": 0.0,
            "alt": 0.0,
            "fix_type": 0,
            "num_satellites": 0,
            "hdop": 99.99,
            "vdop": 99.99,
            "heading": 0.0,
            "heading_status": "",
            "cog": 0.0,
            "sog_knots": 0.0,
            "sog_kmh": 0.0,
            "utc_time": "",
            "utc_date": "",
        }
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ start / stop
    def start(self):
        self.running = True
        try:
            self.ser = serial.Serial(
                self.serial_port_name, self.baud_rate, timeout=self.timeout
            )
            logger.info(f"[UM982] Serial opened: {self.serial_port_name} @ {self.baud_rate}")

            # Send stream commands to receiver
            self._send_stream_commands()
            time.sleep(0.5)

            # Connect NTRIP (optional)
            if self.ntrip_caster and self.mountpoint:
                try:
                    self.ntrip_sock = self._connect_ntrip()
                    logger.info("[UM982] NTRIP connected")
                    self._rtcm_thread = threading.Thread(target=self._rtcm_loop, daemon=True)
                    self._rtcm_thread.start()
                except Exception as e:
                    logger.warning(f"[UM982] NTRIP connection failed: {e}. Running without corrections.")
                    self.ntrip_sock = None

            self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
            self._reader_thread.start()

        except Exception as e:
            logger.error(f"[UM982] Start failed: {e}")
            self.stop()
            raise

    def stop(self):
        self.running = False
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except Exception:
            pass
        try:
            if self.ntrip_sock:
                self.ntrip_sock.close()
        except Exception:
            pass

    # ------------------------------------------------------------------ NTRIP
    def _connect_ntrip(self):
        credentials = base64.b64encode(
            f"{self.username}:{self.password}".encode()
        ).decode()
        request = (
            f"GET /{self.mountpoint} HTTP/1.0\r\n"
            f"User-Agent: NTRIP PythonClient/1.0\r\n"
            f"Authorization: Basic {credentials}\r\n"
            f"\r\n"
        )
        sock = socket.create_connection(
            (self.ntrip_caster, self.ntrip_port), timeout=10
        )
        sock.sendall(request.encode())
        # Read HTTP header until blank line
        header = b""
        while b"\r\n\r\n" not in header:
            chunk = sock.recv(1)
            if not chunk:
                raise ConnectionError("NTRIP: connection closed during header read")
            header += chunk
        return sock

    def _rtcm_loop(self):
        """Forward RTCM corrections from NTRIP caster to receiver serial port."""
        while self.running and self.ntrip_sock:
            try:
                data = self.ntrip_sock.recv(1024)
                if not data:
                    logger.warning("[UM982] NTRIP stream ended")
                    break
                if self.ser and self.ser.is_open:
                    self.ser.write(data)
            except Exception as e:
                logger.warning(f"[UM982] RTCM error: {e}")
                time.sleep(1)

    # ------------------------------------------------------------------ stream commands
    def _send_stream_commands(self):
        """Request NMEA sentence streams from the UM982 at the specified frequency."""
        freq = self.command_freq
        commands = [
            f"GPGGA {freq}",
            f"GPGSA {freq}",
            f"GPTHS {freq}",
            f"GPVTG {freq}",
            f"GPZDA {freq}",
        ]
        for cmd in commands:
            try:
                self.ser.write(f"{cmd}\r\n".encode())
                logger.debug(f"[UM982] Sent: {cmd}")
            except Exception as e:
                logger.warning(f"[UM982] Failed to send {cmd}: {e}")

    # ------------------------------------------------------------------ reader
    def _reader_loop(self):
        time.sleep(0.3)
        while self.running and self.ser and self.ser.is_open:
            try:
                raw = self.ser.readline()
                if not raw:
                    continue
                line = raw.decode(errors="ignore").strip()
                if line.startswith("$G"):
                    self._dispatch(line)
            except serial.SerialException as e:
                logger.error(f"[UM982] Serial error: {e}")
                time.sleep(1)
            except Exception as e:
                logger.warning(f"[UM982] Reader error: {e}")
                time.sleep(0.1)

    # ------------------------------------------------------------------ dispatch / parse
    def _dispatch(self, line: str):
        typ = line[3:6]
        if typ == "GGA":
            self._parse_gga(line)
            self._send_gga_to_ntrip(line)
            # GGA is the trigger sentence — fire callback
            if self.on_data_callback:
                with self._lock:
                    snapshot = dict(self.data)
                self.on_data_callback(snapshot)
        elif typ == "GSA":
            self._parse_gsa(line)
        elif typ == "THS":
            self._parse_ths(line)
        elif typ == "VTG":
            self._parse_vtg(line)
        elif typ == "ZDA":
            self._parse_zda(line)

    def _send_gga_to_ntrip(self, line: str):
        try:
            if self.ntrip_sock:
                self.ntrip_sock.sendall((line + "\r\n").encode())
        except Exception as e:
            logger.warning(f"[UM982] Failed to send GGA to NTRIP: {e}")

    def _parse_gga(self, line: str):
        try:
            msg = pynmea2.parse(line)
            with self._lock:
                self.data["lat"] = msg.latitude if msg.latitude else 0.0
                self.data["lon"] = msg.longitude if msg.longitude else 0.0
                self.data["alt"] = float(msg.altitude) if msg.altitude else 0.0
                self.data["fix_type"] = int(msg.gps_qual) if msg.gps_qual else 0
                self.data["num_satellites"] = int(msg.num_sats) if msg.num_sats else 0
                self.data["hdop"] = float(msg.horizontal_dil) if msg.horizontal_dil else 99.99
        except pynmea2.nmea.ParseError:
            logger.warning(f"[UM982] GGA parse error: {line}")
        except Exception as e:
            logger.warning(f"[UM982] GGA exception: {e}")

    def _parse_gsa(self, line: str):
        """Parse $GPGSA / $GNGSA — DOP and active satellites."""
        try:
            msg = pynmea2.parse(line)
            # GSA fields: pdop (index 15), hdop (16), vdop (17)
            pdop = getattr(msg, 'pdop', None)
            hdop = getattr(msg, 'hdop', None)
            vdop = getattr(msg, 'vdop', None)
            with self._lock:
                if vdop:
                    self.data["vdop"] = float(vdop)
                if hdop:
                    self.data["hdop"] = float(hdop)
        except pynmea2.nmea.ParseError:
            logger.warning(f"[UM982] GSA parse error: {line}")
        except Exception as e:
            logger.warning(f"[UM982] GSA exception: {e}")

    def _parse_ths(self, line: str):
        """Parse $GPTHS – True Heading and Status (UM982 dual-antenna)."""
        try:
            fields = line.split("*")[0].split(",")
            heading = float(fields[1]) if len(fields) > 1 and fields[1] else 0.0
            status = fields[2] if len(fields) > 2 else ""
            with self._lock:
                self.data["heading"] = heading
                self.data["heading_status"] = status
        except Exception:
            logger.warning(f"[UM982] THS parse error: {line}")

    def _parse_vtg(self, line: str):
        try:
            msg = pynmea2.parse(line)
            with self._lock:
                self.data["cog"] = float(msg.true_track) if msg.true_track else 0.0
                self.data["sog_knots"] = (
                    float(msg.spd_over_grnd_kts) if msg.spd_over_grnd_kts else 0.0
                )
                self.data["sog_kmh"] = (
                    float(msg.spd_over_grnd_kmph) if msg.spd_over_grnd_kmph else 0.0
                )
        except pynmea2.nmea.ParseError:
            logger.warning(f"[UM982] VTG parse error: {line}")
        except Exception as e:
            logger.warning(f"[UM982] VTG exception: {e}")

    def _parse_zda(self, line: str):
        try:
            msg = pynmea2.parse(line)
            utc_raw = msg.data[0] if msg.data[0] else ""
            # Format HH:MM:SS from raw HHMMSS.ss
            if len(utc_raw) >= 6:
                utc_time = f"{utc_raw[0:2]}:{utc_raw[2:4]}:{utc_raw[4:6]}"
            else:
                utc_time = utc_raw
            day = msg.data[1] if len(msg.data) > 1 else ""
            month = msg.data[2] if len(msg.data) > 2 else ""
            year = msg.data[3] if len(msg.data) > 3 else ""
            utc_date = f"{day}/{month}/{year}" if day and month and year else ""
            with self._lock:
                self.data["utc_time"] = utc_time
                self.data["utc_date"] = utc_date
        except pynmea2.nmea.ParseError:
            logger.warning(f"[UM982] ZDA parse error: {line}")
        except Exception as e:
            logger.warning(f"[UM982] ZDA exception: {e}")


# ======================================================================
#  GnssNode – ZMQ pub/sub bridge
# ======================================================================
class GnssNode:
    """
    Connects the UM982 GNSS receiver to the ZMQ data bus.
    Publishes GNSSData messages and listens for configuration commands.
    """

    def __init__(
        self,
        serial_port: str = "/dev/gnss_um982",
        baud_rate: int = 115200,
        ntrip_caster: str = "",
        ntrip_port: int = 2101,
        mountpoint: str = "",
        username: str = "",
        password: str = "",
        command_freq: float = 1.0,
    ):
        # ZMQ Publisher
        self.context = zmq.Context()
        self.pub_socket = self.context.socket(zmq.PUB)
        bus_url = get_zmq_url()
        self.pub_socket.connect(bus_url)
        logger.info(f"[GNSS Node] Publisher connected to ZMQ Bus: {bus_url}")

        # ZMQ Subscriber for config commands
        self.sub_socket = self.context.socket(zmq.SUB)
        sub_url = f"tcp://127.0.0.1:{int(bus_url.split(':')[-1]) + 1}"
        self.sub_socket.connect(sub_url)
        self.sub_socket.setsockopt_string(zmq.SUBSCRIBE, Topics.COMMAND_USER.value)
        self.sub_socket.setsockopt(zmq.RCVTIMEO, 10)
        logger.info(f"[GNSS Node] Subscriber connected to {sub_url} for commands")

        # Store config
        self._serial_port = serial_port
        self._baud_rate = baud_rate
        self._ntrip_caster = ntrip_caster
        self._ntrip_port = ntrip_port
        self._mountpoint = mountpoint
        self._username = username
        self._password = password
        self._command_freq = command_freq

        # Status tracking
        self._connected = False
        self._last_data_time = 0.0
        self._last_status_publish_time = 0.0
        self._STATUS_TIMEOUT = 5.0  # seconds without data → disconnected
        self._RETRY_INTERVAL = 5.0  # seconds between reconnect attempts
        self._STATUS_PUBLISH_INTERVAL = 5.0  # Publish status every 5 seconds for health heartbeat

        # Instantiate driver (will be started in run())
        self.driver = UM982Driver(
            serial_port=serial_port,
            baud_rate=baud_rate,
            ntrip_caster=ntrip_caster,
            ntrip_port=ntrip_port,
            mountpoint=mountpoint,
            username=username,
            password=password,
            command_freq=command_freq,
            on_data_callback=self._on_gnss_data,
        )

    def _publish_status(self, status: SensorStatus, message: str = ""):
        """Publish sensor health status on the bus."""
        try:
            msg = SensorStatusMessage(
                timestamp=time.time(),
                sensor="gnss",
                status=status,
                message=message,
            )
            json_str = msg.model_dump_json()
            self.pub_socket.send_string(f"{Topics.SENSOR_STATUS.value} {json_str}")
            #logger.info(f"[GNSS Node] Published status: {status.value} — {message}")
        except Exception as e:
            logger.error(f"[GNSS Node] Failed to publish status: {e}", exc_info=True)

    def _on_gnss_data(self, raw_data: dict):
        """Called by UM982Driver each time a GGA sentence arrives with full data snapshot."""
        ts = time.time()
        self._last_data_time = ts
        if not self._connected:
            self._connected = True
            self._publish_status(SensorStatus.OK, "Receiving data")
            logger.info("[GNSS Node] Now receiving data")
        try:
            msg = GNSSData(
                timestamp=ts,
                lat=raw_data["lat"],
                lon=raw_data["lon"],
                alt=raw_data["alt"],
                fix_type=raw_data["fix_type"],
                num_satellites=raw_data["num_satellites"],
                hdop=raw_data["hdop"],
                vdop=raw_data.get("vdop", 99.99),
                heading=raw_data["heading"],
                heading_status=raw_data["heading_status"],
                cog=raw_data["cog"],
                sog_knots=raw_data["sog_knots"],
                sog_kmh=raw_data["sog_kmh"],
                utc_time=raw_data["utc_time"],
                utc_date=raw_data["utc_date"],
            )
            json_str = msg.model_dump_json()
            self.pub_socket.send_string(f"{Topics.SENSOR_GNSS.value} {json_str}")
        except ValidationError as e:
            logger.warning(f"[GNSS Node] Validation error: {e}")

    def _check_commands(self):
        """Poll for SET_GNSS_CONFIG commands from the settings UI."""
        try:
            msg = self.sub_socket.recv_string(zmq.NOBLOCK)
            _, payload_str = msg.split(" ", 1)
            cmd = json.loads(payload_str)
            cmd_type = cmd.get("type", "")
            if cmd_type == "SET_GNSS_CONFIG":
                payload = cmd.get("payload", {})
                self._apply_config(payload)
        except zmq.Again:
            pass
        except Exception as e:
            logger.warning(f"[GNSS Node] Command parse error: {e}")

    def _apply_config(self, payload: dict):
        """
        Apply new GNSS configuration: stop old driver, restart with new params.
        Expected payload keys: serial_port, baud_rate, ntrip_caster, ntrip_port,
                               mountpoint, username, password, command_freq
        """
        logger.info(f"[GNSS Node] Applying new config: {payload}")
        self.driver.stop()
        time.sleep(0.5)

        # Update stored config from payload (only if keys present)
        self._serial_port = payload.get("serial_port", self._serial_port)
        self._baud_rate = int(payload.get("baud_rate", self._baud_rate))
        self._ntrip_caster = payload.get("ntrip_caster", self._ntrip_caster)
        self._ntrip_port = int(payload.get("ntrip_port", self._ntrip_port))
        self._mountpoint = payload.get("mountpoint", self._mountpoint)
        self._username = payload.get("username", self._username)
        self._password = payload.get("password", self._password)
        self._command_freq = float(payload.get("command_freq", self._command_freq))

        self.driver = UM982Driver(
            serial_port=self._serial_port,
            baud_rate=self._baud_rate,
            ntrip_caster=self._ntrip_caster,
            ntrip_port=self._ntrip_port,
            mountpoint=self._mountpoint,
            username=self._username,
            password=self._password,
            command_freq=self._command_freq,
            on_data_callback=self._on_gnss_data,
        )
        try:
            self.driver.start()
            logger.info("[GNSS Node] Driver restarted with new config")
        except Exception as e:
            logger.error(f"[GNSS Node] Failed to restart driver: {e}")

    def run(self):
        logger.info("[GNSS Node] Starting (with auto-retry)...")
        while True:
            # Try to start the driver
            try:
                self.driver.start()
                self._connected = False  # Will become True when first data arrives
                self._last_data_time = time.time()
                logger.info(f"[GNSS Node] Driver started on {self._serial_port}, waiting for data...")
            except Exception as e:
                self._connected = False
                self._publish_status(SensorStatus.DISCONNECTED, str(e))
                logger.warning(f"[GNSS Node] Cannot open {self._serial_port}: {e}. Retrying in {self._RETRY_INTERVAL}s...")
                # Wait and retry, but keep checking commands
                deadline = time.time() + self._RETRY_INTERVAL
                while time.time() < deadline:
                    self._check_commands()
                    time.sleep(0.2)
                # Recreate driver for next attempt
                self.driver = UM982Driver(
                    serial_port=self._serial_port,
                    baud_rate=self._baud_rate,
                    ntrip_caster=self._ntrip_caster,
                    ntrip_port=self._ntrip_port,
                    mountpoint=self._mountpoint,
                    username=self._username,
                    password=self._password,
                    command_freq=self._command_freq,
                    on_data_callback=self._on_gnss_data,
                )
                continue

            # Main loop — monitor health and check commands
            try:
                while True:
                    self._check_commands()
                    # Periodic status heartbeat (5 seconds)
                    now = time.time()
                    if now - self._last_status_publish_time > self._STATUS_PUBLISH_INTERVAL:
                        if self._connected:
                            self._publish_status(SensorStatus.OK, "Receiving data")
                        else:
                            self._publish_status(SensorStatus.DISCONNECTED, "No data")
                        self._last_status_publish_time = now
                    # Check for data timeout (device unplugged)
                    if self._connected and self._last_data_time > 0:
                        if time.time() - self._last_data_time > self._STATUS_TIMEOUT:
                            self._connected = False
                            self._publish_status(SensorStatus.DISCONNECTED, "No data received (timeout)")
                            logger.warning("[GNSS Node] No data timeout — device may be disconnected")
                    time.sleep(0.2)
            except KeyboardInterrupt:
                logger.info("[GNSS Node] Keyboard interrupt")
                self.shutdown()
                return
            except Exception as e:
                logger.error(f"[GNSS Node] Unexpected error: {e}")
                self._connected = False
                self._publish_status(SensorStatus.ERROR, str(e))
                self.driver.stop()
                time.sleep(self._RETRY_INTERVAL)

    def shutdown(self):
        self.driver.stop()
        self.pub_socket.close()
        self.sub_socket.close()
        self.context.term()
        logger.info("[GNSS Node] Shutdown complete.")


# ======================================================================
#  Standalone entry point
# ======================================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="UM982 GNSS Driver - standalone test or ZMQ node")
    parser.add_argument("--mode", choices=["test", "node"], default="test",
                        help="'test' = standalone serial read, 'node' = full ZMQ publisher")
    parser.add_argument("--port", default="/dev/gnss_um982", help="Serial port")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate")
    parser.add_argument("--ntrip-caster", default="", help="NTRIP caster host")
    parser.add_argument("--ntrip-port", type=int, default=2101)
    parser.add_argument("--mountpoint", default="")
    parser.add_argument("--username", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--freq", type=float, default=1.0, help="Command/update frequency Hz")
    args = parser.parse_args()

    if args.mode == "node":
        node = GnssNode(
            serial_port=args.port,
            baud_rate=args.baud,
            ntrip_caster=args.ntrip_caster,
            ntrip_port=args.ntrip_port,
            mountpoint=args.mountpoint,
            username=args.username,
            password=args.password,
            command_freq=args.freq,
        )
        node.run()
    else:
        count = [0]

        def on_data(data):
            count[0] += 1
            fix = data["fix_type"]
            fix_labels = {0: "No fix", 1: "GPS", 2: "DGPS", 4: "RTK Fix", 5: "RTK Float"}
            fix_str = fix_labels.get(fix, f"Unknown({fix})")
            print(
                f"[{count[0]:5d}] "
                f"Lat: {data['lat']:12.8f}  Lon: {data['lon']:12.8f}  Alt: {data['alt']:7.2f}m | "
                f"Fix: {fix_str}  Sats: {data['num_satellites']:2d}  HDOP: {data['hdop']:5.2f} | "
                f"Hdg: {data['heading']:6.1f}° ({data['heading_status']})  "
                f"COG: {data['cog']:6.1f}°  SOG: {data['sog_knots']:5.1f}kn | "
                f"UTC: {data['utc_time']} {data['utc_date']}"
            )

        driver = UM982Driver(
            serial_port=args.port,
            baud_rate=args.baud,
            ntrip_caster=args.ntrip_caster,
            ntrip_port=args.ntrip_port,
            mountpoint=args.mountpoint,
            username=args.username,
            password=args.password,
            command_freq=args.freq,
            on_data_callback=on_data,
        )
        driver.start()
        print(f"[TEST] UM982 driver started on {args.port} @ {args.baud}")
        print("[TEST] Waiting for NMEA data (Ctrl+C to stop)...\n")
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            pass
        driver.stop()
        print(f"\n[TEST] Stopped. Total GGA frames: {count[0]}")
