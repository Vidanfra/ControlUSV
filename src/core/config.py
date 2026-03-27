from pydantic_settings import BaseSettings
from typing import Dict

class Settings(BaseSettings):
    SIMULATION_MODE: bool = True
    ZMQ_PORT: int = 5555
    LOG_LEVEL: str = "INFO"
    LOOP_RATES: Dict[str, int] = {
        "hal": 50,
        "gnc": 20,
        "manager": 10
    }

    # Fail-safe parameters
    FAILSAFE_MIN_BATTERY_PCT: float = 25.0
    FAILSAFE_MIN_GNSS_FIX: int = 1        # 0=NoFix, 1=GPS, 2=DGPS, 4=RTK Fix, 5=RTK Float
    FAILSAFE_COMM_TIMEOUT: float = 10.0    # seconds
    FAILSAFE_COMM_ACTION: str = "station_keeping"  # 'station_keeping' or 'return_home'
    FAILSAFE_INS_TIMEOUT: float = 10.0     # seconds without GNSS before action
    FAILSAFE_INS_ACTION: str = "emergency_stop"    # 'emergency_stop' or 'station_keeping'

    class Config:
        env_file = ".env"

settings = Settings()
