#!/usr/bin/env python3
"""
usb_identify.py

Scan serial USB devices, show udev metadata, interactively ask for a permanent name
and generate a udev rules file that creates a stable symlink under /dev.

Usage:
  sudo python3 usb_identify_and_udev.py     # writes rules to /etc/udev/rules.d/99-usb-serial.rules
  python3 usb_identify_and_udev.py         # writes rules to ./99-usb-serial.rules (then run printed sudo mv)

********************************************************************************
**** REMEMBER TO RUN THIS SCRIPT WITH SUDO IF YOU WANT TO INSTALL THE RULES ****
********************************************************************************
Run: sudo /home/usv/CONTROL/venv/bin/python /home/usv/CONTROL/config_tools/usb_identify.py
"""

import os
import sys
import textwrap
import getpass
from pathlib import Path
import subprocess
import json

try:
    import pyudev
except Exception as e:
    print("pyudev is required. Install with: pip install pyudev")
    raise SystemExit(1)


RULES_FILENAME = "99-usb-serial.rules"   # final destination is /etc/udev/rules.d/99-usb-serial.rules


def discover_serial_devices():
    """
    Return a list of dicts describing tty devices discovered via pyudev.
    Each dict contains device_node, vendor/product ids and strings, serial short,
    devpath and a small '_attrs' dict with available raw attributes (as decoded str).
    """
    ctx = pyudev.Context()
    devices = []
    for dev in ctx.list_devices(subsystem='tty'):
        node = dev.device_node  # e.g. /dev/ttyUSB0 or /dev/ttyACM0
        if not node:
            continue
        props = dev.properties  # dict-like

        # Safely fetch serial attribute (may be bytes) and decode if present
        raw_serial = None
        try:
            raw_serial = dev.attributes.get('serial')
            if raw_serial is not None:
                # Attributes are bytes on many systems — decode safely
                try:
                    serial_str = raw_serial.decode(errors='ignore')
                except AttributeError:
                    # dev.attributes.get may already return a str on some platforms
                    serial_str = str(raw_serial)
            else:
                serial_str = None
        except Exception:
            serial_str = None

        # Build a small _attrs mapping with the serial if present
        _attrs = {}
        if serial_str:
            _attrs['serial'] = serial_str

        # Determine the physical USB port (e.g. "1-1.4"). This is the only
        # reliable way to distinguish multiple identical adapters (same
        # VID/PID/serial), such as several CH340 (1a86:7523) devices.
        usb_port = None
        try:
            usb_parent = dev.find_parent('usb', 'usb_device')
            if usb_parent is not None:
                usb_port = usb_parent.sys_name  # e.g. "1-1.4"
        except Exception:
            usb_port = None

        info = {
            "device_node": node,
            "id_vendor": props.get("ID_VENDOR_ID"),
            "id_product": props.get("ID_MODEL_ID"),
            "id_vendor_str": props.get("ID_VENDOR"),
            "id_model_str": props.get("ID_MODEL"),
            "id_serial_short": props.get("ID_SERIAL_SHORT") or props.get("ID_SERIAL") or serial_str,
            "id_usb_port": usb_port,
            "devpath": props.get("DEVPATH") or getattr(dev, "device_path", None),
            "_attrs": _attrs,
            "udev_device": dev,
        }
        if info.get("id_vendor") or info.get("id_product") or info.get("id_serial_short"):
            # Only include devices with some identifiable attribute
            devices.append(info)

    return devices


def pretty_print_device(i, d):
    print(f"[{i}] {d['device_node']}")
    print(f"     Vendor:    {d['id_vendor']}  ({d['id_vendor_str']})")
    print(f"     Product:   {d['id_product']}  ({d['id_model_str']})")
    print(f"     Serial:    {d['id_serial_short']}")
    print(f"     USB port:  {d.get('id_usb_port')}")
    print(f"     Devpath:   {d['devpath']}")
    print()


def build_udev_rule(device_info, symlink_name):
    """
    Build a udev rule string for one device_info.
    We prefer to match idVendor and idProduct and include serial if present for extra safety.
    """
    vid = device_info.get("id_vendor")
    pid = device_info.get("id_product")
    serial = device_info.get("id_serial_short")
    usb_port = device_info.get("id_usb_port")

    match_parts = []
    if vid:
        match_parts.append(f'ATTRS{{idVendor}}==\"{vid}\"')
    if pid:
        match_parts.append(f'ATTRS{{idProduct}}==\"{pid}\"')
    # Bind to the physical USB port. Without this, multiple identical adapters
    # (same VID/PID, e.g. CH340 1a86:7523) cannot be told apart and would all
    # match the same rule. Requires each device to stay in its dedicated port.
    if usb_port:
        match_parts.append(f'KERNELS==\"{usb_port}\"')

    if not match_parts:
        raise ValueError("No usable attributes to match for device: " + str(device_info))

    # Infer a kernel glob from device_node (prefer specific kernels)
    devnode = device_info.get("device_node", "")
    kernel_glob = "tty*"
    if devnode.startswith("/dev/ttyUSB"):
        kernel_glob = "ttyUSB*"
    elif devnode.startswith("/dev/ttyACM"):
        kernel_glob = "ttyACM*"
    elif devnode.startswith("/dev/ttyAMA"):
        kernel_glob = "ttyAMA*"
    elif devnode.startswith("/dev/ttyS"):
        kernel_glob = "ttyS*"

    # Sanitize symlink name (no leading slash)
    symlink = symlink_name.lstrip("/")

    # Compose rule. Use SYMLINK to create /dev/<symlink>.
    # Set group to dialout and mode to 0660 (adjust if you prefer different perms).
    rule = (
        f'SUBSYSTEM=="tty", KERNEL=="{kernel_glob}", {", ".join(match_parts)}, '
        f'SYMLINK+="{symlink}", MODE="0660", GROUP="dialout"'
    )
    return rule


def interactive_assign(devices):
    """
    Interactively present detected devices and let user choose a symlink name or skip.
    Returns list of tuples: (device_info, symlink_name)
    """
    assignments = []
    print("Detected serial devices:\n")
    for i, d in enumerate(devices):
        pretty_print_device(i, d)

    print("For each device enter a friendly symlink name (e.g. gnss, pzem, power_sensor).")
    print("Press Enter to skip creating a symlink for that device.\n")

    for i, d in enumerate(devices):
        default_suggest = None
        # suggest a name from model if available
        if d.get("id_model_str"):
            default_suggest = d["id_model_str"].lower().replace(" ", "_").replace("/", "_")
        prompt = f"Name for {d['device_node']} [suggest: {default_suggest}] (blank=skip): "
        try:
            name = input(prompt).strip()
        except KeyboardInterrupt:
            print("\nAborted by user.")
            break
        if not name:
            continue
        # sanitize name: allow letters, numbers, dash, underscore
        name = "".join(ch for ch in name if (ch.isalnum() or ch in ("-", "_")))
        if not name:
            print("Empty or invalid name after sanitization, skipping.")
            continue
        symlink = name if name.startswith("/") else name  # we'll construct /dev/<symlink> later
        assignments.append((d, symlink))
    return assignments


def write_rules_file(assignments, outpath: Path, source_path: Path = None):
    """
    Write udev rules, preserving existing rules for devices not being updated.
    Reads existing rules from source_path if provided, otherwise from outpath.
    """
    existing_rules = []
    read_from = source_path if source_path is not None else outpath

    # Read existing rules if file exists
    if read_from.exists():
        try:
            content = read_from.read_text()
            existing_rules = [
                line for line in content.splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
        except Exception as e:
            print(f"Warning: could not read existing rules from {read_from}: {e}")

    # Identify what we're (re)assigning: physical USB ports and symlink names.
    # We key retention on the physical port (not VID/PID) so that adding a
    # second identical adapter (same VID/PID) no longer clobbers the existing
    # rule for the first one.
    new_ports = set()
    new_names = set()
    for dev, name in assignments:
        port = dev.get("id_usb_port")
        if port:
            new_ports.add(port)
        new_names.add(name.lstrip("/"))

    # Drop existing rules only if they target the same physical port or reuse a
    # symlink name we're about to write; keep everything else untouched.
    retained_rules = []
    for rule in existing_rules:
        to_skip = False
        for port in new_ports:
            if f'KERNELS==\"{port}\"' in rule:
                to_skip = True
                break
        if not to_skip:
            for name in new_names:
                if f'SYMLINK+=\"{name}\"' in rule:
                    to_skip = True
                    break
        if not to_skip:
            retained_rules.append(rule)
    
    # Build new rules
    new_rules = []
    for dev, name in assignments:
        rule = build_udev_rule(dev, name)
        new_rules.append(rule)
    
    # Combine and write
    header = textwrap.dedent(f"""\
        # udev rules generated by usb_identify_and_udev.py
        # user: {getpass.getuser()}
        # Generated file: {outpath}
        # DO NOT EDIT MANUALLY unless you know what you are doing.
        """)
    
    all_rules = retained_rules + new_rules
    lines = [header.strip() + "\n"]
    for rule in all_rules:
        lines.append(rule + "\n")
    
    outpath.write_text("".join(lines))
    print(f"Wrote {len(all_rules)} rules to: {outpath} ({len(retained_rules)} retained + {len(new_rules)} new)")


def reload_udev_rules():
    # Requires root
    try:
        subprocess.run(["udevadm", "control", "--reload-rules"], check=False)
        subprocess.run(["udevadm", "trigger"], check=False)
        print("Reloaded udev rules and triggered udev.")
    except Exception as e:
        print("Failed to reload udev rules:", e)

def check_udev_rules():
    """
    Return the contents of /etc/udev/rules.d/99-usb-serial.rules as a string.
    Also prints the rules to stdout.
    """
    rules_path = "/etc/udev/rules.d/99-usb-serial.rules"
    try:
        with open(rules_path, "r") as f:
            rules_content = f.read()
        print(f"Current udev rules in {rules_path}:")
        print(rules_content)
        return rules_content
    except Exception as e:
        print("Failed to read udev rules:", e)
        return None

def main():
    print("**** REMEMBER TO RUN THIS SCRIPT WITH SUDO IF YOU WANT TO INSTALL THE RULES ****\n")
    print("Scanning serial devices via udev...")
    devices = discover_serial_devices()
    if not devices:
        print("No serial devices found.")
        return

    assignments = interactive_assign(devices)
    if not assignments:
        print("No assignments chosen. Exiting.")
        return

    # choose destination
    dest = Path("/etc/udev/rules.d") / RULES_FILENAME
    if os.geteuid() != 0:
        # not root: write local file and instruct how to install
        # Read existing installed rules for merging so prior rules are preserved on mv
        local_out = Path.cwd() / RULES_FILENAME
        write_rules_file(assignments, local_out, source_path=dest)
        print("\nYou are not root. To install the rules run:")
        print(f"  sudo mv {local_out} {dest}")
        print("Then reload udev rules with:")
        print("  sudo udevadm control --reload-rules && sudo udevadm trigger")
    else:
        write_rules_file(assignments, dest)
        reload_udev_rules()
        rules_output = check_udev_rules()
        if rules_output:
            json_path = Path.cwd() / "usb_symlink_assignments.json"
            # Parse rules_output into a list of rule lines (skip header/comments)
            rule_lines = [
                line for line in rules_output.splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
            with open(json_path, "w") as f:
                json.dump({"rules": rule_lines}, f, indent=2)
            print(f"Saved rules output to {json_path}")

        print("Done. You should now see the symlinks under /dev (e.g., /dev/gnss).")

        example_symlink_name = assignments[0][1] if assignments else "your_symlink"
        print(f"Example: ls -l /dev/{example_symlink_name}")

if __name__ == "__main__":
    main()
