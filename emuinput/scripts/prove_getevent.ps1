$EventN = Get-UinputdEventN -Serial $S
Write-Host "Using: /dev/input/$EventN"

$cap = "rm -f /data/local/tmp/uinputd_getevent.txt; toybox nohup toybox timeout 3 getevent -lt /dev/input/$EventN > /data/local/tmp/uinputd_getevent.txt 2>&1 &"
adb -s $S shell $cap | Out-Null
Start-Sleep -Milliseconds 200

python -c @"
import socket,time
hp=$HostPort
s=socket.create_connection(('127.0.0.1',hp),2)
def req(c): s.sendall((c+'\n').encode()); s.recv(1024)
req('DOWN 270 480'); time.sleep(0.05); req('UP')
s.close()
"@

Start-Sleep -Seconds 4
adb -s $S shell 'toybox tail -n 80 /data/local/tmp/uinputd_getevent.txt 2>/dev/null || echo NO_CAPTURE'
