# =============================================================================
#  MailBridge : installation en un clic (Windows 10 / 11)
#
#  Depuis Internet (PowerShell) :
#      irm https://raw.githubusercontent.com/Andrianarivelo/MailBridge/main/install.ps1 | iex
#  Depuis un dossier téléchargé : double-clic sur Install-MailBridge.cmd
#
#  Ce que fait le script (aucun droit administrateur requis) :
#    1. récupère MailBridge dans %LOCALAPPDATA%\Programs\MailBridge (ou l'utilise sur place) ;
#    2. installe un Python privé + pywebview / pywin32 grâce à « uv » (rien n'est ajouté au PATH) ;
#    3. crée la tâche planifiée « MailBridge » (ouverture de session + toutes les 5 min,
#       sans fenêtre, priorité basse), une icône de notification à l'ouverture de session
#       et les raccourcis MailBridge (Bureau + menu Démarrer) ;
#    4. ouvre MailBridge.
#
#  Options (variables d'environnement, à définir avant de lancer le script) :
#    MAILBRIDGE_DIR        dossier d'installation        (défaut : %LOCALAPPDATA%\Programs\MailBridge)
#    MAILBRIDGE_INTERVAL   minutes entre deux passes     (défaut : 5)
#    MAILBRIDGE_NO_LAUNCH=1     ne pas ouvrir MailBridge à la fin
#  Désinstaller : powershell -ExecutionPolicy Bypass -File install.ps1 -Remove
#                 (garde vos réglages, journaux et identifiants)
# =============================================================================
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# ----------------------------- Paramètres ------------------------------------
$Repo        = 'Andrianarivelo/MailBridge'
$Branch      = 'main'
$TaskName    = 'MailBridge'
$TrayTaskName = 'MailBridgeTray'
$PythonVer   = '3.12'
# Dossier source : celui du script (lancé depuis un dossier téléchargé) ou rien (lancé depuis Internet)
$Here        = if ($env:MAILBRIDGE_SRC) { $env:MAILBRIDGE_SRC.TrimEnd('\') } `
               elseif ($PSCommandPath) { Split-Path -Parent $PSCommandPath } else { $null }
$InPlace     = $Here -and (Test-Path (Join-Path $Here 'mailbridge\__init__.py'))
$InstallDir  = if ($env:MAILBRIDGE_DIR) { $env:MAILBRIDGE_DIR } elseif ($InPlace) { $Here } `
               else { Join-Path $env:LOCALAPPDATA 'Programs\MailBridge' }
$Interval    = if ($env:MAILBRIDGE_INTERVAL) { [int]$env:MAILBRIDGE_INTERVAL } else { 5 }
$Remove      = ($args -contains '-Remove') -or $env:MAILBRIDGE_REMOVE
$UserId      = "$env:USERDOMAIN\$env:USERNAME"
# -----------------------------------------------------------------------------

function Step([string]$Text) { Write-Host "  > $Text" -ForegroundColor Cyan }
function Done([string]$Text) { Write-Host "    $Text" -ForegroundColor DarkGray }

function Remove-Shortcuts {
    foreach ($folder in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
        Remove-Item (Join-Path $folder 'MailBridge.lnk') -Force -ErrorAction SilentlyContinue
    }
}

Write-Host ""
Write-Host "  MailBridge : tous vos mails, un seul Gmail" -ForegroundColor Magenta
Write-Host ""

if ($Remove) {
    Step "Désinstallation"
    # Ferme aussi une icône lancée depuis le raccourci, puis attend sa terminaison.
    $removePython = Join-Path $InstallDir '.venv\Scripts\python.exe'
    if (Test-Path $removePython) {
        Push-Location $InstallDir
        try {
            & $removePython -m mailbridge.tray --stop
            if ($LASTEXITCODE) { throw "Arrêt de l'icône impossible." }
        } finally { Pop-Location }
    }
    Stop-ScheduledTask -TaskName $TrayTaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TrayTaskName -Confirm:$false -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Remove-Shortcuts
    Done "Tâche et raccourcis supprimés. Le dossier $InstallDir (réglages, journaux) est conservé."
    return
}

# 1) Fichiers ------------------------------------------------------------------
$tmp = $null
if ($InPlace) {
    $SourceDir = $Here
} else {
    Step "Téléchargement de MailBridge ($Repo)"
    $tmp = Join-Path $env:TEMP ("mailbridge_" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force $tmp | Out-Null
    $zip = Join-Path $tmp 'src.zip'
    Invoke-WebRequest "https://github.com/$Repo/archive/refs/heads/$Branch.zip" -OutFile $zip -UseBasicParsing
    Expand-Archive $zip -DestinationPath $tmp -Force
    $SourceDir = (Get-ChildItem $tmp -Directory | Select-Object -First 1).FullName
}
if ((Resolve-Path $SourceDir).Path.TrimEnd('\') -ne [IO.Path]::GetFullPath($InstallDir).TrimEnd('\')) {
    New-Item -ItemType Directory -Force $InstallDir | Out-Null
    Get-ChildItem $SourceDir -Force | Where-Object { $_.Name -notin '.git', 'data', '.venv', '.tools' } |
        Copy-Item -Destination $InstallDir -Recurse -Force        # vos réglages (data\) ne sont jamais écrasés
}
if ($tmp) { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Force (Join-Path $InstallDir 'data') | Out-Null
Done "Dossier : $InstallDir"

# 2) Python privé via uv ----------------------------------------------------------
Step "Préparation de Python $PythonVer (privé à MailBridge)"
$ToolsDir = Join-Path $InstallDir '.tools'
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) {
    $uv = Join-Path $ToolsDir 'uv.exe'
    if (-not (Test-Path $uv)) {
        New-Item -ItemType Directory -Force $ToolsDir | Out-Null
        $uvZip = Join-Path $ToolsDir 'uv.zip'
        Invoke-WebRequest 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' -OutFile $uvZip -UseBasicParsing
        Expand-Archive $uvZip -DestinationPath $ToolsDir -Force
        Remove-Item $uvZip -Force
    }
}
$env:UV_PYTHON_INSTALL_DIR = Join-Path $ToolsDir 'python'     # tout reste dans le dossier MailBridge
$env:UV_CACHE_DIR          = Join-Path $ToolsDir 'cache'
$Venv = Join-Path $InstallDir '.venv'
if (-not (Test-Path (Join-Path $Venv 'Scripts\python.exe'))) {
    & $uv venv $Venv --python $PythonVer --quiet
    if ($LASTEXITCODE) { throw "Création de l'environnement Python impossible." }
}
$Py  = Join-Path $Venv 'Scripts\python.exe'
$PyW = Join-Path $Venv 'Scripts\pythonw.exe'
& $uv pip install --python $Py -r (Join-Path $InstallDir 'requirements.txt') --quiet
if ($LASTEXITCODE) { throw "Installation des dépendances impossible." }
& $Py (Join-Path $InstallDir 'mailbridge\icon.py') | Out-Null
Done "Python et dépendances prêts"

# 3) Tâche planifiée + icône ---------------------------------------------------------
Step "Démarrage automatique (tâche « $TaskName », toutes les $Interval min)"
$cfgFile = Join-Path $InstallDir 'data\config.json'
if (Test-Path $cfgFile) {   # garde la fréquence choisie dans la configuration
    try { $Interval = [int]((Get-Content $cfgFile -Raw -Encoding UTF8 | ConvertFrom-Json).settings.interval_minutes) } catch { }
}
$action = New-ScheduledTaskAction -Execute $PyW -Argument '-m mailbridge.engine' -WorkingDirectory $InstallDir
$every  = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $Interval)
$logon  = New-ScheduledTaskTrigger -AtLogOn -User $UserId
$logon.Delay = 'PT1M'
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries `
              -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -Priority 7
$principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($every, $logon) -Settings $settings `
    -Principal $principal -Force -Description 'MailBridge : copie vos comptes mail dans Gmail.' | Out-Null

# L'icône reste résidente, sans charger WebView. La tâche moteur reste indépendante.
# Fermeture propre avant l'arrêt de la tâche pour retirer aussi l'icône d'Explorer.
Push-Location $InstallDir
try {
    & $Py -m mailbridge.tray --stop
    if ($LASTEXITCODE) { throw "Arrêt de l'ancienne icône impossible." }
} finally { Pop-Location }
Stop-ScheduledTask -TaskName $TrayTaskName -ErrorAction SilentlyContinue
$trayAction = New-ScheduledTaskAction -Execute $PyW -Argument '-m mailbridge.tray' -WorkingDirectory $InstallDir
$trayLogon = New-ScheduledTaskTrigger -AtLogOn -User $UserId
$trayLogon.Delay = 'PT10S'
$traySettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -Priority 7
Register-ScheduledTask -TaskName $TrayTaskName -Action $trayAction -Trigger $trayLogon -Settings $traySettings `
    -Principal $principal -Force -Description 'MailBridge : icône de notification et état de la synchronisation.' | Out-Null
Start-ScheduledTask -TaskName $TrayTaskName

Remove-Shortcuts
$shell = New-Object -ComObject WScript.Shell
foreach ($folder in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    $lnk = $shell.CreateShortcut((Join-Path $folder 'MailBridge.lnk'))
    $lnk.TargetPath = $PyW
    $lnk.Arguments = "`"$InstallDir\MailBridge.pyw`""
    $lnk.WorkingDirectory = $InstallDir
    $lnk.IconLocation = "$InstallDir\assets\mailbridge.ico,0"
    $lnk.Description = 'MailBridge : tous vos mails, un seul Gmail'
    $lnk.Save()
}
Done "Icône MailBridge ajoutée au Bureau et au menu Démarrer"
Done "Icône de notification active en arrière-plan"

# 4) C'est parti ----------------------------------------------------------------------
Write-Host ""
Write-Host "  MailBridge est installé." -ForegroundColor Green
Write-Host "  Ouvrez-le, renseignez Gmail puis ajoutez vos comptes." -ForegroundColor Green
Write-Host ""
if (-not $env:MAILBRIDGE_NO_LAUNCH) { Start-Process $PyW -ArgumentList "`"$InstallDir\MailBridge.pyw`"" -WorkingDirectory $InstallDir }
