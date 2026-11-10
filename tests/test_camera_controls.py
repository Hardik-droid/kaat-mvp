"""Selector units, separate from real camera recording in check_camera_recording."""
import os
from pathlib import Path
import subprocess

import pytest


@pytest.mark.skipif(os.name != 'nt', reason='Windows UI Automation')
def test_camera_state_ignores_stale_hidden_and_duplicate_mode_controls(tmp_path):
    adapter = Path(__file__).resolve().parents[1] / 'scripts/camera_control.ps1'
    script = tmp_path / 'selector_test.ps1'
    script.write_text(r'''
param([string]$Adapter)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Adapter, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Adapter syntax error' }
# Load only function definitions; never execute the adapter's device actions.
$definitions = $ast.FindAll({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst]}, $false)
foreach ($definition in $definitions) { . ([ScriptBlock]::Create($definition.Extent.Text)) }
function CameraRoot {
    $root = New-Object PSObject
    $root | Add-Member ScriptMethod FindAll { param($scope, $condition) return $script:rows }
    return $root
}
function Row($name, $enabled=$true, $hidden=$false, $id='CaptureButton_1') {
    return [PSCustomObject]@{Current=[PSCustomObject]@{Name=$name; IsEnabled=$enabled; IsOffscreen=$hidden; AutomationId=$id}}
}
$script:rows = @((Row 'Switch to video mode' $false), (Row 'Take video'), (Row 'Stop taking video' $true $true))
if ((State) -ne 'ready') { throw 'Disabled or hidden control displaced live video button' }
$script:rows = @((Row 'Switch to video mode'), (Row 'Take video'))
if ((State) -ne 'ready') { throw 'Duplicate mode ID displaced the actual video button' }
$script:rows = @((Row 'Take video' $false), (Row 'Stop taking video'))
if ((State) -ne 'recording') { throw 'Recording state not detected' }
$script:rows = @((Row 'Resume video recording' $true $false 'VideoPauseToggleButton'))
if ((State) -ne 'paused') { throw 'Paused state not detected' }
$script:rows = @((Row 'Take video' $false))
if ((State) -ne 'unavailable') { throw 'Disabled video button treated as ready' }
$script:rows = @((Row 'Take video'))
if (-not (IdleVerified (State))) { throw 'Ready video mode must be idle' }
$script:rows = @((Row 'Take photo' $true $false 'CaptureButton_0'), (Row 'Switch to video mode'))
if ((State) -ne 'unavailable' -or -not (IdleVerified (State))) { throw 'Live photo preview must be idle without changing the existing state name' }
$script:rows = @((Row 'Take photo' $false $false 'CaptureButton_0'))
if (IdleVerified (State)) { throw 'Disabled photo capture is not idle evidence' }
$script:rows = @((Row 'Take photo' $true $true 'CaptureButton_0'))
if (IdleVerified (State)) { throw 'Hidden photo capture is not idle evidence' }
$script:rows = @((Row 'Switch to video mode'))
if (IdleVerified (State)) { throw 'Mode toggle alone does not verify idle' }
$script:rows = @((Row 'Take photo'), (Row 'Stop taking video'))
if (IdleVerified (State)) { throw 'Recording must not be treated as idle' }
$script:rows = @((Row 'Take photo'), (Row 'Resume video recording'))
if (IdleVerified (State)) { throw 'Paused recording must not be treated as idle' }
$script:rows = @((Row 'Take photo'), (Row 'Pause video recording'))
if (IdleVerified 'unavailable') { throw 'Conflicting recording evidence must not be treated as idle' }
Write-Output '13 selector checks passed; no camera action executed'
''', encoding='utf-8')
    powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                             '-File', str(script), str(adapter)], capture_output=True, text=True, timeout=12)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '13 selector checks passed' in result.stdout
