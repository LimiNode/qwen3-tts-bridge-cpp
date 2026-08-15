Set-StrictMode -Version Latest

function Get-Cmp50hxWorkerProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProcessReport
    )

    $playerMatches = [regex]::Matches(
        $ProcessReport,
        '(?im)^.*qwen_tts_play\.exe\s+\(\s*(\d+)\),\s+\d+,')
    $playerPids = @($playerMatches | ForEach-Object { [int]$_.Groups[1].Value } | Select-Object -Unique)
    if ($playerPids.Count -ne 1) {
        return [ordered]@{
            worker_process_status = 'unresolved'
            player_pids = $playerPids
            worker_pids = @()
        }
    }

    $pythonMatches = [regex]::Matches(
        $ProcessReport,
        '(?im)^.*python\.exe\s+\(\s*(\d+)\),\s+(\d+),')
    $workerPids = @(
        $pythonMatches |
        Where-Object { [int]$_.Groups[2].Value -eq $playerPids[0] } |
        ForEach-Object { [int]$_.Groups[1].Value } |
        Select-Object -Unique)
    if ($workerPids.Count -ne 1) {
        return [ordered]@{
            worker_process_status = 'unresolved'
            player_pids = $playerPids
            worker_pids = $workerPids
        }
    }

    return [ordered]@{
        worker_process_status = 'resolved'
        player_pids = $playerPids
        worker_pids = $workerPids
    }
}

function Get-Cmp50hxDxgKrnlEventSummary {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$DumperLines,

        [Parameter(Mandatory = $true)]
        [int]$WorkerPid
    )

    $eventCounts = [ordered]@{}
    $workerPattern = "python\.exe\s+\(\s*$WorkerPid\)"
    foreach ($line in $DumperLines) {
        $eventMatch = [regex]::Match($line, '^Microsoft-Windows-DxgKrnl/(?<event>[^/]+)/')
        if ($eventMatch.Success -and
            $line -match $workerPattern) {
            $eventName = $eventMatch.Groups['event'].Value
            if (-not $eventCounts.Contains($eventName)) {
                $eventCounts[$eventName] = 0
            }
            $eventCounts[$eventName]++
        }
    }

    $eventCount = if ($eventCounts.Count -eq 0) { 0 } else { ($eventCounts.Values | Measure-Object -Sum).Sum }
    return [ordered]@{
        worker_dxgkrnl_event_count = $eventCount
        worker_dxgkrnl_event_types = $eventCounts
    }
}

function Get-Cmp50hxWorkerAttributionStatus {
    param(
        [Parameter(Mandatory = $true)]
        [bool]$WorkerCswitchPresent,

        [Parameter(Mandatory = $true)]
        [int]$WorkerDxgKrnlEventCount
    )

    $invalidReasons = New-Object 'System.Collections.Generic.List[string]'
    if (-not $WorkerCswitchPresent) {
        $invalidReasons.Add('worker_cswitch_absent')
    }
    if ($WorkerDxgKrnlEventCount -le 0) {
        $invalidReasons.Add('worker_dxgkrnl_events_absent')
    }

    return [ordered]@{
        worker_attribution_valid = ($invalidReasons.Count -eq 0)
        invalid_reasons = @($invalidReasons)
    }
}

Export-ModuleMember -Function Get-Cmp50hxWorkerProcess, Get-Cmp50hxDxgKrnlEventSummary, Get-Cmp50hxWorkerAttributionStatus
