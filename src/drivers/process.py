from src.core.process import ServiceProcess
from src.core.messaging import Publisher, Topics
from src.core.models import BatteryMessage, ControlDebugMessage
from src.drivers.imu import ImuNode
from src.drivers.power_pzem import PowerNode
from src.drivers.gnss_um982 import GnssNode
from src.core.config import settings
from loguru import logger
import time
import math
import random
import threading

class HALProcess(ServiceProcess):
    def setup(self):
        self.control_debug_pub = Publisher(Topics.CONTROL_DEBUG)
        self.control_cmd_pub = Publisher(Topics.CONTROL_CMD)
        
        self.start_time = time.time()

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
        now = time.time()

        # Dummy Control Debug Data
        try:
            t = now - self.start_time
            # Add some random noise for errors
            fake_target = math.pi * math.sin(t * 0.15)
            fake_h_err = 0.2 * random.uniform(-1, 1) + 0.5 * math.sin(t * 0.2)
            fake_xte = 5.0 * math.sin(t * 0.1) + random.uniform(-0.5, 0.5)
            
            control_debug_data = ControlDebugMessage(
                timestamp=now,
                target_heading=fake_target,
                heading_error=fake_h_err,
                cross_track_error=fake_xte
            )
            self.control_debug_pub.publish(control_debug_data.model_dump())
            
            # Dummy Control Output (Motors)
            fake_motor_p = 50.0 * math.sin(t * 0.2)
            fake_motor_s = 50.0 * math.cos(t * 0.2)
            self.control_cmd_pub.publish({
                "timestamp": now,
                "port_pct": fake_motor_p,
                "starboard_pct": fake_motor_s
            })
        except Exception as e:
            logger.error(f"Error publishing Dummy Control Debug/Output: {e}")

