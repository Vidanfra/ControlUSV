from src.core.process import ServiceProcess
from src.core.messaging import Publisher, Topics
from src.core.models import BatteryMessage, ControlDebugMessage
from src.drivers.manager import get_gnss_driver
from src.drivers.imu import ImuNode
from src.drivers.power_pzem import PowerNode
from src.core.config import settings
from loguru import logger
import time
import math
import random
import threading

class HALProcess(ServiceProcess):
    def setup(self):
        self.gnss_driver = get_gnss_driver()
        self.gnss_pub = Publisher(Topics.SENSOR_GNSS)
        self.control_debug_pub = Publisher(Topics.CONTROL_DEBUG)
        self.control_cmd_pub = Publisher(Topics.CONTROL_CMD)
        
        self.start_time = time.time()
        logger.info(f"HAL Initialized with GNSS Driver: {self.gnss_driver.__class__.__name__}")

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
                port="/dev/ttyUSB0", device_address=1,
                baud_rate=9600, update_hz=1, battery_capacity_wh=500.0
            )
            self.power_thread = threading.Thread(target=self.power_node.run, daemon=True)
            self.power_thread.start()
            logger.info("Power Node (PZEM-017) started on /dev/ttyUSB0")
        except Exception as e:
            logger.warning(f"Could not start Power Node: {e}. Power data will not be available.")
            self.power_node = None

    def loop(self):
        now = time.time()
        
        # Read GNSS
        try:
            gnss_data = self.gnss_driver.read()
            self.gnss_pub.publish(gnss_data.model_dump())
        except Exception as e:
            logger.error(f"Error reading GNSS: {e}")

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

