#!/bin/bash
# Removes the Folder Collage Quick Actions and its private Python environment.
# Folders you already collaged keep their icon — right-click → "Remove collage" first if you want them back to normal.
rm -rf "$HOME/Library/Services/Collage it.workflow" \
       "$HOME/Library/Services/Remove collage.workflow" \
       "$HOME/Library/Application Support/FolderCollage"
[[ -x /System/Library/CoreServices/pbs ]] && /System/Library/CoreServices/pbs -update 2>/dev/null
echo "Folder Collage removed."
read -n 1 -s -r -p "Press any key to close."
