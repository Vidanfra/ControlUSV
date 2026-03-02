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

        info = {
            "device_node": node,
            "id_vendor": props.get("ID_VENDOR_ID"),
            "id_product": props.get("ID_MODEL_ID"),
            "id_vendor_str": props.get("ID_VENDOR"),
            "id_model_str": props.get("ID_MODEL"),
            "id_serial_short": props.get("ID_SERIAL_SHORT") or props.get("ID_SERIAL") or serial_str,
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

    match_parts = []
    if vid:
        match_parts.append(f'ATTRS{{idVendor}}==\"{vid}\"')
    if pid:
        match_parts.append(f'ATTRS{{idProduct}}==\"{pid}\"')

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


def write_rules_file(assignments, outpath: Path):
    header = textwrap.dedent(f"""\
        # udev rules generated by usb_identify_and_udev.py
        # user: {getpass.getuser()}
        # Generated file: {outpath}
        # DO NOT EDIT MANUALLY unless you know what you are doing.
        """)
    lines = [header.strip() + "\n"]
    for dev, name in assignments:
        rule = build_udev_rule(dev, name)
        lines.append(rule + "\n")
    outpath.write_text("".join(lines))
    print(f"Wrote {len(assignments)} rules to: {outpath}")


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
        local_out = Path.cwd() / RULES_FILENAME
        write_rules_file(assignments, local_out)
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
