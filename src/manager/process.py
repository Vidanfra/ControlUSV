from src.core.process import ServiceProcess
from src.core.messaging import PubSubBroker, Publisher, Subscriber, Topics
from src.core.models import CommandMessage, CommandType, USVState, VehicleMode, FailsafeConfig, GncConfig
from src.core.config import settings
from loguru import logger
import json
import os
import time

# Persisted user settings survive backend restarts.
# Path is relative to the project root (two levels above this file).
_SETTINGS_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'manager_settings.json')

class ManagerProcess(ServiceProcess):
    def setup(self):
        # 1. Subscribe to User Commands + GNSS for fix type
        self.cmd_sub = Subscriber([Topics.COMMAND_USER])
        self.gnss_sub = Subscriber([Topics.SENSOR_GNSS])
        
        # 2. Publishers
        self.status_pub = Publisher(Topics.SYSTEM_STATUS)
        self.control_cmd_pub = Publisher(Topics.CONTROL_CMD)
        
        # 3. State
        self.is_armed = False
        self.mode = VehicleMode.MANUAL.value
        self.sim_mode = "REAL"
        
        # Station keeping state
        self.station_wp = None       # {lat, lon}
        self.station_reaching_radius = 3.0
        self.station_radius = 10.0
        self.station_active = False
        
        # WP Route state
        self.wp_route_active = False
        
        # Fail-safe state
        self.home_wp = None  # {lat, lon}
        self.failsafe_config = FailsafeConfig()
        self.gnc_config = GncConfig()
        self.gnss_fix_type = 0
        self.battery_level_pct = 0.0
        self.last_command_time = time.time()

        # Load previously saved user settings (overrides defaults above)
        self._load_settings()

        logger.info("Manager Process Initialized. Waiting for commands...")

    def loop(self):
        # 1. Process Incoming Commands
        while True:
            msg = self.cmd_sub.receive(timeout_ms=0)
            if msg is None:
                break
            
            topic, payload = msg
            if topic == Topics.COMMAND_USER.value:
                self.handle_command(payload)
                self.last_command_time = time.time()

        # 2. Consume GNSS for fix type tracking
        while True:
            msg = self.gnss_sub.receive(timeout_ms=0)
            if msg is None:
                break
            _, data = msg
            self.gnss_fix_type = data.get('fix_type', self.gnss_fix_type)

        # 3. Publish System Status Heartbeat
        status_payload = {
            "timestamp": time.time(),
            "is_armed": self.is_armed,
            "mode": self.mode,
            "sim_mode": self.sim_mode,
            "station_active": self.station_active,
            "station_wp": self.station_wp,
            "station_reaching_radius": self.station_reaching_radius,
            "station_radius": self.station_radius,
            "wp_route_active": self.wp_route_active,
            "gnss_fix_type": self.gnss_fix_type,
            "battery_level_pct": self.battery_level_pct,
            "home_wp": self.home_wp,
            "failsafe_config": self.failsafe_config.model_dump(),
            "gnc_config": self.gnc_config.model_dump(),
            "battery_voltage": 12.6,
            "system_status": "ACTIVE"
        }
        self.status_pub.publish(status_payload)

    def handle_command(self, payload_dict):
        try:
            cmd = CommandMessage(**payload_dict)
            if cmd.type != CommandType.MANUAL_INPUT:
                logger.info(f"Manager received command: {cmd.type}")

            if cmd.type == CommandType.ARM:
                if self.sim_mode == 'SIMULATION':
                    logger.warning("Manager: ARM rejected — RT simulation is active")
                else:
                    self.is_armed = True
                    logger.warning(">>> VEHICLE ARMED <<<")
                
            elif cmd.type == CommandType.DISARM:
                self.is_armed = False
                logger.warning(">>> VEHICLE DISARMED <<<")
                
            elif cmd.type == CommandType.SET_MODE:
                new_mode = cmd.payload.get("mode")
                if new_mode and new_mode in [m.value for m in VehicleMode]:
                    self.mode = new_mode
                    # Deactivate station/route when switching modes
                    if new_mode != VehicleMode.STATION.value:
                        self.station_active = False
                    if new_mode != VehicleMode.WP_ROUTE.value:
                        self.wp_route_active = False
                    logger.info(f"Mode changed to: {self.mode}")
                else:
                    logger.warning(f"Invalid mode requested: {new_mode}")

            elif cmd.type == CommandType.MANUAL_INPUT:
                throttle = cmd.payload.get("throttle", 0.0)
                steering = cmd.payload.get("steering", 0.0)
                # Arcade differential mixing: port = throttle + steering, stbd = throttle - steering
                port_pct = max(-100, min(100, (throttle + steering) * 100))
                stbd_pct = max(-100, min(100, (throttle - steering) * 100))
                # Only drive real hardware in REAL mode when ARMED.
                # In SIM mode the GNC physics process handles the command.
                if self.is_armed and self.mode == VehicleMode.MANUAL.value and self.sim_mode == 'REAL':
                    self.control_cmd_pub.publish({
                        'timestamp': time.time(),
                        'port_pct': port_pct,
                        'starboard_pct': stbd_pct,
                        'n1_rads': 0.0,
                        'n2_rads': 0.0,
                        'source': 'manual',
                    })
            
            elif cmd.type == CommandType.SET_STATION:
                self.station_wp = {
                    "lat": cmd.payload.get("lat"),
                    "lon": cmd.payload.get("lon")
                }
                self.station_reaching_radius = cmd.payload.get("reaching_radius", 3.0)
                self.station_radius = cmd.payload.get("station_radius", 10.0)
                logger.info(f"Station WP set: {self.station_wp}, reaching: {self.station_reaching_radius}m, station: {self.station_radius}m")

            elif cmd.type == CommandType.START_STATION:
                if 'cruise_speed_kn' in cmd.payload:
                    self.gnc_config.cruise_speed_kn = cmd.payload['cruise_speed_kn']
                    self._save_settings()
                self.station_active = True
                logger.info("Station keeping STARTED")

            elif cmd.type == CommandType.STOP_STATION:
                self.station_active = False
                logger.info("Station keeping STOPPED")

            elif cmd.type == CommandType.START_WP_ROUTE:
                if 'cruise_speed_kn' in cmd.payload:
                    self.gnc_config.cruise_speed_kn = cmd.payload['cruise_speed_kn']
                    self._save_settings()
                self.wp_route_active = True
                logger.info(f"WP Route STARTED: {cmd.payload}")

            elif cmd.type == CommandType.STOP_WP_ROUTE:
                self.wp_route_active = False
                logger.info("WP Route STOPPED")

            elif cmd.type == CommandType.SET_HOME_WP:
                self.home_wp = {
                    "lat": cmd.payload.get("lat"),
                    "lon": cmd.payload.get("lon")
                }
                logger.info(f"Home WP set: {self.home_wp}")
                self._save_settings()

            elif cmd.type == CommandType.SET_FAILSAFE_CONFIG:
                try:
                    self.failsafe_config = FailsafeConfig(**cmd.payload)
                    logger.info(f"Failsafe config updated: {self.failsafe_config}")
                    self._save_settings()
                except Exception as e:
                    logger.error(f"Invalid failsafe config: {e}")

            elif cmd.type == CommandType.SET_GNC_CONFIG:
                try:
                    # Merge into existing config so partial payloads (e.g. only
                    # cruise_speed_kn) don't reset unrelated fields to defaults.
                    merged = {**self.gnc_config.model_dump(), **cmd.payload}
                    self.gnc_config = GncConfig(**merged)
                    logger.info(f"GNC config updated: {self.gnc_config}")
                    self._save_settings()
                except Exception as e:
                    logger.error(f"Invalid GNC config: {e}")

            elif cmd.type == CommandType.START_RT_SIM:
                self.sim_mode = 'SIMULATION'
                self.is_armed = False   # Real motors must never run during simulation
                logger.info("Manager: RT Simulation STARTED — vehicle auto-DISARMED")

            elif cmd.type == CommandType.STOP_RT_SIM:
                self.sim_mode = 'REAL'
                logger.info("Manager: RT Simulation STOPPED — back to REAL mode")

        except Exception as e:
            logger.error(f"Failed to handle command: {e}")

    # ----------------------------------------------------------------
    #  Settings persistence
    # ----------------------------------------------------------------

    def _load_settings(self):
        """Load user-configured settings from JSON file, if it exists."""
        try:
            if os.path.exists(_SETTINGS_FILE):
                with open(_SETTINGS_FILE, 'r') as f:
                    data = json.load(f)
                if 'gnc_config' in data:
                    self.gnc_config = GncConfig(**data['gnc_config'])
                if 'failsafe_config' in data:
                    self.failsafe_config = FailsafeConfig(**data['failsafe_config'])
                if 'home_wp' in data:
                    self.home_wp = data['home_wp']
                logger.info(f"Manager: settings loaded from {_SETTINGS_FILE}")
        except Exception as e:
            logger.warning(f"Manager: could not load settings ({e}), using defaults")

    def _save_settings(self):
        """Persist user-configured settings to JSON file."""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(_SETTINGS_FILE)), exist_ok=True)
            with open(_SETTINGS_FILE, 'w') as f:
                json.dump({
                    'gnc_config': self.gnc_config.model_dump(),
                    'failsafe_config': self.failsafe_config.model_dump(),
                    'home_wp': self.home_wp,
                }, f, indent=2)
        except Exception as e:
            logger.warning(f"Manager: could not save settings: {e}")
