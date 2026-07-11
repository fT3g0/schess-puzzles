param(
    [int]$TargetVisible = 500,
    [int]$MaxBatches = 200,
    [int]$SelfPlayGames = 20,
    [int]$SelectorDepth = 10,
    [int]$MultiPv = 6,
    [int]$RescreenDepth = 14,
    [int]$RescreenMultiPv = 8,
    [int]$RescreenMinGapCp = 80,
    [int]$RescreenMarginCp = 120,
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
    [int]$WorkerQueueMultiplier = 2,
    [switch]$Profile,
    [int]$StartBatchOverride = 0,
    [switch]$SkipInitialCombine,
    [switch]$WorkerMode
)

$ErrorActionPreference = "Stop"

function Format-PythonCommand {
    param([string[]]$CommandArgs)

    if ($CommandArgs.Count -ge 3 -and $CommandArgs[0] -eq "-m" -and $CommandArgs[1] -eq "schess_puzzles.cli") {
        $subcommand = $CommandArgs[2]
        if ($subcommand -eq "combine-reports") {
            $outputIndex = [Array]::IndexOf($CommandArgs, "--output")
            $output = if ($outputIndex -ge 0 -and $outputIndex + 1 -lt $CommandArgs.Count) { $CommandArgs[$outputIndex + 1] } else { "<output>" }
            $inputs = if ($outputIndex -gt 3) { $outputIndex - 3 } else { [Math]::Max($CommandArgs.Count - 3, 0) }
            return "> python -m schess_puzzles.cli combine-reports <${inputs} report file(s)> --output $output"
        }
        if ($subcommand -eq "select-batch") {
            $globIndex = [Array]::IndexOf($CommandArgs, "--glob")
            $reportIndex = [Array]::IndexOf($CommandArgs, "--report-jsonl")
            $glob = if ($globIndex -ge 0 -and $globIndex + 1 -lt $CommandArgs.Count) { $CommandArgs[$globIndex + 1] } else { "<glob>" }
            $report = if ($reportIndex -ge 0 -and $reportIndex + 1 -lt $CommandArgs.Count) { $CommandArgs[$reportIndex + 1] } else { "<report>" }
            return "> python -m schess_puzzles.cli select-batch --glob $glob --report-jsonl $report"
        }
        if ($subcommand -eq "selfplay") {
            $gamesIndex = [Array]::IndexOf($CommandArgs, "--games")
            $outIndex = [Array]::IndexOf($CommandArgs, "--output-dir")
            $seedIndex = [Array]::IndexOf($CommandArgs, "--seed")
            $games = if ($gamesIndex -ge 0 -and $gamesIndex + 1 -lt $CommandArgs.Count) { $CommandArgs[$gamesIndex + 1] } else { "?" }
            $out = if ($outIndex -ge 0 -and $outIndex + 1 -lt $CommandArgs.Count) { $CommandArgs[$outIndex + 1] } else { "<output-dir>" }
            $seed = if ($seedIndex -ge 0 -and $seedIndex + 1 -lt $CommandArgs.Count) { $CommandArgs[$seedIndex + 1] } else { "?" }
            return "> python -m schess_puzzles.cli selfplay --games $games --output-dir $out --seed $seed"
        }
    }

    return "> python $($CommandArgs -join ' ')"
}

function Invoke-Python {
    param([string[]]$CommandArgs)
    Write-Host ""
    Write-Host (Format-PythonCommand $CommandArgs)
    & python @CommandArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE"
    }
}

function Write-CondensedWorkerOutput {
    param([object[]]$Lines)

    $profileRows = 0
    foreach ($item in $Lines) {
        $line = "$item".TrimEnd()
        if (-not $line) { continue }

        if ($line -match '^=== Generating ') { Write-Host $line; continue }
        if ($line -match '^Reusing existing ') { Write-Host $line; continue }
        if ($line -match '^Done\. files=') { Write-Host $line; continue }
        if ($line -match '^Wrote .*_report\.jsonl with \d+ refreshed tactic') { Write-Host $line; continue }
        if ($line -match '^Wrote .*_review\.html with \d+ tactic') { Write-Host $line; continue }

        if ($line -match '^By phase:') {
            Write-Host "Profile summary:"
            $profileRows = 0
            continue
        }
        if ($line -match '^(engine_eval|extension_reply_scan|confirm_candidate|extend_critical_line)\s+' -and $profileRows -lt 6) {
            Write-Host "  $line"
            $profileRows += 1
            continue
        }

        if ($line -match '(Traceback|Exception|Error|failed|Command failed)') {
            Write-Host $line
            continue
        }
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
        "trivial-capture-cleanup" = $true
        "check-evasion" = $true
        "manual-reject" = $true
        "failed-reverify" = $true
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
    $selfPlayCount = @(Get-ChildItem -Path "data\puzzles" -Filter "selfplay_batch*_report.jsonl" -ErrorAction SilentlyContinue).Count

    $tmp = "data\puzzles\all_report.next.jsonl"
    Write-Host ""
    Write-Host "Combining $($reports.Count + $selfPlayCount) report file(s) into data\puzzles\all_report.jsonl..."
    Invoke-Python (@("-m", "schess_puzzles.cli", "combine-reports") + $reports + @("--glob", "data/puzzles/selfplay_batch*_report.jsonl", "--output", $tmp))
    Move-Item -Force -Path $tmp -Destination "data\puzzles\all_report.jsonl"
    Invoke-Python @("-m", "schess_puzzles.cli", "review-html", "data\puzzles\all_report.jsonl", "data\puzzles\all_review.html")
    Invoke-Python @("-m", "schess_puzzles.cli", "enrich-mate-lines", "data\puzzles\all_report.jsonl", "--depth", "20", "--multipv", "5")
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
            "--rescreen-depth", "$RescreenDepth",
            "--rescreen-multipv", "$RescreenMultiPv",
            "--rescreen-min-gap-cp", "$RescreenMinGapCp",
            "--rescreen-margin-cp", "$RescreenMarginCp",
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

function Start-SelfPlayWorkerJob {
    param([int]$BatchNumber)

    $batchName = "selfplay_batch{0:D2}" -f $BatchNumber
    Write-Host "Queueing $batchName"
    $root = (Get-Location).Path
    return Start-Job -Name $batchName -ScriptBlock {
        param($Root, $BatchNumber, $Params)
        Set-Location $Root
        $args = @(
            "-ExecutionPolicy", "Bypass", "-File", ".\tools\Grow-SelfPlayToTarget.ps1",
            "-TargetVisible", "999999999",
            "-MaxBatches", "1",
            "-SelfPlayGames", "$($Params.SelfPlayGames)",
            "-SelectorDepth", "$($Params.SelectorDepth)",
            "-MultiPv", "$($Params.MultiPv)",
            "-RescreenDepth", "$($Params.RescreenDepth)",
            "-RescreenMultiPv", "$($Params.RescreenMultiPv)",
            "-RescreenMinGapCp", "$($Params.RescreenMinGapCp)",
            "-RescreenMarginCp", "$($Params.RescreenMarginCp)",
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
            "-WorkerQueueMultiplier", "1",
            "-StartBatchOverride", "$BatchNumber",
            "-SkipInitialCombine",
            "-WorkerMode"
        )
        if ($Params.Profile) { $args += "-Profile" }
        & powershell @args
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    } -ArgumentList $root, $BatchNumber, @{
        SelfPlayGames=$SelfPlayGames; SelectorDepth=$SelectorDepth; MultiPv=$MultiPv; RescreenDepth=$RescreenDepth;
        RescreenMultiPv=$RescreenMultiPv; RescreenMinGapCp=$RescreenMinGapCp; RescreenMarginCp=$RescreenMarginCp; ConfirmDepth=$ConfirmDepth;
        ConfirmMultiPv=$ConfirmMultiPv; ConfirmFastDepth=$ConfirmFastDepth; ConfirmClearGapCp=$ConfirmClearGapCp;
        ConfirmClearMarginCp=$ConfirmClearMarginCp; ConfirmBorderlineDepth=$ConfirmBorderlineDepth;
        ConfirmBorderlineWinCp=$ConfirmBorderlineWinCp; ConfirmBorderlineGapCp=$ConfirmBorderlineGapCp;
        LineMaxPlies=$LineMaxPlies; ExtensionBeamWidth=$ExtensionBeamWidth; SelfPlayDepth=$SelfPlayDepth;
        SelfPlayMaxPlies=$SelfPlayMaxPlies; TemperatureCp=$TemperatureCp; BlunderChance=$BlunderChance;
        ResignCp=$ResignCp; ResignMoves=$ResignMoves; SeedBase=$SeedBase; Profile=[bool]$Profile
    }
}

$batchesRun = 0
while ($visible -lt $TargetVisible -and $batchesRun -lt $MaxBatches) {
    if ($Workers -le 1) {
        $batch = Get-NextSelfPlayBatch
        $batchName = "selfplay_batch{0:D2}" -f $batch
        Invoke-SelfPlayBatch -BatchName $batchName -BatchNumber $batch -Seed ($SeedBase + $batch)
        $batchesRun += 1
    } else {
        $queueLimit = [Math]::Min([Math]::Max($Workers, 1) * [Math]::Max($WorkerQueueMultiplier, 1), $MaxBatches - $batchesRun)
        $jobs = @()
        $started = 0
        $nextBatch = Get-NextSelfPlayBatch
        Write-Host "Starting dynamic worker queue: workers=$Workers queued_batches=$queueLimit"

        while ($started -lt $queueLimit -and $jobs.Count -lt $Workers) {
            $jobs += Start-SelfPlayWorkerJob -BatchNumber $nextBatch
            $nextBatch += 1
            $started += 1
        }

        $failed = $false
        while ($jobs.Count -gt 0) {
            $finished = Wait-Job -Job $jobs -Any
            Write-Host ""
            Write-Host "--- Worker $($finished.Name) summary ---"
            $workerErrors = @()
            $workerOutput = Receive-Job -Job $finished -ErrorAction SilentlyContinue -ErrorVariable workerErrors
            Write-CondensedWorkerOutput -Lines $workerOutput
            foreach ($workerError in $workerErrors) { Write-Host $workerError }
            if ($finished.State -ne "Completed") { $failed = $true }
            Remove-Job -Job $finished
            $jobs = @($jobs | Where-Object { $_.Id -ne $finished.Id })
            $batchesRun += 1

            if (-not $failed -and $started -lt $queueLimit) {
                $jobs += Start-SelfPlayWorkerJob -BatchNumber $nextBatch
                $nextBatch += 1
                $started += 1
            }
        }
        if ($failed) { throw "At least one worker failed." }
    }

    Update-CombinedArtifacts
    $visible = Get-VisibleCount
    Write-Host "Visible puzzles after worker queue: $visible / $TargetVisible"
}

Write-Host ""
Write-Host "Growth run finished. visible=$visible target=$TargetVisible batches_run=$batchesRun workers=$Workers profile=$([bool]$Profile)"
Write-Host "Review: data\puzzles\all_review.html"
Write-Host "Publish files: docs\"
