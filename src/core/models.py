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
    RESET_ENERGY = "RESET_ENERGY"
    SET_BATTERY_CAPACITY = "SET_BATTERY_CAPACITY"

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

class ImuMessage(BaseModel):
    """
    Detailed data from IMU (Inertial Measurement Unit), adapted for WT901C but universalized.
    """
    timestamp: float = Field(..., description="Unix timestamp of the measurement")

    # Angles (deg or rad, typically we use deg for raw messages until EKF)
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0

    # Accelerometer (m/s^2)
    ax: float = 0.0
    ay: float = 0.0
    az: float = 0.0

    # Gyroscope (deg/s)
    wx: float = 0.0
    wy: float = 0.0
    wz: float = 0.0

    # Magnetometer
    mx: float = 0.0
    my: float = 0.0
    mz: float = 0.0
    
    # Internal Temp
    temp: float = 0.0
    
    # Computed mag compass heading
    mag_heading: float = 0.0

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

class BatteryMessage(BaseModel):
    """
    Battery / Power telemetry from PZEM-017 or simulation.
    """
    timestamp: float = Field(..., description="Unix timestamp of the measurement")
    voltage: float = Field(..., description="Battery voltage in V")
    current: float = Field(..., description="Battery current in A")
    power: float = Field(0.0, description="Instantaneous power in W")
    energy_wh: int = Field(0, description="PZEM hardware energy counter in Wh")
    level_pct: float = Field(0.0, description="Estimated battery level 0-100%")
    capacity_wh: float = Field(500.0, description="Total battery capacity in Wh")
    accumulated_wh: float = Field(0.0, description="Software-integrated consumed energy in Wh")
    measurement_start: float = Field(0.0, description="Unix timestamp when energy measurement started")
    high_voltage_alarm: int = Field(0, description="High voltage alarm status")
    low_voltage_alarm: int = Field(0, description="Low voltage alarm status")

class ControlDebugMessage(BaseModel):
    """
    GNC Control Debugging data for charts/UI.
    """
    timestamp: float = Field(..., description="Unix timestamp of the calculation")
    target_heading: float = Field(..., description="Target heading in radians")
    heading_error: float = Field(..., description="Heading error in radians")
    cross_track_error: float = Field(..., description="Cross-track error in meters")
