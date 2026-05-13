import serial
import json
import time
from loguru import logger
from src.core.messaging import Subscriber, Topics

'''
ESP32 pinout:

const int PIN_M1 = 20;  // Babor (Port)
const int PIN_M2 = 21;  // Estribor (Starboard)
const int PIN_R1 = 38;  // Motor Relay [WHITE]
const int PIN_R2 = 39;  // Comms Relay (Default ON) [GREEN]
const int PIN_R3 = 40;  // Payload Relay [YELLOW]
'''


class ESP32Driver:
    def __init__(self, port, baudrate=115200):
        self.ser = serial.Serial(port, baudrate, timeout=0.1)
        self.last_ack_time = time.time()
        time.sleep(2)  # Wait for ESP32 reset if DTR triggers reset

    def send_command(self, m1, m2, r1, r2, r3):
        """
        Send command to ESP32.
        m1, m2: Motor percentages (-100 to 100)
        r1, r2, r3: Relay states (0 or 1)
        """
        checksum = int(m1) + int(m2) + int(r1) + int(r2) + int(r3)
        payload = {
            "M1": m1,
            "M2": m2,
            "R1": int(r1),
            "R2": int(r2),
            "R3": int(r3),
            "C": checksum,
        }

        msg = json.dumps(payload) + "\n"
        self.ser.write(msg.encode('utf-8'))

        # Wait for ACK (200 ms timeout)
        start = time.time()
        while (time.time() - start) < 0.2:
            if self.ser.in_waiting:
                try:
                    line = self.ser.readline().decode('utf-8').strip()
                    resp = json.loads(line)
                    if "ACK" in resp and resp["ACK"] == checksum:
                        return True
                    if "ERR" in resp:
                        logger.warning(f"[ESP32] Firmware error: {resp}")
                except Exception as e:
                    logger.warning(f"[ESP32] Parse error: {e}")
            time.sleep(0.005)

        raise TimeoutError("ESP32 ACK Timeout")

    def close(self):
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except Exception:
            pass


class Esp32Node:
    """
    ZMQ-to-serial bridge for the ESP32 motor controller.

    Subscribes to ``gnc/control_output``, filters out simulation-sourced
    commands, and forwards real motor commands to the ESP32 over serial.

    Applies the same retry + log-once pattern as the sensor nodes:
    - If the serial port cannot be opened, logs *once* and retries silently.
    - If an ACK timeout or serial error occurs in the inner loop, logs once
      and reconnects automatically.
    """

    _RETRY_INTERVAL = 3.0  # seconds between reconnect attempts

    def __init__(self, port: str = "/dev/esp32", baudrate: int = 115200):
        self._port = port
        self._baudrate = baudrate
        self.driver: ESP32Driver | None = None
        self._connected = False

    def run(self):
        logger.info("[ESP32 Node] Starting (with auto-retry)...")
        _start_error_logged = False

        while True:
            # ── Try to open the serial port ───────────────────────────────
            try:
                self.driver = ESP32Driver(port=self._port, baudrate=self._baudrate)
                _start_error_logged = False
                self._connected = True
                logger.info(
                    f"[ESP32 Node] Connected on {self._port} — ready for motor commands"
                )
            except Exception as e:
                self._connected = False
                if not _start_error_logged:
                    logger.error(
                        f"[ESP32 Node] Cannot open {self._port}: {e}. "
                        f"Retrying every {self._RETRY_INTERVAL}s (this message will not repeat)."
                    )
                    _start_error_logged = True
                time.sleep(self._RETRY_INTERVAL)
                continue

            # ── Inner loop: receive from ZMQ, send to serial ──────────────
            sub = Subscriber([Topics.CONTROL_CMD])
            _send_error_logged = False
            try:
                while True:
                    msg = sub.receive(timeout_ms=100)
                    if msg is None:
                        continue

                    _, payload = msg

                    # Never forward simulation-sourced commands to real hardware
                    if payload.get('source') == 'sim':
                        continue

                    port_pct = float(payload.get('port_pct', 0.0))
                    stbd_pct = float(payload.get('starboard_pct', 0.0))

                    try:
                        self.driver.send_command(port_pct, stbd_pct, 1, 1, 1)
                        if _send_error_logged:
                            logger.info(
                                f"[ESP32 Node] Communication restored on {self._port}"
                            )
                            _send_error_logged = False
                    except Exception as e:
                        if not _send_error_logged:
                            logger.warning(
                                f"[ESP32 Node] Send error: {e} — reconnecting..."
                            )
                            _send_error_logged = True
                        break  # exit inner loop → outer retry loop

            except KeyboardInterrupt:
                return
            finally:
                self._connected = False
                try:
                    self.driver.close()
                except Exception:
                    pass
                sub.close()

            logger.info(f"[ESP32 Node] Reconnecting in {self._RETRY_INTERVAL}s...")
            time.sleep(self._RETRY_INTERVAL)


if __name__ == "__main__":
    # Standalone test — sends a sine wave directly without ZMQ
    import math

    try:
        driver = ESP32Driver("/dev/esp32")
        logger.info("Driver started. Sending sine wave (Ctrl+C to stop)...")
        t = 0
        while True:
            val = 100 * math.sin(t)
            try:
                driver.send_command(val, -val, 1, 1, 0)
                logger.info(f"Sent: {val:.1f}")
            except Exception as e:
                logger.error(f"Error: {e}")
            t += 0.1
            time.sleep(1 / 15)
    except KeyboardInterrupt:
        driver.close()
