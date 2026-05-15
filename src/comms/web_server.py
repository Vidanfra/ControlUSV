import asyncio
import json
import math
import os
from typing import List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import zmq
import zmq.asyncio
import numpy as np
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
                logger.warning(f"Failed to send to client, removing: {e}")
                self.disconnect(connection)
                # Close the WebSocket explicitly so the client's onclose fires
                # and it reconnects automatically (prevents zombie connections).
                try:
                    await connection.close()
                except Exception:
                    pass  # Already broken; ignore close errors

manager = ConnectionManager()

# --- FastAPI App ---
app = FastAPI(title="USV Control System")

# --- Background Task: ZMQ Consumer ---
_ZMQ_URL = f"tcp://127.0.0.1:{settings.ZMQ_PORT + 1}"
_ZMQ_TOPICS = [
    Topics.SENSOR_GNSS,
    Topics.SENSOR_IMU,
    Topics.SENSOR_BATTERY,
    Topics.SENSOR_STATUS,
    Topics.STATE_ESTIMATION,
    Topics.SYSTEM_STATUS,
    Topics.CONTROL_DEBUG,
    Topics.CONTROL_CMD,
    Topics.SIM_STATUS,
]

async def consume_zmq():
    """
    Listens to ZMQ topics and broadcasts them to WebSocket clients.

    The outer ``while True`` restart loop means any unexpected ZMQ error
    (e.g. a transient socket fault on backend restart) is logged and the
    subscriber is recreated automatically — the task never dies silently.
    """
    while True:
        ctx        = None
        sub_socket = None
        try:
            ctx        = zmq.asyncio.Context()
            sub_socket = ctx.socket(zmq.SUB)
            sub_socket.connect(_ZMQ_URL)
            for t in _ZMQ_TOPICS:
                sub_socket.setsockopt_string(zmq.SUBSCRIBE, t.value)
            logger.info(f"[Web Server] ZMQ consumer subscribed on {_ZMQ_URL}")

            while True:
                # poll() on a zmq.asyncio socket is a coroutine — must be awaited.
                # Returns the ready event mask (truthy) or 0 on timeout.
                if await sub_socket.poll(100):
                    msg = await sub_socket.recv_string()
                    try:
                        topic_str, payload_str = msg.split(" ", 1)
                        data       = json.loads(payload_str)
                        ws_payload = json.dumps({"topic": topic_str, "data": data})
                        await manager.broadcast(ws_payload)
                    except (ValueError, json.JSONDecodeError) as e:
                        logger.warning(f"[Web Server] Failed to parse ZMQ message: {e}")
                # poll timed out → loop again; asyncio event loop yielded during wait

        except asyncio.CancelledError:
            logger.info("[Web Server] ZMQ consumer task cancelled")
            return  # clean shutdown — do not restart
        except Exception as e:
            logger.error(f"[Web Server] ZMQ consumer crashed: {e}. Restarting in 2 s...")
        finally:
            if sub_socket is not None:
                try:
                    sub_socket.close()
                except Exception:
                    pass
            if ctx is not None:
                try:
                    ctx.term()
                except Exception:
                    pass

        await asyncio.sleep(2.0)  # brief pause before creating a fresh subscriber

@app.on_event("startup")
async def startup_event():
    global cmd_pub, cmd_ctx
    logger.info("Starting Web Server...")

    # Create ZMQ command publisher HERE (post-fork, inside the child process).
    # Creating it at module level causes the socket to be forked from the parent
    # process, which silently breaks ZMQ delivery.
    cmd_ctx = zmq.Context()
    cmd_pub = cmd_ctx.socket(zmq.PUB)
    cmd_pub.connect(f"tcp://127.0.0.1:{settings.ZMQ_PORT}")
    await asyncio.sleep(0.2)   # allow ZMQ connection establishment (async — does not block event loop)
    logger.info("Command publisher connected to ZMQ broker")

    # Run the ZMQ consumer in the background
    asyncio.create_task(consume_zmq())

from src.core.models import CommandMessage, CommandType
from src.core.models import SimulationRequest, SimulationResult, SimulationConfig, Waypoint
from src.core.config import settings

# --- ZMQ Publisher for Commands ---
# Initialized in startup_event() to avoid pre-fork socket issues.
cmd_ctx = None
cmd_pub = None

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
        
        if cmd.type != CommandType.MANUAL_INPUT:
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


# --- Simulation Runner ---
def _run_simulation_sync(req: SimulationRequest) -> List[dict]:
    """Run simulation(s) in a blocking thread. Returns list of result dicts."""
    from src.gnc.vehicle_model import Salpa1Model
    from src.gnc.autopilot import GNCController
    from src.gnc.gnc_utils import latlon_to_ned, ned_to_latlon, attitudeEuler

    results = []

    # Convert waypoints to NED relative to first waypoint
    if len(req.waypoints) < 2:
        return []

    origin_lat = req.waypoints[0].lat
    origin_lon = req.waypoints[0].lon

    wp_ned = []
    for wp in req.waypoints:
        n, e = latlon_to_ned(wp.lat, wp.lon, origin_lat, origin_lon)
        wp_ned.append((n, e, wp.radius, wp.speed))

    for cfg in req.configs:
        # Determine waypoint order based on start_mode
        if cfg.start_mode == 'last_wp':
            sim_wp_ned = list(reversed(wp_ned))
        else:
            sim_wp_ned = list(wp_ned)

        # Determine initial position
        if cfg.start_mode == "current_pos" and (req.current_lat != 0 or req.current_lon != 0):
            n0, e0 = latlon_to_ned(req.current_lat, req.current_lon, origin_lat, origin_lon)
            psi0 = math.radians(req.current_heading)
        else:
            # Start at first wp of (possibly reversed) list
            n0, e0 = sim_wp_ned[0][0], sim_wp_ned[0][1]
            dn = sim_wp_ned[1][0] - sim_wp_ned[0][0]
            de = sim_wp_ned[1][1] - sim_wp_ned[0][1]
            psi0 = math.atan2(de, dn)

        # Build vehicle model (extracts physical parameters)
        model = Salpa1Model(
            payload_mass=cfg.payload_kg,
            V_current=cfg.current_speed,
            beta_current=cfg.current_dir,
            tau_X=cfg.surge_force,
        )

        # Build controller using model's computed physical constants
        controller = GNCController(
            m_yaw=model.Izz_total,
            B_inv=model.Binv,
            n_max=model.n_max,
            n_min=model.n_min,
            wn=cfg.wn_pid,
            zeta=cfg.zeta_pid,
            wn_d=cfg.wn_ref,
            zeta_d=cfg.zeta_ref,
            delta=cfg.delta,
            gamma=cfg.gamma,
            tau_X=cfg.surge_force,
        )

        # Load waypoints as list of dicts
        wp_dicts = [
            {'N': n, 'E': e, 'radius': r, 'speed': s}
            for n, e, r, s in sim_wp_ned
        ]
        controller.set_waypoints(wp_dicts)
        controller.reset(psi0)

        # Initial state
        eta = np.zeros(6)
        eta[0] = n0
        eta[1] = e0
        eta[5] = psi0
        nu = np.zeros(6)
        u_actual = np.array([0.0, 0.0])

        # Pre-allocate result lists
        dt = req.time_step
        N_steps = int(req.total_time / dt)

        t_log = []
        N_log, E_log = [], []
        psi_log, psi_d_log = [], []
        speed_log, cte_log = [], []
        n1_log, n2_log = [], []
        psi_err_log = []
        wp_reached_log = []

        LOG_DECIMATION = max(1, int(0.1 / dt))  # log at ~10 Hz

        # Completion mode support for one-shot:
        # For loop/loop_reverse, when route completes within total_time,
        # restart the waypoint sequence and continue.
        completion_mode = getattr(cfg, 'completion_mode', 'stop_time')
        is_forward = (cfg.start_mode != 'last_wp')
        current_wp_ned = list(sim_wp_ned)  # mutable copy for reversing

        for i in range(N_steps):
            t = i * dt

            # GNC step
            n1, n2, debug = controller.step(eta, nu, dt)
            u_control = np.array([n1, n2], dtype=float)

            # Physics step
            nu, u_actual = model.dynamics(eta, nu, u_actual, u_control, dt)

            # Kinematics
            eta = attitudeEuler(eta, nu, dt)

            # Handle completion modes (loop/loop_reverse) during one-shot
            if controller.is_mission_complete():
                if completion_mode == 'loop':
                    # Restart same direction
                    wp_dicts_loop = [
                        {'N': n, 'E': e, 'radius': r, 'speed': s}
                        for n, e, r, s in current_wp_ned
                    ]
                    controller.set_waypoints(wp_dicts_loop)
                    dn_l = current_wp_ned[1][0] - current_wp_ned[0][0]
                    de_l = current_wp_ned[1][1] - current_wp_ned[0][1]
                    controller.reset(math.atan2(de_l, dn_l))
                elif completion_mode == 'loop_reverse':
                    # Reverse waypoints
                    is_forward = not is_forward
                    current_wp_ned = list(reversed(current_wp_ned))
                    wp_dicts_loop = [
                        {'N': n, 'E': e, 'radius': r, 'speed': s}
                        for n, e, r, s in current_wp_ned
                    ]
                    controller.set_waypoints(wp_dicts_loop)
                    dn_l = current_wp_ned[1][0] - current_wp_ned[0][0]
                    de_l = current_wp_ned[1][1] - current_wp_ned[0][1]
                    controller.reset(math.atan2(de_l, dn_l))
                # For 'stop_time' and 'one_way', one-shot always runs to total_time

            # Log at reduced rate
            if i % LOG_DECIMATION == 0:
                t_log.append(round(t, 3))
                N_log.append(round(float(eta[0]), 3))
                E_log.append(round(float(eta[1]), 3))
                psi_log.append(round(float(eta[5]), 4))
                psi_d_log.append(round(debug.get("psi_d", 0.0), 4))
                spd = math.sqrt(float(nu[0])**2 + float(nu[1])**2)
                speed_log.append(round(spd, 3))
                cte_log.append(round(debug.get("cross_track_error", 0.0), 3))
                n1_log.append(round(float(n1), 1))
                n2_log.append(round(float(n2), 1))
                psi_err_log.append(round(debug.get("heading_error", 0.0), 4))
                wp_reached_log.append(debug.get("wp_index", 0))

        # Convert N/E to lat/lon
        lat_log = []
        lon_log = []
        for n_val, e_val in zip(N_log, E_log):
            lat, lon = ned_to_latlon(n_val, e_val, origin_lat, origin_lon)
            lat_log.append(round(lat, 8))
            lon_log.append(round(lon, 8))

        results.append(SimulationResult(
            profile_id=cfg.profile_id,
            config=cfg,
            time=t_log,
            lat=lat_log,
            lon=lon_log,
            N=N_log,
            E=E_log,
            psi=psi_log,
            psi_d=psi_d_log,
            speed=speed_log,
            cte=cte_log,
            n1=n1_log,
            n2=n2_log,
            psi_error=psi_err_log,
            wp_reached=wp_reached_log,
        ).model_dump())

    return results


@app.post("/api/simulate")
async def run_simulation(req: SimulationRequest):
    """Run one or more simulation profiles and return results."""
    logger.info(f"Simulation requested: {len(req.configs)} profile(s), {len(req.waypoints)} waypoints, T={req.total_time}s")
    try:
        results = await asyncio.get_event_loop().run_in_executor(None, _run_simulation_sync, req)
        return {"status": "ok", "results": results}
    except Exception as e:
        logger.error(f"Simulation failed: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/upload-waypoints")
async def upload_waypoints(file: UploadFile = File(...)):
    """Parse a CSV file of waypoints (lat,lon[,radius[,speed]])."""
    try:
        content = await file.read()
        text = content.decode("utf-8")
        waypoints = []
        for i, line in enumerate(text.strip().splitlines()):
            line = line.strip()
            if not line or line.startswith("#") or line.lower().startswith("lat"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                continue
            wp = Waypoint(
                lat=float(parts[0]),
                lon=float(parts[1]),
                radius=float(parts[2]) if len(parts) > 2 else 5.0,
                speed=float(parts[3]) if len(parts) > 3 else 1.0,
            )
            waypoints.append(wp.model_dump())
        logger.info(f"Parsed {len(waypoints)} waypoints from uploaded CSV")
        return {"status": "ok", "waypoints": waypoints}
    except Exception as e:
        logger.error(f"CSV upload failed: {e}")
        return {"status": "error", "message": str(e)}


# --- Static Files ---
# Mount the Vue build output directory
frontend_dist_path = os.path.join(os.getcwd(), "frontend", "dist")

if os.path.exists(frontend_dist_path):
    _index_html_path = os.path.join(frontend_dist_path, "index.html")

    # Serve index.html with no-cache headers so browsers never serve a stale
    # entry point after a frontend rebuild.  Hashed assets (index-abc123.js)
    # are safe to cache because their filename changes on every build.
    # These explicit routes must be registered BEFORE the static mount so they
    # take priority over Starlette's StaticFiles handler.
    @app.get("/")
    @app.get("/index.html")
    async def serve_index():
        return FileResponse(
            _index_html_path,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

    app.mount("/", StaticFiles(directory=frontend_dist_path, html=True), name="static")
    logger.info(f"Serving static files from {frontend_dist_path}")
else:
    logger.warning(f"Frontend dist folder not found at {frontend_dist_path}. Did you run 'npm run build'?")

    @app.get("/")
    def index():
        return {"message": "Frontend not built or not found. Please run 'npm run build' in frontend/ folder."}
