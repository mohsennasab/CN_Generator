param(
    [Parameter(Mandatory = $true)]
    [string]$VenvDir,

    [Parameter(Mandatory = $true)]
    [string]$RequirementsPath,

    [Parameter(Mandatory = $true)]
    [string]$HashPath
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName Microsoft.VisualBasic

function New-SetupForm {
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "CN Generator Setup"
    $form.Size = New-Object System.Drawing.Size(680, 470)
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    $form.MinimizeBox = $true
    $form.BackColor = [System.Drawing.Color]::FromArgb(247, 249, 247)

    $title = New-Object System.Windows.Forms.Label
    $title.Text = "Preparing CN Generator"
    $title.Font = New-Object System.Drawing.Font("Segoe UI", 15, [System.Drawing.FontStyle]::Bold)
    $title.ForeColor = [System.Drawing.Color]::FromArgb(31, 48, 47)
    $title.Location = New-Object System.Drawing.Point(24, 22)
    $title.Size = New-Object System.Drawing.Size(610, 32)
    $form.Controls.Add($title)

    $intro = New-Object System.Windows.Forms.Label
    $intro.Text = "First launch can take several minutes while the local Python environment is created and geospatial libraries are installed. Future launches should be much faster."
    $intro.Font = New-Object System.Drawing.Font("Segoe UI", 9)
    $intro.ForeColor = [System.Drawing.Color]::FromArgb(70, 83, 80)
    $intro.Location = New-Object System.Drawing.Point(26, 62)
    $intro.Size = New-Object System.Drawing.Size(610, 42)
    $form.Controls.Add($intro)

    $status = New-Object System.Windows.Forms.Label
    $status.Text = "Starting setup..."
    $status.Font = New-Object System.Drawing.Font("Segoe UI", 10, [System.Drawing.FontStyle]::Bold)
    $status.ForeColor = [System.Drawing.Color]::FromArgb(47, 118, 109)
    $status.Location = New-Object System.Drawing.Point(26, 116)
    $status.Size = New-Object System.Drawing.Size(610, 24)
    $form.Controls.Add($status)

    $progress = New-Object System.Windows.Forms.ProgressBar
    $progress.Location = New-Object System.Drawing.Point(28, 148)
    $progress.Size = New-Object System.Drawing.Size(605, 20)
    $progress.Style = "Marquee"
    $progress.MarqueeAnimationSpeed = 28
    $form.Controls.Add($progress)

    $log = New-Object System.Windows.Forms.TextBox
    $log.Location = New-Object System.Drawing.Point(28, 186)
    $log.Size = New-Object System.Drawing.Size(605, 190)
    $log.Multiline = $true
    $log.ReadOnly = $true
    $log.ScrollBars = "Vertical"
    $log.BackColor = [System.Drawing.Color]::White
    $log.Font = New-Object System.Drawing.Font("Consolas", 8.5)
    $form.Controls.Add($log)

    $close = New-Object System.Windows.Forms.Button
    $close.Text = "Close"
    $close.Location = New-Object System.Drawing.Point(548, 390)
    $close.Size = New-Object System.Drawing.Size(85, 28)
    $close.Enabled = $false
    $close.Add_Click({ $form.Close() })
    $form.Controls.Add($close)

    return @{
        Form = $form
        Status = $status
        Progress = $progress
        Log = $log
        Close = $close
    }
}

function Update-SetupStatus {
    param([string]$Message)
    $script:Ui.Status.Text = $Message
    $script:Ui.Log.AppendText("[$((Get-Date).ToString('HH:mm:ss'))] $Message`r`n")
    [System.Windows.Forms.Application]::DoEvents()
}

function Add-SetupLog {
    param([string]$Message)
    if ([string]::IsNullOrWhiteSpace($Message)) {
        return
    }
    $script:Ui.Log.AppendText("$Message`r`n")
    $script:Ui.Log.SelectionStart = $script:Ui.Log.TextLength
    $script:Ui.Log.ScrollToCaret()
    [System.Windows.Forms.Application]::DoEvents()
}

function Quote-Argument {
    param([string]$Value)
    if ($Value -match '[\s"]') {
        return '"' + ($Value -replace '"', '\"') + '"'
    }
    return $Value
}

function Invoke-LoggedCommand {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$StepName
    )

    Update-SetupStatus $StepName

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $psi.Arguments = ($Arguments | ForEach-Object { Quote-Argument $_ }) -join " "
    $psi.WorkingDirectory = Split-Path -Parent $RequirementsPath
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    [void]$process.Start()

    while (-not $process.HasExited) {
        while ($process.StandardOutput.Peek() -ge 0) {
            Add-SetupLog $process.StandardOutput.ReadLine()
        }
        while ($process.StandardError.Peek() -ge 0) {
            Add-SetupLog $process.StandardError.ReadLine()
        }
        Start-Sleep -Milliseconds 120
        [System.Windows.Forms.Application]::DoEvents()
    }

    while ($process.StandardOutput.Peek() -ge 0) {
        Add-SetupLog $process.StandardOutput.ReadLine()
    }
    while ($process.StandardError.Peek() -ge 0) {
        Add-SetupLog $process.StandardError.ReadLine()
    }

    return $process.ExitCode
}

function Test-PythonCommand {
    param(
        [string]$Exe,
        [string[]]$BaseArgs
    )

    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $Exe
        $psi.Arguments = (($BaseArgs + @("-c", "import sys")) | ForEach-Object { Quote-Argument $_ }) -join " "
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.CreateNoWindow = $true

        $process = [System.Diagnostics.Process]::Start($psi)
        $process.WaitForExit()
        return $process.ExitCode -eq 0
    }
    catch {
        return $false
    }
}

function Find-Python {
    $candidates = @(
        @{ Exe = "py"; Args = @("-3.11") },
        @{ Exe = "py"; Args = @("-3") },
        @{ Exe = "python"; Args = @() }
    )

    foreach ($candidate in $candidates) {
        if (Test-PythonCommand -Exe $candidate.Exe -BaseArgs $candidate.Args) {
            return $candidate
        }
    }

    return $null
}

function Get-ProxyFromUser {
    $message = "Package installation could not complete. If your network requires a proxy, enter it below and setup will retry. Leave blank to cancel."
    return [Microsoft.VisualBasic.Interaction]::InputBox($message, "Proxy Required", "")
}

$script:Ui = New-SetupForm
$script:Ui.Form.Show()
[System.Windows.Forms.Application]::DoEvents()

try {
    $requirements = (Resolve-Path -LiteralPath $RequirementsPath).Path
    $venv = $VenvDir
    $venvPython = Join-Path $venv "Scripts\python.exe"
    $requirementsHash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash

    $python = Find-Python
    if ($null -eq $python) {
        throw "Python was not found. Install Python 3.11 or newer and enable 'Add python.exe to PATH'."
    }

    if (-not (Test-Path -LiteralPath $venvPython)) {
        $code = Invoke-LoggedCommand -FilePath $python.Exe -Arguments ($python.Args + @("-m", "venv", $venv)) -StepName "Creating the local Python environment..."
        if ($code -ne 0) {
            throw "Could not create the local Python environment."
        }
    }

    $install = {
        $pipCode = Invoke-LoggedCommand -FilePath $venvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip") -StepName "Updating the package installer..."
        if ($pipCode -ne 0) {
            return $pipCode
        }

        return Invoke-LoggedCommand -FilePath $venvPython -Arguments @("-m", "pip", "install", "-r", $requirements) -StepName "Installing CN Generator dependencies..."
    }

    $installCode = & $install
    if ($installCode -ne 0 -and -not $env:CN_PROXY) {
        $proxy = Get-ProxyFromUser
        if (-not [string]::IsNullOrWhiteSpace($proxy)) {
            $env:CN_PROXY = $proxy
            $env:HTTP_PROXY = $proxy
            $env:HTTPS_PROXY = $proxy
            $env:http_proxy = $proxy
            $env:https_proxy = $proxy
            $installCode = & $install
        }
    }

    if ($installCode -ne 0) {
        throw "Dependency installation failed. Check proxy settings, network access, or the log above."
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $HashPath) | Out-Null
    Set-Content -LiteralPath $HashPath -Value $requirementsHash -Encoding ASCII

    $script:Ui.Progress.Style = "Continuous"
    $script:Ui.Progress.Value = 100
    Update-SetupStatus "Setup complete. Launching CN Generator..."
    Start-Sleep -Milliseconds 900
    $script:Ui.Form.Close()
    exit 0
}
catch {
    $script:Ui.Progress.Style = "Continuous"
    $script:Ui.Progress.Value = 0
    Update-SetupStatus "Setup could not complete."
    Add-SetupLog $_.Exception.Message
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, "CN Generator Setup", "OK", "Error") | Out-Null
    $script:Ui.Close.Enabled = $true
    while ($script:Ui.Form.Visible) {
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 100
    }
    exit 1
}
