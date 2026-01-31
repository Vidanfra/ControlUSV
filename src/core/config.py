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

    class Config:
        env_file = ".env"

settings = Settings()
