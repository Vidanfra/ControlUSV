import sys
import time
import multiprocessing
import os

# Ensure src is in the python path
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from src.core.config import settings
from src.core.process import setup_logging
from src.drivers.process import HALProcess
from src.comms.manager import CommsProcess
from src.manager.process import ManagerProcess
from src.core.messaging import PubSubBroker
from loguru import logger

def run_broker():
    """Wrapper to run the broker in a separate process"""
    setup_logging("BROKER")
    broker = PubSubBroker()
    broker.start()

def main():
    # Setup main process logging
    setup_logging("MAIN")
    
    logger.info("Starting USV Control System")
    logger.info(f"Mode: {'SIMULATION' if settings.SIMULATION_MODE else 'REAL HARDWARE'}")

    # 1. Start Messaging Broker
    p_broker = multiprocessing.Process(target=run_broker, name="ZMQBroker", daemon=True)
    p_broker.start()
    
    # 2. Define Services
    processes = [
        ManagerProcess(name="ManagerService", loop_rate_hz=settings.LOOP_RATES["manager"]),
        CommsProcess(),
        HALProcess(name="HALService", loop_rate_hz=settings.LOOP_RATES["hal"]),
    ]

    # 3. Start Services
    for p in processes:
        p.start()

    try:
        # Keep main process alive to monitor children
        while True:
            time.sleep(1)
            # Check if any process died unexpectedly
            for p in processes:
                if not p.is_alive():
                    # Check exit code if possible, or just restart logic could go here
                    pass
                    
    except KeyboardInterrupt:
        logger.warning("Main process received KeyboardInterrupt. Stopping services...")
        
        # Signal all processes to stop
        for p in processes:
            p.stop()
            
        # Wait for them to join
        for p in processes:
            p.join(timeout=2)
            if p.is_alive():
                logger.error(f"Process {p.name} did not stop gracefully, terminating.")
                p.terminate()
        
        # Broker is daemon, will die with main
        logger.success("All services stopped. Exiting.")

if __name__ == "__main__":
    multiprocessing.freeze_support() # Recommended for Windows
    main()
