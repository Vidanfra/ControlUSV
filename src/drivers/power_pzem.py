"""
power_pzem.py
PZEM-017 DC Power Monitor driver for the USV pub/sub architecture.
Reads voltage, current, power, energy via Modbus RTU over RS485 (USB adapter).
Publishes BatteryMessage on the ZMQ bus.
"""
import time
import threading
import zmq
import minimalmodbus
import serial as pyserial
from pydantic import ValidationError

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.core.models import BatteryMessage
from src.core.messaging import Topics, get_zmq_url


class PZEMDriver:
    """
    Low-level Modbus RTU driver for PZEM-017 DC energy meter.
    Reads registers in a background thread and fires a callback with the data dict.
    """

    def __init__(self, port="/dev/power_pzem", device_address=0x01, baud_rate=9600,
                 timeout=1, update_hz=1, on_data_callback=None):
        self.port = port
        self.device_address = device_address
        self.baud_rate = baud_rate
        self.timeout = timeout
        self.update_interval = 1.0 / update_hz
        self.on_data_callback = on_data_callback

        self.running = False
        self.thread = None
        self.instrument = None

        self.data = {
            "voltage": 0.0,
            "current": 0.0,
            "power": 0.0,
            "energy": 0,
            "high_voltage_alarm": 0,
            "low_voltage_alarm": 0
        }

    def start(self):
        self.instrument = minimalmodbus.Instrument(self.port, self.device_address)
        self.instrument.serial.baudrate = self.baud_rate
        self.instrument.serial.bytesize = 8
        self.instrument.serial.parity = pyserial.PARITY_NONE
        self.instrument.serial.stopbits = 2
        self.instrument.serial.timeout = self.timeout
        self.running = True
        self.thread = threading.Thread(target=self._read_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()

    def _read_loop(self):
        while self.running:
            try:
                voltage = self.instrument.read_register(0x0000, number_of_decimals=2, functioncode=4)
                current = self.instrument.read_register(0x0001, number_of_decimals=2, functioncode=4)
                power_low = self.instrument.read_register(0x0002, functioncode=4)
                power_high = self.instrument.read_register(0x0003, functioncode=4)
                power = (power_high << 16) + power_low  # in 0.1W
                energy_low = self.instrument.read_register(0x0004, functioncode=4)
                energy_high = self.instrument.read_register(0x0005, functioncode=4)
                energy = (energy_high << 16) + energy_low  # in Wh
                high_voltage_alarm = self.instrument.read_register(0x0006, functioncode=4)
                low_voltage_alarm = self.instrument.read_register(0x0007, functioncode=4)

                self.data.update({
                    "voltage": voltage,
                    "current": current,
                    "power": power * 0.1,  # Convert to Watts
                    "energy": energy,
                    "high_voltage_alarm": high_voltage_alarm,
                    "low_voltage_alarm": low_voltage_alarm
                })

                if self.on_data_callback:
                    self.on_data_callback(self.data)

            except minimalmodbus.IllegalRequestError as e:
                print(f"[PZEM] Modbus read error: {e}")
            except Exception as e:
                print(f"[PZEM] Read error: {e}")
                time.sleep(1)

            time.sleep(self.update_interval)


class PowerNode:
    """
    Connects the PZEM-017 power monitor to the ZMQ data bus.
    Tracks energy consumption with reset capability and computes battery level.
    """

    def __init__(self, port="/dev/power_pzem", device_address=0x01, baud_rate=9600,
                 update_hz=1, battery_capacity_wh=500.0):
        self.battery_capacity_wh = battery_capacity_wh

        # Energy tracking
        self._energy_start_time = time.time()
        self._accumulated_wh = 0.0
        self._last_power_w = 0.0
        self._last_sample_time = time.time()
        self._lock = threading.Lock()

        # ZMQ Publisher
        self.context = zmq.Context()
        self.pub_socket = self.context.socket(zmq.PUB)
        bus_url = get_zmq_url()
        self.pub_socket.connect(bus_url)
        print(f"[Power Node] Publisher connected to ZMQ Bus: {bus_url}")

        # ZMQ Subscriber (for reset commands from the UI)
        self.sub_socket = self.context.socket(zmq.SUB)
        sub_url = f"tcp://127.0.0.1:{int(bus_url.split(':')[-1]) + 1}"
        self.sub_socket.connect(sub_url)
        self.sub_socket.setsockopt_string(zmq.SUBSCRIBE, Topics.COMMAND_USER.value)
        self.sub_socket.setsockopt(zmq.RCVTIMEO, 10)  # 10ms timeout
        print(f"[Power Node] Subscriber connected to {sub_url} for commands")

        # Instantiate driver
        self.driver = PZEMDriver(
            port=port,
            device_address=device_address,
            baud_rate=baud_rate,
            update_hz=update_hz,
            on_data_callback=self._on_pzem_data
        )

    def reset_energy(self):
        """Reset the accumulated energy counter and start time."""
        with self._lock:
            self._accumulated_wh = 0.0
            self._energy_start_time = time.time()
            self._last_sample_time = time.time()
            print("[Power Node] Energy consumption counter reset.")

    def set_battery_capacity(self, capacity_wh):
        """Update battery capacity (called from settings)."""
        self.battery_capacity_wh = capacity_wh
        print(f"[Power Node] Battery capacity set to {capacity_wh} Wh")

    def _on_pzem_data(self, raw_data):
        """Called by PZEMDriver each time new readings are available."""
        ts = time.time()

        voltage = raw_data["voltage"]
        current = raw_data["current"]
        power_w = raw_data["power"]

        # Integrate energy: E += P * dt (convert seconds to hours)
        with self._lock:
            dt = ts - self._last_sample_time
            if dt > 0 and dt < 10:  # Guard against huge gaps
                self._accumulated_wh += power_w * (dt / 3600.0)
            self._last_sample_time = ts
            accumulated = self._accumulated_wh
            start_time = self._energy_start_time
            capacity = self.battery_capacity_wh

        # Battery level estimate: remaining = capacity - consumed
        level_pct = max(0.0, min(100.0, (1.0 - accumulated / capacity) * 100.0)) if capacity > 0 else 0.0

        try:
            msg = BatteryMessage(
                timestamp=ts,
                voltage=voltage,
                current=current,
                power=power_w,
                energy_wh=raw_data["energy"],
                level_pct=level_pct,
                capacity_wh=capacity,
                accumulated_wh=accumulated,
                measurement_start=start_time,
                high_voltage_alarm=raw_data["high_voltage_alarm"],
                low_voltage_alarm=raw_data["low_voltage_alarm"]
            )

            json_str = msg.model_dump_json()
            self.pub_socket.send_string(f"{Topics.SENSOR_BATTERY.value} {json_str}")

        except ValidationError as e:
            print(f"[Power Node] Validation error: {e}")

    def _check_commands(self):
        """Poll for incoming commands (reset energy, set capacity)."""
        try:
            msg = self.sub_socket.recv_string(zmq.NOBLOCK)
            _, payload_str = msg.split(" ", 1)
            import json
            cmd = json.loads(payload_str)
            cmd_type = cmd.get("type", "")

            if cmd_type == "RESET_ENERGY":
                self.reset_energy()
            elif cmd_type == "SET_BATTERY_CAPACITY":
                new_cap = cmd.get("payload", {}).get("capacity_wh", self.battery_capacity_wh)
                self.set_battery_capacity(float(new_cap))
        except zmq.Again:
            pass  # No message available
        except Exception as e:
            print(f"[Power Node] Command parse error: {e}")

    def run(self):
        print("[Power Node] Starting PZEM driver thread...")
        self.driver.start()
        try:
            while True:
                self._check_commands()
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\n[Power Node] Shutting down...")
            self.shutdown()

    def shutdown(self):
        self.driver.stop()
        self.pub_socket.close()
        self.sub_socket.close()
        self.context.term()
        print("[Power Node] Shutdown complete.")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description="PZEM-017 Power Monitor - standalone test or ZMQ node")
    parser.add_argument("--mode", choices=["test", "node"], default="test",
                        help="'test' = standalone Modbus read (no ZMQ), 'node' = full ZMQ publisher")
    parser.add_argument("--port", default="/dev/power_pzem", help="Serial port (default: /dev/power_pzem)")
    parser.add_argument("--address", type=int, default=1, help="Modbus device address (default: 1)")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate (default: 9600)")
    parser.add_argument("--capacity", type=float, default=500.0, help="Battery capacity in Wh (default: 500)")
    args = parser.parse_args()

    if args.mode == "node":
        node = PowerNode(
            port=args.port, device_address=args.address,
            baud_rate=args.baud, battery_capacity_wh=args.capacity
        )
        node.run()
    else:
        # Standalone test - read and print, no ZMQ
        def on_data(data):
            print(
                f"V: {data['voltage']:6.2f} V | "
                f"I: {data['current']:6.2f} A | "
                f"P: {data['power']:7.1f} W | "
                f"E: {data['energy']:6d} Wh | "
                f"HiAlarm: {data['high_voltage_alarm']} | "
                f"LoAlarm: {data['low_voltage_alarm']}"
            )

        driver = PZEMDriver(args.port, device_address=args.address,
                            baud_rate=args.baud, on_data_callback=on_data)
        driver.start()
        print(f"[TEST] PZEM driver started on {args.port} @ addr {args.address}")
        print("[TEST] Waiting for data (Ctrl+C to stop)...\n")

        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            pass

        driver.stop()
        print("\n[TEST] Stopped.")
