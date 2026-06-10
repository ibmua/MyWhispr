param(
  [string]$Model = "parakeet-tdt-0.6b-v3",
  [string]$TorchIndexUrl = "https://download.pytorch.org/whl/cu128",
  [switch]$SkipModelDownload,
  [switch]$Start,
  [switch]$CreateStartMenuShortcut,
  [switch]$CreateStartupShortcut,
  [switch]$NoStart,
  [switch]$NoStartupShortcut,
  [switch]$SkipQwenBackend,
  [switch]$SkipWhisperServer,
  [string]$WhisperCppVersion = "v1.8.6",
  [switch]$AllowNoCuda,
  [switch]$ResetConfig
)

$ErrorActionPreference = "Stop"

if (-not $IsWindows -and $PSVersionTable.PSVersion.Major -ge 6) {
  throw "This installer is for Windows. Use scripts/install.sh on Linux."
}

$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$MainPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$GpuPython = Join-Path $ProjectDir ".venv-gpu-asr\Scripts\python.exe"
$QwenPython = Join-Path $ProjectDir ".venv-qwen-asr\Scripts\python.exe"
$ConfigPath = Join-Path $ProjectDir "config.json"
$ExampleConfigPath = Join-Path $ProjectDir "config.example.json"
Set-Location $ProjectDir

function Write-Step([string]$Message) {
  Write-Host ""
  Write-Host "==> $Message" -ForegroundColor Cyan
}

function Resolve-BasePython {
  $candidates = @()
  if (Test-Path $MainPython) {
    $candidates += @{ Exe = $MainPython; Args = @() }
  }
  $candidates += @(
    @{ Exe = "py"; Args = @("-3") },
    @{ Exe = "python"; Args = @() },
    @{ Exe = "python3"; Args = @() }
  )
  $localPrograms = Join-Path $env:LOCALAPPDATA "Programs\Python"
  if (Test-Path $localPrograms) {
    Get-ChildItem -Path $localPrograms -Filter python.exe -Recurse -ErrorAction SilentlyContinue |
      Sort-Object FullName -Descending |
      ForEach-Object { $candidates += @{ Exe = $_.FullName; Args = @() } }
  }
  foreach ($candidate in $candidates) {
    $exe = Get-Command $candidate.Exe -ErrorAction SilentlyContinue
    if (-not $exe -and -not (Test-Path $candidate.Exe)) { continue }
    try {
      $out = & $candidate.Exe @($candidate.Args + @("-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}'); print(sys.executable)")) 2>$null
      if ($LASTEXITCODE -ne 0) { continue }
      $version = $out | Select-Object -First 1
      if ($version -match "^3\.(1[0-9]|[2-9][0-9])$") {
        return $candidate
      }
    } catch {
      continue
    }
  }
  throw "Python 3 was not found. Install Python 3.10+ from python.org, then rerun this script."
}

function Invoke-BasePython([object]$Base, [string[]]$PyArgs) {
  & $Base.Exe @($Base.Args + $PyArgs)
  if ($LASTEXITCODE -ne 0) {
    throw "Python command failed: $($Base.Exe) $($PyArgs -join ' ')"
  }
}

function Invoke-Python([string]$PythonExe, [string[]]$PyArgs) {
  & $PythonExe @PyArgs
  if ($LASTEXITCODE -ne 0) {
    throw "Python command failed: $PythonExe $($PyArgs -join ' ')"
  }
}

function Stop-ExistingMyWhispr {
  $currentPid = $PID
  $procs = Get-CimInstance Win32_Process |
    Where-Object {
      $_.ProcessId -ne $currentPid -and
      $_.Name -like "python*.exe" -and
      $_.CommandLine -match "mywhispr"
    }
  foreach ($proc in ($procs | Sort-Object ParentProcessId -Descending)) {
    try {
      Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
    } catch {
      Write-Warning "Could not stop process $($proc.ProcessId): $($_.Exception.Message)"
    }
  }
}

function New-Shortcut([string]$Path, [string]$Target, [string]$WorkingDirectory) {
  $shell = New-Object -ComObject WScript.Shell
  $shortcut = $shell.CreateShortcut($Path)
  $shortcut.TargetPath = $Target
  $shortcut.WorkingDirectory = $WorkingDirectory
  $shortcut.IconLocation = Join-Path $ProjectDir "assets\mywhispr.ico"
  $shortcut.WindowStyle = 7
  $shortcut.Description = "MyWhispr dictation daemon"
  $shortcut.Save()
}

Write-Step "Resolving Python"
$BasePython = Resolve-BasePython

Write-Step "Creating daemon virtual environment"
if (-not (Test-Path $MainPython)) {
  Invoke-BasePython $BasePython @("-m", "venv", (Join-Path $ProjectDir ".venv"))
}
Invoke-Python $MainPython @("-m", "pip", "install", "--upgrade", "pip")
Invoke-Python $MainPython @("-m", "pip", "install", "aiohttp", "sounddevice", "numpy", "truststore")

Write-Step "Creating GPU ASR virtual environment"
if (-not (Test-Path $GpuPython)) {
  Invoke-BasePython $BasePython @("-m", "venv", (Join-Path $ProjectDir ".venv-gpu-asr"))
}
Invoke-Python $GpuPython @("-m", "pip", "install", "--upgrade", "pip")
Invoke-Python $GpuPython @("-m", "pip", "install", "torch", "--index-url", $TorchIndexUrl)
Invoke-Python $GpuPython @("-m", "pip", "install", "transformers", "accelerate", "soundfile", "librosa", "huggingface_hub", "truststore")

if (-not $SkipQwenBackend) {
  Write-Step "Creating isolated Qwen ASR virtual environment"
  if (-not (Test-Path $QwenPython)) {
    Invoke-BasePython $BasePython @("-m", "venv", (Join-Path $ProjectDir ".venv-qwen-asr"))
  }
  Invoke-Python $QwenPython @("-m", "pip", "install", "--upgrade", "pip")
  Invoke-Python $QwenPython @("-m", "pip", "install", "torch", "--index-url", $TorchIndexUrl)
  Invoke-Python $QwenPython @("-m", "pip", "install", "qwen-asr", "truststore")
}

$WhisperServerExe = ""
if (-not $SkipWhisperServer) {
  Write-Step "Installing whisper.cpp server (CUDA build, for local GGML models)"
  $WhisperDir = Join-Path $ProjectDir "tools\whisper.cpp-$WhisperCppVersion"
  $WhisperServerExe = Join-Path $WhisperDir "Release\whisper-server.exe"
  if (Test-Path $WhisperServerExe) {
    Write-Host "whisper-server already present: $WhisperServerExe"
  } else {
    $ZipName = "whisper-cublas-12.4.0-bin-x64.zip"
    $ZipPath = Join-Path $env:TEMP $ZipName
    $Url = "https://github.com/ggml-org/whisper.cpp/releases/download/$WhisperCppVersion/$ZipName"
    Write-Host "Downloading $Url (~460 MB)"
    $OldProgress = $ProgressPreference
    $ProgressPreference = "SilentlyContinue"
    try {
      Invoke-WebRequest -Uri $Url -OutFile $ZipPath
      New-Item -ItemType Directory -Force $WhisperDir | Out-Null
      Expand-Archive -Force $ZipPath $WhisperDir
      Remove-Item -Force $ZipPath -ErrorAction SilentlyContinue
    } catch {
      Write-Warning "whisper.cpp server download failed: $($_.Exception.Message)"
      Write-Warning "GGML whisper.cpp models will stay disabled; rerun later or pass -SkipWhisperServer to silence this step."
      $WhisperServerExe = ""
    } finally {
      $ProgressPreference = $OldProgress
    }
    if ($WhisperServerExe -and -not (Test-Path $WhisperServerExe)) {
      $Found = Get-ChildItem -Path $WhisperDir -Recurse -Filter whisper-server.exe -ErrorAction SilentlyContinue | Select-Object -First 1
      if ($Found) { $WhisperServerExe = $Found.FullName } else { $WhisperServerExe = "" }
    }
  }
  if ($WhisperServerExe) {
    Write-Host "whisper-server: $WhisperServerExe"
    Write-Host "NOTE: some antivirus products (e.g. Avast/AVG 'IDP.Generic') falsely flag the unsigned"
    Write-Host "whisper-server.exe and freeze or quarantine it. If GGML models never become ready,"
    Write-Host "add an exclusion for this project folder in your antivirus settings."
  }
}

Write-Step "Writing Windows config"
if ($ResetConfig -or -not (Test-Path $ConfigPath)) {
  Copy-Item -Force $ExampleConfigPath $ConfigPath
}

$ConfigScript = @'
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
example_path = Path(sys.argv[2])
model = sys.argv[3]
qwen_python = sys.argv[4]
whisper_server = sys.argv[5] if len(sys.argv) > 5 else ""

cfg = json.loads(config_path.read_text(encoding="utf-8-sig"))
example = json.loads(example_path.read_text(encoding="utf-8-sig"))

cfg.setdefault("models", {})
for key, value in (example.get("models") or {}).items():
    cfg["models"].setdefault(key, value)
if model not in cfg["models"]:
    raise SystemExit(f"model {model!r} is not present in config models")
if qwen_python:
    for key, value in cfg["models"].items():
        if isinstance(value, dict) and value.get("backend") == "qwen_asr":
            value["python"] = qwen_python

cfg["default_model"] = model
cfg["preload_default_model_on_startup"] = True
cfg["gpu_asr_python"] = "./.venv-gpu-asr/Scripts/python.exe"
cfg.setdefault("web", {})["host"] = "127.0.0.1"
cfg.setdefault("web", {})["port"] = int(cfg.get("web", {}).get("port") or 16666)
existing_binary = str(cfg.get("whisper_server_binary") or "")
if whisper_server and Path(whisper_server).is_file():
    try:
        rel = Path(whisper_server).resolve().relative_to(config_path.parent.resolve())
        cfg["whisper_server_binary"] = "./" + str(rel).replace("\\", "/")
    except ValueError:
        cfg["whisper_server_binary"] = whisper_server
elif not Path(existing_binary).is_file():
    cfg["whisper_server_binary"] = ""

api = cfg.setdefault("transcription_api", {})
api.setdefault("enabled", False)
api["model_name"] = str(api.get("model_name") or model)

triggers = cfg.setdefault("triggers", {})
grave = triggers.setdefault("grave", {})
grave.setdefault("binding", "grave")
grave.setdefault("default_mode", "en")
grave.setdefault("language", "en")
grave.setdefault("stop_on_release_codes", [41])
combo = grave.setdefault("combo", {})
combo.setdefault("enabled", True)
combo.setdefault("hold_grab_until_release", True)
combo.setdefault("deadline_seconds", 1.2)
combo.setdefault("keys", [{"code": 2, "binding": "1", "label": "1", "type": "language", "language": "en", "short_mode": "en", "switch_language": "en"}])

config_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
'@
$QwenPythonConfig = if ($SkipQwenBackend) { "" } else { "./.venv-qwen-asr/bin/python" }
$ConfigScript | & $MainPython - $ConfigPath $ExampleConfigPath $Model $QwenPythonConfig $WhisperServerExe
if ($LASTEXITCODE -ne 0) {
  throw "Failed to write config.json"
}

if (-not $SkipModelDownload) {
  Write-Step "Downloading default model weights"
  switch ($Model) {
    "parakeet-tdt-0.6b-v3" {
      Invoke-Python $GpuPython @("-m", "mywhispr.hf_download", "nvidia/parakeet-tdt-0.6b-v3", "--exclude", "*.nemo", "--exclude", "plots/*")
    }
    "qwen3-asr-0.6b" {
      if ($SkipQwenBackend) { throw "qwen3-asr-0.6b requires the Qwen backend; rerun without -SkipQwenBackend." }
      Invoke-Python $QwenPython @("-m", "mywhispr.hf_download", "Qwen/Qwen3-ASR-0.6B")
    }
    "qwen3-asr-1.7b" {
      if ($SkipQwenBackend) { throw "qwen3-asr-1.7b requires the Qwen backend; rerun without -SkipQwenBackend." }
      Invoke-Python $QwenPython @("-m", "mywhispr.hf_download", "Qwen/Qwen3-ASR-1.7B")
    }
    default {
      Write-Warning "No installer download recipe for model '$Model'. Use the web UI download button or scripts/download-gpu-asr-model.sh equivalent."
    }
  }
}

Write-Step "Checking CUDA availability"
$CudaCheck = @'
import sys
try:
    import torch
except Exception as e:
    print(f"torch import failed: {e}")
    sys.exit(2)
print(f"torch={torch.__version__}")
print(f"cuda_available={torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"gpu={torch.cuda.get_device_name(0)}")
else:
    sys.exit(3)
'@
$CudaCheck | & $GpuPython -
if ($LASTEXITCODE -eq 3 -and $AllowNoCuda) {
  Write-Warning "CUDA is not available. Continuing only because -AllowNoCuda was passed; GPU ASR models will not run until CUDA works."
} elseif ($LASTEXITCODE -ne 0) {
  throw "GPU environment check failed"
}
if (-not $SkipQwenBackend) {
  $CudaCheck | & $QwenPython -
  if ($LASTEXITCODE -eq 3 -and $AllowNoCuda) {
    Write-Warning "CUDA is not available in the Qwen runtime. Continuing only because -AllowNoCuda was passed."
  } elseif ($LASTEXITCODE -ne 0) {
    throw "Qwen GPU environment check failed"
  }
}

if ($NoStart -and $Start) {
  Write-Warning "-NoStart was passed with -Start; MyWhispr will not be launched."
}

if ($NoStartupShortcut -and $CreateStartupShortcut) {
  Write-Warning "-NoStartupShortcut was passed with -CreateStartupShortcut; the startup shortcut will not be created."
}

if ($CreateStartMenuShortcut -or ($CreateStartupShortcut -and -not $NoStartupShortcut)) {
  Write-Step "Creating shortcuts"
  $Launcher = Join-Path $ProjectDir "bin\mywhisprd.cmd"
  $StartMenu = Join-Path ([Environment]::GetFolderPath("Programs")) "MyWhispr.lnk"
  $Startup = Join-Path ([Environment]::GetFolderPath("Startup")) "MyWhispr.lnk"
  if ($CreateStartMenuShortcut) {
    New-Shortcut $StartMenu $Launcher $ProjectDir
    Write-Host "Created Start Menu shortcut: $StartMenu"
  }
  if ($CreateStartupShortcut -and -not $NoStartupShortcut) {
    New-Shortcut $Startup $Launcher $ProjectDir
    Write-Host "Created Startup shortcut: $Startup"
  }
}

if ($Start -and -not $NoStart) {
  Write-Step "Starting MyWhispr"
  Stop-ExistingMyWhispr
  Start-Process -FilePath (Join-Path $ProjectDir "bin\mywhisprd.cmd") -WorkingDirectory $ProjectDir -WindowStyle Hidden | Out-Null
  Start-Sleep -Seconds 3
  try {
    $status = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:16666/api/models" -TimeoutSec 10
    if ($status.StatusCode -eq 200) {
      Write-Host "MyWhispr is running: http://127.0.0.1:16666/"
    }
  } catch {
    Write-Warning "MyWhispr was started, but the web UI did not answer yet: $($_.Exception.Message)"
  }
}

Write-Step "Done"
if (-not $Start -or $NoStart) {
  Write-Host "Start MyWhispr with: .\bin\mywhisprd.cmd"
}
Write-Host "After MyWhispr is running, open http://127.0.0.1:16666/"
Write-Host "Default model: $Model"
if ($WhisperServerExe) {
  Write-Host "whisper.cpp GGML models (Whisper Large Q5 etc.) can be downloaded with one click in the web UI."
} else {
  Write-Host "whisper.cpp local GGML models stay disabled until whisper_server_binary points to a real whisper-server.exe."
}
