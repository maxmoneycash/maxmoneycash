#!/bin/bash
# Open dashboard in browser — reuse an existing matching tab when supported.
# Checks supported running browsers with the default browser first on macOS.
# Usage: ./scripts/open-dashboard.sh [url]

URL="${1:-http://localhost:5173/}"

# Detect default browser bundle ID
DEFAULT_BUNDLE=$(defaults read com.apple.LaunchServices/com.apple.launchservices.secure LSHandlers 2>/dev/null \
  | grep -B1 "https" | grep "LSHandlerRoleAll" | head -1 | sed 's/.*= "\(.*\)";/\1/')

# Map bundle ID to app name
DEFAULT_BROWSER=""
case "$DEFAULT_BUNDLE" in
  com.google.chrome)       DEFAULT_BROWSER="Google Chrome" ;;
  com.apple.safari)        DEFAULT_BROWSER="Safari" ;;
  com.microsoft.edgemac)   DEFAULT_BROWSER="Microsoft Edge" ;;
  company.thebrowser.browser) DEFAULT_BROWSER="Arc" ;;
esac

# Build ordered browser list (default first)
if [ -n "$DEFAULT_BROWSER" ]; then
  BROWSER_ORDER="\"$DEFAULT_BROWSER\""
  for b in "Google Chrome" "Safari" "Microsoft Edge" "Arc"; do
    [ "$b" != "$DEFAULT_BROWSER" ] && BROWSER_ORDER="$BROWSER_ORDER, \"$b\""
  done
else
  BROWSER_ORDER="\"Google Chrome\", \"Safari\", \"Microsoft Edge\", \"Arc\""
fi

osascript -e "
tell application \"System Events\"
  set browserList to {${BROWSER_ORDER}}
  set runningBrowser to \"\"
  repeat with b in browserList
    if (exists process (b as text)) then
      set runningBrowser to (b as text)
      exit repeat
    end if
  end repeat
end tell

if runningBrowser is \"\" then
  open location \"$URL\"
else if runningBrowser is \"Google Chrome\" then
  tell application \"Google Chrome\"
    set found to false
    repeat with w in windows
      set tabIndex to 0
      repeat with t in tabs of w
        set tabIndex to tabIndex + 1
        if URL of t starts with \"$URL\" then
          set active tab index of w to tabIndex
          set index of w to 1
          reload t
          activate
          set found to true
          exit repeat
        end if
      end repeat
      if found then exit repeat
    end repeat
    if not found then
      open location \"$URL\"
      activate
    end if
  end tell
else if runningBrowser is \"Safari\" then
  tell application \"Safari\"
    set found to false
    repeat with w in windows
      set tabIndex to 0
      repeat with t in tabs of w
        set tabIndex to tabIndex + 1
        if URL of t starts with \"$URL\" then
          set current tab of w to t
          set index of w to 1
          do JavaScript \"location.reload()\" in t
          activate
          set found to true
          exit repeat
        end if
      end repeat
      if found then exit repeat
    end repeat
    if not found then
      open location \"$URL\"
      activate
    end if
  end tell
else
  open location \"$URL\"
end if
" 2>/dev/null
