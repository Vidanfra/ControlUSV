from src.core.process import ServiceProcess
from src.core.messaging import Publisher, Subscriber, Topics
from src.core.models import CommandMessage, CommandType, GnssConfig
from src.drivers.imu import ImuNode
from src.drivers.power_pzem import PowerNode
from src.drivers.gnss_um982 import GnssNode
from src.drivers.esp32 import Esp32Node
from src.core.config import settings
from loguru import logger
import json
import os
import time
import threading

# Same persisted settings file the ManagerProcess writes to — read directly so
# the GNSS node starts with the saved NTRIP config instead of blank defaults.
_SETTINGS_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'manager_settings.json')


def _load_gnss_config() -> GnssConfig:
    try:
        if os.path.exists(_SETTINGS_FILE):
            with open(_SETTINGS_FILE, 'r') as f:
                data = json.load(f)
            if 'gnss_config' in data:
                return GnssConfig(**data['gnss_config'])
    except Exception as e:
        logger.warning(f"HAL: could not load persisted GNSS config ({e}), using defaults")
    return GnssConfig()


class HALProcess(ServiceProcess):
    def setup(self):
        # Command subscriber for mute/unmute
        self.cmd_sub = Subscriber([Topics.COMMAND_USER])
        self.sensors_muted = False

        # Start GNSS Node (UM982) in a background thread
        try:
            gnss_cfg = _load_gnss_config()
            self.gnss_node = GnssNode(
                serial_port=gnss_cfg.serial_port,
                baud_rate=gnss_cfg.baud_rate,
                ntrip_caster=gnss_cfg.ntrip_caster,
                ntrip_port=gnss_cfg.ntrip_port,
                mountpoint=gnss_cfg.mountpoint,
                username=gnss_cfg.username,
                password=gnss_cfg.password,
                command_freq=gnss_cfg.command_freq,
            )
            self.gnss_thread = threading.Thread(target=self.gnss_node.run, daemon=True)
            self.gnss_thread.start()
            logger.info(f"GNSS Node (UM982) started on {gnss_cfg.serial_port}")
        except Exception as e:
            logger.warning(f"Could not start GNSS Node: {e}. GNSS data will not be available.")
            self.gnss_node = None

        # Start IMU Node in a background thread
        try:
            self.imu_node = ImuNode(serial_port="/dev/serial0", baud_rate=9600)
            self.imu_thread = threading.Thread(target=self.imu_node.run, daemon=True)
            self.imu_thread.start()
            logger.info("IMU Node started on /dev/serial0")
        except Exception as e:
            logger.warning(f"Could not start IMU Node: {e}. IMU data will not be available.")
            self.imu_node = None

        # Start Power Node (PZEM-017) in a background thread
        try:
            self.power_node = PowerNode(
                port="/dev/power_pzem", device_address=1,
                baud_rate=9600, update_hz=1, battery_capacity_wh=500.0
            )
            self.power_thread = threading.Thread(target=self.power_node.run, daemon=True)
            self.power_thread.start()
            logger.info("Power Node (PZEM-017) started on /dev/power_pzem")
        except Exception as e:
            logger.warning(f"Could not start Power Node: {e}. Power data will not be available.")
            self.power_node = None

        # Start ESP32 Motor Controller Node in a background thread
        try:
            self.esp32_node = Esp32Node(port="/dev/esp32", baudrate=115200)
            self.esp32_thread = threading.Thread(target=self.esp32_node.run, daemon=True)
            self.esp32_thread.start()
            logger.info("ESP32 Node started on /dev/esp32")
        except Exception as e:
            logger.error(f"Could not start ESP32 Node: {e}. Motor control will not be available.")
            self.esp32_node = None

    def loop(self):
        # Process mute/unmute commands
        while True:
            msg = self.cmd_sub.receive(timeout_ms=0)
            if msg is None:
                break
            _, payload = msg
            try:
                cmd = CommandMessage(**payload)
                if cmd.type == CommandType.MUTE_SENSORS:
                    self.sensors_muted = True
                    # Propagate mute to sensor nodes
                    if self.gnss_node:
                        self.gnss_node.muted = True
                    if self.imu_node:
                        self.imu_node.muted = True
                    logger.info("HAL: Sensors MUTED (RT simulation active)")
                elif cmd.type == CommandType.UNMUTE_SENSORS:
                    self.sensors_muted = False
                    if self.gnss_node:
                        self.gnss_node.muted = False
                    if self.imu_node:
                        self.imu_node.muted = False
                    logger.info("HAL: Sensors UNMUTED")
            except Exception as e:
                logger.warning(f"HAL: Error processing command: {e}")

