import asyncio
import json
import math
import os
import time
import traceback
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
# Per-connection state is attached as plain attributes on the WebSocket object:
#   ws._last_ping_ts  : float (monotonic) — last PING received from this client
#   ws._last_seq      : int — highest CommandMessage.seq accepted from this client
# Both are initialized in ConnectionManager.connect.
_PING_ALIVE_WINDOW_S = 2.0   # client is "alive" if it pinged within this window

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        # Treat a fresh connection as "alive" for the first window so the
        # comm-failsafe doesn't trip in the gap before the first client PING.
        websocket._last_ping_ts = time.monotonic()
        websocket._last_seq = -1
        self.active_connections.append(websocket)
        logger.info(f"WebSocket client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket client disconnected. Total: {len(self.active_connections)}")

    def link_status(self) -> dict:
        """Aggregate frontend-link liveness across all connections."""
        now = time.monotonic()
        n = len(self.active_connections)
        if n == 0:
            return {"ws_alive": False, "n_clients": 0, "last_ping_age_s": None}
        ages = [now - getattr(ws, "_last_ping_ts", 0.0) for ws in self.active_connections]
        youngest = min(ages)
        return {
            "ws_alive": youngest <= _PING_ALIVE_WINDOW_S,
            "n_clients": n,
            "last_ping_age_s": youngest,
        }

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
    Topics.COMMS_LINK,
    Topics.SYSTEM_MONITOR,
    Topics.LOGGER_PREVIEW,
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
    global cmd_pub, cmd_ctx, link_pub
    logger.info("Starting Web Server...")

    # Create ZMQ command publisher HERE (post-fork, inside the child process).
    # Creating it at module level causes the socket to be forked from the parent
    # process, which silently breaks ZMQ delivery.
    cmd_ctx = zmq.Context()
    cmd_pub = cmd_ctx.socket(zmq.PUB)
    cmd_pub.connect(f"tcp://127.0.0.1:{settings.ZMQ_PORT}")

    # Dedicated publisher for the comms/link liveness topic. Tiny HWM so a slow
    # GNC consumer never holds stale liveness frames.
    link_pub = cmd_ctx.socket(zmq.PUB)
    link_pub.setsockopt(zmq.SNDHWM, 10)
    link_pub.setsockopt(zmq.LINGER, 0)
    link_pub.connect(f"tcp://127.0.0.1:{settings.ZMQ_PORT}")

    await asyncio.sleep(0.2)   # allow ZMQ connection establishment (async — does not block event loop)
    logger.info("Command publisher connected to ZMQ broker")

    # Run the ZMQ consumer in the background
    asyncio.create_task(consume_zmq())
    asyncio.create_task(publish_link_status())


async def publish_link_status():
    """Publish frontend-link liveness on `comms/link` at 1 Hz.

    GNCProcess subscribes to this topic and uses `ws_alive` to gate the
    comm-loss failsafe. Without this, the failsafe is bound to the local
    Manager heartbeat and never trips on a real 4G/commander drop.
    """
    topic = Topics.COMMS_LINK.value
    while True:
        try:
            payload = manager.link_status()
            payload["ts"] = time.time()
            link_pub.send_string(f"{topic} {json.dumps(payload)}")
        except Exception:
            logger.exception("[Web Server] Failed to publish comms/link")
        await asyncio.sleep(1.0)

from src.core.models import CommandMessage, CommandType
from src.core.models import SimulationRequest, SimulationResult, SimulationConfig, Waypoint
from src.core.config import settings

# --- ZMQ Publisher for Commands ---
# Initialized in startup_event() to avoid pre-fork socket issues.
cmd_ctx = None
cmd_pub = None
link_pub = None  # publisher for Topics.COMMS_LINK

async def process_incoming_command(data_str: str, websocket: WebSocket):
    """Parses and publishes commands from the UI.

    Special-cases:
      - PING frames are intercepted before Pydantic validation and only update
        the per-connection liveness timestamp (no ZMQ publish).
      - CommandMessage with a `seq` <= last accepted seq for this connection
        is dropped as a duplicate (idempotency on retransmits / TCP buffers).
    Accepted commands echo an ACK frame back to the same client.
    """
    try:
        data = json.loads(data_str)
    except json.JSONDecodeError:
        logger.warning(f"Invalid JSON received from websocket: {data_str}")
        return

    # PING: keep-alive from the frontend, not a real command.
    if isinstance(data, dict) and data.get("type") == "PING":
        websocket._last_ping_ts = time.monotonic()
        # Echo PONG with seq so the client can measure RTT later if desired.
        try:
            await websocket.send_text(json.dumps({
                "topic": "comms/pong",
                "data": {"seq": data.get("seq"), "ts": time.time()},
            }))
        except Exception:
            pass
        return

    try:
        cmd = CommandMessage(**data)
    except Exception:
        logger.exception(f"Invalid CommandMessage payload: {data_str[:200]}")
        return

    # Duplicate-suppression by per-connection sequence number.
    if cmd.seq is not None:
        if cmd.seq <= websocket._last_seq:
            logger.warning(
                f"Duplicate command dropped (seq={cmd.seq} <= last={websocket._last_seq}, type={cmd.type})"
            )
            # Re-ACK so the frontend stops retrying.
            try:
                await websocket.send_text(json.dumps({
                    "topic": "comms/ack",
                    "data": {"seq": cmd.seq, "duplicate": True, "ts": time.time()},
                }))
            except Exception:
                pass
            return
        websocket._last_seq = cmd.seq

    try:
        topic = Topics.COMMAND_USER.value
        msg = f"{topic} {cmd.model_dump_json()}"
        cmd_pub.send_string(msg)
    except Exception:
        logger.exception(f"Failed to publish command {cmd.type} to ZMQ")
        return

    if cmd.type != CommandType.MANUAL_INPUT:
        logger.info(f"Command received and published: {cmd.type} (seq={cmd.seq})")

    # ACK the accepted command so the frontend can clear its retry/echo state.
    if cmd.seq is not None:
        try:
            await websocket.send_text(json.dumps({
                "topic": "comms/ack",
                "data": {"seq": cmd.seq, "duplicate": False, "ts": time.time()},
            }))
        except Exception:
            pass

# --- Routes ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Receive text from client
            data = await websocket.receive_text()
            # Process command
            await process_incoming_command(data, websocket)
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        logger.exception("WebSocket handler error")
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


# --- Logs feature: catalog + filesystem browser ---
from src.comms.log_fields import LOG_FIELD_GROUPS
from pydantic import BaseModel
import platform


@app.get("/api/log-fields")
async def get_log_fields():
    """Return the curated log-field catalog used by the Logs tab."""
    return {"groups": LOG_FIELD_GROUPS, "os": platform.system()}


class FsListRequest(BaseModel):
    path: str = ""
    show_hidden: bool = False


@app.post("/api/fs/list")
async def fs_list(req: FsListRequest):
    """
    List contents of a directory on the backend host. Returns parent
    directory, entries (with name/is_dir/size/mtime), and the host OS so
    the frontend can render drive letters on Windows vs / on Linux.
    """
    try:
        os_name = platform.system()
        path = req.path or ("" if os_name == "Windows" else "/")

        # Root view on Windows: enumerate drive letters
        if os_name == "Windows" and (not path or path in ("/", "\\")):
            import string
            entries = []
            for letter in string.ascii_uppercase:
                root = f"{letter}:\\"
                if os.path.exists(root):
                    entries.append({"name": root, "is_dir": True, "size": 0, "mtime": 0})
            return {"path": "", "parent": "", "entries": entries, "os": os_name}

        if not path:
            path = "/"
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            return {"status": "error", "message": f"not a directory: {path}"}

        entries = []
        try:
            for name in sorted(os.listdir(path)):
                if not req.show_hidden and name.startswith("."):
                    continue
                full = os.path.join(path, name)
                try:
                    st = os.stat(full)
                    entries.append({
                        "name": name,
                        "is_dir": os.path.isdir(full),
                        "size": st.st_size,
                        "mtime": st.st_mtime,
                    })
                except Exception:
                    entries.append({"name": name, "is_dir": False, "size": 0, "mtime": 0})
        except PermissionError as e:
            return {"status": "error", "message": f"permission denied: {e}"}

        parent = os.path.dirname(path)
        # Windows: parent of a drive root is the drive-letter selector
        if os_name == "Windows" and len(path) <= 3:
            parent = ""

        return {"path": path, "parent": parent, "entries": entries, "os": os_name}
    except Exception as e:
        logger.error(f"fs_list failed: {e}")
        return {"status": "error", "message": str(e)}


class FsMkdirRequest(BaseModel):
    path: str


@app.post("/api/fs/mkdir")
async def fs_mkdir(req: FsMkdirRequest):
    """Create a directory (recursive)."""
    try:
        os.makedirs(req.path, exist_ok=True)
        return {"status": "ok", "path": os.path.abspath(req.path)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/app-log")
async def get_app_log(lines: int = 50, offset: int = 0):
    """
    Return the tail of the loguru log file (logs/usv_control.log).

    `lines`  : number of lines to return (clamped to [1, 5000])
    `offset` : how many *trailing* lines to SKIP (used by the "Load more"
               button — pass the count already shown to walk further back).
    """
    log_path = os.path.join(os.getcwd(), "logs", "usv_control.log")
    if not os.path.exists(log_path):
        return {"status": "error", "message": "log file not found", "lines": []}

    lines = max(1, min(int(lines), 5000))
    offset = max(0, int(offset))

    try:
        size = os.path.getsize(log_path)
        # Read at most the last 4 MB — more than enough for several thousand lines
        read_bytes = min(size, 4 * 1024 * 1024)
        with open(log_path, "rb") as fh:
            fh.seek(size - read_bytes)
            buf = fh.read()
        all_lines = buf.decode("utf-8", errors="replace").splitlines()
        # all_lines[-1] is the newest line
        total = len(all_lines)
        end = total - offset                  # exclusive
        start = max(0, end - lines)
        chunk = all_lines[start:end]
        return {
            "status": "ok",
            "path": log_path,
            "size_bytes": size,
            "total_buffered_lines": total,
            "returned_lines": len(chunk),
            "offset": offset,
            "has_more": start > 0,
            "lines": chunk,
        }
    except Exception as e:
        logger.error(f"get_app_log failed: {e}")
        return {"status": "error", "message": str(e), "lines": []}


# --- Map Tile Cache (server-side, disk-backed) ---
# Tiles requested by the frontend are proxied through these endpoints and
# stored on the server's disk. This makes the offline map cache persistent
# across browser reloads and server restarts, and shared across all connected
# client devices. When there is no internet, previously cached tiles are still
# served straight from disk.
import urllib.request
import urllib.error
from fastapi import Response
from fastapi.responses import JSONResponse

TILE_PROVIDERS = {
    "osm": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    "satellite": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    "dark": "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
    "nautical": "https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png",
}

# Content type served for each provider's tiles.
TILE_CONTENT_TYPE = {
    "osm": "image/png",
    "satellite": "image/jpeg",
    "dark": "image/png",
    "nautical": "image/png",
}

TILE_CACHE_DIR = os.path.join(os.getcwd(), "data", "tile_cache")
_TILE_USER_AGENT = "ControlUSV/1.0 (offline map tile cache)"


def _tile_path(provider: str, z: int, x: int, y: int) -> str:
    return os.path.join(TILE_CACHE_DIR, provider, str(z), str(x), str(y))


def _fetch_tile_sync(url: str) -> bytes:
    """Blocking upstream tile fetch (run in a threadpool)."""
    req = urllib.request.Request(url, headers={"User-Agent": _TILE_USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


@app.get("/tiles/stats")
async def tiles_stats():
    """Return the number of cached tiles and their total size in bytes."""
    count = 0
    total = 0
    if os.path.isdir(TILE_CACHE_DIR):
        for root, _dirs, files in os.walk(TILE_CACHE_DIR):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                    count += 1
                except OSError:
                    pass
    return {"count": count, "bytes": total}


@app.post("/tiles/clear")
async def tiles_clear():
    """Delete every cached tile from disk."""
    import shutil
    removed = 0
    if os.path.isdir(TILE_CACHE_DIR):
        for root, _dirs, files in os.walk(TILE_CACHE_DIR):
            removed += len(files)
        shutil.rmtree(TILE_CACHE_DIR, ignore_errors=True)
    return {"removed": removed}


@app.get("/tiles/{provider}/{z}/{x}/{y}")
async def get_tile(provider: str, z: int, x: int, y: int):
    """
    Serve a map tile, using the on-disk cache when available and falling back
    to the upstream provider (which is then cached). Returns 404 when a tile
    is neither cached nor fetchable (e.g. offline and never downloaded).
    """
    if provider not in TILE_PROVIDERS:
        return JSONResponse({"error": "unknown provider"}, status_code=404)

    # z/x/y are already coerced to ints by FastAPI, so no path-traversal risk.
    content_type = TILE_CONTENT_TYPE.get(provider, "image/png")
    path = _tile_path(provider, z, x, y)

    # 1. Serve from disk if cached.
    if os.path.isfile(path):
        return FileResponse(
            path,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=604800", "X-Tile-Cache": "HIT"},
        )

    # 2. Cache miss — fetch from upstream and persist to disk.
    url = TILE_PROVIDERS[provider].format(z=z, x=x, y=y)
    try:
        data = await asyncio.to_thread(_fetch_tile_sync, url)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        logger.debug(f"[Tiles] fetch failed for {url}: {e}")
        return JSONResponse({"error": "tile unavailable"}, status_code=404)

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except OSError as e:
        logger.warning(f"[Tiles] failed to cache {path}: {e}")

    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=604800", "X-Tile-Cache": "MISS"},
    )


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
