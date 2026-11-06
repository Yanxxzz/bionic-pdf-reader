on run argv
  set chosenPath to item 1 of argv
  set capturePath to item 2 of argv
  tell application "Safari" to activate
  tell application "System Events"
    tell process "Safari"
      set foundPanel to false
      repeat 300 times
        set hasOpen to false
        set hasCancel to false
        repeat with targetWindow in windows
          repeat with elementRef in entire contents of targetWindow
            try
              if role of elementRef is "AXButton" then
                if name of elementRef is "Open" then set hasOpen to true
                if name of elementRef is "Cancel" then set hasCancel to true
              end if
            end try
          end repeat
        end repeat
        if hasOpen and hasCancel then
          set foundPanel to true
          exit repeat
        end if
        delay 0.1
      end repeat
      if not foundPanel then
        log name of every window
        repeat with targetWindow in windows
          log entire contents of targetWindow
        end repeat
        error "Safari system file dialog did not appear"
      end if
      log "Observed native file panel with Open and Cancel buttons"
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
