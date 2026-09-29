# Discover the router's UPnP IGD and list its current port mappings (read-only).
$msg = "M-SEARCH * HTTP/1.1`r`nHOST: 239.255.255.250:1900`r`nMAN: `"ssdp:discover`"`r`nMX: 2`r`nST: urn:schemas-upnp-org:device:InternetGatewayDevice:1`r`n`r`n"
$udp = New-Object System.Net.Sockets.UdpClient
$udp.Client.ReceiveTimeout = 3000
$bytes = [Text.Encoding]::ASCII.GetBytes($msg)
[void]$udp.Send($bytes, $bytes.Length, '239.255.255.250', 1900)
$locations = @()
try {
  while ($true) {
    $ep = New-Object System.Net.IPEndPoint([Net.IPAddress]::Any, 0)
    $resp = [Text.Encoding]::ASCII.GetString($udp.Receive([ref]$ep))
    if ($resp -match '(?im)^LOCATION:\s*(\S+)') { $locations += $Matches[1] }
  }
} catch {}
$udp.Close()
$locations = $locations | Select-Object -Unique
if (-not $locations) { "No UPnP gateway answered (UPnP likely disabled on the router)."; return }
"UPnP gateway(s): $($locations -join ', ')"
foreach ($loc in $locations) {
  [xml]$desc = (Invoke-WebRequest -Uri $loc -UseBasicParsing -TimeoutSec 5).Content
  $base = ([Uri]$loc).GetLeftPart('Authority')
  $ns = @{u='urn:schemas-upnp-org:device-1-0'}
  $svcs = Select-Xml -Xml $desc -XPath '//u:service' -Namespace $ns | ForEach-Object { $_.Node } |
          Where-Object { $_.serviceType -match 'WAN(IP|PPP)Connection' }
  "Model: $($desc.root.device.manufacturer) $($desc.root.device.modelName)"
  foreach ($s in $svcs) {
    $ctl = if ($s.controlURL -match '^http') { $s.controlURL } else { $base + $s.controlURL }
    $n = 0; $count = 0
    while ($n -lt 200) {
      $body = "<?xml version=`"1.0`"?><s:Envelope xmlns:s=`"http://schemas.xmlsoap.org/soap/envelope/`" s:encodingStyle=`"http://schemas.xmlsoap.org/soap/encoding/`"><s:Body><u:GetGenericPortMappingEntry xmlns:u=`"$($s.serviceType)`"><NewPortMappingIndex>$n</NewPortMappingIndex></u:GetGenericPortMappingEntry></s:Body></s:Envelope>"
      try {
        $r = Invoke-WebRequest -Uri $ctl -Method Post -Body $body -ContentType 'text/xml; charset="utf-8"' -Headers @{SOAPAction="`"$($s.serviceType)#GetGenericPortMappingEntry`""} -UseBasicParsing -TimeoutSec 5
        [xml]$x = $r.Content
        $e = $x.Envelope.Body.FirstChild
        "  ext {0}/{1} -> {2}:{3}  enabled={4}  desc='{5}'" -f $e.NewExternalPort, $e.NewProtocol, $e.NewInternalClient, $e.NewInternalPort, $e.NewEnabled, $e.NewPortMappingDescription
        $count++
      } catch { break }
      $n++
    }
    "  ($count UPnP mappings on $($s.serviceType))"
  }
}
