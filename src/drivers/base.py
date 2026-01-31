import abc
from typing import Any

class SensorDriver(abc.ABC):
    @abc.abstractmethod
    def read(self) -> Any:
        """Reads data from the sensor and returns it."""
        pass

class GNSSDriver(SensorDriver):
    """Interface for GNSS/GPS Drivers"""
    pass
