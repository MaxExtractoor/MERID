Get-WinEvent -FilterHashtable @{LogName='Application'; StartTime=(Get-Date).AddHours(-3)} -MaxEvents 400 -ErrorAction SilentlyContinue |
  Where-Object { $_.Message -match 'python|uvicorn|Application Error|Windows Error' -or $_.ProviderName -match 'Application Error|Windows Error' } |
  Select-Object TimeCreated,ProviderName,Id,@{n='Msg';e={$_.Message.Substring(0,[Math]::Min(200,$_.Message.Length))}} |
  Format-List | Out-String -Width 300
