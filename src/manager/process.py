from src.core.process import ServiceProcess
from src.core.messaging import PubSubBroker, Publisher, Subscriber, Topics
from src.core.models import CommandMessage, CommandType, USVState, VehicleMode, FailsafeConfig
from src.core.config import settings
from loguru import logger
import json
import time

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
        self.gnss_fix_type = 0
        self.battery_level_pct = 0.0
        self.last_command_time = time.time()
        
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
                if self.is_armed and self.mode == VehicleMode.MANUAL.value:
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
                self.station_active = True
                logger.info("Station keeping STARTED")

            elif cmd.type == CommandType.STOP_STATION:
                self.station_active = False
                logger.info("Station keeping STOPPED")

            elif cmd.type == CommandType.START_WP_ROUTE:
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

            elif cmd.type == CommandType.SET_FAILSAFE_CONFIG:
                try:
                    self.failsafe_config = FailsafeConfig(**cmd.payload)
                    logger.info(f"Failsafe config updated: {self.failsafe_config}")
                except Exception as e:
                    logger.error(f"Invalid failsafe config: {e}")

        except Exception as e:
            logger.error(f"Failed to handle command: {e}")
