#!/usr/bin/env python3
"""
GameVault NIC Auto-Setup helper.

Generic helper for detecting a newly plugged-in gigabit NIC on a Linux server.
It does not hardcode local IPs, passwords, or project paths.

Use carefully: bridge/firewall changes are host-specific and should be reviewed
before use on production servers.
"""
import json
import os
import re
import subprocess
import sys
import time


def run(cmd):
    print(f"  {cmd}")
    try:
        return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        print(f"  ERROR: {e.output.strip()}")
        return ""


def detect_nics():
    nics = []
    out = run("ip -o link show")
    for line in out.strip().split("\n"):
        parts = line.split(":")
        if len(parts) < 2:
            continue
        iface = parts[1].strip()
        if iface in ("lo", "docker0"):
            continue

        speed = "?"
        try:
            eth_out = subprocess.check_output(["ethtool", iface], text=True, stderr=subprocess.DEVNULL)
            sm = re.search(r"Speed: (\d+[Mm]b/s|Unknown)", eth_out)
            if sm:
                speed = sm.group(1)
        except Exception:
            pass

        ip = None
        try:
            ip_out = subprocess.check_output(["ip", "-o", "addr", "show", iface], text=True, stderr=subprocess.DEVNULL)
            m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", ip_out)
            if m:
                ip = m.group(1)
        except Exception:
            pass

        is_fast = False
        try:
            if speed != "?" and "Mb/s" in speed:
                is_fast = int(re.search(r"(\d+)", speed).group(1)) >= 1000
        except Exception:
            pass

        nics.append({"name": iface, "ip": ip, "speed": speed, "is_fast": is_fast})
    return nics


def find_new_nic(old_nics):
    old_names = {n["name"] for n in old_nics}
    current = detect_nics()
    for n in current:
        if n["name"] not in old_names:
            return n, current
    return None, current


def configure_new_nic(iface):
    run(f"ip link set {iface} up")
    run(f"dhclient {iface}")


def main():
    print("=== GameVault NIC Detection Helper ===\n")
    current = detect_nics()
    print("Current interfaces:")
    for n in current:
        fast = " gigabit" if n["is_fast"] else ""
        print(f"  {n['name']:12} {n['speed']:10} {n['ip'] or 'no IP'}{fast}")

    gigabit = [n for n in current if n["is_fast"]]
    if gigabit:
        print("\nGigabit-capable interface already detected:")
        print(json.dumps(gigabit, indent=2))
        return

    print("\nNo gigabit NIC detected yet.")
    print("Plug in a USB/PCIe gigabit adapter now, or press Ctrl+C to cancel.")

    try:
        while True:
            time.sleep(2)
            new_nic, _ = find_new_nic(current)
            if not new_nic:
                continue

            print(f"\nNew NIC detected: {new_nic['name']}")
            print(f"Speed: {new_nic['speed']}")
            configure_new_nic(new_nic["name"])
            time.sleep(1)

            updated = detect_nics()
            for n in updated:
                if n["name"] == new_nic["name"]:
                    print("\nUpdated interface:")
                    print(json.dumps(n, indent=2))
                    if n.get("ip"):
                        print(f"\nUse this IP for SMB/dashboard if desired: {n['ip']}")
                    break
            return
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(1)


if __name__ == "__main__":
    main()
