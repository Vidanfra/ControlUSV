from src.core.process import ServiceProcess
from src.core.messaging import Publisher, Topics
from src.core.models import BatteryMessage, ControlDebugMessage
from src.drivers.manager import get_gnss_driver
from src.core.config import settings
from loguru import logger
import time
import math
import random

class HALProcess(ServiceProcess):
    def setup(self):
        self.gnss_driver = get_gnss_driver()
        self.gnss_pub = Publisher(Topics.SENSOR_GNSS)
        self.battery_pub = Publisher(Topics.SENSOR_BATTERY)
        self.control_debug_pub = Publisher(Topics.CONTROL_DEBUG)
        self.control_cmd_pub = Publisher(Topics.CONTROL_CMD)
        
        self.start_time = time.time()
        logger.info(f"HAL Initialized with GNSS Driver: {self.gnss_driver.__class__.__name__}")

    def loop(self):
        now = time.time()
        
        # Read GNSS
        try:
            gnss_data = self.gnss_driver.read()
            self.gnss_pub.publish(gnss_data.model_dump())
        except Exception as e:
            logger.error(f"Error reading GNSS: {e}")
            
        # Dummy Battery Data
        try:
            t = now - self.start_time
            # Simulate voltage swinging between 10V and 14V (sine wave)
            fake_voltage = 12.0 + 2.0 * math.sin(t * 0.1)
            fake_current = 2.0 + abs(math.sin(t * 0.5)) * 10.0 # 2A to 12A
            
            battery_data = BatteryMessage(
                timestamp=now,
                voltage=fake_voltage,
                current=fake_current,
                level_pct=max(0.0, min(100.0, (fake_voltage - 10.0) / 4.0 * 100)), # 10V=0%, 14V=100%
                capacity_wh=500.0,
                accumulated_wh=(fake_current * 12.0 * (t / 3600.0)) # Rough energy estimate
            )
            self.battery_pub.publish(battery_data.model_dump())
        except Exception as e:
            logger.error(f"Error publishing Dummy Battery: {e}")

        # Dummy Control Debug Data
        try:
            # Simulate a target heading moving slowly
            fake_target = math.pi * math.sin(t * 0.05)
            # Add some random noise for errors
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

