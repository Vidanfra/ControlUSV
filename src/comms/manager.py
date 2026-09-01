import uvicorn
from src.core.process import ServiceProcess, setup_logging
from src.comms.web_server import app
from loguru import logger
import sys

class CommsProcess(ServiceProcess):
    def __init__(self):
        super().__init__(name="CommsService")

    def run(self):
        # We override run because uvicorn is a blocking server,
        # not a periodic loop like the other services.
        setup_logging(self.name)

        logger.info(f"Starting Web Server on port 8000")
        
        # We pass log_config=None to prevent uvicorn from configuring standard logging,
        # letting Loguru handle everything if we intercepted it, 
        # but since we haven't set up full interception, uvicorn logs might appear in stderr.
        # To keep it simple and avoid conflict/duplication:
        try:
            uvicorn.run(app, host="0.0.0.0", port=8000, log_config=None)
        except KeyboardInterrupt:
            # Ctrl+C pressed — exit cleanly without traceback
            pass
        except Exception as e:
            logger.error(f"Web server crashed: {e}")

    # Start/Loop unused for this specific process type
    def setup(self):
        pass
    
    def loop(self):
        pass
