Set-StrictMode -Version Latest

function Get-Cmp50hxEventLossStatus {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TraceStatsText
    )

    $bufferMatches = [regex]::Matches(
        $TraceStatsText,
        '(?im)^\s*(?:Total\s+)?#\s+Lost\s+Buffers\s*:\s*(\d+)\s*$')
    $eventMatches = [regex]::Matches(
        $TraceStatsText,
        '(?im)^\s*(?:Total\s+)?#\s+Lost\s+Events\s*:\s*(\d+)\s*$')

    if ($bufferMatches.Count -eq 0 -or $eventMatches.Count -eq 0) {
        return [ordered]@{
            event_loss_status = 'unparseable'
            lost_buffer_count = $null
            lost_event_count = $null
        }
    }

    $lostBuffers = @($bufferMatches | ForEach-Object { [int64]$_.Groups[1].Value })
    $lostEvents = @($eventMatches | ForEach-Object { [int64]$_.Groups[1].Value })
    $status = if (@($lostBuffers | Where-Object { $_ -gt 0 }).Count -gt 0 -or
                  @($lostEvents | Where-Object { $_ -gt 0 }).Count -gt 0) {
        'nonzero'
    }
    else {
        'verified_zero'
    }

    return [ordered]@{
        event_loss_status = $status
        lost_buffer_count = ($lostBuffers | Measure-Object -Maximum).Maximum
        lost_event_count = ($lostEvents | Measure-Object -Maximum).Maximum
    }
}

function Test-Cmp50hxPlaybackOutlier {
    param(
        [Parameter(Mandatory = $true)]
        [bool]$PlaybackCompleted,

        [Parameter(Mandatory = $true)]
        [int]$QueueEmptyBeforeLaterChunkCount,

        [Parameter(Mandatory = $true)]
        [int]$QueueEmptyThreshold
    )

    return $PlaybackCompleted -and
        $QueueEmptyBeforeLaterChunkCount -ge $QueueEmptyThreshold
}

function Get-Cmp50hxTraceSemanticStatus {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TraceStatsText
    )

    $providerMatch = [regex]::Match(
        $TraceStatsText,
        '(?im)^\{802ec45a-1e99-4b83-9920-87c98277ba9d\}\s+(?<count>\d+)\s+\d+\s+Microsoft-Windows-DxgKrnl\s*$')
    $cswitchPresent = $TraceStatsText -match '(?im)Thread:\s+CSwitch\s*$'
    $schedulerMatches = [regex]::Matches(
        $TraceStatsText,
        '(?im)^\s*0x[0-9a-f]+\s+0x[0-9a-f]+.*\s+(?<count>\d+)\s+\d+\s+Microsoft-Windows-DxgKrnl/(?<event>DmaPacket|QueuePacket)/')
    $schedulerTypes = @($schedulerMatches | ForEach-Object { $_.Groups['event'].Value } | Select-Object -Unique)
    $schedulerEventCount = if ($schedulerMatches.Count -eq 0) {
        0
    }
    else {
        ($schedulerMatches | ForEach-Object { [int64]$_.Groups['count'].Value } |
            Measure-Object -Sum).Sum
    }
    $schedulerPresent = $schedulerTypes -contains 'DmaPacket' -and
        $schedulerTypes -contains 'QueuePacket'

    return [ordered]@{
        dxgkrnl_present = $providerMatch.Success
        dxgkrnl_event_count = if ($providerMatch.Success) { [int64]$providerMatch.Groups['count'].Value } else { $null }
        cswitch_present = $cswitchPresent
        scheduler_event_presence_verified = $schedulerPresent
        scheduler_event_types = $schedulerTypes
        scheduler_event_count = $schedulerEventCount
        semantic_trace_valid = $providerMatch.Success -and $cswitchPresent -and $schedulerPresent
    }
}

Export-ModuleMember -Function Get-Cmp50hxEventLossStatus, Get-Cmp50hxTraceSemanticStatus, Test-Cmp50hxPlaybackOutlier
