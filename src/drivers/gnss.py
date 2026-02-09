import time
import math
import random
from src.drivers.base import GNSSDriver
from src.core.models import GNSSData
from loguru import logger

class SimulatedGNSS(GNSSDriver):
    def __init__(self):
        self.center_lat = 39.5
        self.center_lon = 2.4
        self.radius = 0.001
        self.start_time = time.time()
        logger.info("Simulated GNSS Driver initialized.")

    def read(self) -> GNSSData:
        t = time.time() - self.start_time
        # Circular path
        offset_lat = self.radius * math.cos(t * 0.01) + 0.0002 * math.sin(t * 0.2) + 0.000001 * random.random() # Add some noise
        offset_lon = self.radius * math.sin(t * 0.02) + 0.0001 * math.cos(t * 0.1) + 0.000001 * random.random()  # Add some noise
        
        return GNSSData(
            timestamp=time.time(),
            lat=self.center_lat + offset_lat,
            lon=self.center_lon + offset_lon,
            alt=10.0,
            fix_type=3
        )

class RealGNSS(GNSSDriver):
    def __init__(self):
        logger.info("Real GNSS Driver initialized (Not Implemented).")

    def read(self) -> GNSSData:
        # Placeholder
        return GNSSData(
            timestamp=time.time(),
            lat=0.0,
            lon=0.0,
            fix_type=0
        )
