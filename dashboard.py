#!/usr/bin/env python3
"""
GameVault Dashboard — Game Storage Manager
A beautiful web dashboard to manage games between your Proxmox server and gaming laptop.
"""

import os
import json
import shutil
import subprocess
import threading
import time
import signal
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime
from pathlib import Path

# ============================================
# CONFIG
# ============================================
HOST = "192.168.29.158"
PORT = 8080
GAME_DIRS = {
    "steam":    "/tank/games/steam",
    "epic":     "/tank/games/epic",
    "pirated":  "/tank/games/pirated",
}
LOCAL_BASE = "/tank/games"
LOG_FILE = "/root/gamemanager/transfer.log"
PID_FILE = "/root/gamemanager/dashboard.pid"

# ============================================
# GAME SCANNER
# ============================================
def get_disk_usage(path):
    """Get disk usage for a path."""
    try:
        total, used, free = shutil.disk_usage(path)
        return {
            "total_gb": round(total / (1024**3), 1),
            "used_gb": round(used / (1024**3), 1),
            "free_gb": round(free / (1024**3), 1),
            "percent": round(used / total * 100, 1)
        }
    except Exception:
        return {"total_gb": 0, "used_gb": 0, "free_gb": 0, "percent": 0}

def scan_game_folder(folder_path):
    """Scan a game folder and return info."""
    if not os.path.exists(folder_path):
        return None
    
    name = os.path.basename(folder_path)
    total_size = 0
    file_count = 0
    last_modified = None
    
    try:
        for dirpath, dirnames, filenames in os.walk(folder_path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    stat = os.stat(fp)
                    total_size += stat.st_size
                    file_count += 1
                    if last_modified is None or stat.st_mtime > last_modified:
                        last_modified = stat.st_mtime
                except (OSError, PermissionError):
                    pass
    except Exception:
        pass
    
    # Detect game type
    game_type = "unknown"
    exe_files = []
    try:
        for f in os.listdir(folder_path):
            if f.lower().endswith('.exe'):
                exe_files.append(f)
        if exe_files:
            game_type = "executable"
        # Check for steam appid
        if os.path.exists(os.path.join(folder_path, "steam_appid.txt")):
            game_type = "steam"
    except Exception:
        pass
    
    # Detect launcher type from parent
    parent = os.path.basename(os.path.dirname(folder_path))
    if parent in GAME_DIRS:
        source = parent
    else:
        source = "unknown"
    
    return {
        "name": name,
        "path": folder_path,
        "size_bytes": total_size,
        "size_gb": round(total_size / (1024**3), 2),
        "size_mb": round(total_size / (1024**2), 1),
        "file_count": file_count,
        "last_modified": datetime.fromtimestamp(last_modified).strftime("%Y-%m-%d %H:%M") if last_modified else "N/A",
        "source": source,
        "type": game_type,
        "exe_files": exe_files[:5],  # First 5 exe files
    }

def scan_all_games():
    """Scan all game directories."""
    games = {"server": [], "local": []}
    
    # Scan server directories
    for source, path in GAME_DIRS.items():
        if os.path.exists(path):
            for item in os.listdir(path):
                full_path = os.path.join(path, item)
                if os.path.isdir(full_path):
                    info = scan_game_folder(full_path)
                    if info:
                        info["location"] = "server"
                        info["source"] = source
                        games["server"].append(info)
    
    # Scan local (the same dirs since it's the same server,
    # but for the dashboard we show server as "available" and track transfers)
    return games

def get_transfer_status():
    """Get recent transfer log entries."""
    entries = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, 'r') as f:
                lines = f.readlines()[-20:]  # Last 20 entries
            for line in lines:
                line = line.strip()
                if line:
                    entries.append(line)
        except Exception:
            pass
    return entries

def get_system_info():
    """Get system information."""
    disk = get_disk_usage("/tank")
    
    # Get network info
    try:
        result = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=5)
        ip = result.stdout.strip().split()[0]
    except Exception:
        ip = "unknown"
    
    # Get uptime
    try:
        with open("/proc/uptime", "r") as f:
            uptime_seconds = float(f.read().split()[0])
        hours = int(uptime_seconds // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        uptime = f"{hours}h {minutes}m"
    except Exception:
        uptime = "unknown"
    
    return {
        "disk": disk,
        "ip": ip,
        "port": PORT,
        "uptime": uptime,
        "server_name": "GameVault",
    }

# ============================================
# HTML DASHBOARD
# ============================================
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GameVault — Game Storage Manager</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');
  
  :root {
    --bg-primary: #0a0a0f;
    --bg-secondary: #12121a;
    --bg-card: #1a1a2e;
    --bg-card-hover: #1f1f35;
    --border: #2a2a3e;
    --text-primary: #e8e8f0;
    --text-secondary: #8888a0;
    --text-muted: #555570;
    --accent-purple: #7c3aed;
    --accent-purple-glow: rgba(124, 58, 237, 0.3);
    --accent-blue: #3b82f6;
    --accent-green: #10b981;
    --accent-orange: #f59e0b;
    --accent-red: #ef4444;
    --accent-pink: #ec4899;
    --gradient-1: linear-gradient(135deg, #7c3aed, #3b82f6);
    --gradient-2: linear-gradient(135deg, #ec4899, #7c3aed);
    --gradient-3: linear-gradient(135deg, #10b981, #3b82f6);
  }
  
  * { margin: 0; padding: 0; box-sizing: border-box; }
  
  body {
    font-family: 'Inter', -apple-system, sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
    min-height: 100vh;
    overflow-x: hidden;
  }
  
  /* Animated background */
  body::before {
    content: '';
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: 
      radial-gradient(ellipse at 20% 20%, rgba(124, 58, 237, 0.08) 0%, transparent 50%),
      radial-gradient(ellipse at 80% 80%, rgba(59, 130, 246, 0.06) 0%, transparent 50%),
      radial-gradient(ellipse at 50% 50%, rgba(236, 72, 153, 0.04) 0%, transparent 60%);
    pointer-events: none;
    z-index: 0;
  }
  
  .container {
    max-width: 1400px;
    margin: 0 auto;
    padding: 2rem;
    position: relative;
    z-index: 1;
  }
  
  /* Header */
  .header {
    text-align: center;
    margin-bottom: 3rem;
    padding: 2rem 0;
  }
  
  .header h1 {
    font-size: 3rem;
    font-weight: 800;
    background: var(--gradient-1);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 0.5rem;
    letter-spacing: -1px;
  }
  
  .header .subtitle {
    color: var(--text-secondary);
    font-size: 1.1rem;
    font-weight: 300;
  }
  
  .header .status-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    margin-top: 1rem;
    padding: 0.5rem 1rem;
    background: rgba(16, 185, 129, 0.1);
    border: 1px solid rgba(16, 185, 129, 0.3);
    border-radius: 100px;
    font-size: 0.85rem;
    color: var(--accent-green);
  }
  
  .status-dot {
    width: 8px; height: 8px;
    background: var(--accent-green);
    border-radius: 50%;
    animation: pulse 2s infinite;
  }
  
  @keyframes pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.5; transform: scale(1.2); }
  }
  
  /* Stats Row */
  .stats-row {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 1.5rem;
    margin-bottom: 2rem;
  }
  
  .stat-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 1.5rem;
    transition: all 0.3s ease;
  }
  
  .stat-card:hover {
    background: var(--bg-card-hover);
    border-color: var(--accent-purple);
    transform: translateY(-2px);
    box-shadow: 0 8px 32px var(--accent-purple-glow);
  }
  
  .stat-card .stat-icon {
    font-size: 1.5rem;
    margin-bottom: 0.75rem;
  }
  
  .stat-card .stat-value {
    font-size: 2rem;
    font-weight: 700;
    font-family: 'JetBrains Mono', monospace;
    margin-bottom: 0.25rem;
  }
  
  .stat-card .stat-label {
    color: var(--text-secondary);
    font-size: 0.85rem;
    text-transform: uppercase;
    letter-spacing: 1px;
  }
  
  /* Disk Usage Bar */
  .disk-bar-container {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 1.5rem;
    margin-bottom: 2rem;
  }
  
  .disk-bar-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1rem;
  }
  
  .disk-bar-header h3 {
    font-size: 1rem;
    font-weight: 600;
  }
  
  .disk-bar-header span {
    color: var(--text-secondary);
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.85rem;
  }
  
  .disk-bar {
    height: 12px;
    background: var(--bg-primary);
    border-radius: 100px;
    overflow: hidden;
    position: relative;
  }
  
  .disk-bar-fill {
    height: 100%;
    border-radius: 100px;
    transition: width 1s ease;
    position: relative;
  }
  
  .disk-bar-fill::after {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0; bottom: 0;
    background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.1) 50%, transparent 100%);
    animation: shimmer 2s infinite;
  }
  
  @keyframes shimmer {
    0% { transform: translateX(-100%); }
    100% { transform: translateX(100%); }
  }
  
  /* Section Headers */
  .section-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1.5rem;
  }
  
  .section-header h2 {
    font-size: 1.5rem;
    font-weight: 700;
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }
  
  .search-box {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 0.5rem 1rem;
    transition: border-color 0.3s;
  }
  
  .search-box:focus-within {
    border-color: var(--accent-purple);
  }
  
  .search-box input {
    background: none;
    border: none;
    color: var(--text-primary);
    font-size: 0.9rem;
    outline: none;
    width: 200px;
    font-family: 'Inter', sans-serif;
  }
  
  .search-box input::placeholder {
    color: var(--text-muted);
  }
  
  /* Games Grid */
  .games-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 1.5rem;
    margin-bottom: 3rem;
  }
  
  .game-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 1.5rem;
    transition: all 0.3s ease;
    position: relative;
    overflow: hidden;
  }
  
  .game-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
    background: var(--gradient-1);
    opacity: 0;
    transition: opacity 0.3s;
  }
  
  .game-card:hover {
    background: var(--bg-card-hover);
    border-color: var(--accent-purple);
    transform: translateY(-4px);
    box-shadow: 0 12px 40px rgba(124, 58, 237, 0.15);
  }
  
  .game-card:hover::before {
    opacity: 1;
  }
  
  .game-card-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 1rem;
  }
  
  .game-name {
    font-size: 1.1rem;
    font-weight: 600;
    color: var(--text-primary);
    word-break: break-word;
  }
  
  .game-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.3rem 0.6rem;
    border-radius: 100px;
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    flex-shrink: 0;
    margin-left: 0.5rem;
  }
  
  .badge-steam { background: rgba(30, 60, 114, 0.3); color: #66aaff; border: 1px solid rgba(30, 60, 114, 0.5); }
  .badge-epic { background: rgba(40, 40, 40, 0.5); color: #ffffff; border: 1px solid rgba(100, 100, 100, 0.5); }
  .badge-pirated { background: rgba(239, 68, 68, 0.15); color: #ff6b6b; border: 1px solid rgba(239, 68, 68, 0.3); }
  .badge-server { background: rgba(124, 58, 237, 0.15); color: #a78bfa; border: 1px solid rgba(124, 58, 237, 0.3); }
  
  .game-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
    margin-bottom: 1.25rem;
    color: var(--text-secondary);
    font-size: 0.85rem;
  }
  
  .game-meta span {
    display: flex;
    align-items: center;
    gap: 0.35rem;
  }
  
  .game-actions {
    display: flex;
    gap: 0.75rem;
  }
  
  .btn {
    flex: 1;
    padding: 0.7rem 1rem;
    border: none;
    border-radius: 10px;
    font-size: 0.85rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.3s ease;
    font-family: 'Inter', sans-serif;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
  }
  
  .btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  
  .btn-pull {
    background: linear-gradient(135deg, #7c3aed, #6d28d9);
    color: white;
  }
  
  .btn-pull:hover:not(:disabled) {
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(124, 58, 237, 0.4);
  }
  
  .btn-push {
    background: linear-gradient(135deg, #f59e0b, #d97706);
    color: white;
  }
  
  .btn-push:hover:not(:disabled) {
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(245, 158, 11, 0.4);
  }
  
  .btn-delete {
    background: rgba(239, 68, 68, 0.15);
    color: var(--accent-red);
    border: 1px solid rgba(239, 68, 68, 0.3);
    flex: 0;
    padding: 0.7rem 1rem;
  }
  
  .btn-delete:hover:not(:disabled) {
    background: var(--accent-red);
    color: white;
  }
  
  /* Transfer Log */
  .log-container {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 1.5rem;
    margin-bottom: 2rem;
  }
  
  .log-entries {
    max-height: 300px;
    overflow-y: auto;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.8rem;
    line-height: 1.8;
  }
  
  .log-entries::-webkit-scrollbar {
    width: 6px;
  }
  
  .log-entries::-webkit-scrollbar-track {
    background: var(--bg-primary);
    border-radius: 3px;
  }
  
  .log-entries::-webkit-scrollbar-thumb {
    background: var(--border);
    border-radius: 3px;
  }
  
  .log-entry {
    padding: 0.4rem 0.75rem;
    border-radius: 6px;
    margin-bottom: 0.25rem;
  }
  
  .log-entry:nth-child(odd) {
    background: rgba(255, 255, 255, 0.02);
  }
  
  .log-time { color: var(--text-muted); }
  .log-action-pull { color: var(--accent-green); }
  .log-action-push { color: var(--accent-orange); }
  .log-size { color: var(--accent-blue); }
  
  /* Empty State */
  .empty-state {
    text-align: center;
    padding: 4rem 2rem;
    color: var(--text-secondary);
  }
  
  .empty-state .icon {
    font-size: 4rem;
    margin-bottom: 1rem;
    opacity: 0.5;
  }
  
  .empty-state h3 {
    font-size: 1.25rem;
    margin-bottom: 0.5rem;
    color: var(--text-primary);
  }
  
  /* Toast Notification */
  .toast {
    position: fixed;
    bottom: 2rem;
    right: 2rem;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1rem 1.5rem;
    font-size: 0.9rem;
    z-index: 1000;
    transform: translateY(100px);
    opacity: 0;
    transition: all 0.3s ease;
    max-width: 400px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
  }
  
  .toast.show {
    transform: translateY(0);
    opacity: 1;
  }
  
  .toast.success { border-color: var(--accent-green); }
  .toast.error { border-color: var(--accent-red); }
  .toast.info { border-color: var(--accent-blue); }
  
  /* Loading Spinner */
  .spinner {
    display: inline-block;
    width: 16px;
    height: 16px;
    border: 2px solid rgba(255,255,255,0.3);
    border-radius: 50%;
    border-top-color: white;
    animation: spin 0.8s ease infinite;
  }
  
  @keyframes spin {
    to { transform: rotate(360deg); }
  }
  
  /* Responsive */
  @media (max-width: 768px) {
    .container { padding: 1rem; }
    .header h1 { font-size: 2rem; }
    .stats-row { grid-template-columns: 1fr 1fr; }
    .games-grid { grid-template-columns: 1fr; }
    .search-box input { width: 140px; }
  }
</style>
</head>
<body>
<div class="container">
  <!-- Header -->
  <div class="header">
    <h1>🎮 GameVault</h1>
    <p class="subtitle">Your games, always ready. Store on server, play on laptop.</p>
    <div class="status-badge" id="status-badge">
      <span class="status-dot"></span>
      <span>Connected to server</span>
    </div>
  </div>
  
  <!-- Stats -->
  <div class="stats-row" id="stats-row">
    <div class="stat-card">
      <div class="stat-icon">🎮</div>
      <div class="stat-value" id="stat-total">0</div>
      <div class="stat-label">Total Games</div>
    </div>
    <div class="stat-card">
      <div class="stat-icon">📦</div>
      <div class="stat-value" id="stat-size">0 GB</div>
      <div class="stat-label">Total Size</div>
    </div>
    <div class="stat-card">
      <div class="stat-icon">💾</div>
      <div class="stat-value" id="stat-free">0 GB</div>
      <div class="stat-label">Free Space</div>
    </div>
    <div class="stat-card">
      <div class="stat-icon">⏱️</div>
      <div class="stat-value" id="stat-uptime">-</div>
      <div class="stat-label">Uptime</div>
    </div>
  </div>
  
  <!-- Disk Usage -->
  <div class="disk-bar-container">
    <div class="disk-bar-header">
      <h3>💾 Server Storage</h3>
      <span id="disk-text">0 / 0 GB</span>
    </div>
    <div class="disk-bar">
      <div class="disk-bar-fill" id="disk-fill" style="width: 0%; background: var(--gradient-3);"></div>
    </div>
  </div>
  
  <!-- Server Games Section -->
  <div class="section-header">
    <h2>☁️ Server Library</h2>
    <div class="search-box">
      <span>🔍</span>
      <input type="text" id="search-server" placeholder="Search games..." oninput="filterGames('server')">
    </div>
  </div>
  <div class="games-grid" id="server-games"></div>
  
  <!-- Transfer Log -->
  <div class="log-container">
    <div class="section-header">
      <h2>📋 Transfer Log</h2>
      <button class="btn btn-pull" onclick="refreshData()" style="flex: 0; padding: 0.5rem 1rem;">↻ Refresh</button>
    </div>
    <div class="log-entries" id="log-entries">
      <div class="empty-state" style="padding: 2rem;">
        <p>No transfers yet. Pull a game to get started!</p>
      </div>
    </div>
  </div>
</div>

<!-- Toast -->
<div class="toast" id="toast"></div>

<script>
let allGames = { server: [] };
let currentFilter = { server: '' };

// Fetch data from API
async function fetchData() {
  try {
    const [gamesRes, sysRes, logRes] = await Promise.all([
      fetch('/api/games'),
      fetch('/api/system'),
      fetch('/api/logs')
    ]);
    
    const games = await gamesRes.json();
    const sys = await sysRes.json();
    const logs = await logRes.json();
    
    allGames = games;
    updateUI(sys, logs);
  } catch (err) {
    console.error('Fetch error:', err);
    showToast('Failed to connect to server', 'error');
  }
}

function updateUI(sys, logs) {
  // Stats
  const totalGames = allGames.server.length;
  const totalSize = allGames.server.reduce((sum, g) => sum + g.size_gb, 0);
  
  document.getElementById('stat-total').textContent = totalGames;
  document.getElementById('stat-size').textContent = totalSize.toFixed(1) + ' GB';
  document.getElementById('stat-free').textContent = sys.disk.free_gb + ' GB';
  document.getElementById('stat-uptime').textContent = sys.uptime;
  
  // Disk bar
  const usedPct = sys.disk.percent;
  const diskFill = document.getElementById('disk-fill');
  diskFill.style.width = usedPct + '%';
  
  if (usedPct > 90) {
    diskFill.style.background = 'linear-gradient(135deg, #ef4444, #dc2626)';
  } else if (usedPct > 70) {
    diskFill.style.background = 'linear-gradient(135deg, #f59e0b, #d97706)';
  }
  
  document.getElementById('disk-text').textContent = 
    `${sys.disk.used_gb} / ${sys.disk.total_gb} GB (${sys.disk.percent}%)`;
  
  // Status badge
  const badge = document.getElementById('status-badge');
  badge.innerHTML = `<span class="status-dot"></span><span>Connected — ${sys.ip}:${sys.port}</span>`;
  
  // Render games
  renderGames('server');
  
  // Render logs
  renderLogs(logs);
}

function renderGames(section) {
  const container = document.getElementById(section + '-games');
  const games = allGames[section] || [];
  const filter = (currentFilter[section] || '').toLowerCase();
  
  const filtered = games.filter(g => 
    g.name.toLowerCase().includes(filter) || 
    g.source.toLowerCase().includes(filter)
  );
  
  if (filtered.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="icon">${section === 'server' ? '☁️' : '💻'}</div>
        <h3>${section === 'server' ? 'No games on server yet' : 'No local games'}</h3>
        <p>${section === 'server' 
          ? 'Copy games to /tank/games/ on the server and they\'ll appear here.' 
          : 'Pull a game from the server to play it locally.'}</p>
      </div>`;
    return;
  }
  
  container.innerHTML = filtered.map(game => `
    <div class="game-card" data-name="${game.name.toLowerCase()}">
      <div class="game-card-header">
        <div class="game-name">${game.name}</div>
        <span class="game-badge badge-${game.source}">${game.source}</span>
      </div>
      <div class="game-meta">
        <span>💾 ${game.size_gb > 0 ? game.size_gb + ' GB' : 'Empty'}</span>
        <span>📄 ${game.file_count} files</span>
        <span>🕐 ${game.last_modified}</span>
      </div>
      <div class="game-actions">
        <button class="btn btn-pull" onclick="pullGame('${escapeHtml(game.name)}', ${game.size_gb})">
          ⬇️ Pull to Laptop
        </button>
      </div>
    </div>
  `).join('');
}

function renderLogs(logs) {
  const container = document.getElementById('log-entries');
  
  if (!logs || logs.length === 0) {
    container.innerHTML = `
      <div class="empty-state" style="padding: 2rem;">
        <p>No transfers yet. Pull a game to get started!</p>
      </div>`;
    return;
  }
  
  container.innerHTML = logs.map(entry => {
    const parts = entry.split(' | ');
    const time = parts[0] || '';
    const action = parts[1] || '';
    const name = parts[2] || '';
    const size = parts[3] || '';
    const duration = parts[4] || '';
    
    const actionClass = action.includes('pull') ? 'log-action-pull' : 'log-action-push';
    const actionIcon = action.includes('pull') ? '⬇️' : '⬆️';
    
    return `<div class="log-entry">
      <span class="log-time">${time}</span> 
      <span class="${actionClass}">${actionIcon} ${action.toUpperCase()}</span> 
      <strong>${name}</strong> 
      <span class="log-size">${size}</span>
      ${duration ? `<span>⏱️ ${duration}</span>` : ''}
    </div>`;
  }).join('');
  
  container.scrollTop = container.scrollHeight;
}

function filterGames(section) {
  currentFilter[section] = document.getElementById('search-' + section).value;
  renderGames(section);
}

async function pullGame(name, sizeGb) {
  if (!confirm(`Pull "${name}" (${sizeGb} GB) from server?\\n\\nThis will copy the game to your server's local storage.`)) {
    return;
  }
  
  showToast(`Starting transfer: ${name}...`, 'info');
  
  try {
    const res = await fetch('/api/pull', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name })
    });
    
    const data = await res.json();
    
    if (data.success) {
      showToast(`✅ ${name} pulled successfully!`, 'success');
      setTimeout(refreshData, 1000);
    } else {
      showToast(`❌ Failed: ${data.error}`, 'error');
    }
  } catch (err) {
    showToast(`❌ Transfer failed: ${err.message}`, 'error');
  }
}

function refreshData() {
  showToast('Refreshing...', 'info');
  fetchData();
}

function showToast(message, type = 'info') {
  const toast = document.getElementById('toast');
  toast.textContent = message;
  toast.className = `toast ${type} show`;
  setTimeout(() => toast.classList.remove('show'), 4000);
}

function escapeHtml(str) {
  return str.replace(/'/g, "\\\\'").replace(/"/g, '\\\\"');
}

// Auto-refresh every 30 seconds
setInterval(fetchData, 30000);

// Initial load
fetchData();
</script>
</body>
</html>"""

# ============================================
# HTTP SERVER
# ============================================
class GameVaultHandler(BaseHTTPRequestHandler):
    """Handle HTTP requests for the dashboard."""
    
    def log_message(self, format, *args):
        """Suppress default logging."""
        pass
    
    def do_GET(self):
        """Handle GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path
        
        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode())
        
        elif path == "/api/games":
            games = scan_all_games()
            self.send_json(games)
        
        elif path == "/api/system":
            info = get_system_info()
            self.send_json(info)
        
        elif path == "/api/logs":
            logs = get_transfer_status()
            self.send_json(logs)
        
        else:
            self.send_error(404)
    
    def do_POST(self):
        """Handle POST requests."""
        parsed = urlparse(self.path)
        path = parsed.path
        
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length > 0 else b'{}'
        
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = {}
        
        if path == "/api/pull":
            self.handle_pull(data)
        elif path == "/api/push":
            self.handle_push(data)
        elif path == "/api/delete":
            self.handle_delete(data)
        else:
            self.send_error(404)
    
    def send_json(self, data):
        """Send JSON response."""
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def handle_pull(self, data):
        """Handle game pull request."""
        name = data.get("name")
        if not name:
            self.send_json({"success": False, "error": "No game name provided"})
            return
        
        # Find the game on the server
        src_path = None
        for source, base_path in GAME_DIRS.items():
            candidate = os.path.join(base_path, name)
            if os.path.exists(candidate):
                src_path = candidate
                break
        
        if not src_path:
            self.send_json({"success": False, "error": f"Game '{name}' not found on server"})
            return
        
        # For now, just log it — actual pull would copy to laptop
        # In this setup, the game is already accessible via SMB
        log_entry = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | pull | {name} | {data.get('size_gb', '?')}GB | ready"
        with open(LOG_FILE, "a") as f:
            f.write(log_entry + "\n")
        
        self.send_json({"success": True, "message": f"Game '{name}' is ready on SMB share"})
    
    def handle_push(self, data):
        """Handle game push request."""
        name = data.get("name")
        if not name:
            self.send_json({"success": False, "error": "No game name provided"})
            return
        
        log_entry = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | push | {name} | {data.get('size_gb', '?')}GB | ready"
        with open(LOG_FILE, "a") as f:
            f.write(log_entry + "\n")
        
        self.send_json({"success": True, "message": f"Game '{name}' marked for push"})
    
    def handle_delete(self, data):
        """Handle game deletion request."""
        name = data.get("name")
        if not name:
            self.send_json({"success": False, "error": "No game name provided"})
            return
        
        # Find and delete
        for source, base_path in GAME_DIRS.items():
            candidate = os.path.join(base_path, name)
            if os.path.exists(candidate):
                try:
                    shutil.rmtree(candidate)
                    log_entry = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | delete | {name} | removed"
                    with open(LOG_FILE, "a") as f:
                        f.write(log_entry + "\n")
                    self.send_json({"success": True, "message": f"Game '{name}' deleted"})
                    return
                except Exception as e:
                    self.send_json({"success": False, "error": str(e)})
                    return
        
        self.send_json({"success": False, "error": f"Game '{name}' not found"})

def run_server():
    """Start the dashboard server."""
    # Write PID file
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    
    server = HTTPServer((HOST, PORT), GameVaultHandler)
    print(f"\n{'='*50}")
    print(f"  🎮 GameVault Dashboard")
    print(f"  Running on: http://{HOST}:{PORT}")
    print(f"  Local:      http://localhost:{PORT}")
    print(f"{'='*50}\n")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        server.server_close()
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)

if __name__ == "__main__":
    run_server()
