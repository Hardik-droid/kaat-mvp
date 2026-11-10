param([ValidateSet('status','start_recording','stop_recording','pause_recording','resume_recording')][string]$Action = 'status')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
function CameraRoot {
    $cameraProcess = Get-Process WindowsCamera -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $cameraProcess) { throw 'Open Windows Camera first.' }
    $cameraHandle = $cameraProcess.MainWindowHandle
    if ($cameraHandle -eq [IntPtr]::Zero) {
        $frameProcess = Get-Process ApplicationFrameHost -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -eq 'Camera' } | Select-Object -First 1
        if ($frameProcess) { $cameraHandle = $frameProcess.MainWindowHandle }
    }
    if ($cameraHandle -eq [IntPtr]::Zero) { throw 'Windows Camera has no accessible window. Open it and select video mode.' }
    return [System.Windows.Automation.AutomationElement]::FromHandle($cameraHandle)
}
function Buttons {
    $root = CameraRoot
    $condition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Button)
    # Camera retains disabled controls from the previous mode with duplicate IDs.
    # State and actions must use the currently visible, enabled controls only.
    return $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition) |
        Where-Object { $_.Current.IsEnabled -and -not $_.Current.IsOffscreen }
}
function State {
    $buttons = @(Buttons)
    $capture = @($buttons | Where-Object { $_.Current.AutomationId -eq 'CaptureButton_1' -and $_.Current.Name -in @('Take video','Stop taking video') })
    $resume = $buttons | Where-Object { $_.Current.Name -eq 'Resume video recording' } | Select-Object -First 1
    if ($resume) { return 'paused' }
    if ($capture | Where-Object { $_.Current.Name -eq 'Stop taking video' }) { return 'recording' }
    if ($capture | Where-Object { $_.Current.Name -eq 'Take video' }) { return 'ready' }
    return 'unavailable'
}
function IdleVerified([string]$state) {
    if ($state -eq 'ready') { return $true }
    if ($state -ne 'unavailable') { return $false }
    $buttons = @(Buttons)
    if ($buttons | Where-Object { $_.Current.Name -in @('Stop taking video','Pause video recording','Resume video recording') }) { return $false }
    # Photo mode has no video-ready state. Its live capture button is explicit
    # idle evidence; hidden/disabled photo controls and mode toggles are not.
    return [bool]($buttons | Where-Object { $_.Current.Name -eq 'Take photo' })
}
function InvokeButton($button) {
    if (-not $button -or -not $button.Current.IsEnabled) { throw 'The requested Windows Camera control is unavailable.' }
    $pattern = $button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
    $pattern.Invoke()
}
function WaitPattern($name, [int]$stableMilliseconds = 0) {
    $deadline = [DateTime]::UtcNow.AddSeconds(4)
    $identity = $null
    $stableSince = [DateTime]::UtcNow
    do {
        $button = @(Buttons) | Where-Object { $_.Current.Name -eq $name } | Select-Object -First 1
        if ($button) {
            $currentIdentity = ($button.GetRuntimeId() -join ',') + ':' + $button.Current.BoundingRectangle.ToString()
            if ($identity -ne $currentIdentity) { $identity = $currentIdentity; $stableSince = [DateTime]::UtcNow }
            if (([DateTime]::UtcNow - $stableSince).TotalMilliseconds -ge $stableMilliseconds) {
                try { return $button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern) } catch {}
            }
        } else {
            $identity = $null
        }
        Start-Sleep -Milliseconds 100
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Windows Camera did not make its '$name' control ready."
}
$before = State
if ($Action -eq 'start_recording' -and $before -eq 'unavailable') {
    $switch = @(Buttons) | Where-Object { $_.Current.AutomationId -eq 'CaptureButton_1' -and $_.Current.Name -eq 'Switch to video mode' } | Select-Object -First 1
    if ($switch) {
        InvokeButton $switch
        $switchDeadline = [DateTime]::UtcNow.AddSeconds(3)
        do { Start-Sleep -Milliseconds 100; $before = State } while ($before -ne 'ready' -and [DateTime]::UtcNow -lt $switchDeadline)
    }
}
if ($Action -ne 'status') {
    $required = @{start_recording='ready'; stop_recording='recording'; pause_recording='recording'; resume_recording='paused'}[$Action]
    if ($before -ne $required -and -not ($Action -eq 'stop_recording' -and $before -eq 'paused')) {
        throw "Cannot $Action while Camera is $before. Open Camera in video mode first."
    }
    $name = @{start_recording='Take video'; stop_recording='Stop taking video'; pause_recording='Pause video recording'; resume_recording='Resume video recording'}[$Action]
    # Camera can expose the new button before its mode/preview transition ends.
    $settle = if ($Action -eq 'start_recording') { 750 } else { 0 }
    $pattern = WaitPattern $name $settle
    # Invoke once. Retrying a toggle after dispatch could stop a new recording.
    $pattern.Invoke()
    $expected = @{start_recording='recording'; stop_recording='ready'; pause_recording='paused'; resume_recording='recording'}[$Action]
    $deadline = [DateTime]::UtcNow.AddSeconds(5)
    do {
        Start-Sleep -Milliseconds 100
        $after = State
        if ($after -eq $expected) { break }
    } while ([DateTime]::UtcNow -lt $deadline)
    if ($after -ne $expected) { throw "Windows Camera did not confirm $Action; current state: $after. Check Camera's visible error or permission prompt." }
} else { $after = $before }
$cameraRoll = $null
try { $cameraRoll = (New-Object -ComObject Shell.Application).NameSpace('shell:CameraRoll').Self.Path } catch {}
if (-not $cameraRoll) {
    $defaultRoll = Join-Path ([Environment]::GetFolderPath('MyPictures')) 'Camera Roll'
    if (Test-Path -LiteralPath $defaultRoll) { $cameraRoll = $defaultRoll }
}
@{action=$Action; state=$after; idle_verified=(IdleVerified $after); previous_state=$before; camera_roll=$cameraRoll; backend='Windows Camera UI Automation'} | ConvertTo-Json -Compress
