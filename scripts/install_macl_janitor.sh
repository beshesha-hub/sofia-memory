#!/bin/bash
# install_macl_janitor.sh — installs macl janitor at 5-second interval
# Run once from Terminal: bash ~/Downloads/Claude\ Memory/scripts/install_macl_janitor.sh

python3 -c "
import plistlib, pathlib, os
p = pathlib.Path(os.path.expanduser('~/Library/LaunchAgents/com.sofia.macl-janitor.plist'))
d = {
  'Label': 'com.sofia.macl-janitor',
  'ProgramArguments': ['/usr/bin/python3', os.path.expanduser('~/Downloads/Claude Memory/scripts/macl_janitor.py')],
  'StartInterval': 5,
  'RunAtLoad': True,
  'StandardOutPath': os.path.expanduser('~/Downloads/Claude Memory/macl_janitor.log'),
  'StandardErrorPath': os.path.expanduser('~/Downloads/Claude Memory/macl_janitor.log'),
}
p.write_bytes(plistlib.dumps(d))
print('plist written — 5 second interval')
"

launchctl unload ~/Library/LaunchAgents/com.sofia.macl-janitor.plist 2>/dev/null
launchctl load ~/Library/LaunchAgents/com.sofia.macl-janitor.plist
echo "macl janitor loaded. Running every 5 seconds."
