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

Export-ModuleMember -Function Get-Cmp50hxEventLossStatus, Test-Cmp50hxPlaybackOutlier
