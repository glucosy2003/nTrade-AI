#Requires -Version 7.0
<#
.SYNOPSIS
    Reset the local PostgreSQL passwords for nTrade AI and update .env.

.DESCRIPTION
    Temporarily switches pg_hba.conf to trust authentication, resets the
    ntrade_ai_user and postgres passwords, restores pg_hba.conf, and updates
    the project's .env file. Must be run from an elevated PowerShell session.

.EXAMPLE
    pwsh -File scripts\reset_db_password.ps1
#>

$ErrorActionPreference = 'Stop'

$pgBin = 'D:\software-pg-files\bin'
$pgData = 'D:\postgre-data-pg-files'
$service = 'postgresql-x64-18'
$projectRoot = 'D:\PROJECTS\ntrade_ai'
$envFile = Join-Path $projectRoot '.env'
$logFile = Join-Path $projectRoot 'logs\db_reset.log'
$databaseName = 'ntrade_ai_dev'
$databaseUser = 'ntrade_ai_user'

function Write-Log {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Write-Host $line
    Add-Content -LiteralPath $logFile -Value $line -Encoding utf8
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error 'This script must be run from an elevated (Administrator) PowerShell session.'
    exit 1
}

$userPassword = [guid]::NewGuid().ToString('N')
$adminPassword = [guid]::NewGuid().ToString('N')

$hba = Join-Path $pgData 'pg_hba.conf'
$backup = "$hba.bak-" + (Get-Date -Format 'yyyyMMddHHmmss')
Copy-Item -LiteralPath $hba -Destination $backup
Write-Log "Backed up pg_hba.conf to $backup"

$restored = $false
try {
    $content = Get-Content -LiteralPath $hba -Raw
    $trusted = $content -replace 'scram-sha-256', 'trust'
    Set-Content -LiteralPath $hba -Value $trusted -Encoding ascii
    Write-Log 'Temporarily set pg_hba.conf authentication to trust'

    Restart-Service -Name $service -Force
    Start-Sleep -Seconds 4

    $env:PGPASSWORD = ''
    $sql = @"
ALTER USER $databaseUser WITH PASSWORD '$userPassword';
ALTER USER postgres WITH PASSWORD '$adminPassword';
"@
    & "$pgBin\psql.exe" -h 127.0.0.1 -U postgres -d postgres -v ON_ERROR_STOP=1 -c $sql
    if ($LASTEXITCODE -ne 0) { throw "Password reset failed (psql exit $LASTEXITCODE)" }
    Write-Log 'Passwords reset successfully'

    $dbExists = & "$pgBin\psql.exe" -h 127.0.0.1 -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$databaseName'"
    if ($LASTEXITCODE -ne 0) { throw "Database lookup failed (psql exit $LASTEXITCODE)" }
    if ([string]::IsNullOrWhiteSpace($dbExists)) {
        & "$pgBin\psql.exe" -h 127.0.0.1 -U postgres -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE $databaseName OWNER $databaseUser"
        if ($LASTEXITCODE -ne 0) { throw "Database creation failed (psql exit $LASTEXITCODE)" }
        Write-Log "Created database $databaseName"
    }
    else {
        & "$pgBin\psql.exe" -h 127.0.0.1 -U postgres -d postgres -v ON_ERROR_STOP=1 -c "GRANT ALL PRIVILEGES ON DATABASE $databaseName TO $databaseUser"
        Write-Log "Database $databaseName already exists; privileges granted"
    }
}
finally {
    Copy-Item -LiteralPath $backup -Destination $hba -Force
    Restart-Service -Name $service -Force
    Start-Sleep -Seconds 4
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    $restored = $true
    Write-Log 'Restored pg_hba.conf and restarted PostgreSQL'
}

if (-not $restored) {
    Write-Error 'Failed to restore pg_hba.conf. Restore it manually from the backup.'
    exit 1
}

$envContent = Get-Content -LiteralPath $envFile
$envContent = $envContent -replace '^DATABASE_PASSWORD=.*$', "DATABASE_PASSWORD=$userPassword"
$envContent = $envContent -replace '^DATABASE_ADMIN_PASSWORD=.*$', "DATABASE_ADMIN_PASSWORD=$adminPassword"
Set-Content -LiteralPath $envFile -Value $envContent -Encoding utf8
Write-Log 'Updated .env with the new passwords'

$env:PGPASSWORD = $userPassword
& "$pgBin\psql.exe" -h 127.0.0.1 -U $databaseUser -d $databaseName -tAc 'SELECT 1' | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Verification failed (psql exit $LASTEXITCODE)" }
Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue

Write-Log 'Verification succeeded. Database credentials are working.'
Write-Host ''
Write-Host 'Done. Re-run your synthetic runner now.' -ForegroundColor Green
