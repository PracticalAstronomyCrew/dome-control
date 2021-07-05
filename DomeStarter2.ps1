cd 'C:\Program Files (x86)\Dome'
start-process -FilePath "python3" -ArugumentList "KoepelX.py" -WorkingDirectory 'C:\Program Files (x86)\Dome'
start-process -FilePath "python3" -ArugumentList "DomeCommanderX.py" -WorkingDirectory 'C:\Program Files (x86)\Dome'
do{  Start-Sleep 60  }  until ((get-job).State -notcontains 'running')