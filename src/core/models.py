from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum

class CommandType(str, Enum):
    ARM = "ARM"
    DISARM = "DISARM"
    SET_MODE = "SET_MODE"
    UPLOAD_MISSION = "UPLOAD_MISSION"
    RTL = "RTL"
    EMERGENCY_STOP = "EMERGENCY_STOP"

class Waypoint(BaseModel):
    lat: float
    lon: float
    radius: float = 2.0  # Acceptance radius in meters

class MissionPayload(BaseModel):
    waypoints: List[Waypoint]
    loop: bool = False

class CommandMessage(BaseModel):
    """
    Generic Command Message structure.
    """
    timestamp: float = Field(..., description="Unix timestamp of command creation")
    type: CommandType
    payload: Dict[str, Any] = Field(default_factory=dict)

class GNSSData(BaseModel):
    """
    Raw data from GNSS/GPS sensor.
    """
    timestamp: float = Field(..., description="Unix timestamp of the measurement")
    lat: float = Field(..., description="Latitude in degrees")
    lon: float = Field(..., description="Longitude in degrees")
    alt: float = Field(0.0, description="Altitude in meters (AMSL)")
    fix_type: int = Field(0, description="0: No fix, 1: 2D, 2: 3D, etc.")
    num_satellites: int = Field(0, description="Number of satellites used")
    hdop: float = Field(99.99, description="Horizontal Dilution of Precision")

class IMUData(BaseModel):
    """
    Raw data from IMU (Inertial Measurement Unit).
    """
    timestamp: float = Field(..., description="Unix timestamp of the measurement")
    
    # Accelerometer (m/s^2)
    accel_x: float
    accel_y: float
    accel_z: float
    
    # Gyroscope (rad/s)
    gyro_x: float
    gyro_y: float
    gyro_z: float
    
    # Magnetometer (uT typically, units depend on driver, assuming normalized or raw)
    mag_x: Optional[float] = None
    mag_y: Optional[float] = None
    mag_z: Optional[float] = None

class USVState(BaseModel):
    """
    State estimation of the vehicle (output of EKF/Filter).
    """
    timestamp: float
    
    # Position (Global)
    lat: float
    lon: float
    
    # Velocity (m/s)
    speed: float = Field(..., description="Speed over ground")
    course: float = Field(..., description="Course over ground in radians")
    
    # Attitude (radians)
    heading: float = Field(..., description="Heading/Yaw in radians")
    roll: float = 0.0
    pitch: float = 0.0
    
    # System status
    battery_voltage: float = 0.0
    system_status: str = "INIT"
