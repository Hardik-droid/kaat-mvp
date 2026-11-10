param([ValidateSet('installed','browser','folder')][string]$Action,[string]$Target='')
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
if ($Action -eq 'installed') {
    @((Get-StartApps) | ForEach-Object { @{name=$_.Name;app_id=$_.AppID} }) | ConvertTo-Json -Depth 4 -Compress
    exit
}
if ($Action -eq 'folder') {
    $matches=@()
    foreach ($window in (New-Object -ComObject Shell.Application).Windows()) {
        try {
            if ([System.IO.Path]::GetFileName($window.FullName) -ne 'explorer.exe') {continue}
            $location=([Uri]$window.LocationURL).LocalPath
            if ($location.TrimEnd('\') -eq $Target.TrimEnd('\')) {$matches+=@{path=$location;hwnd=[long]$window.HWND}}
        } catch {}
    }
    ConvertTo-Json -InputObject @($matches) -Compress
    exit
}
Add-Type -AssemblyName UIAutomationClient
$matches=@()
$browserPids=@((Get-Process chrome,msedge,firefox -ErrorAction SilentlyContinue).Id)
$roots=[System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children,[System.Windows.Automation.Condition]::TrueCondition)
foreach ($root in $roots) {
    try {
        if ($root.Current.ProcessId -notin $browserPids) {continue}
        $condition=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::Edit)
        foreach ($edit in $root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition)) {
            if ($edit.Current.Name -notin @('Address and search bar','Search with Google or enter address','Search or enter address') -and $edit.Current.AutomationId -ne 'addressEditBox') {continue}
            $value=$edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value
            if ($value) {$matches+=@{url=$value;pid=$root.Current.ProcessId;hwnd=[long]$root.Current.NativeWindowHandle}}
        }
    } catch {}
}
ConvertTo-Json -InputObject @($matches) -Compress
