param(
    [int]$TargetVisible = 500,
    [int]$MaxBatches = 200,
    [int]$SelfPlayGames = 20,
    [int]$SelectorDepth = 10,
    [int]$MultiPv = 6,
    [int]$ConfirmDepth = 20,
    [int]$ConfirmMultiPv = 3,
    [int]$ConfirmFastDepth = 17,
    [int]$ConfirmClearGapCp = 300,
    [int]$ConfirmClearMarginCp = 300,
    [int]$ConfirmBorderlineDepth = 0,
    [int]$ConfirmBorderlineWinCp = 0,
    [int]$ConfirmBorderlineGapCp = 0,
    [int]$LineMaxPlies = 7,
    [int]$ExtensionBeamWidth = 2,
    [int]$SelfPlayDepth = 1,
    [int]$SelfPlayMaxPlies = 120,
    [int]$TemperatureCp = 250,
    [double]$BlunderChance = 0.20,
    [int]$ResignCp = 700,
    [int]$ResignMoves = 5,
    [int]$SeedBase = 2000,
    [int]$Workers = 1,
    [switch]$Profile,
    [int]$StartBatchOverride = 0,
    [switch]$SkipInitialCombine,
    [switch]$WorkerMode
)

$ErrorActionPreference = "Stop"

function Invoke-Python {
    param([string[]]$CommandArgs)
    Write-Host ""
    Write-Host "> python $($CommandArgs -join ' ')"
    & python @CommandArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE"
    }
}

function Get-NextSelfPlayBatch {
    if ($StartBatchOverride -gt 0) {
        return $StartBatchOverride
    }
    $max = 0
    Get-ChildItem -Path "data\puzzles" -Filter "selfplay_batch*_report.jsonl" -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.Name -match 'selfplay_batch(\d+)_report\.jsonl') {
            $max = [Math]::Max($max, [int]$Matches[1])
        }
    }
    return ($max + 1)
}

function Get-VisibleCount {
    $path = "data\puzzles\all_report.jsonl"
    if (-not (Test-Path $path)) { return 0 }
    $hidden = @{
        "standard-like" = $true
        "trivial-recapture" = $true
        "trivial-capture" = $true
        "check-evasion" = $true
    }
    $count = 0
    foreach ($line in Get-Content -Path $path) {
        if (-not $line.Trim()) { continue }
        $record = $line | ConvertFrom-Json
        $isHidden = $false
        foreach ($flag in @($record.flags)) {
            if ($hidden.ContainsKey([string]$flag)) {
                $isHidden = $true
                break
            }
        }
        if (-not $isHidden) { $count += 1 }
    }
    return $count
}

function Update-CombinedArtifacts {
    $reports = @()
    if (Test-Path "data\puzzles\all_report.jsonl") {
        $reports += "data\puzzles\all_report.jsonl"
    }
    if (Test-Path "data\puzzles\chesscom_all_report.jsonl") {
        $reports += "data\puzzles\chesscom_all_report.jsonl"
    }
    $reports += Get-ChildItem -Path "data\puzzles" -Filter "selfplay_batch*_report.jsonl" -ErrorAction SilentlyContinue | Sort-Object Name | ForEach-Object { $_.FullName }

    $tmp = "data\puzzles\all_report.next.jsonl"
    Invoke-Python (@("-m", "schess_puzzles.cli", "combine-reports") + $reports + @("--output", $tmp))
    Move-Item -Force -Path $tmp -Destination "data\puzzles\all_report.jsonl"
    Invoke-Python @("-m", "schess_puzzles.cli", "review-html", "data\puzzles\all_report.jsonl", "data\puzzles\all_review.html")
    Invoke-Python @("-m", "schess_puzzles.cli", "export-web", "data\puzzles\all_report.jsonl", "web\public\puzzles.json")

    powershell -ExecutionPolicy Bypass -File ".\tools\Publish-WebToDocs.ps1"
    if ($LASTEXITCODE -ne 0) { throw "Could not publish web/ to docs/" }
}

function Invoke-SelfPlayBatch {
    param(
        [string]$BatchName,
        [int]$BatchNumber,
        [int]$Seed
    )

    $rawDir = "data\raw\$BatchName"
    $jsonl = "data\puzzles\$BatchName.jsonl"
    $report = "data\puzzles\${BatchName}_report.jsonl"
    $html = "data\puzzles\${BatchName}_review.html"
    $evalCache = "data\cache\evals\$BatchName"
    $profilePath = "data\profiles\${BatchName}_selector.jsonl"

    Write-Host ""
    Write-Host "=== Generating $BatchName (seed $Seed) ==="

    $existingGames = 0
    if (Test-Path $rawDir) {
        $existingGames = @(Get-ChildItem -Path $rawDir -Filter "*.pgn" -ErrorAction SilentlyContinue).Count
    }
    if ($existingGames -ge $SelfPlayGames) {
        Write-Host "Reusing existing $rawDir with $existingGames PGN(s)."
    } else {
        Invoke-Python @(
            "-m", "schess_puzzles.cli", "selfplay",
            "--games", "$SelfPlayGames",
            "--output-dir", $rawDir,
            "--prefix", $BatchName,
            "--depth", "$SelfPlayDepth",
            "--multipv", "$MultiPv",
            "--max-plies", "$SelfPlayMaxPlies",
            "--temperature-cp", "$TemperatureCp",
            "--blunder-chance", "$BlunderChance",
            "--resign-cp", "$ResignCp",
            "--resign-moves", "$ResignMoves",
            "--seed", "$Seed"
        )
    }

    if (Test-Path $report) {
        Write-Host "Reusing existing $report."
    } else {
        $selectArgs = @(
            "-m", "schess_puzzles.cli", "select-batch",
            "--glob", "$rawDir/*.pgn",
            "--limit", "$SelfPlayGames",
            "--depth", "$SelectorDepth",
            "--multipv", "$MultiPv",
            "--confirm-depth", "$ConfirmDepth",
            "--confirm-multipv", "$ConfirmMultiPv",
            "--extend-critical",
            "--max-plies", "$LineMaxPlies",
            "--extension-beam-width", "$ExtensionBeamWidth",
            "--eval-cache-dir", $evalCache,
            "--output-jsonl", $jsonl,
            "--report-jsonl", $report
        )
        if ($ConfirmFastDepth -gt 0) { $selectArgs += @("--confirm-fast-depth", "$ConfirmFastDepth") }
        if ($ConfirmClearGapCp -gt 0) { $selectArgs += @("--confirm-clear-gap-cp", "$ConfirmClearGapCp") }
        if ($ConfirmClearMarginCp -gt 0) { $selectArgs += @("--confirm-clear-margin-cp", "$ConfirmClearMarginCp") }
        if ($ConfirmBorderlineDepth -gt 0) { $selectArgs += @("--confirm-borderline-depth", "$ConfirmBorderlineDepth") }
        if ($ConfirmBorderlineWinCp -gt 0) { $selectArgs += @("--confirm-borderline-win-cp", "$ConfirmBorderlineWinCp") }
        if ($ConfirmBorderlineGapCp -gt 0) { $selectArgs += @("--confirm-borderline-gap-cp", "$ConfirmBorderlineGapCp") }
        if ($Profile) {
            New-Item -ItemType Directory -Force -Path "data\profiles" | Out-Null
            if (Test-Path $profilePath) { Remove-Item -LiteralPath $profilePath -Force }
            $selectArgs += @("--profile-jsonl", $profilePath)
        }
        Invoke-Python $selectArgs
        Invoke-Python @("-m", "schess_puzzles.cli", "refresh-report-flags", $report)
        Invoke-Python @("-m", "schess_puzzles.cli", "review-html", $report, $html)
        if ($Profile -and (Test-Path $profilePath)) {
            Invoke-Python @("tools\summarize_profile.py", $profilePath)
        }
    }
}

if ($WorkerMode) {
    $batch = Get-NextSelfPlayBatch
    $batchName = "selfplay_batch{0:D2}" -f $batch
    $seed = $SeedBase + $batch
    Invoke-SelfPlayBatch -BatchName $batchName -BatchNumber $batch -Seed $seed
    exit 0
}

if (-not $SkipInitialCombine) {
    Update-CombinedArtifacts
}
$visible = Get-VisibleCount
Write-Host "Visible puzzles before run: $visible / $TargetVisible"

$batchesRun = 0
while ($visible -lt $TargetVisible -and $batchesRun -lt $MaxBatches) {
    $waveSize = [Math]::Min([Math]::Max($Workers, 1), $MaxBatches - $batchesRun)
    $jobs = @()

    for ($i = 0; $i -lt $waveSize; $i++) {
        $batch = Get-NextSelfPlayBatch
        while ($jobs | Where-Object { $_.Name -eq ("selfplay_batch{0:D2}" -f $batch) }) {
            $batch += 1
        }
        $batchName = "selfplay_batch{0:D2}" -f $batch
        $seedBaseForBatch = $SeedBase

        if ($Workers -le 1) {
            Invoke-SelfPlayBatch -BatchName $batchName -BatchNumber $batch -Seed ($seedBaseForBatch + $batch)
        } else {
            Write-Host "Queueing $batchName"
            $root = (Get-Location).Path
            $job = Start-Job -Name $batchName -ScriptBlock {
                param($Root, $BatchNumber, $Params)
                Set-Location $Root
                $args = @(
                    "-ExecutionPolicy", "Bypass", "-File", ".\tools\Grow-SelfPlayToTarget.ps1",
                    "-TargetVisible", "999999999",
                    "-MaxBatches", "1",
                    "-SelfPlayGames", "$($Params.SelfPlayGames)",
                    "-SelectorDepth", "$($Params.SelectorDepth)",
                    "-MultiPv", "$($Params.MultiPv)",
                    "-ConfirmDepth", "$($Params.ConfirmDepth)",
                    "-ConfirmMultiPv", "$($Params.ConfirmMultiPv)",
                    "-ConfirmFastDepth", "$($Params.ConfirmFastDepth)",
                    "-ConfirmClearGapCp", "$($Params.ConfirmClearGapCp)",
                    "-ConfirmClearMarginCp", "$($Params.ConfirmClearMarginCp)",
                    "-ConfirmBorderlineDepth", "$($Params.ConfirmBorderlineDepth)",
                    "-ConfirmBorderlineWinCp", "$($Params.ConfirmBorderlineWinCp)",
                    "-ConfirmBorderlineGapCp", "$($Params.ConfirmBorderlineGapCp)",
                    "-LineMaxPlies", "$($Params.LineMaxPlies)",
                    "-ExtensionBeamWidth", "$($Params.ExtensionBeamWidth)",
                    "-SelfPlayDepth", "$($Params.SelfPlayDepth)",
                    "-SelfPlayMaxPlies", "$($Params.SelfPlayMaxPlies)",
                    "-TemperatureCp", "$($Params.TemperatureCp)",
                    "-BlunderChance", "$($Params.BlunderChance)",
                    "-ResignCp", "$($Params.ResignCp)",
                    "-ResignMoves", "$($Params.ResignMoves)",
                    "-SeedBase", "$($Params.SeedBase)",
                    "-Workers", "1",
                    "-StartBatchOverride", "$BatchNumber",
                    "-SkipInitialCombine",
                    "-WorkerMode"
                )
                if ($Params.Profile) { $args += "-Profile" }
                & powershell @args
                if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            } -ArgumentList $root, $batch, @{
                SelfPlayGames=$SelfPlayGames; SelectorDepth=$SelectorDepth; MultiPv=$MultiPv; ConfirmDepth=$ConfirmDepth;
                ConfirmMultiPv=$ConfirmMultiPv; ConfirmFastDepth=$ConfirmFastDepth; ConfirmClearGapCp=$ConfirmClearGapCp;
                ConfirmClearMarginCp=$ConfirmClearMarginCp; ConfirmBorderlineDepth=$ConfirmBorderlineDepth;
                ConfirmBorderlineWinCp=$ConfirmBorderlineWinCp; ConfirmBorderlineGapCp=$ConfirmBorderlineGapCp;
                LineMaxPlies=$LineMaxPlies; ExtensionBeamWidth=$ExtensionBeamWidth; SelfPlayDepth=$SelfPlayDepth;
                SelfPlayMaxPlies=$SelfPlayMaxPlies; TemperatureCp=$TemperatureCp; BlunderChance=$BlunderChance;
                ResignCp=$ResignCp; ResignMoves=$ResignMoves; SeedBase=$SeedBase; Profile=[bool]$Profile
            }
            $jobs += $job
        }
    }

    if ($Workers -gt 1) {
        Write-Host "Waiting for $($jobs.Count) worker(s)..."
        Wait-Job -Job $jobs | Out-Null
        $failed = $false
        foreach ($job in $jobs) {
            Write-Host ""
            Write-Host "--- Worker $($job.Name) output ---"
            Receive-Job -Job $job
            if ($job.State -ne "Completed") { $failed = $true }
            Remove-Job -Job $job
        }
        if ($failed) { throw "At least one worker failed." }
    }

    Update-CombinedArtifacts
    $visible = Get-VisibleCount
    $batchesRun += $waveSize
    Write-Host "Visible puzzles after wave: $visible / $TargetVisible"
}

Write-Host ""
Write-Host "Growth run finished. visible=$visible target=$TargetVisible batches_run=$batchesRun workers=$Workers profile=$([bool]$Profile)"
Write-Host "Review: data\puzzles\all_review.html"
Write-Host "Publish files: docs\"



