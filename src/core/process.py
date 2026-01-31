import multiprocessing
import time
import abc
import signal
import sys
from loguru import logger
from src.core.config import settings

def setup_logging(process_name: str):
    """
    Configures loguru for a specific process.
    """
    # Remove default handlers to avoid duplication if re-added
    logger.remove()
    
    # Add stdout handler
    logger.add(
        sys.stderr, 
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>" + process_name + "</cyan> | <level>{message}</level>",
        level=settings.LOG_LEVEL,
        enqueue=True  # Thread-safe/Process-safe
    )
    
    # Add file handler
    logger.add(
        "logs/usv_control.log",
        rotation="10 MB",
        retention="1 week",
        level=settings.LOG_LEVEL,
        enqueue=True,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | " + process_name + " | {message}"
    )

class ServiceProcess(multiprocessing.Process, abc.ABC):
    """
    Abstract Base Class for all USV microservices.
    Handles process lifecycle: setup -> loop -> cleanup.
    """
    def __init__(self, name: str, loop_rate_hz: int = 10):
        super().__init__(name=name)
        self.name = name
        self.loop_interval = 1.0 / loop_rate_hz
        self._stop_event = multiprocessing.Event()
        # Daemon processes are killed abruptly, so we prefer non-daemon to handle shutdown cleanup
        self.daemon = False 

    def run(self):
        """
        Main entry point for the process.
        """
        # 1. Setup Logging for this process
        setup_logging(self.name)
        
        # 2. Register Signal Handlers (SIGINT/SIGTERM)
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        logger.info(f"Process {self.name} starting...")
        
        # 3. User Setup
        try:
            self.setup()
        except Exception as e:
            logger.critical(f"Setup failed for {self.name}: {e}")
            return

        # 4. Main Loop
        logger.info(f"Process {self.name} entering loop at {1/self.loop_interval:.1f} Hz")
        last_time = time.time()
        
        while not self._stop_event.is_set():
            now = time.time()
            dt = now - last_time
            last_time = now
            
            try:
                self.loop()
            except Exception as e:
                logger.error(f"Error in {self.name} loop: {e}")
            
            # Sleep to maintain rate
            elapsed = time.time() - now
            sleep_time = self.loop_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
        
        # 5. Cleanup
        self.cleanup()
        logger.info(f"Process {self.name} stopped.")

    def stop(self):
        """Signals the process to stop."""
        self._stop_event.set()

    def _signal_handler(self, sig, frame):
        logger.info(f"Process {self.name} received signal {sig}. Stopping...")
        self.stop()

    @abc.abstractmethod
    def setup(self):
        """Called once before the loop starts. Initialize resources (ZMQ, etc.) here."""
        pass

    @abc.abstractmethod
    def loop(self):
        """Called periodically at the defined loop rate."""
        pass

    def cleanup(self):
        """Optional override for cleanup logic."""
        pass
