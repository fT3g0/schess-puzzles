param(
    [string]$CookieFile = "cookies_env.txt",
    [string]$AccessTokenFile = "access_token.txt",
    [int]$AuthUserId = 7448926,
    [int]$ArchiveStartPage = 50,
    [int]$ArchivePages = 50,
    [string]$ArchiveDays = "0-9999",
    [switch]$AutoArchiveDays,
    [int]$ArchiveChunkPages = 5,
    [double]$DownloadDelay = 1.0,
    [int]$BatchSize = 10,
    [int]$MaxBatches = 9999,
    [int]$Workers = 1,
    [int]$WorkerQueueMultiplier = 2,
    [int]$RescreenDepth = 14,
    [int]$RescreenMultiPv = 8,
    [int]$RescreenMinGapCp = 80,
    [int]$RescreenMarginCp = 120,
    [int]$FetchRetries = 3,
    [int]$FetchRetryDelaySeconds = 20,
    [int]$StopAfterEmptyFetchChunks = 0,
    [switch]$OverlapFetchAndAnalyze,
    [switch]$Profile,
    [switch]$ProcessExistingOnly,
    [string]$ProcessedManifest = "data\puzzles\chesscom_processed_raw.txt",
    [string]$FailedManifest = "data\puzzles\chesscom_failed_raw.txt",
    [string]$ArchiveBlockManifest = "data\cache\chesscom_archive_blocks.jsonl",
    [switch]$CombineAfterEachChunk,
    [switch]$NoFinalCombine
)

$ErrorActionPreference = "Stop"

function Invoke-Step {
    param([string[]]$CommandArgs)
    Write-Host ""
    Write-Host "> python $($CommandArgs -join ' ')"
    & python @CommandArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE"
    }
}

function Invoke-StepWithRetry {
    param(
        [string[]]$CommandArgs,
        [int]$Retries = 3,
        [int]$DelaySeconds = 20,
        [switch]$CaptureOutput
    )
    $attempt = 1
    while ($true) {
        try {
            if ($CaptureOutput) {
                Write-Host ""
                Write-Host "> python $($CommandArgs -join ' ')"
                $output = & python @CommandArgs 2>&1
                $exitCode = $LASTEXITCODE
                $output | ForEach-Object { Write-Host $_ }
                if ($exitCode -ne 0) {
                    throw "Command failed with exit code $exitCode"
                }
                return @($output | ForEach-Object { "$_" })
            }
            Invoke-Step $CommandArgs
            return @()
        } catch {
            if ($attempt -ge $Retries) {
                throw
            }
            Write-Warning "Command failed on attempt $attempt/$($Retries): $($_.Exception.Message)"
            Write-Host "Retrying in $DelaySeconds second(s)..."
            Start-Sleep -Seconds $DelaySeconds
            $attempt += 1
        }
    }
}

function Get-FetchNextPage {
    param([object[]]$OutputLines, [int]$FallbackPage)
    foreach ($line in @($OutputLines)) {
        $text = "$line"
        if ($text -match 'next_page=(\d+)') {
            return [int]$Matches[1]
        }
    }
    return $FallbackPage
}


function Get-FetchEffectivePages {
    param([object[]]$OutputLines, [int]$FallbackPages)
    foreach ($line in @($OutputLines)) {
        $text = "$line"
        if ($text -match 'effective_pages=(\d+)') {
            return [int]$Matches[1]
        }
    }
    return $FallbackPages
}

function Get-FetchSuggestedDays {
    param([object[]]$OutputLines)
    foreach ($line in @($OutputLines)) {
        $text = "$line"
        if ($text -match 'suggested_next_days=([0-9]+-[0-9]+)') {
            return $Matches[1]
        }
    }
    return $null
}

function New-FetchCommandArgs {
    param([int]$Page, [int]$Chunk)
    return @(
        "-m", "schess_puzzles.cli", "fetch-chesscom-archive",
        "--access-token-file", $AccessTokenFile,
        "--auth-user-id", "$AuthUserId",
        "--days", $currentArchiveDays,
        "--title", "seirawan",
        "--start-page", "$Page",
        "--pages", "$Chunk",
        "--delay", "$DownloadDelay",
        "--archive-block-manifest", $ArchiveBlockManifest
    )
}

function Start-FetchChunkJob {
    param([int]$Page, [int]$Chunk, [int]$RawBeforeFetch)
    $root = (Get-Location).Path
    $commandArgs = New-FetchCommandArgs -Page $Page -Chunk $Chunk
    $job = Start-Job -Name ("chesscom_fetch_page{0}" -f $Page) -ScriptBlock {
        param($Root, $CommandArgs, $Retries, $DelaySeconds)
        Set-Location $Root
        $attempt = 1
        while ($true) {
            Write-Host ""
            Write-Host "> python $($CommandArgs -join ' ')"
            & python @CommandArgs
            if ($LASTEXITCODE -eq 0) { return }
            if ($attempt -ge $Retries) { throw "Fetch command failed with exit code $LASTEXITCODE" }
            Write-Warning "Fetch command failed on attempt $attempt/$($Retries) with exit code $LASTEXITCODE"
            Write-Host "Retrying in $DelaySeconds second(s)..."
            Start-Sleep -Seconds $DelaySeconds
            $attempt += 1
        }
    } -ArgumentList $root, $commandArgs, $FetchRetries, $FetchRetryDelaySeconds
    Add-Member -InputObject $job -MemberType NoteProperty -Name Page -Value $Page
    Add-Member -InputObject $job -MemberType NoteProperty -Name Chunk -Value $Chunk
    Add-Member -InputObject $job -MemberType NoteProperty -Name RawBeforeFetch -Value $RawBeforeFetch
    return $job
}
function Get-RawChessComCount {
    return (Get-ChildItem data\raw -Filter "chesscom_*.pgn4.txt" -File).Count
}

function Get-NextChessComBatch {
    $reports = Get-ChildItem data\puzzles -Filter "chesscom_batch*_report.jsonl" -File -ErrorAction SilentlyContinue
    $max = 1
    foreach ($report in $reports) {
        if ($report.Name -match "^chesscom_batch(\d+)_report\.jsonl$") {
            $number = [int]$Matches[1]
            if ($number -gt $max) {
                $max = $number
            }
        }
    }
    return $max + 1
}

function Get-NormalizedPath {
    param([System.IO.FileInfo]$Path)
    return $Path.FullName.ToLowerInvariant()
}

function Initialize-ProcessedManifest {
    if (Test-Path -LiteralPath $ProcessedManifest) {
        return
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ProcessedManifest) | Out-Null
    Get-ChildItem data\raw -Filter "chesscom_*.pgn4.txt" -File |
        ForEach-Object { Get-NormalizedPath $_ } |
        Set-Content -LiteralPath $ProcessedManifest -Encoding UTF8
    Write-Host "Initialized processed manifest with current raw files: $ProcessedManifest"
}

function Get-ProcessedSet {
    $set = [System.Collections.Generic.HashSet[string]]::new()
    if (Test-Path -LiteralPath $ProcessedManifest) {
        foreach ($line in Get-Content -LiteralPath $ProcessedManifest) {
            if ($line.Trim()) {
                [void]$set.Add($line.Trim().ToLowerInvariant())
            }
        }
    }
    return $set
}

function Add-ProcessedFiles {
    param([System.IO.FileInfo[]]$Files)
    foreach ($file in $Files) {
        Add-Content -LiteralPath $ProcessedManifest -Encoding UTF8 -Value (Get-NormalizedPath $file)
    }
}

function Add-FailedFiles {
    param([System.IO.FileInfo[]]$Files, [string]$BatchName)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $FailedManifest) | Out-Null
    foreach ($file in $Files) {
        Add-Content -LiteralPath $FailedManifest -Encoding UTF8 -Value "$(Get-Date -Format o)`t$BatchName`t$(Get-NormalizedPath $file)"
    }
}

function Get-UnprocessedChessComFiles {
    $processed = Get-ProcessedSet
    return @(
        Get-ChildItem data\raw -Filter "chesscom_*.pgn4.txt" -File |
            Sort-Object Name |
            Where-Object { -not $processed.Contains((Get-NormalizedPath $_)) }
    )
}

function Invoke-ChessComFileBatch {
    param([System.IO.FileInfo[]]$Files, [int]$Batch, [switch]$SkipManifest)
    $batchName = "chesscom_batch{0:D2}" -f $Batch
    $jsonl = "data\puzzles\$batchName.jsonl"
    $report = "data\puzzles\${batchName}_report.jsonl"
    $html = "data\puzzles\${batchName}_review.html"
    $evalCache = "data\cache\evals\$batchName"
    $profilePath = "data\profiles\${batchName}_selector.jsonl"
    $args = @("-m", "schess_puzzles.cli", "select-batch")
    foreach ($file in $Files) {
        $args += $file.FullName
    }
    $args += @(
        "--limit", "0",
        "--depth", "10",
        "--multipv", "6",
        "--rescreen-depth", "$RescreenDepth",
        "--rescreen-multipv", "$RescreenMultiPv",
        "--rescreen-min-gap-cp", "$RescreenMinGapCp",
        "--rescreen-margin-cp", "$RescreenMarginCp",
        "--confirm-depth", "20",
        "--confirm-multipv", "3",
        "--confirm-fast-depth", "17",
        "--extend-critical",
        "--max-plies", "7",
        "--extension-beam-width", "2",
        "--eval-cache-dir", $evalCache,
        "--output-jsonl", $jsonl,
        "--report-jsonl", $report
    )
    if ($Profile) {
        New-Item -ItemType Directory -Force -Path "data\profiles" | Out-Null
        if (Test-Path $profilePath) { Remove-Item -LiteralPath $profilePath -Force }
        $args += @("--profile-jsonl", $profilePath)
    }
    Invoke-Step $args
    Invoke-Step @("-m", "schess_puzzles.cli", "refresh-report-flags", $report)
    Invoke-Step @("-m", "schess_puzzles.cli", "review-html", $report, $html)
    if (-not $SkipManifest) { Add-ProcessedFiles $Files }
    if ($Profile -and (Test-Path $profilePath)) {
        Invoke-Step @("tools\summarize_profile.py", $profilePath)
    }
}

function Invoke-ChessComFileBatchJob {
    param([System.IO.FileInfo[]]$Files, [int]$Batch)
    if ($Workers -le 1) {
        Invoke-ChessComFileBatch -Files $Files -Batch $Batch
        return
    }
    $root = (Get-Location).Path
    $serializedFiles = @($Files | ForEach-Object { $_.FullName })
    $profileEnabled = [bool]$Profile
    $job = Start-Job -Name ("chesscom_batch{0:D2}" -f $Batch) -ScriptBlock {
        param($Root, $FilePaths, $BatchNumber, $ProfileEnabled, $RescreenDepth, $RescreenMultiPv, $RescreenMinGapCp, $RescreenMarginCp)
        Set-Location $Root
        $batchName = "chesscom_batch{0:D2}" -f $BatchNumber
        $jsonl = "data\puzzles\$batchName.jsonl"
        $report = "data\puzzles\${batchName}_report.jsonl"
        $html = "data\puzzles\${batchName}_review.html"
        $evalCache = "data\cache\evals\$batchName"
        $profilePath = "data\profiles\${batchName}_selector.jsonl"
        $args = @("-m", "schess_puzzles.cli", "select-batch")
        foreach ($file in $FilePaths) { $args += $file }
        $args += @(
            "--limit", "0",
            "--depth", "10",
            "--multipv", "6",
            "--rescreen-depth", "$RescreenDepth",
            "--rescreen-multipv", "$RescreenMultiPv",
            "--rescreen-min-gap-cp", "$RescreenMinGapCp",
            "--rescreen-margin-cp", "$RescreenMarginCp",
            "--confirm-depth", "20",
            "--confirm-multipv", "3",
            "--confirm-fast-depth", "17",
            "--extend-critical",
            "--max-plies", "7",
            "--extension-beam-width", "2",
            "--eval-cache-dir", $evalCache,
            "--output-jsonl", $jsonl,
            "--report-jsonl", $report
        )
        if ($ProfileEnabled) {
            New-Item -ItemType Directory -Force -Path "data\profiles" | Out-Null
            if (Test-Path $profilePath) { Remove-Item -LiteralPath $profilePath -Force }
            $args += @("--profile-jsonl", $profilePath)
        }
        Write-Host ""
        Write-Host "> python $($args -join ' ')"
        & python @args
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & python -m schess_puzzles.cli refresh-report-flags $report
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & python -m schess_puzzles.cli review-html $report $html
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        if ($ProfileEnabled -and (Test-Path $profilePath)) {
            & python tools\summarize_profile.py $profilePath
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }
    } -ArgumentList $root, $serializedFiles, $Batch, $profileEnabled, $RescreenDepth, $RescreenMultiPv, $RescreenMinGapCp, $RescreenMarginCp
    Add-Member -InputObject $job -MemberType NoteProperty -Name FilePaths -Value $serializedFiles
    return $job
}
$usingAccessTokenFile = $AccessTokenFile -and (Test-Path -LiteralPath $AccessTokenFile)
if ($usingAccessTokenFile) {
    # The Python CLI prefers CHESSCOM_COOKIE over --access-token-file. Clear a stale
    # cookie env var here so an explicitly supplied token file is actually used.
    Remove-Item Env:\CHESSCOM_COOKIE -ErrorAction SilentlyContinue
} elseif (-not $env:CHESSCOM_COOKIE -and (Test-Path -LiteralPath $CookieFile)) {
    $env:CHESSCOM_COOKIE = Get-Content -LiteralPath $CookieFile -Raw
}
if (-not $usingAccessTokenFile -and -not $env:CHESSCOM_COOKIE) {
    throw "Set CHESSCOM_COOKIE, provide -CookieFile, or provide -AccessTokenFile."
}

New-Item -ItemType Directory -Force -Path logs | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logPath = "logs\chesscom_unattended_$timestamp.log"
Start-Transcript -Path $logPath | Out-Null
try {
    Write-Host "Unattended Chess.com run started at $(Get-Date)"
    Write-Host "Log: $logPath"
    Write-Host "Starting raw games: $(Get-RawChessComCount)"
    Write-Host "Next batch before run: $(Get-NextChessComBatch)"
    Initialize-ProcessedManifest

    $pagesDone = 0
    $currentArchiveDays = $ArchiveDays
    $nextArchivePage = $ArchiveStartPage
    $batchesDone = 0
    $emptyFetchChunks = 0
    while (($ProcessExistingOnly -or $pagesDone -lt $ArchivePages -or (Get-UnprocessedChessComFiles).Count -gt 0) -and $batchesDone -lt $MaxBatches) {
        $stopAfterThisChunk = $false
        $fetchJob = $null
        $prefetchUnprocessed = $null
        if (-not $ProcessExistingOnly -and $pagesDone -lt $ArchivePages) {
            $page = $nextArchivePage
            $chunk = [Math]::Min($ArchiveChunkPages, $ArchivePages - $pagesDone)
            $rawBeforeFetch = Get-RawChessComCount
            if ($OverlapFetchAndAnalyze) {
                $prefetchUnprocessed = @(Get-UnprocessedChessComFiles)
                Write-Host "Starting background fetch page=$page pages=$chunk while processing existing backlog=$($prefetchUnprocessed.Count)"
                $fetchJob = Start-FetchChunkJob -Page $page -Chunk $chunk -RawBeforeFetch $rawBeforeFetch
            } else {
                $fetchOutput = Invoke-StepWithRetry -Retries $FetchRetries -DelaySeconds $FetchRetryDelaySeconds -CaptureOutput -CommandArgs (New-FetchCommandArgs -Page $page -Chunk $chunk)
                $nextPage = Get-FetchNextPage -OutputLines $fetchOutput -FallbackPage ($page + $chunk)
                $effectivePages = Get-FetchEffectivePages -OutputLines $fetchOutput -FallbackPages $chunk
                $suggestedDays = Get-FetchSuggestedDays -OutputLines $fetchOutput
                $pagesDone += $effectivePages
                if ($AutoArchiveDays -and $suggestedDays -and $suggestedDays -ne $currentArchiveDays) {
                    Write-Host "Switching archive days from $currentArchiveDays to $suggestedDays based on skipped block dates."
                    $currentArchiveDays = $suggestedDays
                    $nextArchivePage = 0
                    $emptyFetchChunks = 0
                } else {
                    $nextArchivePage = $nextPage
                }
                $newRawFiles = (Get-RawChessComCount) - $rawBeforeFetch
                if ($newRawFiles -le 0) {
                    $emptyFetchChunks += 1
                    Write-Host "Fetch chunk page=$page pages=$chunk added no new raw games. empty_chunks=$emptyFetchChunks"
                    if ($StopAfterEmptyFetchChunks -gt 0 -and $emptyFetchChunks -ge $StopAfterEmptyFetchChunks) {
                        Write-Host "Stopping archive fetch after $emptyFetchChunks empty chunk(s)."
                        $stopAfterThisChunk = $true
                    }
                } else {
                    $emptyFetchChunks = 0
                    Write-Host "Fetch chunk page=$page pages=$chunk added $newRawFiles new raw game(s)."
                }
            }
        }

        while ($batchesDone -lt $MaxBatches) {
            if ($null -ne $prefetchUnprocessed) {
                $processedNow = Get-ProcessedSet
                $unprocessed = @($prefetchUnprocessed | Where-Object { -not $processedNow.Contains((Get-NormalizedPath $_)) })
            } else {
                $unprocessed = @(Get-UnprocessedChessComFiles)
            }
            if ($unprocessed.Count -eq 0) {
                Write-Host "No newly downloaded files to process. raw=$(Get-RawChessComCount) nextBatch=$(Get-NextChessComBatch)"
                break
            }
            $queueLimit = [Math]::Min([Math]::Max($Workers, 1) * [Math]::Max($WorkerQueueMultiplier, 1), $MaxBatches - $batchesDone)
            $jobs = @()
            $batchBase = Get-NextChessComBatch
            $started = 0
            $fileOffset = 0

            if ($Workers -le 1) {
                $files = @($unprocessed | Select-Object -First $BatchSize)
                if ($files.Count -gt 0) {
                    Invoke-ChessComFileBatch -Files $files -Batch $batchBase
                    $batchesDone += 1
                }
            } else {
                Write-Host "Starting dynamic Chess.com worker queue: workers=$Workers queued_batches=$queueLimit"
                while ($started -lt $queueLimit -and $jobs.Count -lt $Workers) {
                    $files = @($unprocessed | Select-Object -Skip $fileOffset -First $BatchSize)
                    if ($files.Count -eq 0) { break }
                    $batch = $batchBase + $started
                    Write-Host "Queueing chesscom_batch$('{0:D2}' -f $batch) files=$($files.Count)"
                    $jobs += Invoke-ChessComFileBatchJob -Files $files -Batch $batch
                    $started += 1
                    $fileOffset += $BatchSize
                }

                $hadWorkerFailures = $false
                while ($jobs.Count -gt 0) {
                    $finished = Wait-Job -Job $jobs -Any
                    Write-Host ""
                    Write-Host "--- Worker $($finished.Name) output ---"
                    $workerErrors = @()
                    Receive-Job -Job $finished -ErrorAction SilentlyContinue -ErrorVariable workerErrors
                    foreach ($workerError in $workerErrors) { Write-Host $workerError }
                    if ($finished.State -ne "Completed") {
                        $hadWorkerFailures = $true
                        $failedFiles = @($finished.FilePaths | ForEach-Object { Get-Item -LiteralPath $_ -ErrorAction SilentlyContinue } | Where-Object { $_ })
                        if ($failedFiles.Count -gt 0) {
                            Write-Warning "Worker $($finished.Name) failed; marking $($failedFiles.Count) file(s) as failed and continuing."
                            Add-FailedFiles -Files $failedFiles -BatchName $finished.Name
                            Add-ProcessedFiles $failedFiles
                        }
                    } else {
                        $processedFiles = @($finished.FilePaths | ForEach-Object { Get-Item -LiteralPath $_ })
                        Add-ProcessedFiles $processedFiles
                    }
                    Remove-Job -Job $finished
                    $jobs = @($jobs | Where-Object { $_.Id -ne $finished.Id })
                    $batchesDone += 1

                    if ($started -lt $queueLimit) {
                        $files = @($unprocessed | Select-Object -Skip $fileOffset -First $BatchSize)
                        if ($files.Count -gt 0) {
                            $batch = $batchBase + $started
                            Write-Host "Queueing chesscom_batch$('{0:D2}' -f $batch) files=$($files.Count)"
                            $jobs += Invoke-ChessComFileBatchJob -Files $files -Batch $batch
                            $started += 1
                            $fileOffset += $BatchSize
                        }
                    }
                }
                if ($hadWorkerFailures) { Write-Warning "One or more Chess.com workers failed. Failed file paths were written to $FailedManifest and the run continued." }
            }
            if ($CombineAfterEachChunk) {
                Invoke-Step @(
                    "-m", "schess_puzzles.cli", "combine-reports",
                    "--output", "data\puzzles\chesscom_all_report.jsonl"
                )
                Invoke-Step @(
                    "-m", "schess_puzzles.cli", "review-html",
                    "data\puzzles\chesscom_all_report.jsonl",
                    "data\puzzles\chesscom_all_review.html"
                )
            }
        }
        if ($fetchJob) {
            Write-Host "Waiting for background fetch page=$($fetchJob.Page) pages=$($fetchJob.Chunk)..."
            Wait-Job -Job $fetchJob | Out-Null
            Write-Host ""
            Write-Host "--- Fetch $($fetchJob.Name) output ---"
            $fetchErrors = @()
            $fetchOutput = @(Receive-Job -Job $fetchJob -ErrorAction SilentlyContinue -ErrorVariable fetchErrors)
            $fetchOutput | ForEach-Object { Write-Host $_ }
            foreach ($fetchError in $fetchErrors) { Write-Host $fetchError }
            if ($fetchJob.State -ne "Completed") {
                Remove-Job -Job $fetchJob
                throw "Background fetch failed."
            }
            $nextPage = Get-FetchNextPage -OutputLines $fetchOutput -FallbackPage ($fetchJob.Page + $fetchJob.Chunk)
            $effectivePages = Get-FetchEffectivePages -OutputLines $fetchOutput -FallbackPages $fetchJob.Chunk
            $suggestedDays = Get-FetchSuggestedDays -OutputLines $fetchOutput
            $pagesDone += $effectivePages
            if ($AutoArchiveDays -and $suggestedDays -and $suggestedDays -ne $currentArchiveDays) {
                Write-Host "Switching archive days from $currentArchiveDays to $suggestedDays based on skipped block dates."
                $currentArchiveDays = $suggestedDays
                $nextArchivePage = 0
                $emptyFetchChunks = 0
            } else {
                $nextArchivePage = $nextPage
            }
            $newRawFiles = (Get-RawChessComCount) - $fetchJob.RawBeforeFetch
            if ($newRawFiles -le 0) {
                $emptyFetchChunks += 1
                Write-Host "Fetch chunk page=$($fetchJob.Page) pages=$($fetchJob.Chunk) added no new raw games. empty_chunks=$emptyFetchChunks"
                if ($StopAfterEmptyFetchChunks -gt 0 -and $emptyFetchChunks -ge $StopAfterEmptyFetchChunks) {
                    Write-Host "Stopping archive fetch after $emptyFetchChunks empty chunk(s)."
                    $stopAfterThisChunk = $true
                }
            } else {
                $emptyFetchChunks = 0
                Write-Host "Fetch chunk page=$($fetchJob.Page) pages=$($fetchJob.Chunk) added $newRawFiles new raw game(s)."
            }
            Remove-Job -Job $fetchJob
        }
        if ($ProcessExistingOnly -or $stopAfterThisChunk) { break }
    }

    if (-not $NoFinalCombine) {
        Invoke-Step @(
            "-m", "schess_puzzles.cli", "combine-reports",
            "--output", "data\puzzles\chesscom_all_report.jsonl"
        )
        Invoke-Step @(
            "-m", "schess_puzzles.cli", "review-html",
            "data\puzzles\chesscom_all_report.jsonl",
            "data\puzzles\chesscom_all_review.html"
        )
        Invoke-Step @(
            "-m", "schess_puzzles.cli", "combine-reports",
            "--glob", "data/puzzles/*_batch*_report.jsonl",
            "--output", "data\puzzles\all_report.jsonl"
        )
        Invoke-Step @(
            "-m", "schess_puzzles.cli", "review-html",
            "data\puzzles\all_report.jsonl",
            "data\puzzles\all_review.html"
        )
        Invoke-Step @(
            "-m", "schess_puzzles.cli", "enrich-mate-lines",
            "data\puzzles\all_report.jsonl",
            "--depth", "20",
            "--multipv", "5"
        )
        Invoke-Step @(
            "-m", "schess_puzzles.cli", "export-web",
            "data\puzzles\all_report.jsonl",
            "web\public\puzzles.json"
        )
        powershell -ExecutionPolicy Bypass -File ".\tools\Publish-WebToDocs.ps1"
        if ($LASTEXITCODE -ne 0) { throw "Could not publish web/ to docs/" }
        Invoke-Step @("tools\status_summary.py")
    }

    Write-Host "Unattended Chess.com run finished at $(Get-Date)"
    Write-Host "Raw games: $(Get-RawChessComCount)"
    Write-Host "Next batch after run: $(Get-NextChessComBatch)"
} finally {
    Stop-Transcript | Out-Null
}
