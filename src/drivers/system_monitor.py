"""SystemMonitorProcess — samples host CPU, RAM, disk, temperature, network at 1 Hz."""
import os
import platform
import socket
import time

from loguru import logger

from src.core.messaging import Publisher, Topics
from src.core.models import SystemMonitorMessage
from src.core.process import ServiceProcess

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


def _read_cpu_temp_linux() -> float:
    """Best-effort CPU temperature on Linux/Raspberry Pi. Returns 0.0 if unavailable."""
    if _HAS_PSUTIL:
        try:
            temps = psutil.sensors_temperatures()
            for key in ("cpu_thermal", "coretemp", "k10temp", "cpu-thermal"):
                if key in temps and temps[key]:
                    return float(temps[key][0].current)
            for entries in temps.values():
                if entries:
                    return float(entries[0].current)
        except Exception:
            pass
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            return float(f.read().strip()) / 1000.0
    except Exception:
        return 0.0


class SystemMonitorProcess(ServiceProcess):
    """Publishes SystemMonitorMessage on Topics.SYSTEM_MONITOR at 1 Hz."""

    def setup(self):
        if not _HAS_PSUTIL:
            logger.warning("SystemMonitor: psutil not installed — CPU/RAM/disk stats will be 0")
        self.pub = Publisher(Topics.SYSTEM_MONITOR)
        self.hostname = socket.gethostname()
        self.os_name = platform.system()
        self._last_net_ts = time.time()
        self._last_net_rx = 0
        self._last_net_tx = 0
        if _HAS_PSUTIL:
            try:
                io = psutil.net_io_counters()
                self._last_net_rx = io.bytes_recv
                self._last_net_tx = io.bytes_sent
                psutil.cpu_percent(interval=None)  # prime
            except Exception:
                pass
        logger.info(f"SystemMonitor initialized (host={self.hostname}, os={self.os_name})")

    def loop(self):
        now = time.time()
        msg = SystemMonitorMessage(
            timestamp=now,
            hostname=self.hostname,
            os_name=self.os_name,
        )

        if _HAS_PSUTIL:
            try:
                msg.cpu_percent = float(psutil.cpu_percent(interval=None))
            except Exception:
                pass
            try:
                vm = psutil.virtual_memory()
                msg.ram_used_mb = vm.used / (1024 * 1024)
                msg.ram_total_mb = vm.total / (1024 * 1024)
                msg.ram_percent = float(vm.percent)
            except Exception:
                pass
            try:
                root = "/" if self.os_name != "Windows" else "C:\\"
                du = psutil.disk_usage(root)
                msg.disk_used_gb = du.used / (1024 ** 3)
                msg.disk_total_gb = du.total / (1024 ** 3)
                msg.disk_percent = float(du.percent)
            except Exception:
                pass
            try:
                msg.uptime_s = now - psutil.boot_time()
            except Exception:
                pass
            try:
                io = psutil.net_io_counters()
                dt = max(now - self._last_net_ts, 1e-3)
                drx = io.bytes_recv - self._last_net_rx
                dtx = io.bytes_sent - self._last_net_tx
                msg.net_rx_kbps = (drx * 8 / 1000.0) / dt
                msg.net_tx_kbps = (dtx * 8 / 1000.0) / dt
                self._last_net_rx = io.bytes_recv
                self._last_net_tx = io.bytes_sent
                self._last_net_ts = now
            except Exception:
                pass

        msg.cpu_temp_c = _read_cpu_temp_linux() if self.os_name == "Linux" else 0.0

        self.pub.publish(msg.model_dump())

    def cleanup(self):
        try:
            self.pub.close()
        except Exception:
            pass
