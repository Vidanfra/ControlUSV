from src.core.process import ServiceProcess
from src.core.messaging import Publisher, Topics
from src.drivers.manager import get_gnss_driver
from src.core.config import settings
from loguru import logger

class HALProcess(ServiceProcess):
    def setup(self):
        self.gnss_driver = get_gnss_driver()
        self.gnss_pub = Publisher(Topics.SENSOR_GNSS)
        logger.info(f"HAL Initialized with GNSS Driver: {self.gnss_driver.__class__.__name__}")

    def loop(self):
        # Read GNSS
        try:
            gnss_data = self.gnss_driver.read()
            self.gnss_pub.publish(gnss_data.model_dump())
            # Optional: Log occasionally to prove it's working
            # logger.debug(f"Published GNSS: {gnss_data.lat:.6f}, {gnss_data.lon:.6f}")
        except Exception as e:
            logger.error(f"Error reading GNSS: {e}")
