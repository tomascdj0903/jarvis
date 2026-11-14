# J.A.R.V.I.S. - installateur : verifie Python, l'installe si besoin, construit Jarvis.exe
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Host.UI.RawUI.WindowTitle = "J.A.R.V.I.S. - Installation"
Add-Type -AssemblyName System.Windows.Forms

$PyVersion = "3.11.9"
$PyUrl     = "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-amd64.exe"

function Say($t, $c = "Cyan") { Write-Host "  $t" -ForegroundColor $c }
function Ask($t) {
    [System.Windows.Forms.MessageBox]::Show($t, "J.A.R.V.I.S.", "YesNo", "Question") -eq "Yes"
}
function Fail($t) {
    [System.Windows.Forms.MessageBox]::Show($t, "J.A.R.V.I.S.", "OK", "Error") | Out-Null
    exit 1
}

Write-Host ""
Say "=== J.A.R.V.I.S. : installation ===" "White"
Write-Host ""

# 1. Infos machine
$arch = $env:PROCESSOR_ARCHITECTURE
if ($env:PROCESSOR_ARCHITEW6432) { $arch = $env:PROCESSOR_ARCHITEW6432 }
Say "Processeur : $arch"
if ($arch -eq "ARM64") {
    Say "PC ARM (Snapdragon) detecte : on utilise Python x64, qui tourne en emulation" "Yellow"
    Say "et dispose de toutes les bibliotheques audio/IA necessaires." "Yellow"
}

# 2. Cherche un Python 3.10-3.12 x64 adapte
function Find-Python {
    $cands = @()
    foreach ($v in "3.11", "3.12", "3.10") { $cands += ,@("py", "-$v") }
    $cands += ,@("python")
    foreach ($c in $cands) {
        try {
            $exe = $c[0]; $args_ = @($c | Select-Object -Skip 1)
            $out = & $exe @args_ -c "import sys,platform;print(sys.version_info[0],sys.version_info[1],platform.machine(),sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $out) {
                $p = $out.Trim().Split(" ", 4)
                $maj = [int]$p[0]; $min = [int]$p[1]; $m = $p[2]
                if ($maj -eq 3 -and $min -ge 10 -and $min -le 12 -and $m -match "AMD64|x86_64") {
                    return @{ Exe = $p[3]; Ver = "$maj.$min"; Machine = $m }
                }
                Say "Python $maj.$min ($m) trouve mais pas adapte (il faut 3.10 a 3.12 en x64)." "Yellow"
            }
        } catch {}
    }
    return $null
}

$py = Find-Python
if ($py) {
    Say "Python adapte trouve : $($py.Ver) x64" "Green"
} else {
    $msg = "Python adapte introuvable.`n`nVersion recommandee pour ton PC : Python $PyVersion (Windows x64).`n" +
           "Il sert uniquement a fabriquer Jarvis.exe (environ 30 Mo).`n`nL'installer maintenant ?"
    if (-not (Ask $msg)) { Fail "Installation annulee. Installe Python $PyVersion x64 depuis python.org puis relance." }

    $ok = $false
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Say "Installation via winget..."
        winget install --id Python.Python.3.11 --architecture x64 --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -eq 0) { $ok = $true }
    }
    if (-not $ok) {
        Say "Telechargement de Python $PyVersion depuis python.org..."
        $tmp = Join-Path $env:TEMP "python-$PyVersion-amd64.exe"
        Invoke-WebRequest $PyUrl -OutFile $tmp -UseBasicParsing
        Say "Installation (quelques minutes)..."
        $p = Start-Process $tmp -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0" -Wait -PassThru
        if ($p.ExitCode -ne 0) { Fail "L'installation de Python a echoue (code $($p.ExitCode))." }
    }
    # recharge le PATH
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
    $py = Find-Python
    if (-not $py) { Fail "Python installe mais introuvable. Redemarre le PC puis relance l'installateur." }
    Say "Python $($py.Ver) installe." "Green"
}

# 3. Environnement + dependances
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Say "Creation de l'environnement..."
    & $py.Exe -m venv .venv
}
$vpy = Join-Path $Root ".venv\Scripts\python.exe"
Say "Installation des composants (micro, voix, IA)..."
& $vpy -m pip install --upgrade pip --quiet
& $vpy -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) { Fail "Echec d'installation des composants. Verifie ta connexion internet." }
Say "Telechargement du modele 'Hey Jarvis'..."
& $vpy -c "import openwakeword.utils as u; u.download_models(['hey_jarvis'])"

# 4. Construction du .exe
Say "Fabrication de Jarvis.exe..."
$oww = (& $vpy -c "import openwakeword,os;print(os.path.dirname(openwakeword.__file__))").Trim()
& $vpy -m PyInstaller --noconfirm --clean --windowed --name Jarvis `
    --icon assets\jarvis.ico --add-data "assets;assets" --add-data "$oww;openwakeword" `
    --collect-all onnxruntime --collect-all winrt --collect-all edge_tts --collect-all sounddevice `
    --hidden-import pystray._win32 --collect-submodules jarvis run_jarvis.py
$exe = Join-Path $Root "dist\Jarvis\Jarvis.exe"
if (-not (Test-Path $exe)) { Fail "La fabrication du .exe a echoue. Lance 2_lancer.bat pour voir l'erreur." }

# 5. Raccourcis Bureau + menu Demarrer
$sh = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath("Desktop"), (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"))) {
    $l = $sh.CreateShortcut((Join-Path $dir "Jarvis.lnk"))
    $l.TargetPath = $exe; $l.WorkingDirectory = Split-Path $exe; $l.IconLocation = "$exe,0"; $l.Save()
}
Say "Raccourcis crees sur le Bureau et dans le menu Demarrer." "Green"

if (Ask "J.A.R.V.I.S. est installe.`n`nLe lancer maintenant ?") { Start-Process $exe }
