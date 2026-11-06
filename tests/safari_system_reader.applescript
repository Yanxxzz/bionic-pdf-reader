on run argv
  set actionName to item 1 of argv
  if actionName is "launch" then
    tell application "Safari"
      activate
      make new document with properties {URL:item 2 of argv}
    end tell
    return "Opened a normal Safari window"
  end if
  if actionName is "quit" then
    tell application "Safari" to quit
    return
  end if
  tell application "Safari" to activate
  tell application "System Events"
    tell process "Safari"
      if actionName is "toggle" then
        key code 11 using option down
        return "Pressed Option+B"
      end if
      if actionName is "next" then
        key code 124
        return "Pressed Right Arrow"
      end if
      if actionName is "copy" then
        keystroke "a" using command down
        keystroke "c" using command down
        return "Copied native selection"
      end if
      if actionName is "open" then
        set chosenPath to item 2 of argv
        set capturePath to item 3 of argv
        set openButton to missing value
        set buttonDescriptions to {}
        repeat with elementRef in entire contents of front window
          try
            if role of elementRef is "AXButton" then
              set buttonText to ""
              try
                set buttonText to (name of elementRef) as text
              end try
              try
                set buttonText to buttonText & " " & ((description of elementRef) as text)
              end try
              set end of buttonDescriptions to buttonText
              if buttonText contains "打开 PDF" then set openButton to elementRef
            end if
          end try
        end repeat
        if openButton is missing value then
          log buttonDescriptions
          error "The reader's native open button was not found"
        end if
        click openButton
        repeat 300 times
          if exists sheet 1 of front window then exit repeat
          delay 0.1
        end repeat
        if not (exists sheet 1 of front window) then error "The system file chooser did not open"
        log "Observed system dialog: " & (role of sheet 1 of front window)
        log name of every button of sheet 1 of front window
      end if
    end tell
  end tell
  try
    do shell script "/usr/sbin/screencapture -x " & quoted form of capturePath
  on error captureError
    log captureError
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
  return "Selected the disk PDF through the system dialog"
end run
