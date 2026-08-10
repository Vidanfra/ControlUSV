#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Yaw inertia / damping identification from USV NAV logs.

Model:      Ieff * r_dot = N_prop(t) - d1*r - d2*r*|r|,   r = yaw rate [rad/s]
Actuation:  N_prop = (b/2) * (T_port - T_stbd),  T from bollard-pull values.

Three estimators are run over a user-selected interval:
  A  initial angular acceleration after the command step (r ~ 0 -> no damping)
  B  steady-state rate + free decay after the thrust cut
  C  nonlinear least-squares fit of the full ODE to the measured yaw angle

Select the file, tick "Correct IMU scale" if the log was written with the
rad->deg logger bug, then drag over the plot to pick the manoeuvre.

Run:  python yaw_inertia_id.py [path/to/NAV_*.csv]
"""

from __future__ import annotations

import json
import math
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.widgets import SpanSelector
from scipy.optimize import least_squares

_HERE = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(_HERE, "logs")
SETTINGS_PATH = os.path.join(_HERE, "data", "yaw_id_settings.json")
TIME_COL = "timestamp_utc"

G = 9.80665
IMU_SCALE_FIX = 180.0 / math.pi  # logger bug: state attitude multiplied by this

DEFAULTS = {
    "last_file": "",
    "yaw_source": "",
    "fix_imu": True,
    "drop_repeats": True,
    "t_fwd_kgf": 9.5,
    "t_rev_kgf": 5.5,
    "separation_m": 1.53,
    "prop_tau_s": 0.1,
    "a_skip_s": 0.2,
    "a_win_s": 1.0,
    "quad_damping": True,
    "fit_delay": True,
    "wn": 1.5,
    "zeta": 0.7,
    "t0": 0.0,
    "t1": 0.0,
}


# --------------------------------------------------------------------- model --
def thrust_n(cmd_pct, t_fwd_n: float, t_rev_n: float) -> np.ndarray:
    """Command->thrust map with separate forward / reverse bollard gains.

    Quadratic because the ESP32 maps percent linearly to the ESC pulse width
    (us = 1500 + 5*pct), i.e. to propeller speed, and thrust goes with n**2.
    """
    c = np.asarray(cmd_pct, dtype=float) / 100.0
    return np.where(c >= 0.0, c * c * t_fwd_n, -c * c * t_rev_n)


def yaw_moment(port_pct, stbd_pct, t_fwd_n: float, t_rev_n: float, sep_m: float) -> np.ndarray:
    arm = 0.5 * sep_m
    return arm * (thrust_n(port_pct, t_fwd_n, t_rev_n) - thrust_n(stbd_pct, t_fwd_n, t_rev_n))


def simulate(t_cmd, n_cmd, I, d1, d2, psi0, r0, prop_tau=0.1, dt=0.01):
    """RK4 integration of the yaw ODE driven by the logged command moment."""
    t0, t1 = float(t_cmd[0]), float(t_cmd[-1])
    steps = max(int(math.ceil((t1 - t0) / dt)), 2)
    tg = np.linspace(t0, t1, steps + 1)
    h = tg[1] - tg[0]

    N = np.interp(tg, t_cmd, n_cmd)
    if prop_tau > 0.0:
        a = h / (prop_tau + h)
        for k in range(1, N.size):
            N[k] = N[k - 1] + a * (N[k] - N[k - 1])

    psi = np.empty_like(tg)
    r = np.empty_like(tg)
    psi[0], r[0] = psi0, r0

    def rdot(rv, nv):
        return (nv - d1 * rv - d2 * rv * abs(rv)) / I

    for k in range(tg.size - 1):
        n0, nh, n1 = N[k], 0.5 * (N[k] + N[k + 1]), N[k + 1]
        k1p, k1r = r[k], rdot(r[k], n0)
        k2p, k2r = r[k] + 0.5 * h * k1r, rdot(r[k] + 0.5 * h * k1r, nh)
        k3p, k3r = r[k] + 0.5 * h * k2r, rdot(r[k] + 0.5 * h * k2r, nh)
        k4p, k4r = r[k] + h * k3r, rdot(r[k] + h * k3r, n1)
        psi[k + 1] = psi[k] + h / 6.0 * (k1p + 2 * k2p + 2 * k3p + k4p)
        r[k + 1] = r[k] + h / 6.0 * (k1r + 2 * k2r + 2 * k3r + k4r)
    return tg, psi, r, N


# ----------------------------------------------------------------- estimators --
def _phase_masks(t, n_moment, frac=0.5):
    """Split the segment into thrust-on / thrust-off phases."""
    peak = np.nanmax(np.abs(n_moment))
    if not np.isfinite(peak) or peak <= 0:
        return None, None, None
    on = np.abs(n_moment) >= frac * peak
    idx = np.flatnonzero(on)
    if idx.size < 2:
        return None, None, None
    i_on, i_off = idx[0], idx[-1]
    off = np.zeros_like(on)
    off[i_off + 1:] = np.abs(n_moment[i_off + 1:]) < 0.1 * peak
    return on, off, (t[i_on], t[i_off])


def method_a(t, psi, n_moment, skip=0.2, win=1.0):
    """Ieff = N / psi_ddot measured right after the step, where damping ~ 0."""
    _, _, edges = _phase_masks(t, n_moment)
    if edges is None:
        return {"ok": False, "msg": "no thrust step found in the selection"}
    t_on = edges[0]
    m = (t >= t_on + skip) & (t <= t_on + skip + win)
    if m.sum() < 4:
        return {"ok": False, "msg": f"only {int(m.sum())} samples in the {win:g} s fit window"}
    tt = t[m] - t[m][0]
    c2, c1, _ = np.polyfit(tt, psi[m], 2)
    rdot = 2.0 * c2
    n_mean = float(np.mean(n_moment[m]))
    if rdot == 0 or np.sign(rdot) != np.sign(n_mean):
        return {"ok": False, "msg": "measured angular acceleration opposes the commanded moment"}
    return {"ok": True, "I": n_mean / rdot, "rdot": rdot, "r0": c1,
            "N": n_mean, "n": int(m.sum()), "t_fit": (t[m][0], t[m][-1])}


def method_b(t, psi, n_moment, ss_frac=0.3):
    """d1 from the steady-state rate; Ieff = d1 * tau from the free decay."""
    _, off, edges = _phase_masks(t, n_moment)
    if edges is None:
        return {"ok": False, "msg": "no thrust step found in the selection"}
    t_on, t_off = edges

    dur = t_off - t_on
    m_ss = (t >= t_off - max(ss_frac * dur, 0.3)) & (t <= t_off)
    if m_ss.sum() < 3:
        return {"ok": False, "msg": "thrust-on phase too short for a steady-state estimate"}
    r_ss = float(np.polyfit(t[m_ss], psi[m_ss], 1)[0])
    n_ss = float(np.mean(n_moment[m_ss]))
    if r_ss == 0 or np.sign(r_ss) != np.sign(n_ss):
        return {"ok": False, "msg": "steady-state rate opposes the commanded moment"}
    d1 = n_ss / r_ss

    m_off = off & (t > t_off)
    if m_off.sum() < 5:
        return {"ok": False, "r_ss": r_ss, "d1": d1, "N_ss": n_ss,
                "msg": "no free-decay phase in the selection (cut the thrust to zero and keep logging)"}

    td, pd_ = t[m_off] - t[m_off][0], psi[m_off]

    def resid(p):
        psi_c, r0, tau = p[0], p[1], abs(p[2]) + 1e-3
        return psi_c + r0 * tau * (1.0 - np.exp(-td / tau)) - pd_

    sol = least_squares(resid, [pd_[0], r_ss, 1.5], method="lm", max_nfev=5000)
    psi_c, r0, tau = sol.x[0], sol.x[1], abs(sol.x[2]) + 1e-3
    rms = float(np.degrees(np.sqrt(np.mean(sol.fun ** 2))))
    return {"ok": True, "I": d1 * tau, "d1": d1, "tau": tau, "r_ss": r_ss, "r0_decay": r0,
            "N_ss": n_ss, "psi_c": psi_c, "rms_deg": rms, "n": int(m_off.sum()),
            "t_off": t_off}


def method_c(t, psi, n_moment, i_guess, d1_guess, quad=True, fit_delay=True, prop_tau=0.1):
    """Full nonlinear least-squares fit of the ODE over the whole selection."""
    d2_guess = 1.0 if quad else 0.0
    head = max(4, len(t) // 10)
    r_guess = float(np.clip(np.polyfit(t[:head], psi[:head], 1)[0], -4.9, 4.9))

    p0 = [math.log(max(i_guess, 1.0)), math.log(max(d1_guess, 1e-3)), r_guess, 0.0]
    lo = [math.log(1.0), math.log(1e-3), -5.0, 0.0]
    hi = [math.log(1e5), math.log(1e5), 5.0, 0.5 if fit_delay else 1e-9]
    if quad:
        p0.insert(2, math.log(max(d2_guess, 1e-3)))
        lo.insert(2, math.log(1e-4))
        hi.insert(2, math.log(1e5))

    def unpack(p):
        I, d1 = math.exp(p[0]), math.exp(p[1])
        d2 = math.exp(p[2]) if quad else 0.0
        r0, delay = p[-2], p[-1]
        return I, d1, d2, r0, delay

    def resid(p):
        I, d1, d2, r0, delay = unpack(p)
        tg, psim, _, _ = simulate(t, n_moment, I, d1, d2, psi[0], r0, prop_tau=prop_tau)
        return np.interp(t - delay, tg, psim) - psi

    sol = least_squares(resid, p0, bounds=(lo, hi), max_nfev=4000)
    I, d1, d2, r0, delay = unpack(sol.x)
    tg, psim, rm, nm = simulate(t, n_moment, I, d1, d2, psi[0], r0, prop_tau=prop_tau)
    return {"ok": sol.success or sol.status > 0, "I": I, "d1": d1, "d2": d2, "r0": r0,
            "delay": delay, "rms_deg": float(np.degrees(np.sqrt(np.mean(sol.fun ** 2)))),
            "n": int(t.size), "t_model": tg, "psi_model": psim, "r_model": rm,
            "n_model": nm, "cost": float(sol.cost)}


# ------------------------------------------------------------------------ GUI --
class YawIdApp(tk.Tk):
    def __init__(self, initial_file: str | None = None):
        super().__init__()
        self.title("USV yaw inertia identification")
        self.geometry("1180x900")

        self.df: pd.DataFrame | None = None
        self.angle_cols: list[str] = []
        self.port_col: str | None = None
        self.stbd_col: str | None = None
        self.settings = self._load_settings()
        self.last_result: dict | None = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        path = initial_file or self.settings.get("last_file", "")
        if not path or not os.path.isfile(path):
            path = self._newest_log()
        if path:
            self.path_var.set(path)
            self.load_file()

    # ---------------------------------------------------------- persistence --
    @staticmethod
    def _newest_log() -> str:
        if not os.path.isdir(LOGS_DIR):
            return ""
        files = [os.path.join(LOGS_DIR, f) for f in os.listdir(LOGS_DIR) if f.lower().endswith(".csv")]
        return max(files, key=os.path.getmtime) if files else ""

    @staticmethod
    def _load_settings() -> dict:
        s = dict(DEFAULTS)
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
                stored = json.load(fh)
            if isinstance(stored, dict):
                s.update({k: v for k, v in stored.items() if k in DEFAULTS})
        except (OSError, ValueError):
            pass
        return s

    def _save_settings(self) -> None:
        self.settings.update({
            "last_file": self.path_var.get().strip('" '),
            "yaw_source": self.yaw_var.get(),
            "fix_imu": bool(self.fix_var.get()),
            "drop_repeats": bool(self.drop_var.get()),
            "t_fwd_kgf": self._f(self.tf_var), "t_rev_kgf": self._f(self.tr_var),
            "separation_m": self._f(self.sep_var), "prop_tau_s": self._f(self.lag_var),
            "a_skip_s": self._f(self.skip_var), "a_win_s": self._f(self.win_var),
            "quad_damping": bool(self.quad_var.get()), "fit_delay": bool(self.delay_var.get()),
            "wn": self._f(self.wn_var), "zeta": self._f(self.zeta_var),
            "t0": self._f(self.t0_var), "t1": self._f(self.t1_var),
        })
        try:
            os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
            with open(SETTINGS_PATH, "w", encoding="utf-8") as fh:
                json.dump(self.settings, fh, indent=2)
        except OSError as exc:
            print(f"Could not save settings: {exc}")

    def _on_close(self) -> None:
        self._save_settings()
        plt.close("all")
        self.destroy()

    @staticmethod
    def _f(var) -> float:
        try:
            return float(var.get())
        except (tk.TclError, ValueError):
            return 0.0

    # ------------------------------------------------------------------ ui --
    def _build_ui(self) -> None:
        s = self.settings

        top = ttk.Frame(self, padding=6)
        top.pack(fill="x")
        self.path_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.path_var).pack(side="left", fill="x", expand=True)
        ttk.Button(top, text="Browse...", command=self.browse).pack(side="left", padx=4)
        ttk.Button(top, text="Load", command=self.load_file).pack(side="left")

        self.info_var = tk.StringVar(value="No file loaded")
        ttk.Label(self, textvariable=self.info_var, padding=(6, 0)).pack(anchor="w")

        r1 = ttk.Frame(self, padding=(6, 4))
        r1.pack(fill="x")
        ttk.Label(r1, text="Yaw source:").pack(side="left")
        self.yaw_var = tk.StringVar()
        self.yaw_combo = ttk.Combobox(r1, textvariable=self.yaw_var, state="readonly", width=24)
        self.yaw_combo.pack(side="left", padx=4)
        self.yaw_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_plot())
        self.fix_var = tk.BooleanVar(value=s["fix_imu"])
        ttk.Checkbutton(r1, text=f"Correct IMU scale (÷{IMU_SCALE_FIX:.4f})", variable=self.fix_var,
                        command=self.refresh_plot).pack(side="left", padx=10)
        self.drop_var = tk.BooleanVar(value=s["drop_repeats"])
        ttk.Checkbutton(r1, text="Drop repeated samples", variable=self.drop_var).pack(side="left")

        r2 = ttk.Frame(self, padding=(6, 2))
        r2.pack(fill="x")
        self.tf_var = tk.DoubleVar(value=s["t_fwd_kgf"])
        self.tr_var = tk.DoubleVar(value=s["t_rev_kgf"])
        self.sep_var = tk.DoubleVar(value=s["separation_m"])
        self.lag_var = tk.DoubleVar(value=s["prop_tau_s"])
        for label, var, w in (("Thrust fwd [kgf]:", self.tf_var, 6),
                              ("reverse [kgf]:", self.tr_var, 6),
                              ("motor separation [m]:", self.sep_var, 6),
                              ("prop lag [s]:", self.lag_var, 5)):
            ttk.Label(r2, text=label).pack(side="left")
            ttk.Entry(r2, textvariable=var, width=w).pack(side="left", padx=(2, 10))

        r3 = ttk.Frame(self, padding=(6, 2))
        r3.pack(fill="x")
        self.skip_var = tk.DoubleVar(value=s["a_skip_s"])
        self.win_var = tk.DoubleVar(value=s["a_win_s"])
        ttk.Label(r3, text="Method A skip [s]:").pack(side="left")
        ttk.Entry(r3, textvariable=self.skip_var, width=5).pack(side="left", padx=(2, 8))
        ttk.Label(r3, text="window [s]:").pack(side="left")
        ttk.Entry(r3, textvariable=self.win_var, width=5).pack(side="left", padx=(2, 12))
        self.quad_var = tk.BooleanVar(value=s["quad_damping"])
        ttk.Checkbutton(r3, text="quadratic damping (d2)", variable=self.quad_var).pack(side="left")
        self.delay_var = tk.BooleanVar(value=s["fit_delay"])
        ttk.Checkbutton(r3, text="fit sensor delay", variable=self.delay_var).pack(side="left", padx=10)
        ttk.Label(r3, text="PID wn:").pack(side="left")
        self.wn_var = tk.DoubleVar(value=s["wn"])
        ttk.Entry(r3, textvariable=self.wn_var, width=5).pack(side="left", padx=2)
        ttk.Label(r3, text="zeta:").pack(side="left")
        self.zeta_var = tk.DoubleVar(value=s["zeta"])
        ttk.Entry(r3, textvariable=self.zeta_var, width=5).pack(side="left", padx=2)

        r4 = ttk.Frame(self, padding=(6, 2))
        r4.pack(fill="x")
        ttk.Label(r4, text="Interval  t0 [s]:").pack(side="left")
        self.t0_var = tk.DoubleVar(value=s["t0"])
        ttk.Entry(r4, textvariable=self.t0_var, width=9).pack(side="left", padx=2)
        ttk.Label(r4, text="t1 [s]:").pack(side="left")
        self.t1_var = tk.DoubleVar(value=s["t1"])
        ttk.Entry(r4, textvariable=self.t1_var, width=9).pack(side="left", padx=2)
        ttk.Button(r4, text="Apply to plot", command=self._draw_span).pack(side="left", padx=6)
        ttk.Button(r4, text="Analyse interval", command=self.analyse).pack(side="left", padx=6)
        ttk.Label(r4, text="(drag over the plot to select)").pack(side="left", padx=6)

        plot_frame = ttk.Frame(self)
        plot_frame.pack(fill="both", expand=True, padx=6)
        self.fig, (self.ax_yaw, self.ax_cmd) = plt.subplots(
            2, 1, sharex=True, figsize=(11, 4.4), gridspec_kw={"height_ratios": [2, 1]}
        )
        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        NavigationToolbar2Tk(self.canvas, plot_frame).update()
        self.span = SpanSelector(self.ax_yaw, self._on_span, "horizontal", useblit=True,
                                 props={"alpha": 0.25, "facecolor": "tab:orange"},
                                 interactive=True, drag_from_anywhere=True)

        self.text = tk.Text(self, height=16, wrap="none", font=("Consolas", 9))
        self.text.pack(fill="both", expand=False, padx=6, pady=(4, 6))

    # ---------------------------------------------------------------- data --
    def browse(self) -> None:
        path = filedialog.askopenfilename(
            title="Select NAV log",
            initialdir=LOGS_DIR if os.path.isdir(LOGS_DIR) else os.getcwd(),
            filetypes=[("CSV logs", "*.csv"), ("All files", "*.*")],
        )
        if path:
            self.path_var.set(path)
            self.load_file()

    def load_file(self) -> None:
        path = self.path_var.get().strip('" ')
        if not os.path.isfile(path):
            messagebox.showerror("Yaw ID", f"File not found:\n{path}")
            return
        try:
            df = pd.read_csv(path)
        except Exception as exc:  # noqa: BLE001 - surface parse errors to the user
            messagebox.showerror("Yaw ID", f"Could not read CSV:\n{exc}")
            return
        if TIME_COL not in df.columns:
            messagebox.showerror("Yaw ID", f"Missing '{TIME_COL}' column.")
            return

        df[TIME_COL] = pd.to_datetime(df[TIME_COL], format="ISO8601", utc=True, errors="coerce")
        df = df.dropna(subset=[TIME_COL]).reset_index(drop=True)
        if df.empty:
            messagebox.showerror("Yaw ID", "No valid rows in file.")
            return
        df["_t"] = (df[TIME_COL] - df[TIME_COL].iloc[0]).dt.total_seconds()
        self.df = df

        self.port_col = self._find(df, "motor port")
        self.stbd_col = self._find(df, "motor starboard")
        if not self.port_col or not self.stbd_col:
            messagebox.showerror("Yaw ID", "Motor Port / Motor Starboard columns not found.")
            return

        cands = [c for c in df.columns
                 if pd.api.types.is_numeric_dtype(df[c])
                 and any(k in c.lower() for k in ("yaw", "heading", "gyro z", "course"))
                 and "status" not in c.lower() and "error" not in c.lower()
                 and "target" not in c.lower()]
        self.angle_cols = cands
        self.yaw_combo["values"] = cands
        stored = self.settings.get("yaw_source", "")
        if stored in cands:
            self.yaw_var.set(stored)
        elif cands:
            yaws = [c for c in cands if "yaw" in c.lower() or "gyro" in c.lower()]
            self.yaw_var.set(yaws[0] if yaws else cands[0])

        dur = df["_t"].iloc[-1]
        self.info_var.set(f"{os.path.basename(path)} - {len(df)} rows, {dur:.1f} s, "
                          f"yaw candidates: {len(cands)}")
        if not (0 < self._f(self.t1_var) <= dur):
            self.t0_var.set(0.0)
            self.t1_var.set(round(dur, 2))
        self.refresh_plot()
        self._save_settings()

    @staticmethod
    def _find(df: pd.DataFrame, key: str) -> str | None:
        for c in df.columns:
            if c.lower().startswith(key):
                return c
        return None

    def _yaw_series(self) -> tuple[np.ndarray, np.ndarray, bool, str]:
        """Return (t, yaw_deg_or_rate, is_rate, label) with the IMU fix applied."""
        assert self.df is not None
        col = self.yaw_var.get()
        y = self.df[col].to_numpy(dtype=float)
        label = col
        if self.fix_var.get() and self._is_state_attitude(col):
            y = y / IMU_SCALE_FIX
            label += "  (÷57.2958)"
        is_rate = "/s]" in col.lower() or "gyro" in col.lower()
        return self.df["_t"].to_numpy(dtype=float), y, is_rate, label

    @staticmethod
    def _is_state_attitude(col: str) -> bool:
        """The logger bug only affected the EKF-state roll/pitch/yaw columns."""
        low = col.lower()
        return low.startswith(("yaw", "roll", "pitch"))

    def _moment(self) -> np.ndarray:
        assert self.df is not None
        return yaw_moment(self.df[self.port_col].to_numpy(dtype=float),
                          self.df[self.stbd_col].to_numpy(dtype=float),
                          self._f(self.tf_var) * G, self._f(self.tr_var) * G,
                          self._f(self.sep_var))

    # --------------------------------------------------------------- plots --
    def refresh_plot(self) -> None:
        if self.df is None or not self.yaw_var.get() or not self.port_col:
            return
        t, y, is_rate, label = self._yaw_series()
        self.ax_yaw.clear()
        self.ax_cmd.clear()

        self.ax_yaw.plot(t, y, lw=0.9, color="tab:blue", label=label)
        self.ax_yaw.set_ylabel("yaw rate [deg/s]" if is_rate else "angle [deg]")
        head = self._find(self.df, "heading [deg]")
        if head and head != self.yaw_var.get() and not is_rate:
            self.ax_yaw.plot(t, self.df[head].to_numpy(dtype=float), lw=0.8,
                             color="0.6", label=head)
        self.ax_yaw.legend(fontsize=8, loc="upper right")
        self.ax_yaw.grid(True, alpha=0.3)

        self.ax_cmd.plot(t, self.df[self.port_col], lw=0.9, color="tab:green", label="port [%]")
        self.ax_cmd.plot(t, self.df[self.stbd_col], lw=0.9, color="tab:red", label="starboard [%]")
        self.ax_cmd.set_ylabel("cmd [%]")
        self.ax_cmd.set_xlabel("elapsed time [s]")
        self.ax_cmd.grid(True, alpha=0.3)
        self.ax_cmd.legend(fontsize=8, loc="upper right")

        self.fig.tight_layout()
        self._draw_span()

    def _draw_span(self) -> None:
        t0, t1 = self._f(self.t0_var), self._f(self.t1_var)
        if t1 > t0:
            self.span.extents = (t0, t1)
        self.canvas.draw_idle()

    def _on_span(self, t0: float, t1: float) -> None:
        if t1 - t0 < 1e-6:
            return
        self.t0_var.set(round(t0, 2))
        self.t1_var.set(round(t1, 2))

    # ------------------------------------------------------------ analysis --
    def analyse(self) -> None:
        if self.df is None:
            messagebox.showinfo("Yaw ID", "Load a log file first.")
            return
        if not self.port_col or not self.stbd_col or not self.yaw_var.get():
            messagebox.showerror("Yaw ID", "Motor command or yaw columns are missing.")
            return
        t_all, y_all, is_rate, label = self._yaw_series()
        n_all = self._moment()
        t0, t1 = self._f(self.t0_var), self._f(self.t1_var)
        if t1 <= t0:
            messagebox.showinfo("Yaw ID", "Select an interval on the plot first.")
            return

        m = (t_all >= t0) & (t_all <= t1) & np.isfinite(y_all) & np.isfinite(n_all)
        t, y, nm = t_all[m], y_all[m], n_all[m]
        if t.size < 10:
            messagebox.showinfo("Yaw ID", f"Only {t.size} samples in the interval.")
            return

        notes = []
        if self.drop_var.get():
            keep = np.ones(t.size, dtype=bool)
            keep[1:] = np.diff(y) != 0.0
            if keep.sum() >= 10 and keep.sum() < t.size:
                notes.append(f"dropped {t.size - int(keep.sum())} repeated (stale) yaw samples")
                t, y, nm = t[keep], y[keep], nm[keep]

        # Work in SI: continuous yaw angle [rad], moment [N.m].
        if is_rate:
            r_meas = np.radians(y)
            psi = np.concatenate([[0.0], np.cumsum(0.5 * (r_meas[1:] + r_meas[:-1]) * np.diff(t))])
            notes.append("rate source integrated to an angle before fitting")
        else:
            psi = np.unwrap(np.radians(y))

        sign = 1.0
        rn = np.gradient(psi, t)
        if float(np.dot(rn, nm)) < 0.0:
            sign = -1.0
            psi = -psi
            notes.append("yaw sign flipped: the source counts positive opposite to the "
                         "commanded moment (starboard-positive)")

        t = t - t[0]
        psi = psi - psi[0]
        dt_med = float(np.median(np.diff(t))) if t.size > 2 else float("nan")

        skip, win = self._f(self.skip_var), self._f(self.win_var)
        res_a = method_a(t, psi, nm, skip=skip, win=win)
        res_b = method_b(t, psi, nm)

        i_guess = res_a.get("I") if res_a.get("ok") else (res_b.get("I") if res_b.get("ok") else 100.0)
        d1_guess = res_b.get("d1") or (i_guess / 1.5)
        res_c = method_c(t, psi, nm, abs(i_guess), abs(d1_guess),
                         quad=self.quad_var.get(), fit_delay=self.delay_var.get(),
                         prop_tau=self._f(self.lag_var))

        self.last_result = {"t": t, "psi": psi, "N": nm, "a": res_a, "b": res_b, "c": res_c,
                            "label": label, "sign": sign, "t0": t0, "t1": t1}
        self._report(dt_med, notes)
        self._plot_fit()
        self._save_settings()

    def _report(self, dt_med: float, notes: list[str]) -> None:
        r = self.last_result
        a, b, c = r["a"], r["b"], r["c"]
        peak_n = float(np.nanmax(np.abs(r["N"])))
        out = []
        add = out.append

        add(f"File     : {os.path.basename(self.path_var.get())}")
        add(f"Interval : {r['t0']:.2f} .. {r['t1']:.2f} s   ({r['t'].size} samples, "
            f"median dt = {dt_med * 1000:.0f} ms)")
        add(f"Source   : {r['label']}   sign = {'+' if r['sign'] > 0 else '-'}")
        add(f"Actuation: T_fwd {self._f(self.tf_var):.2f} kgf, T_rev {self._f(self.tr_var):.2f} kgf, "
            f"arm {0.5 * self._f(self.sep_var):.3f} m  ->  peak |N| = {peak_n:.1f} N.m")
        for n in notes:
            add(f"  note   : {n}")
        add("")

        add("A - initial angular acceleration (damping-free)")
        if a.get("ok"):
            add(f"    psi_ddot = {a['rdot']:.4f} rad/s2 ({math.degrees(a['rdot']):.2f} deg/s2)"
                f"   N = {a['N']:.1f} N.m   [{a['n']} samples]")
            add(f"    Ieff = {a['I']:.1f} kg.m2")
        else:
            add(f"    not available: {a['msg']}")
        add("")

        add("B - steady state + free decay")
        if b.get("r_ss") is not None:
            add(f"    r_ss = {math.degrees(b['r_ss']):.2f} deg/s   N_ss = {b.get('N_ss', float('nan')):.1f} N.m"
                f"   d1 = {b['d1']:.1f} N.m.s")
        if b.get("ok"):
            add(f"    tau  = {b['tau']:.3f} s   (decay fit RMS {b['rms_deg']:.2f} deg, {b['n']} samples)")
            add(f"    Ieff = {b['I']:.1f} kg.m2")
        else:
            add(f"    not available: {b['msg']}")
        add("")

        add("C - full ODE nonlinear least squares")
        add(f"    Ieff = {c['I']:.1f} kg.m2   d1 = {c['d1']:.1f} N.m.s   d2 = {c['d2']:.1f} N.m.s2")
        add(f"    r0 = {math.degrees(c['r0']):.2f} deg/s   sensor delay = {c['delay'] * 1000:.0f} ms"
            f"   heading RMS = {c['rms_deg']:.2f} deg   [{c['n']} samples]")
        add(f"    tau_yaw = Ieff/d1 = {c['I'] / c['d1']:.2f} s")
        add("")

        wn, zeta = self._f(self.wn_var), self._f(self.zeta_var)
        i_best = c["I"]
        kp = i_best * wn ** 2
        kd = 2.0 * zeta * wn * i_best - c["d1"]
        add(f"PID from C at wn={wn:g} rad/s, zeta={zeta:g}:  Kp = {kp:.1f} N.m/rad   "
            f"Kd = {kd:.1f} N.m.s/rad   (Ki ~ {kp * wn / 10:.1f})")
        spread = [x["I"] for x in (a, b, c) if x.get("ok")]
        if len(spread) > 1:
            add(f"Ieff spread across methods: {min(spread):.1f} .. {max(spread):.1f} kg.m2 "
                f"({(max(spread) / min(spread) - 1) * 100:.0f}% apart)")
        add("Reminder: this is Izz + added inertia, and a shallow pool inflates both "
            "added inertia and damping.")

        self.text.delete("1.0", "end")
        self.text.insert("1.0", "\n".join(out))

    def _plot_fit(self) -> None:
        r = self.last_result
        a, b, c = r["a"], r["b"], r["c"]
        t, psi, nm = r["t"], r["psi"], r["N"]

        fig, axes = plt.subplots(3, 1, sharex=True, figsize=(11, 8))
        ax0, ax1, ax2 = axes

        ax0.plot(t, np.degrees(psi), "o", ms=2.5, color="tab:blue", label="measured")
        ax0.plot(c["t_model"] + c["delay"], np.degrees(c["psi_model"]), "-", lw=1.4,
                 color="tab:red", label=f"C fit (RMS {c['rms_deg']:.2f}°)")
        if a.get("ok"):
            ta = np.linspace(a["t_fit"][0], a["t_fit"][1], 20)
            tt = ta - a["t_fit"][0]
            i0 = int(np.argmin(np.abs(t - a["t_fit"][0])))
            ax0.plot(ta, np.degrees(psi[i0] + a["r0"] * tt + 0.5 * a["rdot"] * tt ** 2), "--",
                     lw=1.6, color="tab:green", label="A quadratic fit")
        ax0.set_ylabel("yaw angle [deg]")
        ax0.grid(True, alpha=0.3)
        ax0.legend(fontsize=8)

        ax1.plot(t, np.degrees(np.gradient(psi, t)), ".", ms=3, color="0.5",
                 label="measured (numeric d/dt)")
        ax1.plot(c["t_model"] + c["delay"], np.degrees(c["r_model"]), "-", lw=1.4,
                 color="tab:red", label="C model")
        if b.get("ok"):
            td = np.linspace(0.0, t[-1] - b["t_off"], 50)
            ax1.plot(b["t_off"] + td, np.degrees(b["r0_decay"] * np.exp(-td / b["tau"])), "--",
                     lw=1.6, color="tab:purple", label=f"B decay (tau={b['tau']:.2f}s)")
            ax1.axhline(math.degrees(b["r_ss"]), color="tab:orange", lw=1.0, ls=":",
                        label=f"r_ss={math.degrees(b['r_ss']):.1f}°/s")
        ax1.set_ylabel("yaw rate [deg/s]")
        ax1.grid(True, alpha=0.3)
        ax1.legend(fontsize=8)

        ax2.plot(t, nm, lw=1.0, color="k", label="commanded N")
        ax2.plot(c["t_model"], c["n_model"], lw=1.0, color="tab:cyan",
                 label=f"with prop lag {self._f(self.lag_var):g}s")
        ax2.set_ylabel("yaw moment [N.m]")
        ax2.set_xlabel("time in interval [s]")
        ax2.grid(True, alpha=0.3)
        ax2.legend(fontsize=8)

        fig.suptitle(f"Yaw identification  {r['t0']:.1f}-{r['t1']:.1f} s   "
                     f"Ieff: A={a.get('I', float('nan')):.0f}  B={b.get('I', float('nan')):.0f}  "
                     f"C={c['I']:.0f} kg.m2", fontsize=10)
        fig.tight_layout()
        plt.show(block=False)


def main() -> None:
    YawIdApp(sys.argv[1] if len(sys.argv) > 1 else None).mainloop()


if __name__ == "__main__":
    main()
