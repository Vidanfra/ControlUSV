import time
import json
import threading
import math
import zmq
from pymavlink import mavutil
from loguru import logger
from src.core.config import settings
from src.core.messaging import Topics

class MavlinkSender:
    def __init__(self, zmq_port=settings.ZMQ_PORT + 1, mavlink_ip="127.0.0.1", mavlink_port=14550):
        self.zmq_port = zmq_port
        self.mavlink_connection_str = f"udpout:{mavlink_ip}:{mavlink_port}"
        self.running = False
        self._thread = None
        self.mav = None

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="MavlinkThread")
        self._thread.start()

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=2)

    def _loop(self):
        # 1. Setup ZMQ
        ctx = zmq.Context()
        sub = ctx.socket(zmq.SUB)
        sub.connect(f"tcp://127.0.0.1:{self.zmq_port}")
        # Subscribe to State Estimation (where position/speed comes from)
        sub.setsockopt_string(zmq.SUBSCRIBE, Topics.STATE_ESTIMATION.value)
        # Also subscribe to GNSS just in case we want raw, but GLOBAL_POSITION_INT usually comes from EKF
        # For now, let's assume we map STATE_ESTIMATION to GLOBAL_POSITION_INT
        
        # 2. Setup MAVLink
        try:
            # source_system=1, source_component=1 (Autopilot)
            self.mav = mavutil.mavlink_connection(self.mavlink_connection_str, source_system=1, source_component=1)
            logger.info(f"MAVLink bridge sending to {self.mavlink_connection_str}")
        except Exception as e:
            logger.error(f"Failed to connect MAVLink: {e}")
            sub.close()
            return

        last_heartbeat = 0
        
        while self.running:
            now = time.time()
            
            # Send Heartbeat (1Hz)
            if now - last_heartbeat > 1.0:
                self.mav.mav.heartbeat_send(
                    mavutil.mavlink.MAV_TYPE_SURFACE_BOAT,
                    mavutil.mavlink.MAV_AUTOPILOT_GENERIC,
                    mavutil.mavlink.MAV_MODE_MANUAL_DISARMED, 
                    0, 
                    mavutil.mavlink.MAV_STATE_STANDBY
                )
                last_heartbeat = now
                
            # Check ZMQ
            try:
                # Non-blocking poll
                if sub.poll(10): # 10ms
                    msg = sub.recv_string()
                    topic, payload_str = msg.split(" ", 1)
                    data = json.loads(payload_str)
                    
                    if topic == Topics.STATE_ESTIMATION.value:
                        self._send_global_position(data)
            except Exception as e:
                logger.error(f"MAVLink loop error: {e}")
                
        # Cleanup
        try:
            self.mav.close()
        except:
            pass
        sub.close()
        ctx.term()
        logger.info("MAVLink bridge stopped.")

    def _send_global_position(self, data):
        # Convert timestamp
        time_boot_ms = int(time.time() * 1000) % 4294967295
        
        lat = int(data.get("lat", 0.0) * 1e7)
        lon = int(data.get("lon", 0.0) * 1e7)
        
        # Altitude in mm
        alt = 0 
        relative_alt = 0
        
        speed = data.get("speed", 0.0)
        heading_rad = data.get("heading", 0.0)
        
        # NED Velocity in cm/s
        # x = North, y = East
        vx = int(speed * math.cos(heading_rad) * 100)
        vy = int(speed * math.sin(heading_rad) * 100)
        vz = 0
        
        # Heading in cdeg (0..36000)
        hdg = int(heading_rad * 180.0 / math.pi * 100)
        if hdg < 0: hdg += 36000
        
        self.mav.mav.global_position_int_send(
            time_boot_ms,
            lat, lon, alt, relative_alt,
            vx, vy, vz,
            hdg
        )
