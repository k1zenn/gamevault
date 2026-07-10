# 🎮 GameVault

A LAN-only game storage dashboard for a Proxmox/Linux server + Windows gaming laptop.

GameVault stores big game folders on the server, exposes them over SMB as a Windows mapped drive, and provides a browser dashboard for browsing the server library, checking storage/network status, and downloading Epic library games directly to the server with Legendary.

## Current setup

- Dashboard: `http://192.168.29.158:8080`
- SMB share: `\\192.168.29.158\games`
- Windows mapped drive target: `Z:`
- Server storage root: `/tank/games`
- LAN-only: dashboard binds to `192.168.29.158`, not internet-facing

## Features

- Clean web dashboard with tabs:
  - Server Library
  - Epic Downloader
  - System
  - Activity
- SMB share for Windows access.
- Real disk/storage stats from the server.
- Real network interface status.
- Game scanning under:
  - `/tank/games/steam/<game>`
  - `/tank/games/epic/<game>`
  - `/tank/games/pirated/<game>`
- Utility folders shown separately:
  - `/tank/games/savedata`
  - `/tank/games/setups`
- Epic direct downloader via Legendary CLI:
  - Login with `authorizationCode`
  - Load Epic library
  - Install games to `/tank/games/epic`
  - Pause/resume by stopping/restarting Legendary
  - Real log tail from `epic-install.log`
- Activity logs from real dashboard actions.

## Important behavior

GameVault does **not** stream games or magically run server-side installs on Windows.

The intended workflow is:

1. Download/install/store game files on the server.
2. Copy the game folder to the Windows laptop using `Z:` when you want to play.
3. Remove the laptop copy later to reclaim laptop storage.

For Epic games, the server uses Legendary to download game files into `/tank/games/epic`. You still run/play them on the Windows laptop after copying them locally.

## Quick Windows setup

Map the share:

```powershell
net use Z: \\192.168.29.158\games /user:gameshare <password>
```

Open dashboard:

```text
http://192.168.29.158:8080
```

## Server service

Dashboard service:

```bash
systemctl status gamevault
systemctl restart gamevault
```

SMB services:

```bash
systemctl status smbd nmbd
```

## Files

```text
/root/gamemanager/
├── server.py            # Current GameVault backend
├── index.html           # Current dashboard UI
├── dashboard.py         # Legacy dashboard prototype
├── game-manager.ps1     # Windows PowerShell helper
├── network_detect.py    # NIC detection helper
├── setup_nic.sh         # Future gigabit NIC setup helper
├── transfer.log         # Ignored runtime activity log
├── epic-install.log     # Ignored Legendary install log
├── epic-state.json      # Ignored runtime Epic downloader state
├── SETUP-GUIDE.txt
└── README.md
```

## Epic downloader notes

Legendary is installed with pipx:

```bash
/root/.local/bin/legendary --version
```

Login flow:

1. Open `https://legendary.gl/epiclogin`
2. Login with Epic
3. Copy `authorizationCode`
4. Paste it in the dashboard Epic Downloader tab

Install target:

```text
/tank/games/epic
```

Pause/resume behavior:

- Pause stops the Legendary process group.
- Resume runs the same install again.
- Legendary reuses existing downloaded files and continues/repairs.

## Security

- Dashboard is bound to the LAN IP: `192.168.29.158`.
- SMB and dashboard are intended for LAN only.
- Do not expose this dashboard to the internet.

## Hardware note

The current server Ethernet NIC is a Realtek RTL810xE Fast Ethernet controller, limited to 100 Mbps. For much faster game transfers, use a USB 3.0 gigabit Ethernet adapter or PCIe gigabit NIC.

## Requirements

- Linux/Proxmox server
- Python 3.8+ (current server uses stdlib only)
- Samba
- pipx + Legendary for Epic downloads
- Windows laptop with LAN access
