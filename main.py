import sys
import time
import multiprocessing
import os
from collections import defaultdict

# Ensure src is in the python path
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from src.core.config import settings
from src.core.process import setup_logging
from src.drivers.process import HALProcess
from src.drivers.system_monitor import SystemMonitorProcess
from src.comms.manager import CommsProcess
from src.comms.logger_process import LoggerProcess
from src.manager.process import ManagerProcess
from src.gnc.process import GNCProcess
from src.gnc.navigation import NavigationProcess
from src.core.messaging import PubSubBroker, Publisher, Topics
from loguru import logger

def run_broker():
    """Wrapper to run the broker in a separate process"""
    setup_logging("BROKER")
    broker = PubSubBroker()
    broker.start()

# ── Watchdog parameters ───────────────────────────────────────────────────────
_WATCHDOG_INTERVAL = 1.0   # seconds between health checks
_MAX_RESTARTS      = 5     # max restarts within _CRASH_WINDOW before giving up
_CRASH_WINDOW      = 60.0  # rolling window (seconds) for crash counting
_MAX_BACKOFF       = 30.0  # maximum restart delay (seconds)

# ── Process catalogue ─────────────────────────────────────────────────────────
# (constructor, kwargs, safety_critical)
# safety_critical = crash is immediately dangerous to vehicle / operator awareness
_CATALOGUE = [
    (ManagerProcess,    dict(name="ManagerService",    loop_rate_hz=settings.LOOP_RATES["manager"]), True),
    (CommsProcess,      dict(),                                                                       False),
    (HALProcess,        dict(name="HALService",        loop_rate_hz=settings.LOOP_RATES["hal"]),     True),
    (NavigationProcess, dict(name="NavigationService", loop_rate_hz=settings.LOOP_RATES["gnc"]),     True),
    (GNCProcess,        dict(name="GNCService",        loop_rate_hz=settings.LOOP_RATES["gnc"]),     True),
    (SystemMonitorProcess, dict(name="SystemMonitorService", loop_rate_hz=1),                        False),
    (LoggerProcess,     dict(name="LoggerService",     loop_rate_hz=50),                            False),
]

def _spawn(cls, kwargs):
    p = cls(**kwargs)
    p.start()
    return p

def _watchdog_tick(
    now,
    processes,    # dict[name, process]  — mutated in place on restart
    catalogue,    # dict[name, (cls, kw)]
    critical,     # dict[name, bool]
    crash_times,  # defaultdict(list)    — mutated in place
    backoff_secs, # defaultdict(float)   — mutated in place
    restart_at,   # defaultdict(float)   — mutated in place
    gave_up,      # set                  — mutated in place
    pending,      # set                  — mutated in place
    spawn_fn,     # callable(cls, kw) -> process
    alert_fn,     # callable(level, name, msg)
):
    """
    One watchdog iteration.  All mutable state is passed explicitly so the
    function can be exercised in unit tests without starting real processes.
    """
    # ── Execute any pending restarts whose delay has elapsed ──────────
    for name in list(pending):
        if now >= restart_at[name]:
            pending.discard(name)
            cls, kw = catalogue[name]
            new_proc = spawn_fn(cls, kw)
            processes[name] = new_proc
            attempt = len(crash_times[name])
            logger.success(
                f"[WATCHDOG] {name} restarted (pid={getattr(new_proc,'pid',None)}, "
                f"attempt {attempt}/{_MAX_RESTARTS})"
            )
            alert_fn("warning", name,
                     f"{name} restarted (attempt {attempt}/{_MAX_RESTARTS}). Monitoring...")

    # ── Check liveness of all running processes ───────────────────────
    for name, p in list(processes.items()):
        if name in gave_up or name in pending:
            continue
        if p.is_alive():
            continue

        # ── Process has died ──────────────────────────────────────────
        exit_code = p.exitcode
        logger.error(f"[WATCHDOG] {name} died unexpectedly (exitcode={exit_code})")

        # Prune crash timestamps outside the rolling window
        crash_times[name] = [t for t in crash_times[name] if now - t < _CRASH_WINDOW]
        crash_times[name].append(now)

        if len(crash_times[name]) >= _MAX_RESTARTS:
            logger.critical(
                f"[WATCHDOG] {name} has crashed {len(crash_times[name])} times "
                f"in {_CRASH_WINDOW:.0f}s. Giving up — manual intervention required."
            )
            alert_fn("critical", name,
                     f"CRASH LOOP: {name} failed {_MAX_RESTARTS}× in {_CRASH_WINDOW:.0f}s. "
                     f"Manual restart required.")
            gave_up.add(name)
            continue

        # Schedule restart with exponential backoff
        delay = max(1.0, backoff_secs[name]) if backoff_secs[name] > 0 else 1.0
        backoff_secs[name] = min(delay * 2, _MAX_BACKOFF)
        restart_at[name] = now + delay
        pending.add(name)

        level = "critical" if critical[name] else "warning"
        alert_fn(level, name,
                 f"{name} crashed (exit={exit_code}). "
                 f"{'SAFETY-CRITICAL — ' if critical[name] else ''}"
                 f"Restarting in {delay:.0f}s "
                 f"(crash {len(crash_times[name])}/{_MAX_RESTARTS}).")

def main():
    # Setup main process logging
    setup_logging("MAIN")
    
    logger.info("Starting USV Control System")
    logger.info(f"Mode: {'SIMULATION' if settings.SIMULATION_MODE else 'REAL HARDWARE'}")

    # 1. Start Messaging Broker (daemon — killed automatically when main exits)
    p_broker = multiprocessing.Process(target=run_broker, name="ZMQBroker", daemon=True)
    p_broker.start()
    time.sleep(0.5)  # Give broker time to bind its sockets

    # 2. Start all service processes
    processes  = {cls.__name__: _spawn(cls, kw) for cls, kw, _ in _CATALOGUE}
    critical   = {cls.__name__: crit            for cls, kw, crit in _CATALOGUE}
    catalogue  = {cls.__name__: (cls, kw)       for cls, kw, _ in _CATALOGUE}

    # 3. Alert publisher — lets the watchdog speak on the message bus
    time.sleep(1.0)  # Wait for services to subscribe before publishing
    alert_pub = Publisher(Topics.SYSTEM_STATUS)

    def _alert(level: str, name: str, msg: str):
        logger.warning(f"[WATCHDOG] {msg}")
        try:
            alert_pub.publish({"watchdog_alert": True, "level": level,
                               "process": name, "message": msg})
        except Exception:
            pass  # Never let alert failure kill the watchdog

    # 4. Watchdog state (all non-blocking — no sleep inside the detection loop)
    crash_times    = defaultdict(list)   # name -> [timestamps of recent crashes]
    backoff_secs   = defaultdict(float)  # name -> current backoff delay
    restart_at     = defaultdict(float)  # name -> monotonic time when restart is due
    gave_up        = set()               # names that hit the crash limit
    pending        = set()              # names scheduled for restart but not yet spawned

    try:
        while True:
            time.sleep(_WATCHDOG_INTERVAL)
            now = time.time()
            _watchdog_tick(
                now, processes, catalogue, critical,
                crash_times, backoff_secs, restart_at,
                gave_up, pending,
                spawn_fn=_spawn,
                alert_fn=_alert,
            )

    except KeyboardInterrupt:
        logger.warning("Main process received KeyboardInterrupt. Stopping services...")
        
        # Signal all processes to stop
        for p in processes.values():
            p.stop()
            
        # Wait for them to join
        for p in processes.values():
            p.join(timeout=2)
            if p.is_alive():
                logger.error(f"Process {p.name} did not stop gracefully, terminating.")
                p.terminate()

        alert_pub.close()
        # Broker is daemon, will die with main
        logger.success("All services stopped. Exiting.")

if __name__ == "__main__":
    multiprocessing.freeze_support() # Recommended for Windows
    main()
