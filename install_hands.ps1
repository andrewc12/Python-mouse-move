# Installs the Voice Mouse hands so they start at every logon and keep running (like a server).
#   -Signed   (install_hands_signed.bat)  UI access: make a certificate, trust it, sign the hands, copy them to
#             Program Files, start them from a Startup shortcut. Gives the grid / status box the top window layer
#             and lets the hands reach administrator windows, with no Windows prompt.
#   (default) (install_hands_task.bat)    an ordinary exe, started elevated by a scheduled task (no UI access).
# Run it as administrator (the .bat files check that). Nothing here touches the speech program or its models.
param([switch]$Signed)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$taskName = 'VoiceMouseHands'
$user = "$env:USERDOMAIN\$env:USERNAME"

function Stop-Hands {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Get-Process -Name voice_mouse_hands -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Milliseconds 500
}

if ($Signed) {
    $src = Join-Path $here 'dist\hands'
    $dst = Join-Path $env:ProgramFiles 'VoiceMouse\hands'
    $exe = Join-Path $dst 'voice_mouse_hands.exe'
    if (-not (Test-Path (Join-Path $src 'voice_mouse_hands.exe'))) {
        throw "dist\hands\voice_mouse_hands.exe not found. Run build.bat first (part 1 builds it)."
    }
    Stop-Hands

    # 1. a code-signing certificate that only this PC trusts
    $subject = 'CN=Voice Mouse (local certificate)'
    $cert = Get-ChildItem Cert:\LocalMachine\My | Where-Object {
        $_.Subject -eq $subject -and $_.HasPrivateKey -and $_.NotAfter -gt (Get-Date).AddDays(30) } | Select-Object -First 1
    if (-not $cert) {
        Write-Host 'Creating a local code-signing certificate ...'
        $cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject $subject -KeyUsage DigitalSignature `
            -CertStoreLocation Cert:\LocalMachine\My -NotAfter (Get-Date).AddYears(10)
    }
    # 2. trust it (public part only), as a root and as a publisher
    $pub = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2(, $cert.Export('Cer'))
    foreach ($name in 'Root', 'TrustedPublisher') {
        $store = New-Object System.Security.Cryptography.X509Certificates.X509Store($name, 'LocalMachine')
        $store.Open('ReadWrite'); $store.Add($pub); $store.Close()
    }
    # 3. copy to a protected folder (Windows only grants UI access to programs run from there), then sign
    Write-Host "Copying the hands to $dst ..."
    & robocopy $src $dst /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE)" }
    $sig = Set-AuthenticodeSignature -FilePath $exe -Certificate $cert -HashAlgorithm SHA256
    if ($sig.Status -ne 'Valid') { throw "Signing did not give a valid signature: $($sig.Status) $($sig.StatusMessage)" }
    Write-Host 'Signed.'

    # 4. start at logon from a Startup shortcut. (Task Scheduler cannot start UI-access programs; Explorer can.)
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    $lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'Voice Mouse hands.lnk'
    $sh = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
    $sh.TargetPath = $exe; $sh.WorkingDirectory = $dst; $sh.Save()
    Write-Host "Startup shortcut: $lnk"
    # start it now the way the logon does: through Explorer, as your normal user (not as this elevated window)
    Start-Process explorer.exe -ArgumentList "`"$exe`""
    Write-Host 'Started. Check %LOCALAPPDATA%\voice_mouse\hands.log: it says "UI access: yes" when it worked.'
}
else {
    $exe = @('dist\hands\voice_mouse_hands.exe', 'dist\voice_mouse_hands.exe', 'voice_mouse_hands.exe') |
        ForEach-Object { Join-Path $here $_ } | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($exe) { $action = New-ScheduledTaskAction -Execute $exe -WorkingDirectory (Split-Path $exe) }
    else {
        $py = (Get-Command pythonw.exe, pyw.exe -ErrorAction SilentlyContinue | Select-Object -First 1).Source
        if (-not $py) { throw 'No hands exe found and no pythonw. Run build.bat or install Python.' }
        $action = New-ScheduledTaskAction -Execute $py -Argument "`"$(Join-Path $here 'voice_mouse_hands.py')`"" -WorkingDirectory $here
    }
    Stop-Hands
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
    # no time limit (the default kills a task after 3 days) and restart it if it ever stops
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 `
        -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    Start-ScheduledTask -TaskName $taskName
    Write-Host "Installed task '$taskName' for $user and started it. It runs elevated whenever you are logged in."
}
Write-Host 'Done. Start the program with run_voice_mouse.bat'
