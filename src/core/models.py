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

class VehicleMode(str, Enum):
    MANUAL = "MANUAL"
    STATION = "STATION"
    WP_ROUTE = "WP_ROUTE"

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
    MUTE_SENSORS = "MUTE_SENSORS"
    UNMUTE_SENSORS = "UNMUTE_SENSORS"
    START_RT_SIM = "START_RT_SIM"
    STOP_RT_SIM = "STOP_RT_SIM"
    MANUAL_INPUT = "MANUAL_INPUT"
    SET_STATION = "SET_STATION"
    START_STATION = "START_STATION"
    STOP_STATION = "STOP_STATION"
    START_WP_ROUTE = "START_WP_ROUTE"
    STOP_WP_ROUTE = "STOP_WP_ROUTE"
    CLEAR_WP_ROUTE = "CLEAR_WP_ROUTE"
    SET_HOME_WP = "SET_HOME_WP"
    SET_FAILSAFE_CONFIG = "SET_FAILSAFE_CONFIG"
    SET_GNC_CONFIG = "SET_GNC_CONFIG"
    SET_LOGGING_CONFIG = "SET_LOGGING_CONFIG"
    LOGGER_START_PREVIEW = "LOGGER_START_PREVIEW"
    LOGGER_STOP_PREVIEW = "LOGGER_STOP_PREVIEW"
    SET_RELAY = "SET_RELAY"               # payload: {idx: 0|1|2, state: 0|1}
    RESTART_RELAY = "RESTART_RELAY"       # payload: {idx: 0|1|2}  (open 5 s, then close)
    SET_RELAY_NAMES = "SET_RELAY_NAMES"   # payload: {names: [str, str, str]}

class Waypoint(BaseModel):
    lat: float
    lon: float
    radius: float = 5.0   # Acceptance radius in meters
    speed: float = 1.0    # Crossing speed in knots (0 = stop, None handled by autopilot)

class MissionPayload(BaseModel):
    waypoints: List[Waypoint]
    loop: bool = False

class FailsafeConfig(BaseModel):
    """Fail-safe configuration parameters."""
    min_battery_pct: float = 25.0
    min_gnss_fix: int = 1
    comm_timeout: float = 10.0
    comm_action: str = "station_keeping"
    ins_timeout: float = 10.0
    ins_action: str = "emergency_stop"

class GncConfig(BaseModel):
    """GNC Controller configuration parameters."""
    wn: float = Field(1.5, gt=0, description="Heading PID Natural Frequency (must be > 0)")
    zeta: float = Field(0.7, gt=0, description="Heading PID Damping (must be > 0)")
    wn_ref: float = Field(0.5, gt=0, description="Reference model natural frequency (must be > 0)")
    zeta_ref: float = Field(1.0, gt=0, description="Reference model damping ratio (must be > 0)")
    k_delta: float = Field(15.0, gt=0, description="ALOS CTE convergence time constant [s]: look-ahead = max(delta_min, k_delta * U). tau_ye = k_delta (constant at all speeds).")
    delta_min: float = Field(5.0, gt=0, description="ALOS minimum look-ahead distance [m] (low-speed floor)")
    gamma: float = Field(0.0, ge=0, description="ALOS Adaptive gain (must be >= 0)")
    cruise_speed_kn: float = Field(3.0, gt=0, le=4.0, description="Cruise speed [knots] (0–4 kn = Salpa 1 Umax)")
    e_x_threshold_deg: float = Field(10.0, gt=0, le=90, description="PID anti-windup threshold [deg] (integrator only active when heading error < this value)")
    accel_ms2: float = Field(0.3, gt=0, description="Acceleration rate when leaving a waypoint [m/s²]. Used by VelocityProfiler for the kinematic ramp-up from v_wp to v_cruise.")
    vel_profiler_enabled: bool = Field(True, description="Enable velocity profiler (trapezoidal speed ramp). When False the controller applies cruise surge force directly.")


class ManualInputMessage(BaseModel):
    """
    Manual control input (arcade style). Abstract XY ready for joystick.
    """
    throttle: float = Field(0.0, description="Throttle: -1.0 (full reverse) to 1.0 (full forward)")
    steering: float = Field(0.0, description="Steering: -1.0 (full left) to 1.0 (full right)")

class CommandMessage(BaseModel):
    """
    Generic Command Message structure.
    """
    timestamp: float = Field(..., description="Unix timestamp of command creation")
    type: CommandType
    payload: Dict[str, Any] = Field(default_factory=dict)
    seq: Optional[int] = Field(None, description="Monotonic per-WS-session sequence number; backend dedups by (connection, seq)")

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
    source: str = Field("sensor", description="Data source: 'sensor' or 'sim'")

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

    # Data source tag
    source: str = "sensor"

class USVState(BaseModel):
    """
    State estimation of the vehicle (output of navigation/EKF filter).
    Published on gnc/ekf_state. Consumed by GNC, Dashboard, Map, MAVLink.
    """
    timestamp: float
    
    # Position (Global)
    lat: float
    lon: float
    altitude: float = 0.0
    
    # Velocity (m/s)
    speed: float = Field(0.0, description="Speed over ground")
    course: float = Field(0.0, description="Course over ground in radians")
    
    # Attitude (radians)
    heading: float = Field(0.0, description="Heading/Yaw in radians")
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    
    # Heading quality
    heading_status: str = Field("", description="A=GNSS dual-antenna, M=magnetic, S=simulated")
    
    # Data source tag
    source: str = Field("sensor", description="Data source: 'sensor' or 'sim'")

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
    # Surge/sway velocity and acceleration for the speed monitor chart
    surge_vel: float = Field(0.0, description="Body-frame surge velocity u [m/s]")
    sway_vel: float = Field(0.0, description="Body-frame sway velocity v [m/s]")
    surge_acc: float = Field(0.0, description="Surge acceleration du/dt [m/s²]")
    sway_acc: float = Field(0.0, description="Sway acceleration dv/dt [m/s²]")
    tau_x_eff: float = Field(0.0, description="Effective surge force after velocity profiler [N]")
    tau_x_cruise: float = Field(0.0, description="Nominal cruise surge force [N]")
    v_cruise: float = Field(0.0, description="Equilibrium cruise speed [m/s]")
    wp_index: int = Field(0, description="Current (from) waypoint index")
    dist_to_wp: float = Field(0.0, description="Distance to next waypoint [m]")
    ref_speed_kn: float = Field(0.0, description="Reference speed from tau_x_eff drag inversion [kn]")
    ett_next_wp: float = Field(-1.0, description="Estimated travel time to next WP [s]; -1 if unavailable")
    eta_next_wp: float = Field(0.0, description="ETA at next WP [Unix timestamp]; 0 if unavailable")
    ett_route_end: float = Field(-1.0, description="Estimated travel time to end of route [s]; -1 if not in WP route mode")
    eta_route_end: float = Field(0.0, description="ETA at end of route [Unix timestamp]; 0 if not applicable")
    kp_m: float = Field(0.0, description="Chainage along the original forward route [m]")


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
    start_mode: str = Field("first_wp", description="'first_wp', 'last_wp', or 'current_pos'")
    completion_mode: str = Field("stop_time", description="'stop_time', 'one_way', 'loop', 'loop_reverse'")


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


class RTSimConfig(BaseModel):
    """Configuration for real-time simulation."""
    waypoints: List[Waypoint] = Field(default_factory=list)
    manual_mode: bool = Field(False, description="If True, manual inputs control the simulated vessel")
    start_mode: str = Field("first_wp", description="'first_wp' or 'last_wp'")
    completion_mode: str = Field("one_way", description="'stop_time', 'one_way', 'loop', 'loop_reverse'")
    total_time: float = Field(600.0, description="Max sim time [s] (for stop_time mode)")
    time_step: float = Field(0.05, description="Simulation time step [s]")
    gnss_mode: str = Field("rtk_fix", description="'rtk_fix', 'dgnss', or 'gps'")
    payload_kg: float = Field(25.0, description="Payload mass [kg]")
    current_speed: float = Field(0.0, description="Ocean current speed [m/s]")
    current_dir: float = Field(0.0, description="Ocean current direction [deg]")
    surge_force: float = Field(150.0, description="Surge force [N]")
    wn_pid: float = Field(4.0, description="PID natural frequency [rad/s]")
    zeta_pid: float = Field(0.5, description="PID damping ratio")
    wn_ref: float = Field(1.0, description="Reference model natural frequency [rad/s]")
    zeta_ref: float = Field(1.0, description="Reference model damping ratio")
    delta: float = Field(5.0, description="ALOS look-ahead distance [m]")
    gamma: float = Field(0.0, description="ALOS adaptive sideslip gain")
    # Start position (used when start_mode='current_pos')
    current_lat: float = Field(0.0)
    current_lon: float = Field(0.0)
    current_heading: float = Field(0.0)


class RTSimStatus(BaseModel):
    """Status of the real-time simulation (published on sim/status)."""
    timestamp: float
    running: bool = False
    elapsed_time: float = 0.0
    total_time: float = 0.0
    completion_mode: str = ""
    gnss_mode: str = ""
    current_wp: int = 0
    total_wp: int = 0
    loops_completed: int = 0


# ============================================================================
# SYSTEM MONITOR (Raspberry / host telemetry)
# ============================================================================

class SystemMonitorMessage(BaseModel):
    """Host system telemetry (CPU, RAM, disk, temperature, network).
    Published on system/monitor at 1 Hz by SystemMonitorProcess.
    """
    timestamp: float = Field(..., description="Unix timestamp")
    cpu_percent: float = Field(0.0, description="CPU usage [%]")
    cpu_temp_c: float = Field(0.0, description="CPU temperature [°C]; 0 if unavailable")
    ram_used_mb: float = Field(0.0, description="RAM used [MB]")
    ram_total_mb: float = Field(0.0, description="RAM total [MB]")
    ram_percent: float = Field(0.0, description="RAM used [%]")
    disk_used_gb: float = Field(0.0, description="Root disk used [GB]")
    disk_total_gb: float = Field(0.0, description="Root disk total [GB]")
    disk_percent: float = Field(0.0, description="Root disk used [%]")
    uptime_s: float = Field(0.0, description="System uptime [s]")
    net_rx_kbps: float = Field(0.0, description="Network RX rate [kbps]")
    net_tx_kbps: float = Field(0.0, description="Network TX rate [kbps]")
    hostname: str = Field("", description="Host name")
    os_name: str = Field("", description="OS family: 'Linux' | 'Windows' | 'Darwin'")


# ============================================================================
# LOGGING (CSV file loggers + JSON network broadcasters)
# ============================================================================

class CsvLoggerConfig(BaseModel):
    """One CSV-file logger."""
    id: str = Field(..., description="Stable unique id")
    name: str = Field(..., description="Operator-chosen base file name (no extension)")
    enabled: bool = True
    frequency_value: float = Field(1.0, gt=0, description="Numeric frequency value")
    frequency_unit: str = Field("hz", description="'hz' (samples/s) or 's' (period in seconds)")
    rotation_hours: float = Field(1.0, gt=0, description="Rotate to a new file every N hours")
    output_path: str = Field(..., description="Output directory (created if missing)")
    fields: List[str] = Field(default_factory=list, description="Field IDs from LOG_FIELD_CATALOG (timestamp_utc is always prepended)")


class JsonBroadcasterConfig(BaseModel):
    """One JSON network broadcaster (UDP or TCP server)."""
    id: str = Field(..., description="Stable unique id")
    name: str = Field(..., description="Operator-chosen name (label only)")
    enabled: bool = True
    frequency_value: float = Field(1.0, gt=0, description="Numeric frequency value")
    frequency_unit: str = Field("hz", description="'hz' or 's'")
    protocol: str = Field("udp", description="'udp' (sendto host:port) or 'tcp' (server bound to host:port)")
    host: str = Field("127.0.0.1", description="UDP destination host or TCP bind address")
    port: int = Field(9999, gt=0, lt=65536, description="UDP destination port or TCP listen port")
    fields: List[str] = Field(default_factory=list, description="Field IDs from LOG_FIELD_CATALOG (timestamp_utc is always included)")


class LoggingConfig(BaseModel):
    """All loggers + broadcasters managed by LoggerProcess."""
    csv_loggers: List[CsvLoggerConfig] = Field(default_factory=list)
    json_broadcasters: List[JsonBroadcasterConfig] = Field(default_factory=list)


# ============================================================================
# RELAYS (ESP32 R1 / R2 / R3 — power-cycle of internal subsystems)
# ============================================================================

class RelayConfig(BaseModel):
    """Persistent relay state for the three ESP32 relays.

    Index order MUST match the firmware command order (R1, R2, R3).
    The relays power the internal comms router and two sensor payloads;
    their main purpose is hard-restarting those subsystems.
    """
    names: List[str] = Field(
        default_factory=lambda: ["Relay 1", "Relay 2", "Relay 3"],
        description="Display names — order is fixed (idx 0 = R1, 1 = R2, 2 = R3).",
    )
    states: List[int] = Field(
        default_factory=lambda: [1, 1, 1],
        description="Latched state for each relay (1 = closed/ON, 0 = open/OFF).",
    )
    # Per-index Unix timestamp until which the relay is held in the
    # 'restart' (open) pulse. 0 = no restart pending. Not editable directly.
    restart_until: List[float] = Field(
        default_factory=lambda: [0.0, 0.0, 0.0],
        description="Internal: timestamp at which the 5-second restart pulse ends.",
    )
