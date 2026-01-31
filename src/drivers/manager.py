from src.core.config import settings
from src.drivers.base import GNSSDriver
from src.drivers.gnss import SimulatedGNSS, RealGNSS

def get_gnss_driver() -> GNSSDriver:
    if settings.SIMULATION_MODE:
        return SimulatedGNSS()
    else:
        return RealGNSS()
