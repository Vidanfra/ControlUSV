from src.core.process import ServiceProcess
from src.core.messaging import PubSubBroker, Publisher, Subscriber, Topics
from src.core.models import (
    CommandMessage, CommandType, USVState, VehicleMode,
    FailsafeConfig, GncConfig, LoggingConfig,
)
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
        # 1. Subscribe to User Commands + GNSS for fix type + GNC internal sync
        self.cmd_sub = Subscriber([Topics.COMMAND_USER])
        self.gnss_sub = Subscriber([Topics.SENSOR_GNSS])
        self.sync_sub = Subscriber([Topics.GNC_SYNC])
        
        # 2. Publishers
        self.status_pub = Publisher(Topics.SYSTEM_STATUS)
        self.control_cmd_pub = Publisher(Topics.CONTROL_CMD)
        self.sync_pub = Publisher(Topics.GNC_SYNC)
        
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
        self.wp_route_waypoints = []       # [{lat, lon, radius, speed}]
        self.wp_route_direction = 'forward'
        self.wp_route_completion = 'stop'
        
        # Fail-safe state
        self.home_wp = None  # {lat, lon}
        self.failsafe_config = FailsafeConfig()
        self.gnc_config = GncConfig()
        self.logging_config = LoggingConfig()
        self.gnss_fix_type = 0

        # Load previously saved user settings (overrides defaults above)
        self._load_settings()

        # Publish loaded logging_config so LoggerProcess starts with the right
        # state after a backend restart. Tiny delay so subscribers attach first.
        time.sleep(0.5)
        try:
            self.sync_pub.publish({
                "op": "logging_config",
                "logging_config": self.logging_config.model_dump(),
            })
        except Exception:
            pass

        logger.info("Manager Process Initialized. Waiting for commands...")

    def loop(self):
        # 1. Process Incoming Commands (bounded drain so one bursty reconnect
        # cannot starve the GNSS subscriber for a whole loop tick)
        for _ in range(50):
            msg = self.cmd_sub.receive(timeout_ms=0)
            if msg is None:
                break
            
            topic, payload = msg
            if topic == Topics.COMMAND_USER.value:
                self.handle_command(payload)

        # 2. Consume GNSS for fix type tracking
        for _ in range(50):
            msg = self.gnss_sub.receive(timeout_ms=0)
            if msg is None:
                break
            _, data = msg
            self.gnss_fix_type = data.get('fix_type', self.gnss_fix_type)

        # 3. Consume GNC internal sync (failsafe-driven state updates)
        for _ in range(50):
            msg = self.sync_sub.receive(timeout_ms=0)
            if msg is None:
                break
            _, data = msg
            self._handle_gnc_sync(data)

        # 4. Publish System Status Heartbeat
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
            "wp_route_waypoints": self.wp_route_waypoints,
            "wp_route_direction": self.wp_route_direction,
            "wp_route_completion": self.wp_route_completion,
            "gnss_fix_type": self.gnss_fix_type,
            "home_wp": self.home_wp,
            "failsafe_config": self.failsafe_config.model_dump(),
            "gnc_config": self.gnc_config.model_dump(),
            "logging_config": self.logging_config.model_dump(),
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
                self._save_settings()
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
                # Persist the full mission so it survives page refresh / reconnects.
                wps = cmd.payload.get('waypoints')
                if wps:
                    self.wp_route_waypoints = wps
                self.wp_route_direction  = cmd.payload.get('direction',  self.wp_route_direction)
                self.wp_route_completion = cmd.payload.get('completion', self.wp_route_completion)
                self.wp_route_active = True
                self._save_settings()
                logger.info(f"WP Route STARTED: {len(self.wp_route_waypoints)} waypoints, dir={self.wp_route_direction}")

            elif cmd.type == CommandType.STOP_WP_ROUTE:
                self.wp_route_active = False
                logger.info("WP Route STOPPED")

            elif cmd.type == CommandType.CLEAR_WP_ROUTE:
                self.wp_route_active = False
                self.wp_route_waypoints = []
                self.wp_route_direction = 'forward'
                self.wp_route_completion = 'stop'
                self._save_settings()
                logger.info("WP Route CLEARED")

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

            elif cmd.type == CommandType.SET_LOGGING_CONFIG:
                try:
                    self.logging_config = LoggingConfig(**(cmd.payload or {}))
                    logger.info(
                        f"Logging config updated: "
                        f"csv={len(self.logging_config.csv_loggers)}, "
                        f"json={len(self.logging_config.json_broadcasters)}"
                    )
                    self._save_settings()
                    # Notify LoggerProcess via GNC_SYNC
                    self.sync_pub.publish({
                        "op": "logging_config",
                        "logging_config": self.logging_config.model_dump(),
                    })
                except Exception as e:
                    logger.error(f"Invalid logging config: {e}")

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
    #  GNC internal sync (failsafe-driven state updates)
    # ----------------------------------------------------------------

    def _handle_gnc_sync(self, data: dict):
        """Apply state updates published by GNC on Topics.GNC_SYNC.

        These reflect failsafe transitions GNC has ALREADY executed locally
        (motors zeroed, mode swapped). Manager only mirrors the resulting
        bookkeeping so the frontend heartbeat tells the truth.
        """
        op = data.get('op')
        if op == 'emergency_stop':
            self.is_armed = False
            self.station_active = False
            self.wp_route_active = False
            logger.warning("Manager: GNC reports EMERGENCY_STOP \u2014 mirroring state")
        elif op == 'failsafe_station':
            self.wp_route_active = False
            wp = data.get('station_wp') or {}
            self.station_wp = {"lat": wp.get('lat'), "lon": wp.get('lon')}
            self.station_reaching_radius = data.get('reaching_radius', self.station_reaching_radius)
            self.station_radius = data.get('station_radius', self.station_radius)
            self.station_active = True
            logger.warning(f"Manager: GNC reports FAILSAFE_STATION at {self.station_wp}")
        elif op == 'failsafe_return_home':
            self.station_active = False
            self.wp_route_active = True
            logger.warning("Manager: GNC reports FAILSAFE_RETURN_HOME \u2014 WP route active")
        elif op == 'logging_config':
            # Manager publishes this for LoggerProcess; ignore the echo of our own message.
            pass
        else:
            logger.warning(f"Manager: unknown GNC sync op '{op}'")

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
                if 'wp_route_waypoints' in data:
                    self.wp_route_waypoints = data['wp_route_waypoints']
                if 'wp_route_direction' in data:
                    self.wp_route_direction = data['wp_route_direction']
                if 'wp_route_completion' in data:
                    self.wp_route_completion = data['wp_route_completion']
                # Safety: never auto-resume an active mission on backend restart.
                # wp_route_active / station_active are reset to False so the
                # operator must explicitly press START again.
                if 'station_wp' in data:
                    self.station_wp = data['station_wp']
                if 'station_reaching_radius' in data:
                    self.station_reaching_radius = data['station_reaching_radius']
                if 'station_radius' in data:
                    self.station_radius = data['station_radius']
                if 'logging_config' in data:
                    try:
                        self.logging_config = LoggingConfig(**data['logging_config'])
                    except Exception as e:
                        logger.warning(f"Manager: invalid stored logging_config ({e})")
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
                    'wp_route_waypoints': self.wp_route_waypoints,
                    'wp_route_direction': self.wp_route_direction,
                    'wp_route_completion': self.wp_route_completion,
                    'station_wp': self.station_wp,
                    'station_reaching_radius': self.station_reaching_radius,
                    'station_radius': self.station_radius,
                    'logging_config': self.logging_config.model_dump(),
                }, f, indent=2)
        except Exception as e:
            logger.warning(f"Manager: could not save settings: {e}")
