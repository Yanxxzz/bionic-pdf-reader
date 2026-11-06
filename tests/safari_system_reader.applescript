on run argv
  set actionName to item 1 of argv
  tell application "Safari" to activate
  tell application "System Events"
    tell process "Safari"
      if actionName is "toggle" then
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
