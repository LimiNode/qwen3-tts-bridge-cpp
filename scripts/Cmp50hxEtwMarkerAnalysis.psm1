Set-StrictMode -Version Latest

function Get-Cmp50hxPlaybackMarkers {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$DumperLines
    )

    $markers = New-Object 'System.Collections.Generic.List[object]'
    foreach ($line in $DumperLines) {
        $match = [regex]::Match(
            $line,
            '^\s*Mark,\s*(?<timestamp>\d+),\s*(?<text>qwen_tts_bridge\.playback\..+?)\s*$')
        if (-not $match.Success) {
            continue
        }

        $text = $match.Groups['text'].Value
        $kind = $null
        $queueIndex = $null
        if ($text -eq 'qwen_tts_bridge.playback.request_start') {
            $kind = 'request_start'
        }
        else {
            $queueMatch = [regex]::Match(
                $text,
                '^qwen_tts_bridge\.playback\.queue_empty_before_later_chunk index=(?<index>\d+)$')
            if ($queueMatch.Success) {
                $kind = 'queue_empty_before_later_chunk'
                $queueIndex = [int]$queueMatch.Groups['index'].Value
            }
        }

        if ($null -ne $kind) {
            $markers.Add([pscustomobject]@{
                    timestamp_us = [int64]$match.Groups['timestamp'].Value
                    marker_text = $text
                    kind = $kind
                    queue_index = $queueIndex
                })
        }
    }

    return @($markers.ToArray() | Sort-Object timestamp_us)
}

function Assert-Cmp50hxPlaybackMarkerSequence {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Markers,

        [Parameter(Mandatory = $true)]
        [int]$ExpectedMarkerCount
    )

    if ($ExpectedMarkerCount -lt 1) {
        throw 'Expected playback marker count must include one request_start marker.'
    }
    $orderedMarkers = @($Markers | Sort-Object timestamp_us)
    if ($orderedMarkers.Count -ne $ExpectedMarkerCount) {
        throw "Expected $ExpectedMarkerCount playback markers but found $($Markers.Count)."
    }

    $requestMarkers = @($orderedMarkers | Where-Object { $_.kind -eq 'request_start' })
    if ($requestMarkers.Count -ne 1) {
        throw "Expected exactly one request_start marker but found $($requestMarkers.Count)."
    }

    $queueMarkers = @($orderedMarkers | Where-Object { $_.kind -eq 'queue_empty_before_later_chunk' })
    $expectedQueueCount = $ExpectedMarkerCount - 1
    if ($queueMarkers.Count -ne $expectedQueueCount) {
        throw "Expected $expectedQueueCount queue-empty markers but found $($queueMarkers.Count)."
    }
    for ($index = 0; $index -lt $orderedMarkers.Count; $index++) {
        if ($index -gt 0 -and [int64]$orderedMarkers[$index].timestamp_us -le [int64]$orderedMarkers[$index - 1].timestamp_us) {
            throw 'Playback marker timestamps must be strictly increasing.'
        }
    }
    for ($index = 0; $index -lt $queueMarkers.Count; $index++) {
        $queueIndex = [int]$queueMarkers[$index].queue_index
        if ([int64]$queueMarkers[$index].timestamp_us -le [int64]$requestMarkers[0].timestamp_us) {
            throw "Queue-empty marker index=$queueIndex does not occur after request_start."
        }
        if ($index -gt 0) {
            $previousQueueIndex = [int]$queueMarkers[$index - 1].queue_index
            if ($queueIndex -le $previousQueueIndex) {
                throw "Queue-empty markers must have strictly increasing absolute chunk indices; found index=$queueIndex after index=$previousQueueIndex."
            }
        }
    }

    return [ordered]@{
        expected_marker_count = $ExpectedMarkerCount
        observed_playback_marker_count = $Markers.Count
        request_start_timestamp_us = [int64]$requestMarkers[0].timestamp_us
        queue_empty_marker_count = $queueMarkers.Count
        markers = @($orderedMarkers)
    }
}

function New-Cmp50hxPlaybackMarkerWindows {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Markers,

        [Parameter(Mandatory = $true)]
        [int64]$WindowBeforeUs,

        [Parameter(Mandatory = $true)]
        [int64]$WindowAfterUs
    )

    if ($WindowBeforeUs -lt 0 -or $WindowAfterUs -lt 0) {
        throw 'Marker window sizes must not be negative.'
    }

    $windows = New-Object 'System.Collections.Generic.List[object]'
    foreach ($marker in $Markers) {
        $windowId = if ($marker.kind -eq 'request_start') {
            'request_start'
        }
        else {
            "queue_empty_before_later_chunk_$($marker.queue_index)"
        }
        $timestamp = [int64]$marker.timestamp_us
        $windows.Add([pscustomobject]@{
                window_id = $windowId
                marker_text = $marker.marker_text
                marker_timestamp_us = $timestamp
                start_timestamp_us = $timestamp - $WindowBeforeUs
                end_timestamp_us = $timestamp + $WindowAfterUs
            })
    }
    return $windows.ToArray()
}

function Get-Cmp50hxMarkerWindowDxgKrnlSummary {
    param(
        [Parameter(Mandatory = $true)]
        [System.Collections.IEnumerable]$DumperLines,

        [Parameter(Mandatory = $true)]
        [object[]]$Windows,

        [Parameter(Mandatory = $true)]
        [int]$WorkerPid,

        [ValidateRange(1, 100)]
        [int]$TopCompetingProcesses = 5
    )

    $states = @{}
    foreach ($window in $Windows) {
        $states[$window.window_id] = [ordered]@{
            window_id = $window.window_id
            marker_text = $window.marker_text
            marker_timestamp_us = [int64]$window.marker_timestamp_us
            start_timestamp_us = [int64]$window.start_timestamp_us
            end_timestamp_us = [int64]$window.end_timestamp_us
            direct_dxgkrnl_event_count = 0
            worker_dxgkrnl_event_count = 0
            worker_dxgkrnl_event_types = [ordered]@{}
            competing_process_event_counts = @{}
        }
    }

    foreach ($line in $DumperLines) {
        $match = [regex]::Match(
            $line,
            '^\s*Microsoft-Windows-DxgKrnl/(?<event>[^/]+)/.*?,\s*(?<timestamp>\d+),\s*(?<process>.*?)\s+\(\s*(?<pid>\d+)\),')
        if (-not $match.Success) {
            continue
        }

        $timestamp = [int64]$match.Groups['timestamp'].Value
        $eventName = $match.Groups['event'].Value
        $processName = $match.Groups['process'].Value.Trim()
        $processPid = [int]$match.Groups['pid'].Value
        foreach ($state in $states.Values) {
            if ($timestamp -lt [int64]$state.start_timestamp_us -or
                $timestamp -gt [int64]$state.end_timestamp_us) {
                continue
            }

            $state.direct_dxgkrnl_event_count++
            if ($processPid -eq $WorkerPid) {
                $state.worker_dxgkrnl_event_count++
                if (-not $state.worker_dxgkrnl_event_types.Contains($eventName)) {
                    $state.worker_dxgkrnl_event_types[$eventName] = 0
                }
                $state.worker_dxgkrnl_event_types[$eventName]++
            }
            else {
                $processKey = "$processName ($processPid)"
                if (-not $state.competing_process_event_counts.Contains($processKey)) {
                    $state.competing_process_event_counts[$processKey] = 0
                }
                $state.competing_process_event_counts[$processKey]++
            }
        }
    }

    $summaries = New-Object 'System.Collections.Generic.List[object]'
    foreach ($window in $Windows) {
        $state = $states[$window.window_id]
        $topCompeting = @(
            $state.competing_process_event_counts.GetEnumerator() |
            ForEach-Object {
                [pscustomobject]@{
                    process = $_.Key
                    dxgkrnl_event_count = [int]$_.Value
                }
            } |
            Sort-Object @{ Expression = 'dxgkrnl_event_count'; Descending = $true }, process |
            Select-Object -First $TopCompetingProcesses)
        $summaries.Add([pscustomobject]@{
                window_id = $state.window_id
                marker_text = $state.marker_text
                marker_timestamp_us = $state.marker_timestamp_us
                start_timestamp_us = $state.start_timestamp_us
                end_timestamp_us = $state.end_timestamp_us
                direct_dxgkrnl_event_count = $state.direct_dxgkrnl_event_count
                worker_dxgkrnl_event_count = $state.worker_dxgkrnl_event_count
                worker_dxgkrnl_event_types = $state.worker_dxgkrnl_event_types
                top_competing_processes = $topCompeting
            })
    }
    return $summaries.ToArray()
}

Export-ModuleMember -Function Get-Cmp50hxPlaybackMarkers, Assert-Cmp50hxPlaybackMarkerSequence, New-Cmp50hxPlaybackMarkerWindows, Get-Cmp50hxMarkerWindowDxgKrnlSummary
