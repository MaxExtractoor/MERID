$WshShell = New-Object -ComObject WScript.Shell
$Desktop = [Environment]::GetFolderPath('Desktop')
$Shortcut = $WshShell.CreateShortcut("$Desktop\MERID Control Center.lnk")
$Shortcut.TargetPath = "C:\Dev\MERID\MERID Control Center.bat"
$Shortcut.WorkingDirectory = "C:\Dev\MERID"
$Shortcut.Description = "Launch MERID Control Center"
$Shortcut.Save()
Write-Host "Desktop shortcut created successfully!"
