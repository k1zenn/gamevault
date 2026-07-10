#!/usr/bin/env python3
"""
GameVault NIC Auto-Setup
Run this right after plugging in a new gigabit USB adapter.
It will detect the new NIC, configure it, and switch everything to it.
"""
import subprocess, re, json, sys

def run(cmd, dry=False):
    """Run a command and return output."""
    print(f"  {cmd}")
    if dry:
        return ""
    try:
        out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.STDOUT)
        return out
    except subprocess.CalledProcessError as e:
        print(f"  ERROR: {e.output.strip()}")
        return ""

def detect_nics():
    """Get all NICs with speeds."""
    nics = []
    out = run("ip -o link show")
    for line in out.strip().split('\n'):
        parts = line.split(':')
        if len(parts) >= 2:
            iface = parts[1].strip()
            if iface in ('lo', 'docker0'):
                continue
            speed = "?"
            try:
                eth_out = subprocess.check_output(
                    ["ethtool", iface], text=True, stderr=subprocess.DEVNULL
                )
                sm = re.search(r'Speed: (\d+[Mm]b/s|Unknown)', eth_out)
                if sm:
                    speed = sm.group(1)
            except:
                pass
            ip = None
            try:
                ip_out = subprocess.check_output(
                    ["ip", "-o", "addr", "show", iface], text=True,
                    stderr=subprocess.DEVNULL
                )
                m = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', ip_out)
                if m:
                    ip = m.group(1)
            except:
                pass
            is_fast = False
            try:
                if speed != "?" and "Mb/s" in speed:
                    is_fast = int(re.search(r'(\d+)', speed).group(1)) >= 1000
            except:
                pass
            nics.append({
                "name": iface,
                "ip": ip,
                "speed": speed,
                "is_fast": is_fast
            })
    return nics

def find_new_nic(old_nics):
    """Find new NIC that wasn't in old list."""
    old_names = {n['name'] for n in old_nics}
    current = detect_nics()
    for n in current:
        if n['name'] not in old_names:
            return n, current
    return None, current

def setup_nic(iface, bridge="vmbr0"):
    """Add new NIC to Proxmox bridge."""
    print(f"\nAdding {iface} to {bridge}...")
    # Read current interfaces
    with open("/etc/network/interfaces") as f:
        config = f.read()
    
    if f"bridge-ports {iface}" in config:
        print(f"  {iface} already part of bridge")
        return
    
    # Add to bridge-ports line
    config = re.sub(
        r'(bridge-ports\s+)(.*)',
        rf'\1\2 {iface}',
        config
    )
    
    with open("/etc/network/interfaces", "w") as f:
        f.write(config)
    
    print(f"  Added to bridge")

def update_samba(new_ip):
    """Update Samba to listen on all interfaces (firewall blocks external)."""
    print(f"\nUpdating Samba to use new NIC: {new_ip}")
    with open("/etc/samba/smb.conf") as f:
        conf = f.read()
    
    # Remove old interfaces line if present
    conf = re.sub(r'\ninterfaces =.*', '', conf)
    
    # Add new interfaces line after [global]
    conf = conf.replace("[global]\n", f"[global]\n   interfaces = 127.0.0.0/8 {new_ip}\n   bind interfaces only = yes\n")
    
    with open("/etc/samba/smb.conf", "w") as f:
        f.write(conf)
    
    run("systemctl restart smbd")
    print("  Samba restarted")

def update_dashboard(new_ip):
    """Update dashboard to bind to new IP."""
    print(f"\nUpdating dashboard bind: {new_ip}")
    with open("/root/gamemanager/server.py") as f:
        code = f.read()
    code = code.replace('HOST = "192.168.29.158"', f'HOST = "{new_ip}"')
    code = code.replace('HOST = "0.0.0.0"', f'HOST = "{new_ip}"')
    with open("/root/gamemanager/server.py", "w") as f:
        f.write(code)
    run("systemctl restart gamevault")
    print("  Dashboard restarted")

def update_firewall(new_ip):
    """Add firewall rule for new NIC subnet."""
    print(f"\nUpdating firewall rules")
    subnet = '.'.join(new_ip.split('.')[:3]) + '.0/24'
    
    # Allow Samba on new subnet
    run(f"iptables -C INPUT -s {subnet} -p tcp --dport 445 -j ACCEPT 2>/dev/null || "
        f"iptables -I INPUT 4 -s {subnet} -p tcp --dport 445 -j ACCEPT")
    run(f"iptables -C INPUT -s {subnet} -p tcp --dport 139 -j ACCEPT 2>/dev/null || "
        f"iptables -I INPUT 4 -s {subnet} -p tcp --dport 139 -j ACCEPT")
    run(f"iptables -C INPUT -s {subnet} -p tcp --dport 8080 -j ACCEPT 2>/dev/null || "
        f"iptables -I INPUT 4 -s {subnet} -p tcp --dport 8080 -j ACCEPT")
    
    # Re-save rules
    run("iptables-save > /etc/iptables/rules.v4")
    print("  Firewall updated")

if __name__ == "__main__":
    print("=== GameVault NIC Auto-Setup ===\n")
    
    # Step 1: Detect current NICs
    print("Current NICs:")
    current = detect_nics()
    for n in current:
        fast = " 🚀" if n['is_fast'] else ""
        print(f"  {n['name']:10} {n['speed']:8} {n['ip'] or 'no IP'}{fast}")
    
    gigabit = [n for n in current if n['is_fast']]
    
    if gigabit:
        print("\n🚀 Gigabit NIC already found!")
        g = gigabit[0]
        if not g['ip']:
            print(f"  Getting IP for {g['name']}...")
            run(f"dhclient {g['name']}")
        print(json.dumps(g, indent=2))
        sys.exit(0)
    
    print("\nNo gigabit NIC detected.")
    print("\nPlease:")
    print("  1. Plug in the USB gigabit adapter")
    print("  2. Run this script again")
    print(f"\nDetected {len(current)} interfaces:")
    for n in current:
        print(f"  {n['name']}")
    
    # Wait for new NIC
    print("\nWaiting for new NIC (Ctrl+C to cancel)...")
    try:
        import time
        old_names = {n['name'] for n in current}
        while True:
            time.sleep(2)
            new_nic, all_nics = find_new_nic(current)
            if new_nic:
                print(f"\n✅ New NIC detected: {new_nic['name']}")
                print(f"   Speed: {new_nic['speed']}")
                
                # Configure it
                run(f"ip link set {new_nic['name']} up")
                run(f"dhclient {new_nic['name']}")
                
                time.sleep(1)
                
                # Get updated info
                _, all_nics = detect_nics()
                for n in all_nics:
                    if n['name'] == new_nic['name']:
                        new_nic = n
                        break
                
                print(f"   IP: {new_nic['ip']}")
                
                if not new_nic['ip']:
                    print("\n❌ Failed to get IP. Check your router/DHCP.")
                    sys.exit(1)
                
                print(f"\nConfiguring network + Samba + firewall...")
                
                # Add to bridge for Proxmox access
                setup_nic(new_nic['name'])
                
                # Update services
                update_samba(new_nic['ip'])
                update_dashboard(new_nic['ip'])
                update_firewall(new_nic['ip'])
                
                print(config := f"\n=== DONE ===")
                print(f"Dashboard:  http://{new_nic['ip']}:8080")
                print(f"SMB:        \\\\your-server\\games")
                print(f"Speed:      {new_nic['speed']}")
                print(f"\nMap drive on laptop: net use Z: \\\\{new_nic['ip']}\\games /user:gameshare gamepass123")
                break
    except KeyboardInterrupt:
        print("\nCancelled.")
