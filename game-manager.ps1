<#
  Game Manager for Windows
  Manages game storage between local disk and SMB server
  
  Setup:
    1. Map your SMB share to a drive letter (e.g. Z:)
    2. Edit the config below
    3. Run: powershell -ExecutionPolicy Bypass -File game-manager.ps1
  
  Commands:
    .\game-manager.ps1 list          # Show all games and where they are
    .\game-manager.ps1 pull "Elden"  # Copy game from server to laptop
    .\game-manager.ps1 push "Elden"  # Copy game from laptop back to server
    .\game-manager.ps1 space         # Show disk usage
    .\game-manager.ps1 pull-all      # Pull all games (careful!)
    .\game-manager.ps1 push-all      # Push all local games back
#>

# ============================================
# CONFIG — EDIT THESE
# ============================================
$ServerDrive   = "Z:"                           # Your mapped SMB share
$LocalGamesDir = "D:\Games"                     # Where you keep games locally
$ServerGames   = "$ServerDrive\Games"           # Path on the SMB share
$LogDir        = "$env:USERPROFILE\.gamemgr"    # Log directory

# Game folders to scan for (common patterns)
$GamePatterns  = @("*.exe", "*.bat", "*.lnk", "steam_appid.txt", "*.manifest")

# ============================================
# DON'T EDIT BELOW
# ============================================

# Create dirs
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path $LocalGamesDir | Out-Null

function Write-Header {
    param([string]$Title)
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  $Title" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
}

function Get-GameInfo {
    param([string]$Path, [string]$Location)
    
    if (-not (Test-Path $Path)) { return $null }
    
    $size = (Get-ChildItem -Path $Path -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
    $sizeGB = [math]::Round($size / 1GB, 2)
    $count = (Get-ChildItem -Path $Path -Recurse -File -ErrorAction SilentlyContinue | Measure-Object).Count
    $modified = (Get-ChildItem -Path $Path -Recurse -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1).LastWriteTime
    
    return @{
        Name     = (Get-Item $Path).Name
        Path     = $Path
        Location = $Location
        SizeGB   = $sizeGB
        Files    = $count
        Modified = if ($modified) { $modified.ToString("yyyy-MM-dd HH:mm") } else { "N/A" }
    }
}

function Get-AllGames {
    $games = @()
    
    # Scan server
    if (Test-Path $ServerGames) {
        $dirs = Get-ChildItem -Path $ServerGames -Directory -ErrorAction SilentlyContinue
        foreach ($dir in $dirs) {
            $info = Get-GameInfo -Path $dir.FullName -Location "SERVER"
            if ($info) { $games += $info }
        }
    }
    
    # Scan local
    $dirs = Get-ChildItem -Path $LocalGamesDir -Directory -ErrorAction SilentlyContinue
    foreach ($dir in $dirs) {
        $info = Get-GameInfo -Path $dir.FullName -Location "LOCAL"
        if ($info) { $games += $info }
    }
    
    return $games
}

function Show-List {
    Write-Header "Game Library"
    
    if (-not (Test-Path $ServerGames)) {
        Write-Host "WARNING: Server share not accessible at $ServerGames" -ForegroundColor Red
        Write-Host "Make sure the SMB share is mapped to $ServerDrive" -ForegroundColor Yellow
        Write-Host ""
    }
    
    $games = Get-AllGames
    
    if ($games.Count -eq 0) {
        Write-Host "No games found." -ForegroundColor Yellow
        Write-Host "Put game folders in: $LocalGamesDir (local) or $ServerGames (server)"
        return
    }
    
    # Server games
    $serverGames = $games | Where-Object { $_.Location -eq "SERVER" }
    $localGames = $games | Where-Object { $_.Location -eq "LOCAL" }
    
    Write-Host "`nSERVER ($ServerDrive\Games):" -ForegroundColor Green
    if ($serverGames) {
        foreach ($g in $serverGames) {
            $size = "$($g.SizeGB) GB".PadRight(12)
            Write-Host "  [$size] $($g.Name)" -ForegroundColor White
        }
    } else {
        Write-Host "  (empty)" -ForegroundColor DarkGray
    }
    
    Write-Host "`nLOCAL ($LocalGamesDir):" -ForegroundColor Yellow
    if ($localGames) {
        foreach ($g in $localGames) {
            $size = "$($g.SizeGB) GB".PadRight(12)
            Write-Host "  [$size] $($g.Name)" -ForegroundColor White
        }
    } else {
        Write-Host "  (empty)" -ForegroundColor DarkGray
    }
    
    # Summary
    $totalServer = ($serverGames | Measure-Object -Property SizeGB -Sum).Sum
    $totalLocal = ($localGames | Measure-Object -Property SizeGB -Sum).Sum
    Write-Host "`nTotal: Server=$([math]::Round($totalServer, 2)) GB | Local=$([math]::Round($totalLocal, 2)) GB" -ForegroundColor Cyan
}

function Copy-Game {
    param(
        [string]$GameName,
        [string]$Direction  # "pull" or "push"
    )
    
    if ($Direction -eq "pull") {
        $src = Join-Path $ServerGames $GameName
        $dst = Join-Path $LocalGamesDir $GameName
    } else {
        $src = Join-Path $LocalGamesDir $GameName
        $dst = Join-Path $ServerGames $GameName
    }
    
    if (-not (Test-Path $src)) {
        Write-Host "ERROR: Source not found: $src" -ForegroundColor Red
        return $false
    }
    
    if (Test-Path $dst) {
        Write-Host "WARNING: Destination already exists: $dst" -ForegroundColor Yellow
        $confirm = Read-Host "Overwrite? (y/n)"
        if ($confirm -ne "y") { return $false }
        Remove-Item -Path $dst -Recurse -Force
    }
    
    $size = (Get-ChildItem -Path $src -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
    $sizeGB = [math]::Round($size / 1GB, 2)
    
    Write-Host "`n$($Direction.ToUpper()): $GameName ($sizeGB GB)" -ForegroundColor Cyan
    Write-Host "  From: $src" -ForegroundColor Gray
    Write-Host "  To:   $dst" -ForegroundColor Gray
    Write-Host ""
    
    $start = Get-Date
    
    # Use robocopy for reliability and progress
    $robocopyArgs = @($src, $dst, "/E", "/COPYALL", "/R:3", "/W:5", "/NP", "/NFL", "/NDL")
    $result = & robocopy @robocopyArgs
    
    $elapsed = (Get-Date) - $start
    $mins = [math]::Round($elapsed.TotalMinutes, 1)
    
    # robocopy exit codes: 0-7 are success, 8+ are errors
    if ($LASTEXITCODE -le 7) {
        Write-Host "Done! Took $mins minutes" -ForegroundColor Green
        
        # Log it
        $logEntry = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') | $Direction | $GameName | ${sizeGB}GB | ${mins}min"
        Add-Content -Path "$LogDir\transfer.log" -Value $logEntry
        
        return $true
    } else {
        Write-Host "ERROR: Transfer failed (exit code $LASTEXITCODE)" -ForegroundColor Red
        return $false
    }
}

function Remove-AfterPush {
    param([string]$GameName)
    
    $path = Join-Path $LocalGamesDir $GameName
    if (Test-Path $path) {
        Write-Host "Removing local copy: $path" -ForegroundColor Yellow
        Remove-Item -Path $path -Recurse -Force
        Write-Host "Local copy removed. Space freed!" -ForegroundColor Green
    }
}

function Show-Space {
    Write-Header "Disk Space"
    
    # Local drive
    $localDrive = (Split-Path $LocalGamesDir -Qualifier)
    $localDisk = Get-WmiObject -Class Win32_LogicalDisk -Filter "DeviceID='$localDrive'"
    $localFreeGB = [math]::Round($localDisk.FreeSpace / 1GB, 1)
    $localTotalGB = [math]::Round($localDisk.Size / 1GB, 1)
    $localUsedGB = [math]::Round(($localDisk.Size - $localDisk.FreeSpace) / 1GB, 1)
    $localPct = [math]::Round(($localDisk.Size - $localDisk.FreeSpace) / $localDisk.Size * 100)
    
    Write-Host "LOCAL ($localDrive):" -ForegroundColor Yellow
    Write-Host "  Used: $localUsedGB GB / $localTotalGB GB ($localPct%)" -ForegroundColor White
    Write-Host "  Free: $localFreeGB GB" -ForegroundColor $(if ($localFreeGB -lt 50) { "Red" } else { "Green" })
    
    # Server
    if (Test-Path "$ServerDrive\") {
        $serverDisk = Get-WmiObject -Class Win32_LogicalDisk -Filter "DeviceID='$ServerDrive'"
        if ($serverDisk) {
            $serverFreeGB = [math]::Round($serverDisk.FreeSpace / 1GB, 1)
            $serverTotalGB = [math]::Round($serverDisk.Size / 1GB, 1)
            $serverUsedGB = [math]::Round(($serverDisk.Size - $serverDisk.FreeSpace) / 1GB, 1)
            $serverPct = [math]::Round(($serverDisk.Size - $serverDisk.FreeSpace) / $serverDisk.Size * 100)
            
            Write-Host "`nSERVER ($ServerDrive):" -ForegroundColor Green
            Write-Host "  Used: $serverUsedGB GB / $serverTotalGB GB ($serverPct%)" -ForegroundColor White
            Write-Host "  Free: $serverFreeGB GB" -ForegroundColor Green
        }
    } else {
        Write-Host "`nSERVER ($ServerDrive): NOT ACCESSIBLE" -ForegroundColor Red
    }
    
    # Show what's taking space locally
    Write-Host "`nLOCAL GAMES BREAKDOWN:" -ForegroundColor Cyan
    $localGames = Get-ChildItem -Path $LocalGamesDir -Directory -ErrorAction SilentlyContinue
    foreach ($dir in $localGames) {
        $size = (Get-ChildItem -Path $dir.FullName -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
        $sizeGB = [math]::Round($size / 1GB, 2)
        Write-Host "  $($dir.Name): $sizeGB GB" -ForegroundColor White
    }
}

function Show-Help {
    Write-Header "Game Manager"
    Write-Host @"
  Commands:
    list              Show all games (server + local)
    pull <name>       Copy game from server to laptop
    push <name>       Copy game from laptop to server, then delete local
    space             Show disk usage breakdown
    pull-all          Pull ALL games from server (careful!)
    push-all          Push ALL local games back to server
    
  Setup:
    1. Create an SMB share on your Proxmox server
    2. Map it to drive letter Z: on Windows
    3. Create the folder Z:\Games
    4. Put your game folders there
    5. Edit this script: set `$LocalGamesDir` to your local games folder

  Examples:
    .\game-manager.ps1 pull "Elden Ring"
    .\game-manager.ps1 push "Cyberpunk 2077"
    .\game-manager.ps1 list

  Steam Tip:
    Add Z:\Games as a Steam Library (Steam > Settings > Storage > Add)
    Then use 'pull' to copy games to local, Steam will detect them.
    
  Saves:
    Game saves are separate! Back up your save folders before pushing.
    Usually in: %USERPROFILE%\Documents\My Games
    Or: %APPDATA%
"@ -ForegroundColor White
}

# ============================================
# MAIN
# ============================================

$cmd = $args[0]
$arg = $args[1..($args.Length-1)] -join " "

switch ($cmd) {
    "list"     { Show-List }
    "pull"     { 
        if (-not $arg) { Write-Host "Usage: .\game-manager.ps1 pull 'Game Name'" -ForegroundColor Red; exit 1 }
        $result = Copy-Game -GameName $arg -Direction "pull"
        if ($result) { Write-Host "`nGame is ready to play!" -ForegroundColor Green }
    }
    "push"     {
        if (-not $arg) { Write-Host "Usage: .\game-manager.ps1 push 'Game Name'" -ForegroundColor Red; exit 1 }
        $result = Copy-Game -GameName $arg -Direction "push"
        if ($result) { Remove-AfterPush -GameName $arg }
    }
    "space"    { Show-Space }
    "pull-all" {
        $games = Get-AllGames | Where-Object { $_.Location -eq "SERVER" }
        if (-not $games) { Write-Host "No games on server to pull." -ForegroundColor Yellow; exit 0 }
        Write-Host "About to pull $($games.Count) games:" -ForegroundColor Yellow
        foreach ($g in $games) { Write-Host "  - $($g.Name) ($($g.SizeGB) GB)" }
        $confirm = Read-Host "`nContinue? (y/n)"
        if ($confirm -eq "y") {
            foreach ($g in $games) { Copy-Game -GameName $g.Name -Direction "pull" }
        }
    }
    "push-all" {
        $games = Get-AllGames | Where-Object { $_.Location -eq "LOCAL" }
        if (-not $games) { Write-Host "No local games to push." -ForegroundColor Yellow; exit 0 }
        Write-Host "About to push $($games.Count) games:" -ForegroundColor Yellow
        foreach ($g in $games) { Write-Host "  - $($g.Name) ($($g.SizeGB) GB)" }
        $confirm = Read-Host "`nContinue? (y/n)"
        if ($confirm -eq "y") {
            foreach ($g in $games) {
                $result = Copy-Game -GameName $g.Name -Direction "push"
                if ($result) { Remove-AfterPush -GameName $g.Name }
            }
        }
    }
    default    { Show-Help }
}
