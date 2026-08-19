Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'


function Send-OpenJarvisCodexWebSocketJson {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [System.Net.WebSockets.ClientWebSocket]$Socket,
        [Parameter(Mandatory)]$Payload,
        [Parameter(Mandatory)]
        [System.Threading.CancellationToken]$CancellationToken
    )

    $json = $Payload | ConvertTo-Json -Depth 8 -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    $segment = [System.ArraySegment[byte]]::new($bytes)
    $Socket.SendAsync(
        $segment,
        [System.Net.WebSockets.WebSocketMessageType]::Text,
        $true,
        $CancellationToken
    ).GetAwaiter().GetResult() | Out-Null
}


function Receive-OpenJarvisCodexWebSocketJson {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [System.Net.WebSockets.ClientWebSocket]$Socket,
        [Parameter(Mandatory)]
        [System.Threading.CancellationToken]$CancellationToken,
        [int]$MaximumBytes = 1048576
    )

    $buffer = [byte[]]::new(8192)
    $stream = [System.IO.MemoryStream]::new()
    try {
        do {
            $segment = [System.ArraySegment[byte]]::new($buffer)
            $result = $Socket.ReceiveAsync(
                $segment,
                $CancellationToken
            ).GetAwaiter().GetResult()
            if ($result.MessageType -eq `
                [System.Net.WebSockets.WebSocketMessageType]::Close) {
                return $null
            }
            if ($result.MessageType -ne `
                [System.Net.WebSockets.WebSocketMessageType]::Text) {
                throw 'Codex app-server returned a non-text preflight frame.'
            }
            $stream.Write($buffer, 0, $result.Count)
            if ($stream.Length -gt $MaximumBytes) {
                throw 'Codex app-server preflight exceeded one MiB.'
            }
        } while (-not $result.EndOfMessage)

        $text = [System.Text.Encoding]::UTF8.GetString($stream.ToArray())
        return $text | ConvertFrom-Json
    }
    finally {
        $stream.Dispose()
    }
}


function Test-OpenJarvisSharedCodexProtocol {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$SharedUrl,
        [int]$TimeoutSeconds = 5
    )

    $socket = [System.Net.WebSockets.ClientWebSocket]::new()
    $cancellation = [System.Threading.CancellationTokenSource]::new()
    $cancellation.CancelAfter([TimeSpan]::FromSeconds($TimeoutSeconds))
    try {
        $socket.ConnectAsync(
            [System.Uri]::new($SharedUrl),
            $cancellation.Token
        ).GetAwaiter().GetResult() | Out-Null
        Send-OpenJarvisCodexWebSocketJson -Socket $socket -Payload ([ordered]@{
            method = 'initialize'
            id = 1
            params = [ordered]@{
                clientInfo = [ordered]@{
                    name = 'openjarvis-shared-preflight'
                    title = 'OpenJarvis shared runtime preflight'
                    version = '1.0.0'
                }
                capabilities = [ordered]@{ experimentalApi = $false }
            }
        }) -CancellationToken $cancellation.Token

        for ($index = 0; $index -lt 16; $index++) {
            $message = Receive-OpenJarvisCodexWebSocketJson `
                -Socket $socket -CancellationToken $cancellation.Token
            if ($null -eq $message) { return $false }
            if ($message.PSObject.Properties.Name -contains 'id' -and `
                [int]$message.id -eq 1) {
                if ($message.PSObject.Properties.Name -contains 'error') {
                    return $false
                }
                if (-not ($message.PSObject.Properties.Name -contains 'result')) {
                    return $false
                }
                Send-OpenJarvisCodexWebSocketJson -Socket $socket -Payload `
                    ([ordered]@{ method = 'initialized'; params = @{} }) `
                    -CancellationToken $cancellation.Token
                return $true
            }
        }
        return $false
    }
    catch {
        return $false
    }
    finally {
        $socket.Abort()
        $socket.Dispose()
        $cancellation.Dispose()
    }
}


Export-ModuleMember -Function 'Test-OpenJarvisSharedCodexProtocol'
