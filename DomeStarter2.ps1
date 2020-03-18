cd 'C:\Program Files (x86)\Dome'
start-process -FilePath "python" -ArugumentList "KoepelX.py" -WorkingDirectory 'C:\Program Files (x86)\Dome'
start-process -FilePath "python" -ArugumentList "Domemon9000.py" -WorkingDirectory 'C:\Program Files (x86)\Dome'
start-process -FilePath "python" -ArugumentList "DomeCommanderX.py" -WorkingDirectory 'C:\Program Files (x86)\Dome'
do{  Start-Sleep 60  }  until ((get-job).State -notcontains 'running')