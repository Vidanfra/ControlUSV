import zmq
import json
import time
from enum import Enum
from typing import Any, Optional, Dict, List
from loguru import logger
from src.core.config import settings
import multiprocessing

def get_zmq_url() -> str:
    """Get the ZMQ broker URL for publishers to connect to."""
    return f"tcp://127.0.0.1:{settings.ZMQ_PORT}"

class Topics(str, Enum):
    SENSOR_GNSS = "sensor/gnss"
    SENSOR_IMU = "sensor/imu"
    SENSOR_BATTERY = "sensor/battery"
    SENSOR_STATUS = "sensor/status"
    STATE_ESTIMATION = "gnc/ekf_state"
    CONTROL_CMD = "gnc/control_output"
    CONTROL_DEBUG = "gnc/control_debug"
    SYSTEM_STATUS = "system/status"
    COMMAND_USER = "command/user"
    SIM_STATUS = "sim/status"
    COMMS_LINK = "comms/link"          # frontend↔backend WS liveness (web_server → GNC)
    GNC_SYNC = "gnc/internal_sync"     # GNC → Manager state-sync (failsafe-driven)


# Per-topic high-water-marks. Defaults to 200 (~10 s at 20 Hz). Heartbeats use a
# small HWM so a slow consumer never holds 100 stale status frames.
_TOPIC_HWM = {
    "system/status": 10,
    "comms/link":    10,
    "gnc/internal_sync": 50,
}

def _hwm_for(topic_value: str) -> int:
    return _TOPIC_HWM.get(topic_value, 200)

class PubSubBroker:
    """
    Central Message Broker (zmq.proxy).
    Connects Publishers (XSUB) to Subscribers (XPUB).
    """
    def __init__(self, xsub_port: int = settings.ZMQ_PORT, xpub_port: int = settings.ZMQ_PORT + 1):
        self.xsub_port = xsub_port
        self.xpub_port = xpub_port

    def start(self):
        """Starts the broker in the current process (blocking)"""
        context = zmq.Context()
        frontend = context.socket(zmq.XSUB)  # Publishers connect here
        backend = context.socket(zmq.XPUB)   # Subscribers connect here

        try:
            # Bind to all interfaces
            frontend.bind(f"tcp://*:{self.xsub_port}") # bind so others connect
            backend.bind(f"tcp://*:{self.xpub_port}")  # bind so others connect

            logger.info(f"Broker started. Publishers -> :{self.xsub_port} | Subscribers <- :{self.xpub_port}")
            zmq.proxy(frontend, backend)
        except Exception as e:
            logger.error(f"Broker crashed: {e}")
        finally:
            frontend.close()
            backend.close()
            context.term()

class Publisher:
    def __init__(self, topic: Topics):
        self.topic = topic
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        # Bounded send queue: drop on overflow rather than buffer indefinitely.
        # LINGER=0 so close() returns immediately on shutdown.
        self.socket.setsockopt(zmq.SNDHWM, _hwm_for(topic.value))
        self.socket.setsockopt(zmq.LINGER, 0)
        # Connect to the Broker's XSUB port
        self.socket.connect(f"tcp://127.0.0.1:{settings.ZMQ_PORT}")
        time.sleep(0.1) # Allow connection establishment

    def publish(self, payload: Dict[str, Any]):
        try:
            message = f"{self.topic.value} {json.dumps(payload)}"
            self.socket.send_string(message)
        except Exception as e:
            logger.error(f"Failed to publish on {self.topic}: {e}")

    def close(self):
        self.socket.close()
        self.context.term()

class Subscriber:
    def __init__(self, topics: List[Topics]):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.SUB)
        # Bounded receive queue: under sustained back-pressure, drop the oldest
        # rather than grow unbounded. LINGER=0 for fast shutdown.
        # Use the smallest HWM among subscribed topics so heartbeat-like topics
        # cannot starve sensor topics with stale frames.
        rcv_hwm = min((_hwm_for(t.value) for t in topics), default=200)
        self.socket.setsockopt(zmq.RCVHWM, rcv_hwm)
        self.socket.setsockopt(zmq.LINGER, 0)
        # Connect to the Broker's XPUB port (ZMQ_PORT + 1)
        self.socket.connect(f"tcp://127.0.0.1:{settings.ZMQ_PORT + 1}")
        
        for t in topics:
            self.socket.setsockopt_string(zmq.SUBSCRIBE, t.value)
            
        self.poller = zmq.Poller()
        self.poller.register(self.socket, zmq.POLLIN)

    def receive(self, timeout_ms: int = 10) -> Optional[tuple[str, Dict[str, Any]]]:
        """
        Non-blocking receive (or with timeout).
        Returns (topic, payload_dict) or None.
        """
        socks = dict(self.poller.poll(timeout_ms))
        if self.socket in socks and socks[self.socket] == zmq.POLLIN:
            try:
                message = self.socket.recv_string()
                # Split only on the first space to separate topic from json payload
                topic_str, data_str = message.split(" ", 1)
                return topic_str, json.loads(data_str)
            except ValueError:
                logger.warning(f"Malformed message received: {message}")
            except Exception as e:
                logger.error(f"Error receiving message: {e}")
        return None

    def close(self):
        self.socket.close()
        self.context.term()
