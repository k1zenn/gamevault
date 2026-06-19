# 🎮 GameVault

A self-hosted game storage manager for managing your game library across a Proxmox server and gaming laptop.

Store games on your server, pull them to your laptop when you want to play, push them back when you're done. Works with Steam, Epic, and pirated games.

## Features

- **Web Dashboard** — Beautiful dark-themed UI to browse and manage your games
- **SMB File Sharing** — Access your game library as a network drive from Windows
- **Game Manager CLI** — PowerShell script for quick pull/push operations from Windows
- **Firewall Security** — LAN-only access, nothing exposed to the internet
- **Auto-start** — Dashboard and SMB share start automatically on boot
- **Transfer Logging** — Track all game movements with timestamps

## Quick Start

### Server Setup (Proxmox)

1. Install and configure Samba:
```bash
apt install samba -y
mkdir -p /tank/games/{steam,epic,pirated}
```

2. Configure `/etc/samba/smb.conf` — add:
```ini
[games]
   path = /tank/games
   browseable = yes
   writable = yes
   valid users = gameshare
```

3. Create user and start services:
```bash
useradd -r -s /usr/sbin/nologin gameshare
smbpasswd -a gameshare
systemctl enable --now smbd nmbd
```

4. Start the dashboard:
```bash
systemctl enable --now gamevault
```

### Windows Laptop Setup

1. Map the network drive:
   - Open File Explorer > This PC > Map network drive
   - Drive: `Z:`
   - Folder: `\\192.168.29.158\games`
   - Username: `gameshare`

2. Open dashboard in browser:
```
http://192.168.29.158:8080
```

3. Use the PowerShell game manager:
```powershell
.\game-manager.ps1 list              # See all games
.\game-manager.ps1 pull "Elden Ring"  # Copy to laptop
.\game-manager.ps1 push "Elden Ring"  # Copy back to server
```

## Project Structure

```
gamemanager/
├── dashboard.py          # Web dashboard server (Python)
├── game-manager.ps1      # Windows PowerShell CLI
├── transfer.log          # Transfer history
├── SETUP-GUIDE.txt       # Detailed setup instructions
├── gamevault.service     # Systemd service file
└── README.md
```

## Configuration

Edit `dashboard.py` to change:
- `HOST` — Bind address (default: LAN IP only)
- `PORT` — Dashboard port (default: 8080)
- `GAME_DIRS` — Game storage paths

## Security

The dashboard and SMB share are configured for **LAN-only access**:
- Dashboard bound to LAN IP (not 0.0.0.0)
- Firewall rules block external access to ports 8080, 139, 445
- Rules persist across reboots via iptables

## System Requirements

- Proxmox server (or any Linux server) with Python 3.8+
- Samba installed and configured
- Windows laptop with network access to server

## License

MIT
