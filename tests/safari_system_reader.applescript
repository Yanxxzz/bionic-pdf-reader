on run argv
  set actionName to item 1 of argv
  if actionName is "launch" then
    tell application id "com.apple.Safari"
      activate
      make new document with properties {URL:item 2 of argv}
      set bounds of front window to {0, 25, 1024, 720}
      return "Safari " & version & " at " & (path to application id "com.apple.Safari" as text)
    end tell
  end if
  if actionName is "quit" then
    tell application id "com.apple.Safari" to quit
    return
  end if
  tell application "Safari" to activate
  tell application "System Events"
    tell process "Safari"
      if actionName is "open" then
        keystroke "o" using command down
      else if actionName is "toggle" then
        key code 11 using option down
      else if actionName is "next" then
        key code 124
      else if actionName is "copy" then
        keystroke "a" using command down
        keystroke "c" using command down
      else
        error "Unknown native keyboard action: " & actionName
      end if
    end tell
  end tell
  return "Native keyboard action: " & actionName
end run
