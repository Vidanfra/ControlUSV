from src.core.process import ServiceProcess
from src.core.messaging import PubSubBroker, Publisher, Subscriber, Topics
from src.core.models import CommandMessage, CommandType, USVState
from src.core.config import settings
from loguru import logger
import json
import time

class ManagerProcess(ServiceProcess):
    def setup(self):
        # 1. Subscribe to User Commands
        self.cmd_sub = Subscriber([Topics.COMMAND_USER])
        
        # 2. Publisher for Status Updates (and later Control Output)
        self.status_pub = Publisher(Topics.SYSTEM_STATUS)
        
        # 3. State
        self.is_armed = False
        self.mode = "MANUAL"
        
        logger.info("Manager Process Initialized. Waiting for commands...")

    def loop(self):
        # 1. Process Incoming Commands
        # We process all available commands in the queue for this tick
        while True:
            msg = self.cmd_sub.receive(timeout_ms=0) # Non-blocking
            if msg is None:
                break
            
            topic, payload = msg
            if topic == Topics.COMMAND_USER.value:
                self.handle_command(payload)

        # 2. Publish System Status Heartbeat (e.g. 1Hz or faster)
        # For now, let's just publish occasionally or every loop?
        # Let's publish every loop (10Hz) as defined in main.py
        status_payload = {
            "timestamp": time.time(),
            "is_armed": self.is_armed,
            "mode": self.mode,
            "battery_voltage": 12.6, # Dummy for now, should come from HAL -> State
            "system_status": "ACTIVE"
        }
        self.status_pub.publish(status_payload)

    def handle_command(self, payload_dict):
        try:
            # Parse using Pydantic model for validation
            cmd = CommandMessage(**payload_dict)
            logger.info(f"Manager received command: {cmd.type}")

            if cmd.type == CommandType.ARM:
                self.is_armed = True
                logger.warning(">>> VEHICLE ARMED <<<")
                
            elif cmd.type == CommandType.DISARM:
                self.is_armed = False
                logger.warning(">>> VEHICLE DISARMED <<<")
                
            elif cmd.type == CommandType.SET_MODE:
                new_mode = cmd.payload.get("mode")
                if new_mode:
                    self.mode = new_mode
                    logger.info(f"Mode changed to: {self.mode}")
            
            # TODO: Handle Mission Upload, etc.

        except Exception as e:
            logger.error(f"Failed to handle command: {e}")
