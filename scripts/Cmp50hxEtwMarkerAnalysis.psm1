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

function Get-Cmp50hxDmaPacketLifecycleRecord {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Line,

        [Parameter(Mandatory = $true)]
        [int]$WorkerPid
    )

    $match = [regex]::Match(
        $Line,
        '^\s*Microsoft-Windows-DxgKrnl/DmaPacket/win:(?<phase>Start|Stop),\s*(?<timestamp>\d+),\s*.*?\(\s*(?<pid>\d+)\),(?<fields>.*)$')
    if (-not $match.Success -or [int]$match.Groups['pid'].Value -ne $WorkerPid) {
        return $null
    }

    $fields = @($match.Groups['fields'].Value.TrimStart(',', ' ').Split(',') | ForEach-Object { $_.Trim() })
    # The common ETW header after the PID contributes thread, CPU, activity,
    # related activity, SID and session fields before the task payload.
    if ($match.Groups['phase'].Value -eq 'Start') {
        if ($fields.Count -lt 11 -or $fields[6] -notmatch '^0x' -or $fields[10] -notmatch '^\d+$') {
            return $null
        }
        return [pscustomobject]@{
            phase = 'start'
            timestamp_us = [int64]$match.Groups['timestamp'].Value
            context = $fields[6]
            queue_submit_sequence = [int64]$fields[10]
            preempted = $null
        }
    }
    if ($fields.Count -lt 11 -or $fields[6] -notmatch '^0x' -or $fields[9] -notmatch '^\d+$') {
        return $null
    }
    return [pscustomobject]@{
        phase = 'stop'
        timestamp_us = [int64]$match.Groups['timestamp'].Value
        context = $fields[6]
        queue_submit_sequence = [int64]$fields[9]
        preempted = $fields[10] -match '^(?i:true|1)$'
    }
}

function Get-Cmp50hxDurationStatistics {
    param([int64[]]$DurationsUs)

    if ($DurationsUs.Count -eq 0) {
        return [ordered]@{
            pair_count = 0
            minimum_us = $null
            average_us = $null
            p95_us = $null
            maximum_us = $null
        }
    }
    $sorted = @($DurationsUs | Sort-Object)
    $p95Index = [Math]::Ceiling($sorted.Count * 0.95) - 1
    return [ordered]@{
        pair_count = $sorted.Count
        minimum_us = [int64]$sorted[0]
        average_us = [double](($sorted | Measure-Object -Average).Average)
        p95_us = [int64]$sorted[$p95Index]
        maximum_us = [int64]$sorted[$sorted.Count - 1]
    }
}

function Get-Cmp50hxMarkerWindowDmaPacketLifecycleSummary {
    param(
        [Parameter(Mandatory = $true)]
        [System.Collections.IEnumerable]$DumperLines,

        [Parameter(Mandatory = $true)]
        [object[]]$Windows,

        [Parameter(Mandatory = $true)]
        [int]$WorkerPid
    )

    $states = @{}
    foreach ($window in $Windows) {
        $states[$window.window_id] = [ordered]@{
            window = $window
            start_count = 0
            stop_count = 0
            preempted_stop_count = 0
            starts_by_key = @{}
            durations_us = New-Object 'System.Collections.Generic.List[int64]'
        }
    }

    foreach ($line in $DumperLines) {
        $record = Get-Cmp50hxDmaPacketLifecycleRecord -Line $line -WorkerPid $WorkerPid
        if ($null -eq $record) {
            continue
        }
        foreach ($state in $states.Values) {
            $window = $state.window
            if ($record.timestamp_us -lt [int64]$window.start_timestamp_us -or
                $record.timestamp_us -gt [int64]$window.end_timestamp_us) {
                continue
            }
            $key = "$($record.context)|$($record.queue_submit_sequence)"
            if ($record.phase -eq 'start') {
                $state.start_count++
                if (-not $state.starts_by_key.Contains($key)) {
                    $state.starts_by_key[$key] = New-Object 'System.Collections.Generic.Queue[object]'
                }
                $state.starts_by_key[$key].Enqueue($record)
                continue
            }

            $state.stop_count++
            if ($record.preempted) {
                $state.preempted_stop_count++
            }
            if ($state.starts_by_key.Contains($key) -and $state.starts_by_key[$key].Count -gt 0) {
                $start = $state.starts_by_key[$key].Dequeue()
                $duration = $record.timestamp_us - $start.timestamp_us
                if ($duration -ge 0) {
                    $state.durations_us.Add([int64]$duration)
                }
            }
        }
    }

    $summaries = New-Object 'System.Collections.Generic.List[object]'
    foreach ($window in $Windows) {
        $state = $states[$window.window_id]
        $unmatchedStartCount = [int](($state.starts_by_key.Values | ForEach-Object { $_.Count } | Measure-Object -Sum).Sum)
        $statistics = Get-Cmp50hxDurationStatistics -DurationsUs $state.durations_us.ToArray()
        $summaries.Add([pscustomobject]@{
                window_id = $window.window_id
                marker_timestamp_us = [int64]$window.marker_timestamp_us
                start_timestamp_us = [int64]$window.start_timestamp_us
                end_timestamp_us = [int64]$window.end_timestamp_us
                worker_dma_packet_start_count = $state.start_count
                worker_dma_packet_stop_count = $state.stop_count
                worker_dma_packet_unmatched_start_count = $unmatchedStartCount
                worker_dma_packet_preempted_stop_count = $state.preempted_stop_count
                worker_dma_packet_lifecycle_us = $statistics
            })
    }
    return $summaries.ToArray()
}

Export-ModuleMember -Function Get-Cmp50hxPlaybackMarkers, Assert-Cmp50hxPlaybackMarkerSequence, New-Cmp50hxPlaybackMarkerWindows, Get-Cmp50hxMarkerWindowDxgKrnlSummary, Get-Cmp50hxMarkerWindowDmaPacketLifecycleSummary
