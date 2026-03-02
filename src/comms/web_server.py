import asyncio
import json
import os
from typing import List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import zmq
import zmq.asyncio
from loguru import logger
from src.core.config import settings
from src.core.messaging import Topics

# Windows-specific fix for ProactorEventLoop with ZMQ
import sys
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# --- Connection Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: str):
        # Iterate over a copy to avoid modification issues during iteration (though asyncio is single threaded here)
        for connection in self.active_connections[:]:
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.warning(f"Failed to send to client: {e}")
                self.disconnect(connection)

manager = ConnectionManager()

# --- FastAPI App ---
app = FastAPI(title="USV Control System")

# --- Background Task: ZMQ Consumer ---
async def consume_zmq():
    """
    Listens to ZMQ topics and broadcasts them to WebSocket clients.
    """
    ctx = zmq.asyncio.Context()
    sub_socket = ctx.socket(zmq.SUB)
    
    # Connect to the XPUB port of the Broker
    # Note: Using localhost for now since Comms and Broker are on the same machine
    zmq_url = f"tcp://127.0.0.1:{settings.ZMQ_PORT + 1}"
    sub_socket.connect(zmq_url)
    
    # Subscribe to relevant topics
    topics_to_subscribe = [
        Topics.SENSOR_GNSS, 
        Topics.SENSOR_IMU,
        Topics.STATE_ESTIMATION, 
        Topics.SYSTEM_STATUS,
        Topics.SENSOR_BATTERY,
        Topics.CONTROL_DEBUG,
        Topics.CONTROL_CMD
    ]
    for t in topics_to_subscribe:
        sub_socket.setsockopt_string(zmq.SUBSCRIBE, t.value)
        
    logger.info(f"Web Server ZMQ Consumer connected to {zmq_url} subscribing to {[t.value for t in topics_to_subscribe]}")

    try:
        while True:
            # Receive multipart: [topic, payload] or string "topic payload"
            # Our Publisher sends "topic json_payload" string
            if sub_socket.poll(100): # Check if message available with short timeout to allow loop yielding
                msg = await sub_socket.recv_string()
                
                # We can broadcast the raw message directly to frontend, 
                # and let the frontend parse "topic payload"
                # OR we can parse it here and send a cleaner JSON object.
                # Let's send a JSON object: {topic: "...", data: ...}
                try:
                    topic_str, payload_str = msg.split(" ", 1)
                    # Optimization: sending valid JSON string directly inside a wrapper might avoid double parsing
                    # but for simplicity let's load and dump or just string format
                    # To be robust/simple for frontend:
                    # websocket_msg = json.dumps({"topic": topic_str, "payload": json.loads(payload_str)})
                    
                    # Alternatively, just forward the raw string "topic {json}" and handle in JS
                    # Let's clean it up slightly for the frontend dev experience
                    data = json.loads(payload_str)
                    ws_payload = json.dumps({"topic": topic_str, "data": data})
                    
                    await manager.broadcast(ws_payload)
                    
                except ValueError:
                    # Malformed message
                    pass
            else:
                await asyncio.sleep(0.01)
                
    except asyncio.CancelledError:
        logger.info("ZMQ Consumer task cancelled")
    finally:
        sub_socket.close()
        ctx.term()

@app.on_event("startup")
async def startup_event():
    logger.info("Starting Web Server...")
    # Run the ZMQ consumer in the background
    asyncio.create_task(consume_zmq())

from src.core.models import CommandMessage
from src.core.config import settings

# --- ZMQ Publisher Setup for Commands ---
# We need a dedicated socket to publish user commands to the bus.
# Since uvicorn is async, we can't easily share the "Publisher" class from messaging.py which is sync.
# We'll create a simple async publisher context here or use a sync socket carefully.
# Given low command rate, a sync socket creation per command or a global one is fine.
# Let's create a global command publisher context.

cmd_ctx = zmq.Context()
cmd_pub = cmd_ctx.socket(zmq.PUB)
cmd_pub.connect(f"tcp://127.0.0.1:{settings.ZMQ_PORT}") # Connect to Broker XSUB

async def process_incoming_command(data_str: str):
    """Parses and publishes commands from the UI."""
    try:
        data = json.loads(data_str)
        # Validate against model
        cmd = CommandMessage(**data)
        
        # Publish to ZMQ
        topic = Topics.COMMAND_USER.value
        msg = f"{topic} {cmd.model_dump_json()}"
        cmd_pub.send_string(msg)
        
        logger.info(f"Command received and published: {cmd.type}")
        
    except json.JSONDecodeError:
        logger.warning(f"Invalid JSON received from websocket: {data_str}")
    except Exception as e:
        logger.error(f"Error processing command: {e}")

# --- Routes ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Receive text from client
            data = await websocket.receive_text()
            # Process command
            await process_incoming_command(data)
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)

# --- Static Files ---
# Mount the Vue build output directory
frontend_dist_path = os.path.join(os.getcwd(), "frontend", "dist")

if os.path.exists(frontend_dist_path):
    app.mount("/", StaticFiles(directory=frontend_dist_path, html=True), name="static")
    logger.info(f"Serving static files from {frontend_dist_path}")
else:
    logger.warning(f"Frontend dist folder not found at {frontend_dist_path}. Did you run 'npm run build'?")
    
    @app.get("/")
    def index():
        return {"message": "Frontend not built or not found. Please run 'npm run build' in frontend/ folder."}
