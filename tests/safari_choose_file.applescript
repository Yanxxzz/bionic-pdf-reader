on run argv
  set chosenPath to item 1 of argv
  set capturePath to item 2 of argv
  tell application "Safari" to activate
  tell application "System Events"
    tell process "Safari"
      repeat 300 times
        if exists sheet 1 of front window then exit repeat
        delay 0.1
      end repeat
      if not (exists sheet 1 of front window) then error "Safari system file dialog did not appear"
      set panelRole to role of sheet 1 of front window
      set panelButtons to name of every button of sheet 1 of front window
      log "Observed native panel: " & panelRole
      log panelButtons
    end tell
  end tell
  try
    do shell script "/usr/sbin/screencapture -x " & quoted form of capturePath
  on error captureError
    log "Native screenshot unavailable: " & captureError
  end try
  tell application "System Events"
    tell process "Safari"
      keystroke "g" using {command down, shift down}
      delay 0.5
      keystroke chosenPath
      key code 36
      delay 0.7
      key code 36
    end tell
  end tell
  return "Selected a disk file through Safari's system file dialog"
end run
