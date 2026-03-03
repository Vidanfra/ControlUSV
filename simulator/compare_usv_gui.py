#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
USV Comparison Tool - GUI for comparing Otter and Salpa1 USV simulations

This tool allows you to:
- Add multiple simulation configurations (vehicle, heading, current, thrust, payload)
- Run all simulations and compare results in the same plots
- Easily analyze different operating conditions
- Generate waypoint routes from satellite map

Author: USV Salpa 1 Navigation Development
Date: December 2025
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
from optimization import run_optimization_matrix
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import threading
import webbrowser
import tempfile
import os
from datetime import datetime
import json
import http.server
import socketserver
from urllib.parse import parse_qs, urlparse
import pandas as pd
import contextily as ctx
import geopandas as gpd
from shapely.geometry import Point, LineString

# Import vehicle models
from otter_original import otter
from otter import otter as otter_updated
from salpa1 import salpa1
from simulation.gnc import Rzyx, ssa
from simulation.guidance import ALOSpathFollowing

# Settings file path
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'settings.json')


class USVComparisonGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("USV Comparison Tool - Otter vs Salpa1")
        self.root.geometry("1400x800")
        
        # Simulation configurations list (Heading)
        self.simulations = []
        self.sim_counter = 0
        self.results = []
        
        # Path Following configurations
        self.path_simulations = []
        self.path_sim_counter = 0
        self.path_results = []
        self.waypoints_file = None
        self.waypoints_data = None
        
        # Create main frames
        self.create_widgets()
        
        # Load saved settings
        self.load_settings()
        
        # Save settings on close
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
    def create_widgets(self):
        """Create all GUI widgets with Tabs"""
        # Create Notebook (Tabs)
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Create Tabs
        self.heading_tab = ttk.Frame(self.notebook)
        self.path_tab = ttk.Frame(self.notebook)
        
        self.notebook.add(self.heading_tab, text="Heading Control")
        self.notebook.add(self.path_tab, text="Path Following")
        
        # Initialize tabs
        self._init_heading_tab()
        self._init_path_tab()

    def _init_heading_tab(self):
        """Initialize Heading Control Tab"""
        
        # ====================================================================
        # Top Frame - Simulation Parameters
        # ====================================================================
        top_frame = ttk.LabelFrame(self.heading_tab, text="Simulation Parameters", padding=10)
        top_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Time parameters
        ttk.Label(top_frame, text="Total Time (s):").grid(row=0, column=0, padx=5, pady=5)
        self.total_time_var = tk.StringVar(value="200")
        ttk.Entry(top_frame, textvariable=self.total_time_var, width=10).grid(row=0, column=1, padx=5, pady=5)
        
        ttk.Label(top_frame, text="Time Step (s):").grid(row=0, column=2, padx=5, pady=5)
        self.time_step_var = tk.StringVar(value="0.02")
        ttk.Entry(top_frame, textvariable=self.time_step_var, width=10).grid(row=0, column=3, padx=5, pady=5)
        
        ttk.Label(top_frame, text="(50 Hz = 0.02s, 100 Hz = 0.01s)").grid(row=0, column=4, padx=5, pady=5)
        
        # ====================================================================
        # Middle Frame - Configuration Input
        # ====================================================================
        input_frame = ttk.LabelFrame(self.heading_tab, text="Add Simulation Configuration", padding=10)
        input_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Row 1: Vehicle selection and basic parameters
        ttk.Label(input_frame, text="Vehicle:").grid(row=0, column=0, padx=5, pady=5)
        self.vehicle_var = tk.StringVar(value="salpa1")
        vehicle_combo = ttk.Combobox(input_frame, textvariable=self.vehicle_var, 
                                      values=["otter_original", "otter_updated", "salpa1"], width=12, state="readonly")
        vehicle_combo.grid(row=0, column=1, padx=5, pady=5)
        
        ttk.Label(input_frame, text="Desired Yaw (°):").grid(row=0, column=2, padx=5, pady=5)
        self.yaw_var = tk.StringVar(value="90")
        ttk.Entry(input_frame, textvariable=self.yaw_var, width=10).grid(row=0, column=3, padx=5, pady=5)
        
        ttk.Label(input_frame, text="Current Speed (m/s):").grid(row=0, column=4, padx=5, pady=5)
        self.current_speed_var = tk.StringVar(value="0.0")
        ttk.Entry(input_frame, textvariable=self.current_speed_var, width=10).grid(row=0, column=5, padx=5, pady=5)
        
        ttk.Label(input_frame, text="Current Dir (°):").grid(row=0, column=6, padx=5, pady=5)
        self.current_dir_var = tk.StringVar(value="0")
        ttk.Entry(input_frame, textvariable=self.current_dir_var, width=10).grid(row=0, column=7, padx=5, pady=5)
        
        # Row 2: Force and payload
        ttk.Label(input_frame, text="Surge Force (N):").grid(row=1, column=0, padx=5, pady=5)
        self.surge_force_var = tk.StringVar(value="150")
        ttk.Entry(input_frame, textvariable=self.surge_force_var, width=10).grid(row=1, column=1, padx=5, pady=5)
        
        ttk.Label(input_frame, text="Payload (kg):").grid(row=1, column=2, padx=5, pady=5)
        self.payload_var = tk.StringVar(value="25")
        ttk.Entry(input_frame, textvariable=self.payload_var, width=10).grid(row=1, column=3, padx=5, pady=5)
        
        # Add button
        add_btn = ttk.Button(input_frame, text="Add Configuration", command=self.add_simulation)
        add_btn.grid(row=1, column=5, padx=10, pady=5)
        
        # Quick add buttons
        ttk.Button(input_frame, text="Add Otter Default", 
                   command=self.add_otter_default).grid(row=1, column=6, padx=5, pady=5)
        ttk.Button(input_frame, text="Add Salpa1 Default", 
                   command=self.add_salpa1_default).grid(row=1, column=7, padx=5, pady=5)
        
        # ====================================================================
        # Table Frame - Simulation List
        # ====================================================================
        table_frame = ttk.LabelFrame(self.heading_tab, text="Simulation Configurations", padding=10)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Create Treeview table
        columns = ("ID", "Vehicle", "Yaw (°)", "Current (m/s)", "Current Dir (°)", 
                   "Surge (N)", "Payload (kg)", "Status")
        
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=8)
        
        # Define column headings and widths
        col_widths = [50, 100, 80, 100, 100, 80, 100, 100]
        for col, width in zip(columns, col_widths):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=width, anchor=tk.CENTER)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Table control buttons
        btn_frame = ttk.Frame(table_frame)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=5)
        
        ttk.Button(btn_frame, text="Remove Selected", command=self.remove_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Clear All", command=self.clear_all).pack(side=tk.LEFT, padx=5)
        
        # ====================================================================
        # Control Frame - Run Simulation
        # ====================================================================
        control_frame = ttk.Frame(self.heading_tab, padding=10)
        control_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.run_btn = ttk.Button(control_frame, text="▶ Run All Simulations", 
                                   command=self.run_simulations, style="Accent.TButton")
        self.run_btn.pack(side=tk.LEFT, padx=10)
        
        self.progress_var = tk.StringVar(value="Ready")
        ttk.Label(control_frame, textvariable=self.progress_var).pack(side=tk.LEFT, padx=20)
        
        self.progress_bar = ttk.Progressbar(control_frame, length=300, mode='determinate')
        self.progress_bar.pack(side=tk.LEFT, padx=10)
        
        ttk.Button(control_frame, text="📊 Show Plots", command=self.show_plots).pack(side=tk.RIGHT, padx=10)
        ttk.Button(control_frame, text="💾 Save Plots", command=self.save_plots).pack(side=tk.RIGHT, padx=10)

    def _init_path_tab(self):
        """Initialize Path Following Tab"""
        
        # ====================================================================
        # Top Frame - Simulation Parameters
        # ====================================================================
        top_frame = ttk.LabelFrame(self.path_tab, text="Simulation Parameters", padding=10)
        top_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Time parameters
        ttk.Label(top_frame, text="Total Time (s):").grid(row=0, column=0, padx=5, pady=5)
        self.path_total_time_var = tk.StringVar(value="400")
        ttk.Entry(top_frame, textvariable=self.path_total_time_var, width=10).grid(row=0, column=1, padx=5, pady=5)
        
        ttk.Label(top_frame, text="Time Step (s):").grid(row=0, column=2, padx=5, pady=5)
        self.path_time_step_var = tk.StringVar(value="0.02")
        ttk.Entry(top_frame, textvariable=self.path_time_step_var, width=10).grid(row=0, column=3, padx=5, pady=5)
        
        # Waypoints File Selection
        ttk.Label(top_frame, text="Waypoints File:").grid(row=0, column=4, padx=5, pady=5)
        self.waypoints_file_var = tk.StringVar(value="No file selected")
        ttk.Entry(top_frame, textvariable=self.waypoints_file_var, width=30, state='readonly').grid(row=0, column=5, padx=5, pady=5)
        ttk.Button(top_frame, text="📂 Select CSV", command=self.load_waypoints_file).grid(row=0, column=6, padx=5, pady=5)
        ttk.Button(top_frame, text="🗺️ Generate Route", command=self.generate_route).grid(row=0, column=7, padx=5, pady=5)
        
        # ====================================================================
        # Middle Frame - Configuration Input
        # ====================================================================
        input_frame = ttk.LabelFrame(self.path_tab, text="Add Path Following Configuration", padding=10)
        input_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Row 1: Vehicle selection and basic parameters
        ttk.Label(input_frame, text="Vehicle:").grid(row=0, column=0, padx=5, pady=5)
        self.path_vehicle_var = tk.StringVar(value="salpa1")
        vehicle_combo = ttk.Combobox(input_frame, textvariable=self.path_vehicle_var, 
                                      values=["otter_original", "otter_updated", "salpa1"], width=12, state="readonly")
        vehicle_combo.grid(row=0, column=1, padx=5, pady=5)
        
        ttk.Label(input_frame, text="Look Ahead (m):").grid(row=0, column=2, padx=5, pady=5)
        self.delta_var = tk.StringVar(value="5.0")
        ttk.Entry(input_frame, textvariable=self.delta_var, width=10).grid(row=0, column=3, padx=5, pady=5)

        ttk.Label(input_frame, text="Gamma:").grid(row=0, column=4, padx=5, pady=5)
        self.gamma_var = tk.StringVar(value="0.0")
        ttk.Entry(input_frame, textvariable=self.gamma_var, width=10).grid(row=0, column=5, padx=5, pady=5)
        
        ttk.Label(input_frame, text="Current Speed (m/s):").grid(row=0, column=6, padx=5, pady=5)
        self.path_current_speed_var = tk.StringVar(value="0.0")
        ttk.Entry(input_frame, textvariable=self.path_current_speed_var, width=10).grid(row=0, column=7, padx=5, pady=5)
        
        # Row 2: Force and payload
        ttk.Label(input_frame, text="Current Dir (°):").grid(row=1, column=0, padx=5, pady=5)
        self.path_current_dir_var = tk.StringVar(value="0")
        ttk.Entry(input_frame, textvariable=self.path_current_dir_var, width=10).grid(row=1, column=1, padx=5, pady=5)

        ttk.Label(input_frame, text="Surge Force (N):").grid(row=1, column=2, padx=5, pady=5)
        self.path_surge_force_var = tk.StringVar(value="150")
        ttk.Entry(input_frame, textvariable=self.path_surge_force_var, width=10).grid(row=1, column=3, padx=5, pady=5)
        
        ttk.Label(input_frame, text="Payload (kg):").grid(row=1, column=4, padx=5, pady=5)
        self.path_payload_var = tk.StringVar(value="25")
        ttk.Entry(input_frame, textvariable=self.path_payload_var, width=10).grid(row=1, column=5, padx=5, pady=5)
        
        # Row 3: Autopilot Tuning Parameters
        ttk.Label(input_frame, text="ωn_PID:").grid(row=2, column=0, padx=5, pady=5)
        self.wn_pid_var = tk.StringVar(value="1.5")
        ttk.Entry(input_frame, textvariable=self.wn_pid_var, width=8).grid(row=2, column=1, padx=5, pady=5)
        
        ttk.Label(input_frame, text="ζ_PID:").grid(row=2, column=2, padx=5, pady=5)
        self.zeta_pid_var = tk.StringVar(value="1.0")
        ttk.Entry(input_frame, textvariable=self.zeta_pid_var, width=8).grid(row=2, column=3, padx=5, pady=5)
        
        ttk.Label(input_frame, text="ωn_ref:").grid(row=2, column=4, padx=5, pady=5)
        self.wn_ref_var = tk.StringVar(value="0.5")
        ttk.Entry(input_frame, textvariable=self.wn_ref_var, width=8).grid(row=2, column=5, padx=5, pady=5)
        
        ttk.Label(input_frame, text="ζ_ref:").grid(row=2, column=6, padx=5, pady=5)
        self.zeta_ref_var = tk.StringVar(value="1.0")
        ttk.Entry(input_frame, textvariable=self.zeta_ref_var, width=8).grid(row=2, column=7, padx=5, pady=5)
        
        # Add button
        add_btn = ttk.Button(input_frame, text="Add Configuration", command=self.add_path_simulation)
        add_btn.grid(row=1, column=6, padx=10, pady=5)
        
        # ====================================================================
        # Table Frame - Simulation List
        # ====================================================================
        table_frame = ttk.LabelFrame(self.path_tab, text="Path Following Configurations", padding=10)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Create Treeview table
        columns = ("ID", "Vehicle", "Delta", "Gamma", "ωn_PID", "ζ_PID", "ωn_ref", "ζ_ref", "Status")
        
        self.path_tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=8)
        
        # Define column headings and widths
        col_widths = [40, 80, 50, 50, 55, 45, 50, 45, 70]
        for col, width in zip(columns, col_widths):
            self.path_tree.heading(col, text=col)
            self.path_tree.column(col, width=width, anchor=tk.CENTER)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.path_tree.yview)
        self.path_tree.configure(yscrollcommand=scrollbar.set)
        
        self.path_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Table control buttons
        btn_frame = ttk.Frame(table_frame)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=5)
        
        ttk.Button(btn_frame, text="Remove Selected", command=self.remove_path_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Clear All", command=self.clear_path_all).pack(side=tk.LEFT, padx=5)
        
        # ====================================================================
        # Control Frame - Run Simulation
        # ====================================================================
        control_frame = ttk.Frame(self.path_tab, padding=10)
        control_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.path_run_btn = ttk.Button(control_frame, text="▶ Run Path Simulations", 
                                   command=self.run_path_simulations, style="Accent.TButton")
        self.path_run_btn.pack(side=tk.LEFT, padx=10)
        
        self.path_progress_var = tk.StringVar(value="Ready")
        ttk.Label(control_frame, textvariable=self.path_progress_var).pack(side=tk.LEFT, padx=20)
        
        self.path_progress_bar = ttk.Progressbar(control_frame, length=300, mode='determinate')
        self.path_progress_bar.pack(side=tk.LEFT, padx=10)
        
        ttk.Button(control_frame, text="📊 Show Path Plots", command=self.show_path_plots).pack(side=tk.RIGHT, padx=10)
        
        # Optimization Button
        ttk.Button(control_frame, text="🔍 Optimization Matrix", command=self.run_optimization).pack(side=tk.RIGHT, padx=10)
        
        # Checkbox for arrows
        self.show_arrows_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(control_frame, text="Show Arrows", variable=self.show_arrows_var).pack(side=tk.RIGHT, padx=10)

    def add_path_simulation(self):
        """Add a new path simulation configuration"""
        try:
            config = {
                'id': self.path_sim_counter,
                'vehicle': self.path_vehicle_var.get(),
                'delta': float(self.delta_var.get()),
                'gamma': float(self.gamma_var.get()),
                'current_speed': float(self.path_current_speed_var.get()),
                'current_dir': float(self.path_current_dir_var.get()),
                'surge_force': float(self.path_surge_force_var.get()),
                'payload': float(self.path_payload_var.get()),
                'wn_pid': float(self.wn_pid_var.get()),
                'zeta_pid': float(self.zeta_pid_var.get()),
                'wn_ref': float(self.wn_ref_var.get()),
                'zeta_ref': float(self.zeta_ref_var.get()),
                'status': 'Pending'
            }
            
            self.path_simulations.append(config)
            self.path_sim_counter += 1
            
            # Add to treeview
            self.path_tree.insert("", tk.END, values=(
                config['id'],
                config['vehicle'],
                config['delta'],
                config['gamma'],
                config['wn_pid'],
                config['zeta_pid'],
                config['wn_ref'],
                config['zeta_ref'],
                config['status']
            ))
            
        except ValueError as e:
            messagebox.showerror("Input Error", f"Invalid input values: {e}")

    def remove_path_selected(self):
        """Remove selected path simulation"""
        selected = self.path_tree.selection()
        if selected:
            for item in selected:
                values = self.path_tree.item(item)['values']
                sim_id = values[0]
                self.path_simulations = [s for s in self.path_simulations if s['id'] != sim_id]
                self.path_tree.delete(item)

    def clear_path_all(self):
        """Clear all path simulations"""
        self.path_simulations = []
        self.path_results = []
        for item in self.path_tree.get_children():
            self.path_tree.delete(item)
        self.path_sim_counter = 0

    def load_waypoints_file(self):
        """Load waypoints from CSV file"""
        filename = filedialog.askopenfilename(
            initialdir=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Data'),
            title="Select Waypoints CSV",
            filetypes=(("CSV files", "*.csv"), ("All files", "*.*"))
        )
        
        if filename:
            try:
                self.waypoints_data = pd.read_csv(filename)
                # Check required columns
                required = ['waypoint', 'latitude', 'longitude', 'radius', 'speed']
                if not all(col in self.waypoints_data.columns for col in required):
                    messagebox.showerror("Error", f"CSV must contain columns: {required}")
                    return
                
                self.waypoints_file = filename
                self.waypoints_file_var.set(os.path.basename(filename))
                messagebox.showinfo("Success", f"Loaded {len(self.waypoints_data)} waypoints.")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load file: {e}")

    def latLonToNed(self, lat, lon, lat0, lon0):
        """Convert Lat/Lon to NED (North, East) in meters"""
        R = 6378137  # Earth radius
        dLat = np.deg2rad(lat - lat0)
        dLon = np.deg2rad(lon - lon0)
        lat0Rad = np.deg2rad(lat0)
        
        N = R * dLat
        E = R * np.cos(lat0Rad) * dLon
        return N, E

    def run_optimization(self):
        """Run the optimization matrix function"""
        run_optimization_matrix(self)

    def run_path_simulations(self):
        """Run all path following simulations"""
        if not self.path_simulations:
            messagebox.showwarning("No Simulations", "Please add at least one configuration.")
            return
        
        if self.waypoints_data is None:
            messagebox.showwarning("No Waypoints", "Please select a waypoints file.")
            return
            
        try:
            T_final = float(self.path_total_time_var.get())
            h = float(self.path_time_step_var.get())
        except ValueError:
            messagebox.showerror("Input Error", "Invalid time parameters.")
            return
        
        self.path_results = []
        self.path_progress_bar['value'] = 0
        self.path_run_btn.config(state='disabled')
        
        total_sims = len(self.path_simulations)
        
        # Prepare waypoints in NED
        lat0 = self.waypoints_data.iloc[0]['latitude']
        lon0 = self.waypoints_data.iloc[0]['longitude']
        
        waypoints_ned = []
        for _, row in self.waypoints_data.iterrows():
            n, e = self.latLonToNed(row['latitude'], row['longitude'], lat0, lon0)
            waypoints_ned.append({
                'N': n, 'E': e, 
                'radius': row['radius'], 
                'speed': row['speed'],
                'lat': row['latitude'],
                'lon': row['longitude']
            })
        
        for i, config in enumerate(self.path_simulations):
            self.path_progress_var.set(f"Running {i+1}/{total_sims}: {config['vehicle']}")
            self.root.update()
            
            try:
                result = self.run_single_path_simulation(config, waypoints_ned, T_final, h, lat0, lon0)
                self.path_results.append(result)
                config['status'] = 'Complete'
            except Exception as e:
                config['status'] = f'Error: {str(e)[:20]}'
                print(f"Error in path sim {i}: {e}")
            
            # Update table status
            for item in self.path_tree.get_children():
                values = list(self.path_tree.item(item)['values'])
                if values[0] == config['id']:
                    values[7] = config['status']
                    self.path_tree.item(item, values=values)
                    break
            
            self.path_progress_bar['value'] = (i + 1) / total_sims * 100
            self.root.update()
        
        self.path_progress_var.set(f"Completed {len(self.path_results)}/{total_sims} simulations")
        self.path_run_btn.config(state='normal')
        
        # Save settings after simulation completes
        self.save_settings()
        
        if self.path_results:
            self.show_path_plots()

    def run_single_path_simulation(self, config, waypoints, T_final, h, lat0, lon0):
        """Run a single path following simulation"""
        
        # Create vehicle
        if config['vehicle'] == 'otter':
            vehicle = otter(controlSystem='headingAutopilot', r=0, V_current=config['current_speed'], 
                            beta_current=config['current_dir'], tau_X=config['surge_force'], payload_mass=config['payload'])
        elif config['vehicle'] == 'otter_updated':
            vehicle = otter_updated(controlSystem='headingAutopilot', r=0, V_current=config['current_speed'], 
                                    beta_current=config['current_dir'], tau_X=config['surge_force'], payload_mass=config['payload'])
        else:
            vehicle = salpa1(controlSystem='headingAutopilot', r=0, V_current=config['current_speed'], 
                             beta_current=config['current_dir'], tau_X=config['surge_force'], payload_mass=config['payload'])
        
        # Apply autopilot tuning parameters from config
        vehicle.wn = config.get('wn_pid', 1.5)
        vehicle.zeta = config.get('zeta_pid', 1.0)
        vehicle.wn_d = config.get('wn_ref', 0.5)
        vehicle.zeta_d = config.get('zeta_ref', 1.0)
        
        # Initialize state
        eta = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0], float) # Start at origin (First WP)
        nu = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0], float)
        u_actual = np.array([0.0, 0.0], float)
        
        # Path following state
        wp_index = 0
        current_wp = waypoints[0]
        next_wp = waypoints[1] if len(waypoints) > 1 else waypoints[0]
        beta_c = 0.0 # Sideslip estimate
        prev_progress = 0.0
        
        # Storage
        n_steps = int(T_final / h)
        time_vec = np.linspace(0, T_final, n_steps)
        
        N_hist = np.zeros(n_steps)
        E_hist = np.zeros(n_steps)
        psi_hist = np.zeros(n_steps)
        psi_d_hist = np.zeros(n_steps)
        speed_hist = np.zeros(n_steps)
        cte_hist = np.zeros(n_steps)
        wp_hist = np.zeros(n_steps)
        Nt_hist = np.zeros(n_steps)
        Et_hist = np.zeros(n_steps)
        n1_hist = np.zeros(n_steps)  # Left motor speed
        n2_hist = np.zeros(n_steps)  # Right motor speed
        psi_error_hist = np.zeros(n_steps)  # Heading error
        
        for i in range(n_steps):
            # Store history (wrap angles to [0, 2*pi] for display)
            N_hist[i] = eta[0]
            E_hist[i] = eta[1]
            psi_hist[i] = eta[5] % (2 * np.pi)  # Wrap for display
            speed_hist[i] = np.sqrt(nu[0]**2 + nu[1]**2)
            wp_hist[i] = wp_index
            
            # Check waypoint switching
            dist_to_next = np.sqrt((eta[0] - next_wp['N'])**2 + (eta[1] - next_wp['E'])**2)
            if dist_to_next < next_wp['radius'] and wp_index < len(waypoints) - 2:
                wp_index += 1
                current_wp = waypoints[wp_index]
                next_wp = waypoints[wp_index + 1]
                prev_progress = 0.0
            
            # ALOS Guidance
            wk = np.array([current_wp['N'], current_wp['E']])
            wk_1 = np.array([next_wp['N'], next_wp['E']])
            
            psi_d, beta_c, ye, prev_progress, N_t, E_t = ALOSpathFollowing(eta, wk, wk_1, config['delta'], gamma=config.get('gamma', 0.0), beta_c=beta_c, h=h, prev_progress=prev_progress)
            cte_hist[i] = ye
            psi_d_hist[i] = psi_d % (2 * np.pi)  # Wrap for display
            Nt_hist[i] = N_t
            Et_hist[i] = E_t
            
            # Update vehicle reference
            vehicle.ref = np.rad2deg(psi_d) # Autopilot expects degrees
            
            # Control and Dynamics
            u_control = vehicle.headingAutopilot(eta, nu, h)
            nu, u_actual = vehicle.dynamics(eta, nu, u_actual, u_control, h)
            
            # Store motor speeds and heading error
            n1_hist[i] = u_actual[0]
            n2_hist[i] = u_actual[1]
            psi_error_hist[i] = np.rad2deg(ssa(eta[5] - psi_d))  # Heading error in degrees
            
            # Kinematics
            R = Rzyx(eta[3], eta[4], eta[5])
            eta[0:3] = eta[0:3] + h * np.matmul(R, nu[0:3])
            eta[3] = eta[3] + h * nu[3]
            eta[4] = eta[4] + h * nu[4]
            eta[5] = eta[5] + h * nu[5]
            # Note: psi (eta[5]) kept unwrapped for control continuity
            # Wrapped only when storing to history for display
            
        return {
            'config': config,
            'time': time_vec,
            'N': N_hist,
            'E': E_hist,
            'psi': psi_hist,
            'psi_d': psi_d_hist,
            'speed': speed_hist,
            'cte': cte_hist,
            'Nt': Nt_hist,
            'Et': Et_hist,
            'n1': n1_hist,
            'n2': n2_hist,
            'psi_error': psi_error_hist,
            'waypoints': waypoints,
            'lat0': lat0,
            'lon0': lon0
        }

    def show_path_plots(self):
        """Display path following comparison plots"""
        if not self.path_results:
            messagebox.showwarning("No Results", "Please run simulations first.")
            return
        
        # Figure 1: Standard Plots
        fig1, axes = plt.subplots(2, 2, figsize=(16, 12))
        fig1.suptitle('Path Following Comparison', fontsize=16, fontweight='bold')
        
        colors = plt.cm.tab10(np.linspace(0, 1, len(self.path_results)))
        
        for idx, result in enumerate(self.path_results):
            config = result['config']
            label = f"{config['id']}: ωn={config.get('wn_pid', 1.5)}, ζ={config.get('zeta_pid', 1.0)}, ωn_d={config.get('wn_ref', 0.5)}"
            color = colors[idx]
            
            # Plot 1: XY Track
            ax1 = axes[0, 0]
            ax1.plot(result['E'], result['N'], '-', color=color, linewidth=1.5, label=label)
            
            # Plot Virtual Point and Heading Arrows every second
            if self.show_arrows_var.get():
                if 'Nt' in result and 'Et' in result:
                    if len(result['time']) > 1:
                        h = result['time'][1] - result['time'][0]
                        steps_per_sec = int(1.0 / h)
                        if steps_per_sec > 0:
                            vp_E = result['Et'][::steps_per_sec]
                            vp_N = result['Nt'][::steps_per_sec]
                            ax1.plot(vp_E, vp_N, 'x', color=color, markersize=4, alpha=0.6)
                            
                            # Plot Heading Arrows every second
                            idx_sample = slice(0, len(result['time']), steps_per_sec)
                            E_samp = result['E'][idx_sample]
                            N_samp = result['N'][idx_sample]
                            psi_samp = result['psi'][idx_sample]
                            psi_d_samp = result['psi_d'][idx_sample]
                            
                            # Actual Heading (Vehicle Color)
                            # NED: N=cos, E=sin
                            U_act = np.sin(psi_samp)
                            V_act = np.cos(psi_samp)
                            ax1.quiver(E_samp, N_samp, U_act, V_act, color=color, scale=30, width=0.003, headwidth=3, alpha=0.8, label='_nolegend_')
                            
                            # Reference Heading (Black/Dark Gray)
                            U_ref = np.sin(psi_d_samp)
                            V_ref = np.cos(psi_d_samp)
                            ax1.quiver(E_samp, N_samp, U_ref, V_ref, color='k', scale=30, width=0.002, headwidth=3, alpha=0.5, label='_nolegend_')

            # Plot waypoints
            if idx == 0: # Only plot waypoints once
                wps_N = [wp['N'] for wp in result['waypoints']]
                wps_E = [wp['E'] for wp in result['waypoints']]
                ax1.plot(wps_E, wps_N, 'r--o', alpha=0.5, label='Route')
                
                # Draw acceptance radius circles
                for wp in result['waypoints']:
                    circle = Circle((wp['E'], wp['N']), wp['radius'], color='k', fill=False, linestyle='--', alpha=0.3)
                    ax1.add_patch(circle)
        
        ax1.set_ylabel('North [m]')
        ax1.set_xlabel('East [m]')
        ax1.set_title('XY Track')
        ax1.legend()
        ax1.grid(True)
        ax1.axis('equal')
        
        # Plot 2: Heading
        ax2 = axes[0, 1]
        for idx, result in enumerate(self.path_results):
            config = result['config']
            color = colors[idx]
            ax2.plot(result['time'], np.rad2deg(result['psi']), '-', color=color, label=f"{config['id']} - {config['vehicle']}")
            ax2.plot(result['time'], np.rad2deg(result['psi_d']), '--', color=color)
        ax2.set_ylabel('Heading [deg]')
        ax2.set_title('Heading')
        ax2.grid(True)
        
        # Plot 3: Cross-track Error
        ax3 = axes[1, 0]
        for idx, result in enumerate(self.path_results):
            config = result['config']
            color = colors[idx]
            ax3.plot(result['time'], result['cte'], '-', color=color, label=f"{config['id']} - {config['vehicle']}")
        ax3.set_ylabel('Cross-track Error [m]')
        ax3.set_title('Cross-track Error')
        ax3.grid(True)
        
        # Plot 4: Speed
        ax4 = axes[1, 1]
        for idx, result in enumerate(self.path_results):
            config = result['config']
            color = colors[idx]
            ax4.plot(result['time'], result['speed'], '-', color=color, label=f"{config['id']} - {config['vehicle']}")
        ax4.set_ylabel('Speed [m/s]')
        ax4.set_title('Speed')
        ax4.grid(True)
        
        plt.tight_layout()
        
        # Figure 2: Satellite Map
        fig2, ax_map = plt.subplots(figsize=(12, 12))
        fig2.suptitle('Satellite Map Trajectory', fontsize=16)
        
        # Convert trajectories to Lat/Lon and create GeoDataFrame
        R = 6378137
        
        for idx, result in enumerate(self.path_results):
            lat0 = result['lat0']
            lon0 = result['lon0']
            lat0Rad = np.deg2rad(lat0)
            
            # NED to Lat/Lon
            lats = lat0 + np.rad2deg(result['N'] / R)
            lons = lon0 + np.rad2deg(result['E'] / (R * np.cos(lat0Rad)))
            
            # Create LineString
            points = [Point(xy) for xy in zip(lons, lats)]
            gdf = gpd.GeoDataFrame({'geometry': points}, crs="EPSG:4326")
            gdf = gdf.to_crs(epsg=3857) # Web Mercator
            
            gdf.plot(ax=ax_map, color=colors[idx], markersize=1, label=f"{result['config']['id']} - {result['config']['vehicle']}")
            
            # Plot start/end
            if not gdf.empty:
                ax_map.plot(gdf.geometry.iloc[0].x, gdf.geometry.iloc[0].y, 'o', color=colors[idx])
                ax_map.plot(gdf.geometry.iloc[-1].x, gdf.geometry.iloc[-1].y, '^', color=colors[idx])
                
                # Plot Heading Arrows on Map
                if len(result['time']) > 1:
                    h = result['time'][1] - result['time'][0]
                    steps_per_sec = int(1.0 / h)
                    if steps_per_sec > 0:
                        idx_sample = slice(0, len(result['time']), steps_per_sec)
                        
                        # Get sampled NED positions
                        N_samp = result['N'][idx_sample]
                        E_samp = result['E'][idx_sample]
                        psi_samp = result['psi'][idx_sample]
                        psi_d_samp = result['psi_d'][idx_sample]
                        
                        # Convert to Lat/Lon
                        lats_samp = lat0 + np.rad2deg(N_samp / R)
                        lons_samp = lon0 + np.rad2deg(E_samp / (R * np.cos(lat0Rad)))
                        
                        # Convert to Web Mercator
                        points_samp = [Point(xy) for xy in zip(lons_samp, lats_samp)]
                        gdf_samp = gpd.GeoDataFrame({'geometry': points_samp}, crs="EPSG:4326")
                        gdf_samp = gdf_samp.to_crs(epsg=3857)
                        
                        X_map = gdf_samp.geometry.x
                        Y_map = gdf_samp.geometry.y
                        
                        # Directions (Web Mercator is North-Up, so same logic applies)
                        U_act = np.sin(psi_samp)
                        V_act = np.cos(psi_samp)
                        U_ref = np.sin(psi_d_samp)
                        V_ref = np.cos(psi_d_samp)
                        
                        # Plot Quivers
                        if self.show_arrows_var.get():
                            ax_map.quiver(X_map, Y_map, U_act, V_act, color=colors[idx], scale=30, width=0.003, headwidth=3, alpha=0.8)
                            ax_map.quiver(X_map, Y_map, U_ref, V_ref, color='k', scale=30, width=0.002, headwidth=3, alpha=0.5)

        # Plot Waypoints
        wps = result['waypoints']
        wp_lats = [wp['lat'] for wp in wps]
        wp_lons = [wp['lon'] for wp in wps]
        wp_points = [Point(xy) for xy in zip(wp_lons, wp_lats)]
        gdf_wp = gpd.GeoDataFrame({'geometry': wp_points}, crs="EPSG:4326")
        gdf_wp = gdf_wp.to_crs(epsg=3857)
        
        # Plot Route Line (Red Dashed)
        if len(wp_points) > 1:
            line = LineString(wp_points)
            gdf_line = gpd.GeoDataFrame({'geometry': [line]}, crs="EPSG:4326")
            gdf_line = gdf_line.to_crs(epsg=3857)
            gdf_line.plot(ax=ax_map, color='red', linestyle='--', linewidth=1.5, alpha=0.7)
            
        gdf_wp.plot(ax=ax_map, color='red', marker='x', markersize=100, label='Waypoints')
        
        # Draw acceptance radius circles on map
        radii = [wp['radius'] for wp in wps]
        gdf_circles = gdf_wp.copy()
        gdf_circles['geometry'] = gdf_circles.geometry.buffer(radii)
        gdf_circles.plot(ax=ax_map, color='none', edgecolor='red', linestyle='--', linewidth=1, alpha=0.5)
        
        # Add basemap
        try:
            ctx.add_basemap(ax_map, source=ctx.providers.Esri.WorldImagery)
        except Exception as e:
            print(f"Could not add basemap: {e}")
            
        ax_map.legend()
        ax_map.set_axis_off()
        
        # Figure 3: Heading Error and Motor Speeds
        fig3, axes3 = plt.subplots(2, 1, figsize=(14, 8))
        fig3.suptitle('Heading Error and Motor Speeds', fontsize=16, fontweight='bold')
        
        # Plot 1: Heading Error
        ax_psi_err = axes3[0]
        for idx, result in enumerate(self.path_results):
            config = result['config']
            color = colors[idx]
            label = f"{config['id']}: ωn={config.get('wn_pid', 1.5)}, ζ={config.get('zeta_pid', 1.0)}, ωn_d={config.get('wn_ref', 0.5)}"
            if 'psi_error' in result:
                ax_psi_err.plot(result['time'], result['psi_error'], '-', color=color, linewidth=1.5, label=label)
        ax_psi_err.set_ylabel('Heading Error [deg]')
        ax_psi_err.set_xlabel('Time [s]')
        ax_psi_err.set_title('Heading Error (ψ - ψ_d)')
        ax_psi_err.legend()
        ax_psi_err.grid(True)
        ax_psi_err.axhline(y=0, color='k', linestyle='--', linewidth=0.5)
        
        # Plot 2: Motor Speeds
        ax_motors = axes3[1]
        for idx, result in enumerate(self.path_results):
            config = result['config']
            color = colors[idx]
            if 'n1' in result and 'n2' in result:
                ax_motors.plot(result['time'], result['n1'], '-', color=color, linewidth=1.5, label=f"{config['id']} n1 (left)")
                ax_motors.plot(result['time'], result['n2'], '--', color=color, linewidth=1.5, label=f"{config['id']} n2 (right)")
        ax_motors.set_ylabel('Motor Speed [RPM]')
        ax_motors.set_xlabel('Time [s]')
        ax_motors.set_title('Motor Speeds (n1, n2)')
        ax_motors.legend()
        ax_motors.grid(True)
        
        plt.tight_layout()
        
        plt.show()


        
    def add_simulation(self):
        """Add a new simulation configuration to the list"""
        try:
            config = {
                'id': self.sim_counter,
                'vehicle': self.vehicle_var.get(),
                'yaw': float(self.yaw_var.get()),
                'current_speed': float(self.current_speed_var.get()),
                'current_dir': float(self.current_dir_var.get()),
                'surge_force': float(self.surge_force_var.get()),
                'payload': float(self.payload_var.get()),
                'status': 'Pending'
            }
            
            self.simulations.append(config)
            self.sim_counter += 1
            
            # Add to treeview
            self.tree.insert("", tk.END, values=(
                config['id'],
                config['vehicle'],
                config['yaw'],
                config['current_speed'],
                config['current_dir'],
                config['surge_force'],
                config['payload'],
                config['status']
            ))
            
        except ValueError as e:
            messagebox.showerror("Input Error", f"Invalid input values: {e}")
    
    def add_otter_default(self):
        """Add Otter with default parameters"""
        self.vehicle_var.set("otter")
        self.yaw_var.set("90")
        self.current_speed_var.set("0.0")
        self.current_dir_var.set("0")
        self.surge_force_var.set("120")
        self.payload_var.set("25")
        self.add_simulation()
        
    def add_salpa1_default(self):
        """Add Salpa1 with default parameters"""
        self.vehicle_var.set("salpa1")
        self.yaw_var.set("90")
        self.current_speed_var.set("0.0")
        self.current_dir_var.set("0")
        self.surge_force_var.set("150")
        self.payload_var.set("25")
        self.add_simulation()
    
    def remove_selected(self):
        """Remove selected simulation from the list"""
        selected = self.tree.selection()
        if selected:
            for item in selected:
                values = self.tree.item(item)['values']
                sim_id = values[0]
                self.simulations = [s for s in self.simulations if s['id'] != sim_id]
                self.tree.delete(item)
    
    def clear_all(self):
        """Clear all simulations"""
        self.simulations = []
        self.results = []
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.sim_counter = 0
    
    def run_single_simulation(self, config, T_final, h):
        """Run a single simulation and return results"""
        
        # Create vehicle based on type
        if config['vehicle'] == 'otter':
            vehicle = otter(
                controlSystem='headingAutopilot',
                r=config['yaw'],
                V_current=config['current_speed'],
                beta_current=config['current_dir'],
                tau_X=config['surge_force'],
                payload_mass=config.get('payload', 25.0)
            )
        elif config['vehicle'] == 'otter_updated':
            vehicle = otter_updated(
                controlSystem='headingAutopilot',
                r=config['yaw'],
                V_current=config['current_speed'],
                beta_current=config['current_dir'],
                tau_X=config['surge_force'],
                payload_mass=config.get('payload', 25.0)
            )
        else:  # salpa1
            vehicle = salpa1(
                controlSystem='headingAutopilot',
                r=config['yaw'],
                V_current=config['current_speed'],
                beta_current=config['current_dir'],
                tau_X=config['surge_force'],
                payload_mass=config.get('payload', 25.0)
            )
        
        # Initialize state
        eta = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0], float)
        nu = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0], float)
        u_actual = np.array([0.0, 0.0], float)
        
        # Storage
        n_steps = int(T_final / h)
        time_vec = np.linspace(0, T_final, n_steps)
        
        N_history = np.zeros(n_steps)
        E_history = np.zeros(n_steps)
        psi_history = np.zeros(n_steps)
        psi_d_history = np.zeros(n_steps)
        u_history = np.zeros(n_steps)
        v_history = np.zeros(n_steps)
        r_history = np.zeros(n_steps)
        
        # Run simulation
        for i in range(n_steps):
            N_history[i] = eta[0]
            E_history[i] = eta[1]
            psi_history[i] = eta[5]
            psi_d_history[i] = vehicle.psi_d
            u_history[i] = nu[0]
            v_history[i] = nu[1]
            r_history[i] = nu[5]
            
            u_control = vehicle.headingAutopilot(eta, nu, h)
            nu, u_actual = vehicle.dynamics(eta, nu, u_actual, u_control, h)
            
            R = Rzyx(eta[3], eta[4], eta[5])
            eta[0:3] = eta[0:3] + h * np.matmul(R, nu[0:3])
            eta[3] = eta[3] + h * nu[3]
            eta[4] = eta[4] + h * nu[4]
            eta[5] = eta[5] + h * nu[5]
        
        return {
            'config': config,
            'time': time_vec,
            'N': N_history,
            'E': E_history,
            'psi': psi_history,
            'psi_d': psi_d_history,
            'u': u_history,
            'v': v_history,
            'r': r_history,
            'speed': np.sqrt(u_history**2 + v_history**2)
        }
    
    def run_simulations(self):
        """Run all simulations"""
        if not self.simulations:
            messagebox.showwarning("No Simulations", "Please add at least one simulation configuration.")
            return
        
        try:
            T_final = float(self.total_time_var.get())
            h = float(self.time_step_var.get())
        except ValueError:
            messagebox.showerror("Input Error", "Invalid time parameters.")
            return
        
        self.results = []
        self.progress_bar['value'] = 0
        self.run_btn.config(state='disabled')
        
        total_sims = len(self.simulations)
        
        for i, config in enumerate(self.simulations):
            self.progress_var.set(f"Running simulation {i+1}/{total_sims}: {config['id']} - {config['vehicle']}")
            self.root.update()
            
            try:
                result = self.run_single_simulation(config, T_final, h)
                self.results.append(result)
                config['status'] = 'Complete'
            except Exception as e:
                config['status'] = f'Error: {str(e)[:20]}'
                print(f"Error in simulation {i}: {e}")
            
            # Update table status
            self.update_table_status(config)
            
            self.progress_bar['value'] = (i + 1) / total_sims * 100
            self.root.update()
        
        self.progress_var.set(f"Completed {len(self.results)}/{total_sims} simulations")
        self.run_btn.config(state='normal')
        
        # Save settings after simulation completes
        self.save_settings()
        
        if self.results:
            self.show_plots()
    
    def update_table_status(self, config):
        """Update the status column in the table"""
        for item in self.tree.get_children():
            values = list(self.tree.item(item)['values'])
            if values[0] == config['id']:
                values[7] = config['status']
                self.tree.item(item, values=values)
                break
    
    def show_plots(self):
        """Display comparison plots"""
        if not self.results:
            messagebox.showwarning("No Results", "Please run simulations first.")
            return
        
        # Create figure with subplots
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        fig.suptitle('USV Comparison - Multiple Simulations', fontsize=16, fontweight='bold')
        
        # Color map for different simulations
        colors = plt.cm.tab10(np.linspace(0, 1, len(self.results)))
        
        for idx, result in enumerate(self.results):
            config = result['config']
            # Calculate mass
            payload = config.get('payload', 25.0)
            base_mass = 165.0 if 'salpa1' in config['vehicle'] else 55.0
            total_mass = base_mass + payload
            
            label = f"{config['vehicle']} ({total_mass:.0f}kg, ψ={config['yaw']}°, V_c={config['current_speed']}m/s, τ={config['surge_force']}N)"
            color = colors[idx]
            
            # Plot 1: XY Track
            ax1 = axes[0, 0]
            ax1.plot(result['E'], result['N'], '-', color=color, linewidth=1.5, label=label)
            ax1.plot(result['E'][0], result['N'][0], 'o', color=color, markersize=8)
            ax1.plot(result['E'][-1], result['N'][-1], '^', color=color, markersize=8)
        
        ax1.set_ylabel('North [m]', fontsize=12)
        ax1.set_title('XY Track Comparison', fontsize=14)
        ax1.legend(loc='best', fontsize=8)
        ax1.grid(True, alpha=0.3)
        ax1.axis('equal')
        
        # Plot 2: Heading vs Time
        ax2 = axes[0, 1]
        for idx, result in enumerate(self.results):
            config = result['config']
            # Calculate mass
            payload = config.get('payload', 25.0)
            base_mass = 165.0 if 'salpa1' in config['vehicle'] else 55.0
            total_mass = base_mass + payload
            
            label = f"{config['vehicle']} ({total_mass:.0f}kg)"
            color = colors[idx]
            # Plot actual heading (solid line)
            ax2.plot(result['time'], np.rad2deg(result['psi']), '-', color=color, linewidth=1.5, label=f"{label} - Actual")
            # Plot reference heading (dashed line)
            ax2.plot(result['time'], np.rad2deg(result['psi_d']), '--', color=color, linewidth=1.5, alpha=0.7, label=f"{label} - Reference")
        
        ax2.set_ylabel('Heading [deg]', fontsize=12)
        ax2.set_title('Heading Response Comparison (Solid=Actual, Dashed=Reference)', fontsize=14)
        ax2.legend(loc='best', fontsize=8)
        ax2.grid(True, alpha=0.3)
        
        # Plot 3: Heading Error vs Time
        ax3 = axes[1, 0]
        for idx, result in enumerate(self.results):
            config = result['config']
            # Calculate mass
            payload = config.get('payload', 25.0)
            base_mass = 165.0 if 'salpa1' in config['vehicle'] else 55.0
            total_mass = base_mass + payload
            
            label = f"{config['id']} - {config['vehicle']} ({total_mass:.0f}kg)"
            color = colors[idx]
            error = config['yaw'] - np.rad2deg(result['psi'])
            error = np.rad2deg(np.arctan2(np.sin(np.deg2rad(error)), np.cos(np.deg2rad(error))))
            ax3.plot(result['time'], error, '-', color=color, linewidth=1.5, label=label)
        
        ax3.axhline(y=0, color='k', linestyle='--', alpha=0.5)
        ax3.set_ylabel('Heading Error [deg]', fontsize=12)
        ax3.set_title('Heading Error Comparison', fontsize=14)
        ax3.legend(loc='best', fontsize=8)
        ax3.grid(True, alpha=0.3)
        
        # Plot 4: Speed vs Time
        ax4 = axes[1, 1]
        for idx, result in enumerate(self.results):
            config = result['config']
            # Calculate mass
            payload = config.get('payload', 25.0)
            base_mass = 165.0 if 'salpa1' in config['vehicle'] else 55.0
            total_mass = base_mass + payload
            
            label = f"{config['vehicle']} ({total_mass:.0f}kg, τ={config['surge_force']}N)"
            color = colors[idx]
            ax4.plot(result['time'], result['speed'], '-', color=color, linewidth=1.5, label=label)
        
        ax4.set_ylabel('Speed [m/s]', fontsize=12)
        ax4.set_title('Speed Comparison', fontsize=14)
        ax4.legend(loc='best', fontsize=8)
        ax4.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.show()
    
    def save_plots(self):
        """Save comparison plots to file"""
        if not self.results:
            messagebox.showwarning("No Results", "Please run simulations first.")
            return
        
        # Create figure with subplots
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        fig.suptitle('USV Comparison - Multiple Simulations', fontsize=16, fontweight='bold')
        
        colors = plt.cm.tab10(np.linspace(0, 1, len(self.results)))
        
        for idx, result in enumerate(self.results):
            config = result['config']
            # Calculate mass
            payload = config.get('payload', 25.0)
            base_mass = 165.0 if 'salpa1' in config['vehicle'] else 55.0
            total_mass = base_mass + payload
            
            label = f"{config['vehicle']} ({total_mass:.0f}kg, ψ={config['yaw']}°, V_c={config['current_speed']}m/s, τ={config['surge_force']}N)"
            color = colors[idx]
            
            # Plot 1: XY Track
            axes[0, 0].plot(result['E'], result['N'], '-', color=color, linewidth=1.5, label=label)
            axes[0, 0].plot(result['E'][0], result['N'][0], 'o', color=color, markersize=8)
            axes[0, 0].plot(result['E'][-1], result['N'][-1], '^', color=color, markersize=8)
            
            # Plot 2: Heading
            axes[0, 1].plot(result['time'], np.rad2deg(result['psi']), '-', color=color, linewidth=1.5, label=f"{config['vehicle']} ({total_mass:.0f}kg) - Actual")
            axes[0, 1].plot(result['time'], np.rad2deg(result['psi_d']), '--', color=color, linewidth=1.5, alpha=0.7, label=f"{config['vehicle']} ({total_mass:.0f}kg) - Reference")
            
            # Plot 3: Heading Error
            error = config['yaw'] - np.rad2deg(result['psi'])
            error = np.rad2deg(np.arctan2(np.sin(np.deg2rad(error)), np.cos(np.deg2rad(error))))
            axes[1, 0].plot(result['time'], error, '-', color=color, linewidth=1.5, label=f"{config['vehicle']} ({total_mass:.0f}kg)")
            
            # Plot 4: Speed
            axes[1, 1].plot(result['time'], result['speed'], '-', color=color, linewidth=1.5, label=f"{config['vehicle']} ({total_mass:.0f}kg)")
        
        # Labels and formatting
        axes[0, 0].set_xlabel('East [m]')
        axes[0, 0].set_ylabel('North [m]')
        axes[0, 0].set_title('XY Track Comparison')
        axes[0, 0].legend(loc='best', fontsize=8)
        axes[0, 0].grid(True, alpha=0.3)
        axes[0, 0].axis('equal')
        
        axes[0, 1].set_xlabel('Time [s]')
        axes[0, 1].set_ylabel('Heading [deg]')
        axes[0, 1].set_title('Heading Response')
        axes[0, 1].legend(loc='best', fontsize=8)
        axes[0, 1].grid(True, alpha=0.3)
        
        axes[1, 0].axhline(y=0, color='k', linestyle='--', alpha=0.5)
        axes[1, 0].set_xlabel('Time [s]')
        axes[1, 0].set_ylabel('Heading Error [deg]')
        axes[1, 0].set_title('Heading Error')
        axes[1, 0].legend(loc='best', fontsize=8)
        axes[1, 0].grid(True, alpha=0.3)
        
        axes[1, 1].set_xlabel('Time [s]')
        axes[1, 1].set_ylabel('Speed [m/s]')
        axes[1, 1].set_title('Speed')
        axes[1, 1].legend(loc='best', fontsize=8)
        axes[1, 1].grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        # Save to file
        filename = 'Plots/usv_comparison_results.png'
        plt.savefig(filename, dpi=150, bbox_inches='tight')
        plt.close()
        
        messagebox.showinfo("Saved", f"Plots saved to: {filename}")

    def load_settings(self):
        """Load settings from JSON file"""
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, 'r') as f:
                    settings = json.load(f)
                
                # Heading Tab settings
                if 'heading' in settings:
                    h = settings['heading']
                    self.total_time_var.set(h.get('total_time', '200'))
                    self.time_step_var.set(h.get('time_step', '0.02'))
                    self.vehicle_var.set(h.get('vehicle', 'salpa1'))
                    self.yaw_var.set(h.get('yaw', '90'))
                    self.current_speed_var.set(h.get('current_speed', '0.0'))
                    self.current_dir_var.set(h.get('current_dir', '0'))
                    self.surge_force_var.set(h.get('surge_force', '150'))
                    self.payload_var.set(h.get('payload', '25'))
                
                # Path Following Tab settings
                if 'path' in settings:
                    p = settings['path']
                    self.path_total_time_var.set(p.get('total_time', '400'))
                    self.path_time_step_var.set(p.get('time_step', '0.02'))
                    self.path_vehicle_var.set(p.get('vehicle', 'salpa1'))
                    self.delta_var.set(p.get('delta', '5.0'))
                    self.gamma_var.set(p.get('gamma', '0.0'))
                    self.path_current_speed_var.set(p.get('current_speed', '0.0'))
                    self.path_current_dir_var.set(p.get('current_dir', '0'))
                    self.path_surge_force_var.set(p.get('surge_force', '150'))
                    self.path_payload_var.set(p.get('payload', '25'))
                    self.wn_pid_var.set(p.get('wn_pid', '1.5'))
                    self.zeta_pid_var.set(p.get('zeta_pid', '1.0'))
                    self.wn_ref_var.set(p.get('wn_ref', '0.5'))
                    self.zeta_ref_var.set(p.get('zeta_ref', '1.0'))
                    
                    # Load last waypoints file if it exists
                    if 'waypoints_file' in p and p['waypoints_file']:
                        if os.path.exists(p['waypoints_file']):
                            self.waypoints_file = p['waypoints_file']
                            self.waypoints_file_var.set(os.path.basename(p['waypoints_file']))
                            try:
                                self.waypoints_data = pd.read_csv(p['waypoints_file'])
                            except:
                                pass
                
                # Load heading simulations
                if 'heading_simulations' in settings:
                    self.simulations = settings['heading_simulations']
                    self.sim_counter = settings.get('heading_sim_counter', len(self.simulations))
                    # Populate treeview
                    for config in self.simulations:
                        self.tree.insert("", tk.END, values=(
                            config['id'],
                            config['vehicle'],
                            config['yaw'],
                            config['current_speed'],
                            config['current_dir'],
                            config['surge_force'],
                            config['payload'],
                            config.get('status', 'Pending')
                        ))
                
                # Load path following simulations
                if 'path_simulations' in settings:
                    self.path_simulations = settings['path_simulations']
                    self.path_sim_counter = settings.get('path_sim_counter', len(self.path_simulations))
                    # Populate treeview
                    for config in self.path_simulations:
                        self.path_tree.insert("", tk.END, values=(
                            config['id'],
                            config['vehicle'],
                            config['delta'],
                            config['gamma'],
                            config.get('wn_pid', 1.5),
                            config.get('zeta_pid', 1.0),
                            config.get('wn_ref', 0.5),
                            config.get('zeta_ref', 1.0),
                            config.get('status', 'Pending')
                        ))
                
                print(f"Settings loaded from {SETTINGS_FILE}")
        except Exception as e:
            print(f"Could not load settings: {e}")
    
    def save_settings(self):
        """Save current settings to JSON file"""
        try:
            settings = {
                'heading': {
                    'total_time': self.total_time_var.get(),
                    'time_step': self.time_step_var.get(),
                    'vehicle': self.vehicle_var.get(),
                    'yaw': self.yaw_var.get(),
                    'current_speed': self.current_speed_var.get(),
                    'current_dir': self.current_dir_var.get(),
                    'surge_force': self.surge_force_var.get(),
                    'payload': self.payload_var.get()
                },
                'path': {
                    'total_time': self.path_total_time_var.get(),
                    'time_step': self.path_time_step_var.get(),
                    'vehicle': self.path_vehicle_var.get(),
                    'delta': self.delta_var.get(),
                    'gamma': self.gamma_var.get(),
                    'current_speed': self.path_current_speed_var.get(),
                    'current_dir': self.path_current_dir_var.get(),
                    'surge_force': self.path_surge_force_var.get(),
                    'payload': self.path_payload_var.get(),
                    'wn_pid': self.wn_pid_var.get(),
                    'zeta_pid': self.zeta_pid_var.get(),
                    'wn_ref': self.wn_ref_var.get(),
                    'zeta_ref': self.zeta_ref_var.get(),
                    'waypoints_file': self.waypoints_file
                },
                # Save defined simulations (heading tab)
                'heading_simulations': self.simulations,
                'heading_sim_counter': self.sim_counter,
                # Save defined simulations (path following tab)
                'path_simulations': self.path_simulations,
                'path_sim_counter': self.path_sim_counter
            }
            
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(settings, f, indent=4)
            
            print(f"Settings saved to {SETTINGS_FILE}")
        except Exception as e:
            print(f"Could not save settings: {e}")
    
    def on_closing(self):
        """Handle window close event"""
        self.save_settings()
        self.root.destroy()

    def generate_route(self):
        """
        Open an interactive satellite map for waypoint selection.
        Users can click on the map to add waypoints, then save them to CSV.
        Coordinates are converted from WGS84 to local ENU frame.
        """
        # Create a temporary HTML file with the interactive map
        html_content = self._create_route_map_html()
        
        # Create temp directory for files
        self.route_temp_dir = tempfile.mkdtemp()
        self.route_html_path = os.path.join(self.route_temp_dir, 'route_planner.html')
        self.route_waypoints_path = os.path.join(self.route_temp_dir, 'waypoints.json')
        
        # Initialize empty waypoints file
        with open(self.route_waypoints_path, 'w') as f:
            json.dump({'waypoints': [], 'origin': None}, f)
        
        # Write the HTML file
        with open(self.route_html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        # Start local server to receive waypoints
        self._start_waypoint_server()
        
        # Open the map in the default browser
        webbrowser.open(f'http://localhost:{self.server_port}/route_planner.html')
        
        # Show instructions dialog
        self._show_route_instructions()
    
    def _create_route_map_html(self):
        """Create HTML content for the interactive route planning map"""
        html = '''<!DOCTYPE html>
<html>
<head>
    <title>USV Route Planner - Salpa 1</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        html, body { margin: 0; padding: 0; font-family: Arial, sans-serif; height: 100%; }
        #map { height: calc(100vh - 120px); width: 100%; position: relative; }
        #controls {
            background: #2c3e50;
            color: white;
            padding: 10px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        #controls h2 { margin: 0; font-size: 18px; }
        #waypoint-info {
            background: #34495e;
            padding: 10px 20px;
            color: white;
            font-size: 14px;
        }
        button {
            padding: 10px 20px;
            margin-left: 10px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-weight: bold;
            font-size: 14px;
        }
        .btn-undo { background: #e74c3c; color: white; }
        .btn-clear { background: #95a5a6; color: white; }
        .btn-save { background: #27ae60; color: white; }
        .btn-save:disabled { background: #95a5a6; cursor: not-allowed; }
        button:hover:not(:disabled) { opacity: 0.8; }
        #coords-display {
            position: absolute;
            bottom: 30px;
            left: 10px;
            background: rgba(0,0,0,0.7);
            color: white;
            padding: 8px 12px;
            border-radius: 5px;
            font-size: 12px;
            z-index: 1000;
        }
        #waypoint-list {
            position: absolute;
            top: 350px;
            left: 10px;
            background: rgba(255,255,255,0.95);
            padding: 10px;
            border-radius: 5px;
            max-height: 300px;
            overflow-y: auto;
            z-index: 1000;
            min-width: 200px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
        }
        #waypoint-list h4 { margin: 0 0 10px 0; color: #2c3e50; }
        .wp-item {
            font-size: 12px;
            padding: 5px;
            border-bottom: 1px solid #eee;
            color: #333;
        }
        .wp-item:last-child { border-bottom: none; }
        #instructions {
            position: absolute;
            top: 130px;
            left: 10px;
            background: rgba(255,255,255,0.95);
            padding: 10px;
            border-radius: 5px;
            z-index: 1000;
            max-width: 250px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
        }
        #instructions h4 { margin: 0 0 10px 0; color: #2c3e50; }
        #instructions ul { margin: 0; padding-left: 20px; font-size: 12px; color: #333; }
        #instructions li { margin-bottom: 5px; }
    </style>
</head>
<body>
    <div id="controls">
        <h2>🚤 USV Route Planner - Salpa 1</h2>
        <div>
            <button class="btn-undo" onclick="undoWaypoint()">↩ Undo</button>
            <button class="btn-clear" onclick="clearWaypoints()">🗑 Clear All</button>
            <button class="btn-save" id="saveBtn" onclick="saveWaypoints()" disabled>💾 Save Route</button>
        </div>
    </div>
    <div id="waypoint-info">
        <span id="wp-count">Waypoints: 0</span> | 
        <span id="total-dist">Total Distance: 0 m</span> |
        <span>First waypoint = Origin (0, 0)</span>
    </div>
    <div id="map"></div>
    <div id="coords-display">Lat: --, Lng: --</div>
    <div id="instructions">
        <h4>📋 Instructions</h4>
        <ul>
            <li><b>Click</b> on map to add waypoints</li>
            <li><b>First point</b> becomes the origin (0,0)</li>
            <li><b>Undo</b> removes last waypoint</li>
            <li><b>Save Route</b> exports to CSV</li>
            <li>Use <b>scroll wheel</b> to zoom</li>
            <li>Use <b>satellite/map</b> toggle at top-right</li>
        </ul>
    </div>
    <div id="waypoint-list">
        <h4>📍 Waypoints</h4>
        <div id="wp-items">Click on map to add...</div>
    </div>

    <script>
        // Initialize map centered on Spain (you can change this default location)
        var map = L.map('map', {
            center: [39.47, -0.38],
            zoom: 15
        });
        
        // Add layer control with satellite and street map options
        var osmLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap contributors',
            maxZoom: 19
        });
        
        var satelliteLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
            attribution: 'Tiles © Esri',
            maxZoom: 19
        });
        
        // Use Satellite as default
        satelliteLayer.addTo(map);
        
        L.control.layers({
            "Satellite": satelliteLayer,
            "Street Map": osmLayer
        }).addTo(map);
        
        // Debug: Log tile loading errors
        osmLayer.on('tileerror', function(e) {
            console.error('Tile load error:', e);
        });
        
        // Force map to recalculate size after load
        window.addEventListener('load', function() {
            setTimeout(function() {
                map.invalidateSize();
            }, 100);
        });
        
        // Waypoint storage
        var waypoints = [];
        var markers = [];
        var polyline = null;
        var origin = null;  // First waypoint becomes origin
        
        // Earth radius for distance calculations (WGS84)
        var R = 6378137;  // meters
        
        // Convert lat/lon to local ENU coordinates
        function wgs84ToENU(lat, lon, lat0, lon0) {
            var dLat = (lat - lat0) * Math.PI / 180;
            var dLon = (lon - lon0) * Math.PI / 180;
            var lat0Rad = lat0 * Math.PI / 180;
            
            // North = delta lat * R
            var north = dLat * R;
            // East = delta lon * R * cos(lat0)
            var east = dLon * R * Math.cos(lat0Rad);
            
            return {east: east, north: north};
        }
        
        // Calculate distance between two points
        function haversineDistance(lat1, lon1, lat2, lon2) {
            var dLat = (lat2 - lat1) * Math.PI / 180;
            var dLon = (lon2 - lon1) * Math.PI / 180;
            var lat1Rad = lat1 * Math.PI / 180;
            var lat2Rad = lat2 * Math.PI / 180;
            
            var a = Math.sin(dLat/2) * Math.sin(dLat/2) +
                    Math.cos(lat1Rad) * Math.cos(lat2Rad) *
                    Math.sin(dLon/2) * Math.sin(dLon/2);
            var c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
            return R * c;
        }
        
        // Update waypoint data from inputs
        function updateWaypointData(index, field, value) {
            waypoints[index][field] = parseFloat(value);
        }

        // Update display
        function updateDisplay() {
            document.getElementById('wp-count').textContent = 'Waypoints: ' + waypoints.length;
            document.getElementById('saveBtn').disabled = waypoints.length < 2;
            
            // Calculate total distance
            var totalDist = 0;
            for (var i = 1; i < waypoints.length; i++) {
                totalDist += haversineDistance(
                    waypoints[i-1].lat, waypoints[i-1].lng,
                    waypoints[i].lat, waypoints[i].lng
                );
            }
            document.getElementById('total-dist').textContent = 'Total Distance: ' + totalDist.toFixed(1) + ' m';
            
            // Update waypoint list
            var wpItems = document.getElementById('wp-items');
            if (waypoints.length === 0) {
                wpItems.innerHTML = 'Click on map to add...';
            } else {
                var html = '';
                for (var i = 0; i < waypoints.length; i++) {
                    var wp = waypoints[i];
                    html += '<div class="wp-item">';
                    html += '<b>WP' + (i+1) + '</b><br>';
                    html += 'Rad: <input type="number" value="' + wp.radius + '" style="width:50px" onchange="updateWaypointData(' + i + ', &quot;radius&quot;, this.value)"> m ';
                    html += 'Spd: <input type="number" value="' + wp.speed + '" style="width:50px" onchange="updateWaypointData(' + i + ', &quot;speed&quot;, this.value)"> m/s';
                    html += '</div>';
                }
                wpItems.innerHTML = html;
            }
            
            // Update polyline
            if (polyline) {
                map.removeLayer(polyline);
            }
            if (waypoints.length >= 2) {
                var latlngs = waypoints.map(function(wp) { return [wp.lat, wp.lng]; });
                polyline = L.polyline(latlngs, {color: '#e74c3c', weight: 3}).addTo(map);
            }
        }
        
        // Add waypoint on click
        map.on('click', function(e) {
            var lat = e.latlng.lat;
            var lng = e.latlng.lng;
            
            // First waypoint becomes origin
            if (waypoints.length === 0) {
                origin = {lat: lat, lng: lng};
            }
            
            // Add waypoint
            waypoints.push({
                lat: lat, 
                lng: lng,
                radius: 5.0,
                speed: 1.0
            });
            
            // Add marker with number
            var marker = L.circleMarker([lat, lng], {
                radius: 10,
                fillColor: waypoints.length === 1 ? '#27ae60' : '#3498db',
                color: '#fff',
                weight: 2,
                fillOpacity: 0.9
            }).addTo(map);
            
            marker.bindTooltip('WP' + waypoints.length, {
                permanent: true,
                direction: 'top',
                className: 'wp-label'
            });
            
            markers.push(marker);
            updateDisplay();
        });
        
        // Update coordinates display on mouse move
        map.on('mousemove', function(e) {
            var coordsDiv = document.getElementById('coords-display');
            var lat = e.latlng.lat.toFixed(6);
            var lng = e.latlng.lng.toFixed(6);
            var enuStr = '';
            if (origin) {
                var enu = wgs84ToENU(e.latlng.lat, e.latlng.lng, origin.lat, origin.lng);
                enuStr = ' | Local: E=' + enu.east.toFixed(1) + 'm, N=' + enu.north.toFixed(1) + 'm';
            }
            coordsDiv.textContent = 'Lat: ' + lat + ', Lng: ' + lng + enuStr;
        });
        
        // Undo last waypoint
        function undoWaypoint() {
            if (waypoints.length > 0) {
                waypoints.pop();
                var marker = markers.pop();
                map.removeLayer(marker);
                if (waypoints.length === 0) {
                    origin = null;
                }
                updateDisplay();
            }
        }
        
        // Clear all waypoints
        function clearWaypoints() {
            waypoints = [];
            origin = null;
            markers.forEach(function(m) { map.removeLayer(m); });
            markers = [];
            if (polyline) {
                map.removeLayer(polyline);
                polyline = null;
            }
            updateDisplay();
        }
        
        // Save waypoints to server
        function saveWaypoints() {
            if (waypoints.length < 2) {
                alert('Please add at least 2 waypoints');
                return;
            }
            
            var data = {
                origin: origin,
                waypoints: waypoints.map(function(wp, i) {
                    return {
                        index: i + 1,
                        lat: wp.lat,
                        lng: wp.lng,
                        radius: wp.radius,
                        speed: wp.speed
                    };
                })
            };
            
            // Send to local server
            fetch('/save_waypoints', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(data)
            })
            .then(response => response.json())
            .then(result => {
                if (result.success) {
                    alert('Route saved successfully!\\n\\nFile: ' + result.filename + '\\nWaypoints: ' + waypoints.length);
                } else {
                    alert('Error saving route: ' + result.error);
                }
            })
            .catch(error => {
                alert('Error: ' + error);
            });
        }
        
        // Try to get user's location
        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(function(position) {
                map.setView([position.coords.latitude, position.coords.longitude], 17);
            }, function(error) {
                console.log('Geolocation not available, using default location');
            });
        }
    </script>
</body>
</html>'''
        return html
    
    def _start_waypoint_server(self):
        """Start a local HTTP server to serve the map and receive waypoints"""
        parent = self
        temp_dir = self.route_temp_dir
        
        class RouteHandler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=temp_dir, **kwargs)
            
            def end_headers(self):
                # Add CORS headers for all responses
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
                super().end_headers()
            
            def do_GET(self):
                # Serve HTML with correct content type
                if self.path.endswith('.html'):
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html; charset=utf-8')
                    self.end_headers()
                    with open(os.path.join(temp_dir, self.path.lstrip('/')), 'rb') as f:
                        self.wfile.write(f.read())
                else:
                    super().do_GET()
            
            def do_POST(self):
                if self.path == '/save_waypoints':
                    content_length = int(self.headers['Content-Length'])
                    post_data = self.rfile.read(content_length)
                    
                    try:
                        data = json.loads(post_data.decode('utf-8'))
                        
                        # Generate filename with timestamp
                        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
                        filename = f'route_{timestamp}.csv'
                        
                        # Ask user where to save (we'll save in Data folder by default)
                        save_path = os.path.join(
                            os.path.dirname(os.path.abspath(__file__)),
                            'Data', filename
                        )
                        
                        # Make sure Data folder exists
                        os.makedirs(os.path.dirname(save_path), exist_ok=True)
                        
                        # Write CSV
                        with open(save_path, 'w') as f:
                            f.write('waypoint,latitude,longitude,radius,speed\n')
                            for wp in data['waypoints']:
                                f.write(f"{wp['index']},{wp['lat']:.8f},{wp['lng']:.8f},{wp['radius']},{wp['speed']}\n")
                        
                        # Send success response
                        response = {'success': True, 'filename': save_path}
                        self.send_response(200)
                        self.send_header('Content-type', 'application/json')
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(json.dumps(response).encode())
                        
                    except Exception as e:
                        response = {'success': False, 'error': str(e)}
                        self.send_response(500)
                        self.send_header('Content-type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps(response).encode())
                else:
                    self.send_error(404)
            
            def log_message(self, format, *args):
                pass  # Suppress server log messages
        
        # Find an available port
        for port in range(8765, 8800):
            try:
                socketserver.TCPServer.allow_reuse_address = True
                self.server = socketserver.TCPServer(("", port), RouteHandler)
                self.server_port = port
                break
            except OSError:
                continue
        
        # Run server in background thread
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
    
    def _show_route_instructions(self):
        """Show a dialog with route planning instructions"""
        msg = """Route Planner opened in your browser!

Instructions:
1. Click on the satellite map to add waypoints
2. First waypoint becomes the origin (0, 0)
3. Use 'Undo' to remove the last waypoint
4. Use 'Clear All' to start over
5. Click 'Save Route' when finished

The route will be saved as a CSV file in the Data folder
with local ENU coordinates (East, North) relative to the
first waypoint.

You can toggle between satellite and street map views
using the layer control in the top-right corner."""
        
        messagebox.showinfo("Route Planner", msg)


def main():
    root = tk.Tk()
    
    # Style configuration
    style = ttk.Style()
    style.theme_use('clam')
    
    app = USVComparisonGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
