from src.core.process import ServiceProcess
from src.core.messaging import Publisher, Subscriber, Topics
from src.core.models import CommandMessage, CommandType
from src.drivers.imu import ImuNode
from src.drivers.power_pzem import PowerNode
from src.drivers.gnss_um982 import GnssNode
from src.core.config import settings
from loguru import logger
import time
import threading

class HALProcess(ServiceProcess):
    def setup(self):
        # Command subscriber for mute/unmute
        self.cmd_sub = Subscriber([Topics.COMMAND_USER])
        self.sensors_muted = False

        # Start GNSS Node (UM982) in a background thread
        try:
            self.gnss_node = GnssNode(
                serial_port="/dev/gnss_um982",
                baud_rate=115200,
                ntrip_caster="",     # Set via Settings UI
                ntrip_port=2101,
                mountpoint="",
                username="",
                password="",
                command_freq=1.0,
            )
            self.gnss_thread = threading.Thread(target=self.gnss_node.run, daemon=True)
            self.gnss_thread.start()
            logger.info("GNSS Node (UM982) started on /dev/gnss_um982")
        except Exception as e:
            logger.warning(f"Could not start GNSS Node: {e}. GNSS data will not be available.")
            self.gnss_node = None

        # Start IMU Node in a background thread
        try:
            self.imu_node = ImuNode(serial_port="/dev/serial0", baud_rate=9600, mag_declination=2.5)
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
            except Exception:
                pass

