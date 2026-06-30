import serial
import json
import time
from loguru import logger
from src.core.messaging import Publisher, Subscriber, Topics
from src.core.models import SensorStatusMessage, SensorStatus

'''
ESP32 pinout:

const int PIN_M1 = 20;  // Babor (Port)
const int PIN_M2 = 21;  // Estribor (Starboard)
const int PIN_R1 = 38;  // Motor Relay [WHITE]
const int PIN_R2 = 39;  // Comms Relay (Default ON) [GREEN]
const int PIN_R3 = 40;  // Payload Relay [YELLOW]
'''


def apply_motor_calibration(
    pct: float,
    fwd_deadzone: float, fwd_saturation: float,
    bwd_deadzone: float, bwd_saturation: float,
) -> float:
    """Remap a logical motor command onto the physical thrust band.

    The ESC/propeller has a dead band near zero (no thrust until a minimum
    command) and an effective saturation point (no extra thrust above a
    maximum command). These differ forward vs. reverse, so each direction is
    compensated independently.

    A logical command ``pct`` in [-100, 100] is mapped so that any non-zero
    value clears the dead band and full command reaches the saturation point:

        forward (pct > 0):  out =  dz_f + (pct/100)  * (sat_f - dz_f)
        reverse (pct < 0):  out = -dz_b - (|pct|/100) * (sat_b - dz_b)
        pct == 0:           out =  0   (motor off)

    With the defaults (dz=0, sat=100) this is an identity pass-through.
    """
    if pct > 0:
        lo = max(0.0, min(100.0, fwd_deadzone))
        hi = max(0.0, min(100.0, fwd_saturation))
        mag = min(abs(pct), 100.0)
        return lo + (mag / 100.0) * (hi - lo)
    if pct < 0:
        lo = max(0.0, min(100.0, bwd_deadzone))
        hi = max(0.0, min(100.0, bwd_saturation))
        mag = min(abs(pct), 100.0)
        return -(lo + (mag / 100.0) * (hi - lo))
    return 0.0


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
        # Latched relay state mirrored from Manager's heartbeat
        # (Topics.SYSTEM_STATUS.relay_config.states). Default ALL CLOSED so
        # behaviour before the first heartbeat matches the historical
        # hard-coded `1, 1, 1`.
        self._relay_states: list[int] = [1, 1, 1]
        # Latched motor calibration mirrored from the Manager's heartbeat
        # (Topics.SYSTEM_STATUS.motor_config). Defaults are a pass-through
        # (no dead-zone / saturation compensation).
        self._motor_cal = {
            'fwd_deadzone': 0.0, 'fwd_saturation': 100.0,
            'bwd_deadzone': 0.0, 'bwd_saturation': 100.0,
        }
        self._status_pub = Publisher(Topics.SENSOR_STATUS)

    def _publish_status(self, status: SensorStatus, message: str = ""):
        """Publish ESP32 connection status on the sensor/status bus topic."""
        try:
            msg = SensorStatusMessage(
                timestamp=time.time(),
                sensor="esp32",
                status=status,
                message=message,
            )
            self._status_pub.publish(msg.model_dump())
        except Exception as e:
            logger.error(f"[ESP32 Node] Failed to publish status: {e}")

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
                self._publish_status(SensorStatus.OK, f"Connected on {self._port}")
            except Exception as e:
                self._connected = False
                if not _start_error_logged:
                    logger.error(
                        f"[ESP32 Node] Cannot open {self._port}: {e}. "
                        f"Retrying every {self._RETRY_INTERVAL}s (this message will not repeat)."
                    )
                    self._publish_status(SensorStatus.DISCONNECTED, f"Cannot open {self._port}")
                    _start_error_logged = True
                time.sleep(self._RETRY_INTERVAL)
                continue

            # ── Inner loop: forward motor cmds + heartbeat relay state ────
            # We poll TWO topics:
            #   * gnc/control_output: real motor commands (drives M1/M2)
            #   * system/status: Manager heartbeat (carries latched relay state)
            # If no CONTROL_CMD arrives for 100 ms we still send a frame with
            # M1=M2=0 so the firmware sees a live link and the latest relay
            # state is applied even when the vehicle is disarmed.
            sub  = Subscriber([Topics.CONTROL_CMD])
            stat = Subscriber([Topics.SYSTEM_STATUS])
            _send_error_logged = False
            last_send = 0.0
            try:
                while True:
                    # 1) Drain heartbeats to refresh the latched relay state
                    for _ in range(10):
                        smsg = stat.receive(timeout_ms=0)
                        if smsg is None:
                            break
                        _, sdata = smsg
                        rc = sdata.get('relay_config')
                        if isinstance(rc, dict):
                            states = rc.get('states')
                            if isinstance(states, list) and len(states) >= 3:
                                self._relay_states = [
                                    1 if int(states[i]) else 0 for i in range(3)
                                ]
                        mc = sdata.get('motor_config')
                        if isinstance(mc, dict):
                            for key in self._motor_cal:
                                if key in mc:
                                    try:
                                        self._motor_cal[key] = float(mc[key])
                                    except (TypeError, ValueError):
                                        pass

                    # 2) Wait briefly for a motor command
                    msg = sub.receive(timeout_ms=100)
                    port_pct = 0.0
                    stbd_pct = 0.0
                    if msg is not None:
                        _, payload = msg
                        # Never forward simulation-sourced commands to real hardware
                        if payload.get('source') == 'sim':
                            continue
                        port_pct = float(payload.get('port_pct', 0.0))
                        stbd_pct = float(payload.get('starboard_pct', 0.0))

                    # 3) Rate-limit idle heartbeats so we don't flood the bus
                    #    when armed+silent. Real motor frames always send.
                    now = time.monotonic()
                    if msg is None and (now - last_send) < 0.2:
                        continue
                    last_send = now

                    # Apply per-direction dead-zone / saturation compensation
                    # before the command reaches the physical ESCs.
                    cal = self._motor_cal
                    port_pct = apply_motor_calibration(
                        port_pct,
                        cal['fwd_deadzone'], cal['fwd_saturation'],
                        cal['bwd_deadzone'], cal['bwd_saturation'],
                    )
                    stbd_pct = apply_motor_calibration(
                        stbd_pct,
                        cal['fwd_deadzone'], cal['fwd_saturation'],
                        cal['bwd_deadzone'], cal['bwd_saturation'],
                    )

                    try:
                        self.driver.send_command(
                            port_pct, stbd_pct,
                            self._relay_states[0],
                            self._relay_states[1],
                            self._relay_states[2],
                        )
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
                self._publish_status(SensorStatus.DISCONNECTED, "Serial connection lost")
                try:
                    self.driver.close()
                except Exception:
                    pass
                sub.close()
                try:
                    stat.close()
                except Exception:
                    pass

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
