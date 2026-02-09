import zmq
import json
import time
from enum import Enum
from typing import Any, Optional, Dict, List
from loguru import logger
from src.core.config import settings
import multiprocessing

class Topics(str, Enum):
    SENSOR_GNSS = "sensor/gnss"
    SENSOR_IMU = "sensor/imu"
    STATE_ESTIMATION = "gnc/ekf_state"
    CONTROL_CMD = "gnc/control_output"
    SYSTEM_STATUS = "system/status"
    COMMAND_USER = "command/user"

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
