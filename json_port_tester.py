#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JSON Port Tester — standalone GUI to verify JsonBroadcaster output.

Listens on a chosen UDP port or connects to a TCP server (the broadcaster's
TCP mode is a server, so this tool acts as the client) and shows:
  - connection state + last error
  - packet/sec rate and bytes/sec throughput (1 s and 5 s windows)
  - total packets / bytes
  - last raw payload (pretty-printed JSON)
  - a live table of every field in the latest payload (key, value, type)

Run:
    python json_port_tester.py
"""
import json
import queue
import socket
import threading
import time
import tkinter as tk
from collections import deque
from tkinter import ttk


# ────────────────────────────────────────────────────────────────────────
# Background receiver thread — pushes parsed messages into a queue.
# ────────────────────────────────────────────────────────────────────────
class Receiver(threading.Thread):
    def __init__(self, protocol: str, host: str, port: int, out_q: queue.Queue):
        super().__init__(daemon=True)
        self.protocol = protocol
        self.host = host
        self.port = port
        self.out_q = out_q
        self.stop_event = threading.Event()
        self._sock = None

    def stop(self):
        self.stop_event.set()
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass

    # ── UDP ────────────────────────────────────────────────────────────
    def _run_udp(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Bind to the chosen port on the chosen interface (use "" for all)
        bind_host = "" if self.host in ("0.0.0.0", "", "any") else self.host
        try:
            self._sock.bind((bind_host, self.port))
        except OSError as e:
            self.out_q.put(("error", f"UDP bind failed on {bind_host}:{self.port} — {e}"))
            return
        self._sock.settimeout(0.5)
        self.out_q.put(("info", f"UDP listening on {bind_host or '*'}:{self.port}"))
        while not self.stop_event.is_set():
            try:
                data, addr = self._sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            self._handle(data, addr)

    # ── TCP (client) ───────────────────────────────────────────────────
    def _run_tcp(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(3.0)
        try:
            self._sock.connect((self.host, self.port))
        except OSError as e:
            self.out_q.put(("error", f"TCP connect failed → {self.host}:{self.port} — {e}"))
            return
        self.out_q.put(("info", f"TCP connected to {self.host}:{self.port}"))
        self._sock.settimeout(0.5)
        buf = b""
        while not self.stop_event.is_set():
            try:
                chunk = self._sock.recv(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                self.out_q.put(("error", "TCP server closed the connection"))
                break
            buf += chunk
            # Broadcaster delimits messages with '\n'
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if line.strip():
                    self._handle(line, (self.host, self.port))

    def _handle(self, data: bytes, addr):
        try:
            obj = json.loads(data.decode("utf-8", errors="replace"))
        except Exception as e:
            self.out_q.put(("error", f"JSON parse failed ({e}): {data[:120]!r}"))
            return
        self.out_q.put(("msg", {"obj": obj, "len": len(data), "addr": addr, "ts": time.time()}))

    def run(self):
        try:
            if self.protocol == "udp":
                self._run_udp()
            else:
                self._run_tcp()
        except Exception as e:
            self.out_q.put(("error", f"Receiver crashed: {e}"))
        finally:
            try:
                if self._sock:
                    self._sock.close()
            except Exception:
                pass
            self.out_q.put(("info", "Receiver stopped"))


# ────────────────────────────────────────────────────────────────────────
# Tkinter GUI
# ────────────────────────────────────────────────────────────────────────
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("JSON Port Tester — ControlUSV")
        root.geometry("900x620")
        root.minsize(700, 480)

        self.q: queue.Queue = queue.Queue()
        self.recv: Receiver | None = None

        # Stats
        self.total_pkts = 0
        self.total_bytes = 0
        self.hist_1s = deque()    # (ts, bytes)
        self.hist_5s = deque()
        self.last_msg_ts = 0.0
        self.last_payload: dict | None = None

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._drain_queue)
        self.root.after(500, self._refresh_stats)

    # ── UI ────────────────────────────────────────────────────────────
    def _build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # ── Connection bar ───────────────────────────────────────────
        bar = ttk.Frame(self.root, padding=8)
        bar.pack(fill="x")

        ttk.Label(bar, text="Protocol:").grid(row=0, column=0, sticky="e")
        self.var_proto = tk.StringVar(value="udp")
        ttk.Combobox(bar, textvariable=self.var_proto, values=["udp", "tcp"],
                     width=6, state="readonly").grid(row=0, column=1, padx=4)

        ttk.Label(bar, text="Host/IP:").grid(row=0, column=2, sticky="e", padx=(12, 0))
        self.var_host = tk.StringVar(value="127.0.0.1")
        ttk.Entry(bar, textvariable=self.var_host, width=18).grid(row=0, column=3, padx=4)

        ttk.Label(bar, text="Port:").grid(row=0, column=4, sticky="e", padx=(12, 0))
        self.var_port = tk.StringVar(value="9000")
        ttk.Entry(bar, textvariable=self.var_port, width=8).grid(row=0, column=5, padx=4)

        self.btn_conn = ttk.Button(bar, text="Connect", command=self._toggle)
        self.btn_conn.grid(row=0, column=6, padx=10)

        ttk.Button(bar, text="Reset stats", command=self._reset_stats)\
            .grid(row=0, column=7, padx=4)

        # UDP help hint
        hint = ttk.Label(self.root,
                         text="UDP: this tool BINDS the port to receive the broadcast "
                              "(use 0.0.0.0 to listen on all interfaces).   "
                              "TCP: this tool CONNECTS to the broadcaster (which is the server).",
                         foreground="#555")
        hint.pack(fill="x", padx=8)

        # ── Status / stats strip ─────────────────────────────────────
        stats = ttk.LabelFrame(self.root, text="Live stats", padding=6)
        stats.pack(fill="x", padx=8, pady=6)

        def stat_cell(parent, label, col):
            ttk.Label(parent, text=label, foreground="#555").grid(row=0, column=col, padx=8, sticky="w")
            v = tk.StringVar(value="—")
            ttk.Label(parent, textvariable=v, font=("Consolas", 11, "bold"))\
                .grid(row=1, column=col, padx=8, sticky="w")
            return v

        self.var_state    = stat_cell(stats, "State",        0)
        self.var_rate1    = stat_cell(stats, "Rate (1 s)",   1)
        self.var_rate5    = stat_cell(stats, "Rate (5 s)",   2)
        self.var_thru1    = stat_cell(stats, "Throughput",   3)
        self.var_avgsize  = stat_cell(stats, "Avg pkt size", 4)
        self.var_total    = stat_cell(stats, "Total pkts",   5)
        self.var_bytes    = stat_cell(stats, "Total bytes",  6)
        self.var_age      = stat_cell(stats, "Last pkt age", 7)
        self.var_state.set("disconnected")

        # ── Paned: table on top, raw JSON on bottom ───────────────────
        pane = ttk.PanedWindow(self.root, orient="vertical")
        pane.pack(fill="both", expand=True, padx=8, pady=(0, 6))

        # Field table
        tbl_frame = ttk.LabelFrame(pane, text="Latest payload — field table", padding=4)
        cols = ("key", "value", "type")
        self.tree = ttk.Treeview(tbl_frame, columns=cols, show="headings", height=12)
        self.tree.heading("key",   text="Field")
        self.tree.heading("value", text="Value")
        self.tree.heading("type",  text="Type")
        self.tree.column("key",   width=240, anchor="w")
        self.tree.column("value", width=420, anchor="w")
        self.tree.column("type",  width=80,  anchor="w")
        tsb = ttk.Scrollbar(tbl_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tsb.pack(side="right", fill="y")
        pane.add(tbl_frame, weight=3)

        # Raw JSON
        raw_frame = ttk.LabelFrame(pane, text="Raw JSON (last packet)", padding=4)
        self.txt = tk.Text(raw_frame, height=10, wrap="word",
                           font=("Consolas", 9), bg="#111", fg="#9ef",
                           insertbackground="#fff")
        rsb = ttk.Scrollbar(raw_frame, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=rsb.set)
        self.txt.pack(side="left", fill="both", expand=True)
        rsb.pack(side="right", fill="y")
        pane.add(raw_frame, weight=2)

        # ── Log line at the bottom ───────────────────────────────────
        self.var_log = tk.StringVar(value="Ready.")
        ttk.Label(self.root, textvariable=self.var_log, foreground="#444",
                  anchor="w", padding=4).pack(fill="x")

    # ── connect / disconnect ──────────────────────────────────────────
    def _toggle(self):
        if self.recv and self.recv.is_alive():
            self._stop_recv()
            return
        try:
            port = int(self.var_port.get())
            if not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            self._log("Port must be an integer 1–65535", err=True)
            return
        proto = self.var_proto.get()
        host = self.var_host.get().strip() or "127.0.0.1"
        self._reset_stats()
        self.recv = Receiver(proto, host, port, self.q)
        self.recv.start()
        self.btn_conn.configure(text="Disconnect")
        self.var_state.set(f"{proto.upper()} starting…")

    def _stop_recv(self):
        if self.recv:
            self.recv.stop()
            self.recv.join(timeout=2.0)
            self.recv = None
        self.btn_conn.configure(text="Connect")
        self.var_state.set("disconnected")

    def _on_close(self):
        self._stop_recv()
        self.root.destroy()

    # ── stats ─────────────────────────────────────────────────────────
    def _reset_stats(self):
        self.total_pkts = 0
        self.total_bytes = 0
        self.hist_1s.clear()
        self.hist_5s.clear()
        self.last_msg_ts = 0.0
        self.last_payload = None
        self.txt.delete("1.0", "end")
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.var_total.set("0")
        self.var_bytes.set("0")
        self.var_rate1.set("—")
        self.var_rate5.set("—")
        self.var_thru1.set("—")
        self.var_avgsize.set("—")
        self.var_age.set("—")

    def _refresh_stats(self):
        now = time.time()
        # Prune windows
        while self.hist_1s and now - self.hist_1s[0][0] > 1.0:
            self.hist_1s.popleft()
        while self.hist_5s and now - self.hist_5s[0][0] > 5.0:
            self.hist_5s.popleft()

        rate1 = len(self.hist_1s)
        rate5 = len(self.hist_5s) / 5.0 if self.hist_5s else 0.0
        bytes1 = sum(b for _, b in self.hist_1s)
        avg_size = (self.total_bytes / self.total_pkts) if self.total_pkts else 0

        self.var_rate1.set(f"{rate1} pkt/s")
        self.var_rate5.set(f"{rate5:.1f} pkt/s")
        self.var_thru1.set(f"{bytes1/1024:.1f} kB/s")
        self.var_avgsize.set(f"{avg_size:.0f} B")
        self.var_total.set(str(self.total_pkts))
        self.var_bytes.set(f"{self.total_bytes:,}")
        if self.last_msg_ts > 0:
            age = now - self.last_msg_ts
            self.var_age.set(f"{age:.2f} s")
        self.root.after(500, self._refresh_stats)

    # ── queue drain ───────────────────────────────────────────────────
    def _drain_queue(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "msg":
                    self._on_msg(payload)
                elif kind == "info":
                    self._log(payload)
                    self.var_state.set(payload if "listening" in payload or "connected" in payload
                                       else self.var_state.get())
                elif kind == "error":
                    self._log(payload, err=True)
                    self.var_state.set("error")
        except queue.Empty:
            pass
        self.root.after(80, self._drain_queue)

    def _on_msg(self, info: dict):
        now = info["ts"]
        n = info["len"]
        obj = info["obj"]
        self.total_pkts += 1
        self.total_bytes += n
        self.hist_1s.append((now, n))
        self.hist_5s.append((now, n))
        self.last_msg_ts = now
        self.last_payload = obj
        self.var_state.set(f"receiving from {info['addr'][0]}:{info['addr'][1]}")

        # Update raw text (truncate if huge)
        try:
            pretty = json.dumps(obj, indent=2, default=str)
        except Exception:
            pretty = str(obj)
        if len(pretty) > 50_000:
            pretty = pretty[:50_000] + "\n…(truncated)"
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", pretty)

        # Update field table
        rows = list(self._flatten(obj))
        existing = self.tree.get_children()
        # Rebuild if shape changed; otherwise update in place to avoid flicker
        if len(existing) != len(rows) or any(
            self.tree.item(iid, "values")[0] != rows[i][0] for i, iid in enumerate(existing)
        ):
            for iid in existing:
                self.tree.delete(iid)
            for key, val, typ in rows:
                self.tree.insert("", "end", values=(key, val, typ))
        else:
            for iid, (key, val, typ) in zip(existing, rows):
                self.tree.item(iid, values=(key, val, typ))

    @staticmethod
    def _flatten(obj, prefix=""):
        """Yield (key, value-as-str, type-name) for every leaf in a JSON tree."""
        if isinstance(obj, dict):
            for k, v in obj.items():
                yield from App._flatten(v, f"{prefix}.{k}" if prefix else k)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                yield from App._flatten(v, f"{prefix}[{i}]")
        else:
            t = type(obj).__name__
            if isinstance(obj, float):
                s = f"{obj:.6g}"
            else:
                s = "" if obj is None else str(obj)
            if len(s) > 300:
                s = s[:300] + "…"
            yield (prefix or "(root)", s, t)

    # ── log ────────────────────────────────────────────────────────────
    def _log(self, msg: str, err: bool = False):
        ts = time.strftime("%H:%M:%S")
        self.var_log.set(f"[{ts}] {'ERR ' if err else ''}{msg}")


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
