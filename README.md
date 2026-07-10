# 🎮 GameVault

GameVault is a LAN-only game storage dashboard for a Linux server and a Windows gaming laptop.

It helps you keep large game folders on a server, browse them in a web dashboard, access them from Windows through an SMB mapped drive, and optionally download Epic Games library files directly to the server using Legendary.

## Typical setup

- Linux server: hosts storage, SMB share, and GameVault dashboard
- Windows laptop/PC: maps the SMB share as a drive such as `Z:`
- Browser dashboard: `http://<server-ip>:8080`
- SMB share: `\\<server-ip>\games`
- Default server game root: `/srv/gamevault/games`

GameVault is designed for LAN use only. Do not expose it to the public internet.

## Features

- Web dashboard for Linux + Windows game storage workflows
- Server Library tab for installed/stored game folders
- Epic Downloader tab powered by Legendary CLI
- Download Manager drawer with real log output and pause/resume controls
- System tab for real storage and network status
- Activity tab using real local logs
- SMB-friendly folder layout:
  - `steam/<game>`
  - `epic/<game>`
  - `pirated/<game>`
  - `savedata/`
  - `setups/`
- Runtime configuration through environment variables
- No internet exposure required

## What GameVault does and does not do

GameVault does:

1. Store game files on a Linux server.
2. Expose them to Windows over SMB.
3. Let you download Epic game files directly to the server.
4. Help you copy games to/from the Windows laptop when needed.

GameVault does not:

- Stream games.
- Make Windows run games from Linux magically.
- Bypass DRM or launcher requirements.
- Guarantee every game can run directly from a network share.

Recommended workflow:

1. Store/download game files on the server.
2. Copy a game to local Windows storage when you want to play.
3. Remove the local copy later to reclaim laptop space.

## Folder layout

Default layout:

```text
/srv/gamevault/games/
├── steam/
├── epic/
├── pirated/
├── savedata/
└── setups/
```

You can override this with `GAMEVAULT_GAME_ROOT`.

## Configuration

GameVault reads environment variables, so the repo can stay generic and private details stay local.

Common variables:

```bash
GAMEVAULT_HOST=192.168.1.10
GAMEVAULT_PORT=8080
GAMEVAULT_GAME_ROOT=/srv/gamevault/games
GAMEVAULT_SMB_HOST=192.168.1.10
GAMEVAULT_SMB_SHARE=games
GAMEVAULT_HTML_FILE=/opt/gamevault/index.html
GAMEVAULT_LOG_FILE=/var/log/gamevault/transfer.log
GAMEVAULT_EPIC_ROOT=/srv/gamevault/games/epic
GAMEVAULT_EPIC_LOG=/var/log/gamevault/epic-install.log
GAMEVAULT_EPIC_STATE=/var/lib/gamevault/epic-state.json
GAMEVAULT_LEGENDARY=/root/.local/bin/legendary
```

Example systemd service:

```ini
[Unit]
Description=GameVault Dashboard
After=network.target smbd.service

[Service]
EnvironmentFile=/etc/gamevault.env
WorkingDirectory=/opt/gamevault
ExecStart=/usr/bin/python3 /opt/gamevault/server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## Windows setup

Map the SMB share:

```powershell
net use Z: \\<server-ip>\games /user:<samba-user> <password> /persistent:yes
```

Open the dashboard:

```text
http://<server-ip>:8080
```

## Epic downloader

GameVault uses Legendary CLI for Epic library downloads.

Install Legendary on the Linux server:

```bash
python3 -m pipx install legendary-gl
```

Login flow:

1. Open `https://legendary.gl/epiclogin`
2. Login with your Epic account
3. Copy the `authorizationCode` value
4. Paste it in the dashboard Epic Downloader tab

Epic install target defaults to:

```text
/srv/gamevault/games/epic
```

Pause/resume behavior:

- Pause stops the Legendary process group.
- Resume starts Legendary again for the same app.
- Legendary checks existing files and continues/repairs the download.

## Linux server setup summary

Install packages:

```bash
sudo apt update
sudo apt install -y samba python3 pipx
```

Create folders:

```bash
sudo mkdir -p /srv/gamevault/games/{steam,epic,pirated,savedata,setups}
```

Create an SMB user and share, then map it from Windows.

## Security notes

- Bind the dashboard to a LAN IP, not a public interface.
- Firewall ports 8080, 445, and 139 to LAN only.
- Do not commit local env files, passwords, logs, or runtime state.

## Repository files

```text
server.py           # GameVault backend
index.html          # Dashboard UI
game-manager.ps1   # Optional Windows copy helper
network_detect.py   # Network interface detection helper
setup_nic.sh        # Optional NIC upgrade helper
SETUP-GUIDE.txt     # Linux + Windows setup walkthrough
README.md
```

## License

MIT
