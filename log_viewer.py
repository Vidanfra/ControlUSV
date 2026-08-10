#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NAV log viewer - simple GUI to plot telemetry CSV logs written by LoggerProcess.

Left column  : checkboxes -> stacked time-series plots (shared time axis).
Right column : checkboxes -> one map per parameter, track position coloured by
               the parameter and heading/course drawn as arrows.

Run:  python log_viewer.py [path/to/NAV_*.csv]
"""

from __future__ import annotations

import json
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

try:
    import contextily as ctx
except ImportError:
    ctx = None

_HERE = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(_HERE, "logs")
SETTINGS_PATH = os.path.join(_HERE, "data", "log_viewer_settings.json")
TIME_COL = "timestamp_utc"
MAX_CATEGORIES = 30

DEFAULT_SETTINGS = {
    "last_file": "",
    "ts_selected": [],
    "map_selected": [],
    "arrow_field": "",
    "decimation": 20,
    "local_enu": True,
    "basemap": False,
    "single_axes": False,
    "utc_axis": False,
    "sample_markers": True,
    "min_extent_m": 50.0,
    "marker_size": 12.0,
}


def is_lat(col: str) -> bool:
    return col.lower().startswith("latitude")


def is_lon(col: str) -> bool:
    return col.lower().startswith("longitude")


def is_angle(col: str) -> bool:
    low = col.lower()
    return "[deg]" in low and any(k in low for k in ("heading", "course", "yaw", "cog"))


def newest_log() -> str:
    if not os.path.isdir(LOGS_DIR):
        return ""
    csvs = [os.path.join(LOGS_DIR, f) for f in os.listdir(LOGS_DIR) if f.lower().endswith(".csv")]
    return max(csvs, key=os.path.getmtime) if csvs else ""


class ScrollableChecklist(ttk.Frame):
    """Scrollable column of checkboxes."""

    def __init__(self, master, title: str, height: int = 380):
        super().__init__(master)
        ttk.Label(self, text=title, font=("TkDefaultFont", 10, "bold")).pack(anchor="w")

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(2, 4))
        ttk.Button(bar, text="All", width=6, command=self.select_all).pack(side="left")
        ttk.Button(bar, text="None", width=6, command=self.clear_all).pack(side="left", padx=4)

        box = ttk.Frame(self)
        box.pack(fill="both", expand=True)
        self._canvas = tk.Canvas(box, height=height, highlightthickness=0, width=250)
        scroll = ttk.Scrollbar(box, orient="vertical", command=self._canvas.yview)
        self._inner = ttk.Frame(self._canvas)
        self._inner.bind(
            "<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")),
        )
        self._canvas.create_window((0, 0), window=self._inner, anchor="nw")
        self._canvas.configure(yscrollcommand=scroll.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._canvas.bind_all("<MouseWheel>", self._on_wheel)

        self._vars: dict[str, tk.BooleanVar] = {}

    def _on_wheel(self, event):
        widget = self.winfo_toplevel().winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if widget is self._canvas:
                self._canvas.yview_scroll(int(-event.delta / 120), "units")
                return
            widget = getattr(widget, "master", None)

    def set_items(self, items: list[str], preselect: list[str] | None = None) -> None:
        keep = set(preselect or [])
        for child in self._inner.winfo_children():
            child.destroy()
        self._vars = {}
        for name in items:
            var = tk.BooleanVar(value=name in keep)
            ttk.Checkbutton(self._inner, text=name, variable=var).pack(anchor="w")
            self._vars[name] = var

    def selected(self) -> list[str]:
        return [name for name, var in self._vars.items() if var.get()]

    def select_all(self) -> None:
        for var in self._vars.values():
            var.set(True)

    def clear_all(self) -> None:
        for var in self._vars.values():
            var.set(False)


class LogViewer(tk.Tk):
    def __init__(self, initial_file: str | None = None):
        super().__init__()
        self.title("USV NAV log viewer")
        self.geometry("660x760")

        self.df: pd.DataFrame | None = None
        self.numeric_cols: list[str] = []
        self.plottable_cols: list[str] = []
        self.settings = self._load_settings()

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        path = initial_file or self.settings.get("last_file", "")
        if not path or not os.path.isfile(path):
            path = newest_log()
        if path:
            self.path_var.set(path)
            self.load_file()

    # ---------------------------------------------------------- settings ---
    @staticmethod
    def _load_settings() -> dict:
        settings = dict(DEFAULT_SETTINGS)
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as fh:
                stored = json.load(fh)
            if isinstance(stored, dict):
                settings.update({k: v for k, v in stored.items() if k in DEFAULT_SETTINGS})
        except (OSError, ValueError):
            pass
        return settings

    def _save_settings(self) -> None:
        self.settings.update({
            "last_file": self.path_var.get().strip('" '),
            "ts_selected": self.ts_list.selected(),
            "map_selected": self.map_list.selected(),
            "arrow_field": self.arrow_var.get(),
            "decimation": int(self.decim_var.get() or 1),
            "local_enu": bool(self.local_var.get()),
            "basemap": bool(self.basemap_var.get()),
            "single_axes": bool(self.same_axes_var.get()),
            "utc_axis": bool(self.utc_axis_var.get()),
            "sample_markers": bool(self.markers_var.get()),
            "min_extent_m": float(self.min_extent_var.get() or 0.0),
            "marker_size": float(self.marker_size_var.get() or 12.0),
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

    # ---------------------------------------------------------------- UI ---
    def _build_ui(self) -> None:
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        self.path_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.path_var).pack(side="left", fill="x", expand=True)
        ttk.Button(top, text="Browse...", command=self.browse).pack(side="left", padx=4)
        ttk.Button(top, text="Load", command=self.load_file).pack(side="left")

        self.info_var = tk.StringVar(value="No file loaded")
        ttk.Label(self, textvariable=self.info_var, padding=(8, 0)).pack(anchor="w")

        cols = ttk.Frame(self, padding=8)
        cols.pack(fill="both", expand=True)

        left = ttk.Frame(cols)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self.ts_list = ScrollableChecklist(left, "Time series")
        self.ts_list.pack(fill="both", expand=True)

        ts_opts = ttk.Frame(left)
        ts_opts.pack(fill="x", pady=4)
        self.same_axes_var = tk.BooleanVar(value=self.settings["single_axes"])
        ttk.Checkbutton(ts_opts, text="Single axes (overlay)", variable=self.same_axes_var).pack(anchor="w")
        self.utc_axis_var = tk.BooleanVar(value=self.settings["utc_axis"])
        ttk.Checkbutton(ts_opts, text="UTC time axis", variable=self.utc_axis_var).pack(anchor="w")
        self.markers_var = tk.BooleanVar(value=self.settings["sample_markers"])
        ttk.Checkbutton(ts_opts, text="Show every sample (markers)", variable=self.markers_var).pack(anchor="w")
        ttk.Button(left, text="Plot time series", command=self.plot_time_series).pack(fill="x")

        right = ttk.Frame(cols)
        right.pack(side="left", fill="both", expand=True, padx=(6, 0))
        self.map_list = ScrollableChecklist(right, "Maps (colour scale)")
        self.map_list.pack(fill="both", expand=True)

        map_opts = ttk.Frame(right)
        map_opts.pack(fill="x", pady=4)

        pos = ttk.Frame(map_opts)
        pos.pack(fill="x")
        ttk.Label(pos, text="Position:").pack(side="left")
        self.pos_var = tk.StringVar()
        self.pos_combo = ttk.Combobox(pos, textvariable=self.pos_var, state="readonly", width=22)
        self.pos_combo.pack(side="left", padx=4)

        arr = ttk.Frame(map_opts)
        arr.pack(fill="x", pady=2)
        ttk.Label(arr, text="Arrows:").pack(side="left")
        self.arrow_var = tk.StringVar()
        self.arrow_combo = ttk.Combobox(arr, textvariable=self.arrow_var, state="readonly", width=22)
        self.arrow_combo.pack(side="left", padx=4)

        dec = ttk.Frame(map_opts)
        dec.pack(fill="x", pady=2)
        ttk.Label(dec, text="Arrow every N samples:").pack(side="left")
        self.decim_var = tk.IntVar(value=self.settings["decimation"])
        ttk.Spinbox(dec, from_=1, to=1000, textvariable=self.decim_var, width=6).pack(side="left", padx=4)

        ext = ttk.Frame(map_opts)
        ext.pack(fill="x", pady=2)
        ttk.Label(ext, text="Min map extent [m]:").pack(side="left")
        self.min_extent_var = tk.DoubleVar(value=self.settings["min_extent_m"])
        ttk.Spinbox(ext, from_=0, to=5000, increment=10, textvariable=self.min_extent_var,
                    width=6).pack(side="left", padx=4)

        msz = ttk.Frame(map_opts)
        msz.pack(fill="x", pady=2)
        ttk.Label(msz, text="Marker size:").pack(side="left")
        self.marker_size_var = tk.DoubleVar(value=self.settings["marker_size"])
        ttk.Spinbox(msz, from_=1, to=200, increment=2, textvariable=self.marker_size_var,
                    width=6).pack(side="left", padx=4)

        self.local_var = tk.BooleanVar(value=self.settings["local_enu"])
        ttk.Checkbutton(map_opts, text="Local ENU axes [m]", variable=self.local_var).pack(anchor="w")
        self.basemap_var = tk.BooleanVar(value=self.settings["basemap"] and ctx is not None)
        self.basemap_cb = ttk.Checkbutton(
            map_opts,
            text="Satellite basemap (lat/lon only)",
            variable=self.basemap_var,
            state="normal" if ctx else "disabled",
        )
        self.basemap_cb.pack(anchor="w")
        ttk.Button(right, text="Plot maps", command=self.plot_maps).pack(fill="x")

    # -------------------------------------------------------------- data ---
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
            messagebox.showerror("Log viewer", f"File not found:\n{path}")
            return
        try:
            df = pd.read_csv(path)
        except Exception as exc:  # noqa: BLE001 - surface any parse error to the user
            messagebox.showerror("Log viewer", f"Could not read CSV:\n{exc}")
            return

        if TIME_COL not in df.columns:
            messagebox.showerror("Log viewer", f"Missing '{TIME_COL}' column.")
            return

        df[TIME_COL] = pd.to_datetime(df[TIME_COL], format="ISO8601", utc=True, errors="coerce")
        n_raw = len(df)
        df = df.dropna(subset=[TIME_COL]).reset_index(drop=True)
        dropped = n_raw - len(df)
        if df.empty:
            messagebox.showerror("Log viewer", "No valid rows in file.")
            return
        df["_t"] = (df[TIME_COL] - df[TIME_COL].iloc[0]).dt.total_seconds()

        data_cols = [c for c in df.columns if c not in (TIME_COL, "_t")]
        self.numeric_cols = [
            c for c in data_cols
            if pd.api.types.is_numeric_dtype(df[c]) and df[c].notna().any()
        ]
        cat_cols = [
            c for c in data_cols
            if c not in self.numeric_cols and 0 < df[c].nunique(dropna=True) <= MAX_CATEGORIES
        ]
        self.plottable_cols = [c for c in data_cols if c in self.numeric_cols or c in cat_cols]
        self.df = df

        self.ts_list.set_items(self.plottable_cols, self.settings.get("ts_selected"))
        self.map_list.set_items(self.numeric_cols, self.settings.get("map_selected"))

        pairs = self._position_pairs()
        self.pos_combo["values"] = [f"{la} / {lo}" for la, lo in pairs]
        if pairs:
            self.pos_combo.current(0)
        else:
            self.pos_var.set("")

        angles = ["(none)"] + [c for c in self.numeric_cols if is_angle(c)]
        self.arrow_combo["values"] = angles
        stored_arrow = self.settings.get("arrow_field", "")
        self.arrow_combo.current(angles.index(stored_arrow) if stored_arrow in angles
                                 else (1 if len(angles) > 1 else 0))

        dur = df["_t"].iloc[-1]
        msg = (f"{os.path.basename(path)} - {len(df)} rows, {dur:.1f} s "
               f"({dur / 60:.1f} min), {len(data_cols)} columns")
        if dropped:
            msg += f"  [{dropped} rows with bad timestamp skipped]"
        self.info_var.set(msg)
        self._save_settings()

    def _position_pairs(self) -> list[tuple[str, str]]:
        assert self.df is not None
        lats = [c for c in self.numeric_cols if is_lat(c)]
        lons = [c for c in self.numeric_cols if is_lon(c)]
        return [(la, lo) for la, lo in zip(lats, lons)]

    def _series(self, col: str) -> tuple[np.ndarray, list[str] | None]:
        """Return plottable values; for text columns return codes + tick labels."""
        assert self.df is not None
        s = self.df[col]
        if col in self.numeric_cols:
            return s.to_numpy(dtype=float), None
        cat = s.astype("category")
        return cat.cat.codes.to_numpy(dtype=float), list(cat.cat.categories.astype(str))

    # ------------------------------------------------------------- plots ---
    def plot_time_series(self) -> None:
        if self.df is None:
            messagebox.showinfo("Log viewer", "Load a log file first.")
            return
        cols = self.ts_list.selected()
        if not cols:
            messagebox.showinfo("Log viewer", "Select at least one time-series variable.")
            return
        self._save_settings()

        use_utc = self.utc_axis_var.get()
        x = self.df[TIME_COL].dt.tz_convert("UTC") if use_utc else self.df["_t"]
        xlabel = "UTC time" if use_utc else "Elapsed time [s]"
        marker = "." if self.markers_var.get() else None

        if self.same_axes_var.get():
            fig, ax = plt.subplots(figsize=(12, 6))
            for col in cols:
                y, labels = self._series(col)
                ax.plot(x, y, lw=1.0, marker=marker, ms=3, label=col)
                if labels:
                    ax.set_yticks(range(len(labels)))
                    ax.set_yticklabels(labels)
            ax.set_xlabel(xlabel)
            ax.grid(True, alpha=0.3)
            ax.legend(fontsize=8, ncol=2)
            axes = [ax]
        else:
            fig, axes = plt.subplots(
                len(cols), 1, sharex=True, figsize=(12, min(2.0 * len(cols) + 1, 11))
            )
            axes = np.atleast_1d(axes).tolist()
            for ax, col in zip(axes, cols):
                y, labels = self._series(col)
                ax.plot(x, y, lw=1.0, marker=marker, ms=3, color="tab:blue")
                ax.set_ylabel(col, fontsize=8)
                ax.grid(True, alpha=0.3)
                if labels:
                    ax.set_yticks(range(len(labels)))
                    ax.set_yticklabels(labels, fontsize=7)
            axes[-1].set_xlabel(xlabel)

        if use_utc:
            fig.autofmt_xdate()
        fig.suptitle(f"{os.path.basename(self.path_var.get())} - {len(self.df)} samples", fontsize=10)
        fig.tight_layout()
        plt.show(block=False)

    def _xy(self, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray, str, str]:
        if self.local_var.get():
            lat0, lon0 = float(np.nanmean(lat)), float(np.nanmean(lon))
            east = np.radians(lon - lon0) * 6378137.0 * np.cos(np.radians(lat0))
            north = np.radians(lat - lat0) * 6356752.3
            return east, north, "East [m]", "North [m]"
        return lon, lat, "Longitude [deg]", "Latitude [deg]"

    def plot_maps(self) -> None:
        if self.df is None:
            messagebox.showinfo("Log viewer", "Load a log file first.")
            return
        pairs = self._position_pairs()
        if not pairs:
            messagebox.showerror("Log viewer", "No latitude/longitude columns found in this log.")
            return
        self._save_settings()
        idx = max(self.pos_combo.current(), 0)
        lat_col, lon_col = pairs[idx]

        lat = self.df[lat_col].to_numpy(dtype=float)
        lon = self.df[lon_col].to_numpy(dtype=float)
        valid = np.isfinite(lat) & np.isfinite(lon) & ~((lat == 0.0) & (lon == 0.0))
        if valid.sum() < 2:
            messagebox.showerror("Log viewer", "Not enough valid position samples.")
            return

        x, y, xlabel, ylabel = self._xy(lat, lon)
        params = self.map_list.selected() or [None]
        for param in params:
            self._plot_one_map(x, y, lat, valid, param, xlabel, ylabel, f"{lat_col} / {lon_col}")
        plt.show(block=False)

    def _set_extent(self, ax, x, y, lat_ref: float) -> None:
        """Frame the track, never tighter than the configured minimum extent."""
        min_m = max(float(self.min_extent_var.get() or 0.0), 0.0)
        if self.local_var.get():
            m_per_x = m_per_y = 1.0
        else:
            m_per_y = 111320.0
            m_per_x = 111320.0 * max(np.cos(np.radians(lat_ref)), 1e-6)
        cx, cy = 0.5 * (x.min() + x.max()), 0.5 * (y.min() + y.max())
        half_x = max(0.575 * (x.max() - x.min()), 0.5 * min_m / m_per_x, 1e-9)
        half_y = max(0.575 * (y.max() - y.min()), 0.5 * min_m / m_per_y, 1e-9)
        ax.set_xlim(cx - half_x, cx + half_x)
        ax.set_ylim(cy - half_y, cy + half_y)

    @staticmethod
    def _add_basemap(ax) -> None:
        provider = ctx.providers.Esri.WorldImagery
        max_zoom = int(provider.get("max_zoom", 19) or 19)
        for zoom in (min(19, max_zoom), 17, 15):
            try:
                ctx.add_basemap(ax, crs="EPSG:4326", source=provider,
                                zoom=zoom, attribution_size=6)
                return
            except Exception as exc:  # noqa: BLE001 - basemap is best-effort
                last = exc
        print(f"Basemap unavailable: {last}")

    def _plot_one_map(self, x, y, lat, valid, param, xlabel, ylabel, pos_label) -> None:
        assert self.df is not None
        size = float(self.marker_size_var.get() or 12.0)
        fig, ax = plt.subplots(figsize=(9, 8))
        ax.plot(x[valid], y[valid], "-", color="0.6", lw=0.8, zorder=1)

        n_total = len(x)
        if param is None:
            ax.scatter(x[valid], y[valid], s=size, c="tab:blue", zorder=2)
            n_shown = int(valid.sum())
            title = f"Track ({pos_label})"
        else:
            c = self.df[param].to_numpy(dtype=float)
            m = valid & np.isfinite(c)
            sc = ax.scatter(x[m], y[m], c=c[m], s=size, cmap="viridis", zorder=2)
            fig.colorbar(sc, ax=ax, label=param)
            n_shown = int(m.sum())
            title = f"Track coloured by {param}"
        title += f"\n{n_shown} of {n_total} samples plotted"

        ax.plot(x[valid][0], y[valid][0], "o", color="lime", ms=10, mec="k", zorder=4, label="start")
        ax.plot(x[valid][-1], y[valid][-1], "s", color="red", ms=9, mec="k", zorder=4, label="end")

        arrow_col = self.arrow_var.get()
        if arrow_col and arrow_col != "(none)":
            step = max(int(self.decim_var.get()), 1)
            ang = self.df[arrow_col].to_numpy(dtype=float)
            m = valid & np.isfinite(ang)
            sel = np.flatnonzero(m)[::step]
            if sel.size:
                theta = np.radians(ang[sel])
                ax.quiver(
                    x[sel], y[sel], np.sin(theta), np.cos(theta),
                    angles="uv", scale_units="inches", scale=6.0, width=0.003,
                    color="crimson", zorder=3,
                )
                ax.add_artist(
                    ax.legend(
                        handles=[
                            Line2D([], [], color="crimson", marker=">", ls="-", label=arrow_col),
                            Line2D([], [], color="lime", marker="o", ls="", mec="k", label="start"),
                            Line2D([], [], color="red", marker="s", ls="", mec="k", label="end"),
                        ],
                        fontsize=8, loc="best",
                    )
                )
        else:
            ax.legend(fontsize=8, loc="best")

        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.set_title(title, fontsize=10)
        ax.grid(True, alpha=0.3)

        lat_ref = float(np.nanmean(lat[valid]))
        if self.local_var.get():
            ax.set_aspect("equal", adjustable="box")
        else:
            ax.set_aspect(1.0 / max(np.cos(np.radians(lat_ref)), 1e-6), adjustable="box")
        self._set_extent(ax, x[valid], y[valid], lat_ref)
        if not self.local_var.get() and self.basemap_var.get() and ctx is not None:
            self._add_basemap(ax)
        fig.tight_layout()


def main() -> None:
    initial = sys.argv[1] if len(sys.argv) > 1 else None
    LogViewer(initial).mainloop()


if __name__ == "__main__":
    main()
