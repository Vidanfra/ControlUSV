from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum

class SensorStatus(str, Enum):
    OK = "ok"
    DISCONNECTED = "disconnected"
    ERROR = "error"

class SensorStatusMessage(BaseModel):
    """
    Health status of a sensor node. Published on sensor/status.
    """
    timestamp: float = Field(..., description="Unix timestamp")
    sensor: str = Field(..., description="Sensor identifier: gnss, imu, power")
    status: SensorStatus = Field(..., description="Current status")
    message: str = Field("", description="Human-readable status detail")

class CommandType(str, Enum):
    ARM = "ARM"
    DISARM = "DISARM"
    SET_MODE = "SET_MODE"
    UPLOAD_MISSION = "UPLOAD_MISSION"
    RTL = "RTL"
    EMERGENCY_STOP = "EMERGENCY_STOP"
    RESET_ENERGY = "RESET_ENERGY"
    SET_BATTERY_CAPACITY = "SET_BATTERY_CAPACITY"
    SET_GNSS_CONFIG = "SET_GNSS_CONFIG"
    RUN_SIMULATION = "RUN_SIMULATION"
    CLEAR_SIM_OVERLAY = "CLEAR_SIM_OVERLAY"

class Waypoint(BaseModel):
    lat: float
    lon: float
    radius: float = 5.0   # Acceptance radius in meters
    speed: float = 1.0    # Desired speed in m/s

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
    Raw data from GNSS/GPS sensor (UM982 dual-antenna receiver).
    """
    timestamp: float = Field(..., description="Unix timestamp of the measurement")
    lat: float = Field(0.0, description="Latitude in degrees")
    lon: float = Field(0.0, description="Longitude in degrees")
    alt: float = Field(0.0, description="Altitude in meters (AMSL)")
    fix_type: int = Field(0, description="GGA quality: 0=No fix, 1=GPS, 2=DGPS, 4=RTK Fix, 5=RTK Float")
    num_satellites: int = Field(0, description="Number of satellites used")
    hdop: float = Field(99.99, description="Horizontal Dilution of Precision")
    vdop: float = Field(99.99, description="Vertical Dilution of Precision")
    heading: float = Field(0.0, description="True heading from dual-antenna THS (degrees)")
    heading_status: str = Field("", description="THS status: A=autonomous, E=estimated, M=manual, V=void")
    cog: float = Field(0.0, description="Course over ground (degrees true)")
    sog_knots: float = Field(0.0, description="Speed over ground in knots")
    sog_kmh: float = Field(0.0, description="Speed over ground in km/h")
    utc_time: str = Field("", description="UTC time string from ZDA (HH:MM:SS)")
    utc_date: str = Field("", description="UTC date string from ZDA (DD/MM/YYYY)")

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


# ============================================================================
# SIMULATION MODELS
# ============================================================================

class SimulationConfig(BaseModel):
    """One simulation profile configuration."""
    profile_id: int = 0
    payload_kg: float = Field(25.0, description="Payload mass [kg]")
    wn_pid: float = Field(4.0, description="PID natural frequency [rad/s]")
    zeta_pid: float = Field(0.5, description="PID damping ratio")
    wn_ref: float = Field(1.0, description="Reference model natural frequency [rad/s]")
    zeta_ref: float = Field(1.0, description="Reference model damping ratio")
    delta: float = Field(5.0, description="ALOS look-ahead distance [m]")
    gamma: float = Field(0.0, description="ALOS adaptive sideslip gain")
    current_speed: float = Field(0.0, description="Ocean current speed [m/s]")
    current_dir: float = Field(0.0, description="Ocean current direction [deg]")
    surge_force: float = Field(150.0, description="Surge force [N]")
    start_mode: str = Field("first_wp", description="'current_pos' or 'first_wp'")


class SimulationRequest(BaseModel):
    """Request to run one or more simulations."""
    configs: List[SimulationConfig]
    waypoints: List[Waypoint]
    total_time: float = Field(400.0, description="Total simulation time [s]")
    time_step: float = Field(0.02, description="Simulation time step [s]")
    # If start_mode='current_pos', these are used:
    current_lat: float = Field(0.0, description="Current USV latitude [deg]")
    current_lon: float = Field(0.0, description="Current USV longitude [deg]")
    current_heading: float = Field(0.0, description="Current USV heading [deg]")


class SimulationResult(BaseModel):
    """Result of one simulation profile."""
    profile_id: int
    config: SimulationConfig
    time: List[float]
    lat: List[float]
    lon: List[float]
    N: List[float]
    E: List[float]
    psi: List[float]
    psi_d: List[float]
    speed: List[float]
    cte: List[float]
    n1: List[float]
    n2: List[float]
    psi_error: List[float]
    wp_reached: List[int]
