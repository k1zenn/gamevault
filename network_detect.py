#!/usr/bin/env python3
"""GameVault Network Detector — auto-configures new NICs."""
import json, subprocess, re, os, sys

def get_nics():
    nics = []
    try:
        out = subprocess.check_output(["ip", "-o", "link", "show"], text=True)
        for line in out.strip().split('\n'):
            parts = line.split(':')
            if len(parts) >= 2:
                iface = parts[1].strip()
                if iface in ('lo', 'docker0', 'veth*'):
                    continue
                # Get IP
                ip = None
                try:
                    ip_out = subprocess.check_output(
                        ["ip", "-o", "addr", "show", iface], text=True
                    )
                    m = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', ip_out)
                    if m:
                        ip = m.group(1)
                except:
                    pass
                # Get speed
                speed = "?"
                if ip:
                    try:
                        eth_out = subprocess.check_output(
                            ["ethtool", iface], text=True, stderr=subprocess.DEVNULL
                        )
                        sm = re.search(r'Speed: (\d+[Mm]b/s|Unknown)', eth_out)
                        if sm:
                            speed = sm.group(1)
                    except:
                        pass
                nics.append({
                    "name": iface,
                    "ip": ip,
                    "speed": speed,
                    "is_fast": speed != "?" and "Mb/s" in speed and int(re.search(r'(\d+)', speed).group(1)) >= 1000
                })
    except:
        pass
    return nics

def get_active_nic():
    nics = get_nics()
    for n in nics:
        if n['ip'] and n['ip'].startswith('192.168.'):
            return n
    return nics[0] if nics else None

if __name__ == "__main__":
    active = get_active_nic()
    print(json.dumps({
        "nics": get_nics(),
        "active": active,
        "can_upgrade": active and not active.get('is_fast', False)
    }, indent=2))
