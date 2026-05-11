# End-to-end smoke test for the license server.
#
# Usage:
#   .\test_endpoints.ps1                              # hits local http://127.0.0.1:8000
#   .\test_endpoints.ps1 -BaseUrl https://license.accgenie.in -AdminToken <tok>
#
# Run the server first in another shell:
#   uvicorn license_server.main:app --reload --port 8000   (from repo root)
#
# Reads ADMIN_TOKEN from -AdminToken, then $env:ADMIN_TOKEN, then license_server\.env.

param(
    [string]$BaseUrl    = "http://127.0.0.1:8000",
    [string]$AdminToken = ""
)

$ErrorActionPreference = "Stop"

# -- Resolve admin token ----------------------------------------------------
if (-not $AdminToken) { $AdminToken = $env:ADMIN_TOKEN }
if (-not $AdminToken) {
    $envFile = Join-Path $PSScriptRoot ".env"
    if (Test-Path $envFile) {
        $line = Select-String -Path $envFile -Pattern '^\s*ADMIN_TOKEN\s*=\s*(.+)$' | Select-Object -First 1
        if ($line) { $AdminToken = $line.Matches[0].Groups[1].Value.Trim('"').Trim("'") }
    }
}
if (-not $AdminToken) { throw "ADMIN_TOKEN not found. Pass -AdminToken or set env / .env." }

$adminHeaders = @{ Authorization = "Bearer $AdminToken" }

function Step($name) { Write-Host "`n=== $name ===" -ForegroundColor Cyan }
function Pass($msg)  { Write-Host "  PASS  $msg" -ForegroundColor Green }
function Fail($msg)  { Write-Host "  FAIL  $msg" -ForegroundColor Red; $script:failures++ }

$script:failures = 0

# 1. Health ------------------------------------------------------------------
Step "Health check"
$h = Invoke-RestMethod -Uri "$BaseUrl/api/v1/health" -TimeoutSec 10
if ($h.status -eq "ok") { Pass "version $($h.version)" } else { Fail "unexpected: $($h | ConvertTo-Json -Compress)" }

# 2. Mint a fresh PRO key, expires +30d -------------------------------------
Step "Mint PRO key"
$expiry = (Get-Date).AddDays(30).ToString("yyyy-MM-dd")
$mintBody = @{
    plan           = "PRO"
    customer_email = "smoketest@accgenie.in"
    company_name   = "Smoke Test Co"
    expires_at     = $expiry
    notes          = "automated smoke test"
} | ConvertTo-Json
$minted = Invoke-RestMethod -Uri "$BaseUrl/admin/keys" -Method POST `
    -Headers $adminHeaders -ContentType "application/json" -Body $mintBody
$key = $minted.license_key
Pass "minted $key (expires $($minted.expires_at))"

# 3. Validate — fresh machine, should succeed and bind ----------------------
Step "Validate (machine #1)"
$v1 = Invoke-RestMethod -Uri "$BaseUrl/api/v1/license/validate" -Method POST `
    -ContentType "application/json" -Body (@{
        license_key = $key; machine_id = "MACHINE-AAA"; app_version = "1.0.0"
    } | ConvertTo-Json)
if ($v1.valid -and $v1.plan -eq "PRO") { Pass "valid=true plan=PRO" } else { Fail ($v1 | ConvertTo-Json -Compress) }

# 4. Re-validate same machine ------------------------------------------------
Step "Re-validate same machine (idempotent)"
$v2 = Invoke-RestMethod -Uri "$BaseUrl/api/v1/license/validate" -Method POST `
    -ContentType "application/json" -Body (@{
        license_key = $key; machine_id = "MACHINE-AAA"; app_version = "1.0.0"
    } | ConvertTo-Json)
if ($v2.valid) { Pass "still valid, no new binding" } else { Fail "unexpectedly invalid" }

# 5. Bind two more machines (up to MAX=3) -----------------------------------
Step "Bind machines #2 and #3"
foreach ($mid in "MACHINE-BBB","MACHINE-CCC") {
    $r = Invoke-RestMethod -Uri "$BaseUrl/api/v1/license/validate" -Method POST `
        -ContentType "application/json" -Body (@{
            license_key = $key; machine_id = $mid; app_version = "1.0.0"
        } | ConvertTo-Json)
    if ($r.valid) { Pass "$mid bound" } else { Fail "$mid : $($r.error)" }
}

# 6. 4th machine should be rejected -----------------------------------------
Step "Machine #4 over limit (expect failure)"
$r4 = Invoke-RestMethod -Uri "$BaseUrl/api/v1/license/validate" -Method POST `
    -ContentType "application/json" -Body (@{
        license_key = $key; machine_id = "MACHINE-DDD"; app_version = "1.0.0"
    } | ConvertTo-Json)
if (-not $r4.valid -and $r4.error -match "activated on") { Pass "rejected: $($r4.error)" } else { Fail "should have rejected" }

# 7. Unknown key -------------------------------------------------------------
Step "Unknown key (expect failure)"
$rU = Invoke-RestMethod -Uri "$BaseUrl/api/v1/license/validate" -Method POST `
    -ContentType "application/json" -Body (@{
        license_key = "ACCG-ZZZZ-ZZZZ-ZZZZ"; machine_id = "MACHINE-XXX"
    } | ConvertTo-Json)
if (-not $rU.valid -and $rU.error -match "not found") { Pass "rejected: $($rU.error)" } else { Fail "should be 'not found'" }

# 8. Bad format --------------------------------------------------------------
Step "Malformed key (expect failure)"
$rM = Invoke-RestMethod -Uri "$BaseUrl/api/v1/license/validate" -Method POST `
    -ContentType "application/json" -Body (@{
        license_key = "garbage"; machine_id = "MACHINE-XXX"
    } | ConvertTo-Json)
if (-not $rM.valid -and $rM.error -match "format") { Pass "rejected: $($rM.error)" } else { Fail "should reject bad format" }

# 9. Heartbeat ---------------------------------------------------------------
Step "Install heartbeat"
$hb = Invoke-RestMethod -Uri "$BaseUrl/api/v1/install/heartbeat" -Method POST `
    -ContentType "application/json" -Body (@{
        install_id  = "smoke-install-001"
        machine_id  = "MACHINE-AAA"
        app_version = "1.0.0"
        plan        = "PRO"
        license_key = $key
        os_name     = "windows"
    } | ConvertTo-Json)
if ($hb.ok) { Pass "heartbeat ok" } else { Fail "heartbeat rejected" }

# 10. Admin: show, list, stats ----------------------------------------------
Step "Admin: show key detail"
$detail = Invoke-RestMethod -Uri "$BaseUrl/admin/keys/$key" -Headers $adminHeaders
if ($detail.machine_count -eq 3) { Pass "3 machines bound" } else { Fail "machine_count=$($detail.machine_count)" }

Step "Admin: install stats"
$stats = Invoke-RestMethod -Uri "$BaseUrl/admin/installs/stats" -Headers $adminHeaders
Pass "total=$($stats.total_installs) new_7d=$($stats.new_last_7d) active_7d=$($stats.active_last_7d)"

# 11. Revoke -> validate should now fail ------------------------------------
Step "Revoke and re-validate"
$null = Invoke-RestMethod -Uri "$BaseUrl/admin/keys/$key/revoke" -Method POST -Headers $adminHeaders
$rR = Invoke-RestMethod -Uri "$BaseUrl/api/v1/license/validate" -Method POST `
    -ContentType "application/json" -Body (@{
        license_key = $key; machine_id = "MACHINE-AAA"
    } | ConvertTo-Json)
if (-not $rR.valid -and $rR.error -match "revoked") { Pass "rejected post-revoke" } else { Fail "should be revoked" }

# 12. Admin auth: missing token should 401 ----------------------------------
Step "Admin without token (expect 401/403)"
try {
    Invoke-RestMethod -Uri "$BaseUrl/admin/keys" -ErrorAction Stop | Out-Null
    Fail "should have rejected unauthenticated call"
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    if ($code -in 401,403) { Pass "got $code" } else { Fail "unexpected $code" }
}

# -- Summary ----------------------------------------------------------------
Write-Host ""
if ($script:failures -eq 0) {
    Write-Host "ALL CHECKS PASSED" -ForegroundColor Green
} else {
    Write-Host "$($script:failures) FAILURE(S)" -ForegroundColor Red
    exit 1
}
