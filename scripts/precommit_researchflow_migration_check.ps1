param(
    [switch]$Full,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
$Failed = $false

function Invoke-Check {
    param(
        [string]$Name,
        [scriptblock]$Action
    )

    Write-Output "### $Name"
    & $Action
    if ($LASTEXITCODE -ne 0) {
        Write-Output "RESULT=FAIL"
        $script:Failed = $true
    } else {
        Write-Output "RESULT=PASS"
    }
}

$CriticalFiles = @(
    "backend/models/enums.py",
    "backend/models/agent_run.py",
    "backend/models/agent_run_step.py",
    "backend/models/human_review.py",
    "backend/models/evidence.py",
    "backend/models/tool_call.py",
    "backend/repositories/agent_run_repository.py",
    "backend/repositories/human_review_repository.py",
    "backend/repositories/report_repository.py",
    "backend/services/report_run_service.py",
    "backend/services/report_status_service.py",
    "backend/services/human_review_service.py",
    "backend/memory/redis_task_status.py",
    "backend/api/report_runs.py",
    "backend/api/schemas_report_runs.py",
    "backend/worker/tasks_report.py",
    "backend/checkpoint/postgres_checkpointer.py",
    "backend/workflow/report_run_graph.py",
    "backend/workflow/human_review_node.py",
    "backend/workflow/adapters.py",
    "scripts/setup_langgraph_checkpointer.py"
)

Write-Output "### critical files"
foreach ($Path in $CriticalFiles) {
    if (-not (Test-Path -LiteralPath $Path)) {
        Write-Output "MISSING $Path"
        $Failed = $true
    } else {
        Write-Output "OK $Path"
    }
}

$KeyTests = @(
    "tests/unit/test_report_run_status_redis.py",
    "tests/unit/test_report_run_celery.py",
    "tests/unit/test_postgres_checkpointer.py",
    "tests/integration/test_report_run_hitl_e2e.py"
) | Where-Object { Test-Path -LiteralPath $_ }

Write-Output "### ignored key tests"
foreach ($TestPath in $KeyTests) {
    git check-ignore --quiet -- $TestPath
    if ($LASTEXITCODE -eq 0) {
        Write-Output "IGNORED $TestPath"
        $Failed = $true
    } else {
        Write-Output "TRACKABLE $TestPath"
    }
}

Invoke-Check "compileall" { & $Python -m compileall -q backend }

if ($KeyTests.Count -gt 0) {
    Invoke-Check "targeted pytest" { & $Python -m pytest -q @KeyTests }
} else {
    Write-Output "### targeted pytest"
    Write-Output "RESULT=SKIP no key tests found"
    $Failed = $true
}

if ($Full) {
    Invoke-Check "full pytest" { & $Python -m pytest -q }
} else {
    Write-Output "### full pytest"
    Write-Output "RESULT=SKIP use -Full to run"
}

$Ruff = Get-Command ruff -ErrorAction SilentlyContinue
Write-Output "### Ruff changed/new Python files"
if ($null -eq $Ruff) {
    Write-Output "RESULT=FAIL ruff is not installed"
    $Failed = $true
} else {
    # Keep this gate scoped to the 03-10B migration boundary. The worktree
    # also contains unrelated historical changes that must not be reformatted
    # or fixed by this migration check.
    $RuffPaths = @($CriticalFiles + @(
        "backend/database/session.py",
        "backend/memory/redis_client.py",
        "backend/repositories/agent_run_step_repository.py",
        "backend/worker/runtime.py",
        "backend/worker/tasks_parse.py",
        "backend/worker/tasks_cleanup.py",
        "scripts/recover_stale_report_runs.py"
    )) | Where-Object {
        $_ -match '\.py$' -and (Test-Path -LiteralPath $_)
    }
    foreach ($TestPath in $KeyTests) {
        if ($TestPath -notin $RuffPaths) { $RuffPaths += $TestPath }
    }
    $RuffPaths = @($RuffPaths | Sort-Object -Unique)
    if ($RuffPaths.Count -eq 0) {
        Write-Output "RESULT=SKIP no Python changes found"
    } else {
        & ruff check @RuffPaths
        if ($LASTEXITCODE -ne 0) {
            Write-Output "RESULT=FAIL"
            $Failed = $true
        } else {
            Write-Output "RESULT=PASS"
        }
    }
}

Invoke-Check "git diff --check" { git diff --check }

if ($Failed) {
    Write-Output "COMMIT_READY=NO"
    exit 1
}

Write-Output "COMMIT_READY=YES"
exit 0
