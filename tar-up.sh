#!/bin/bash
cd "$(dirname "$0")"

# 🧾 Help text
show_help() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Options:
  -d             Copy the tar to the downloads dir.
  -h             Show this help message

Example:
  $0 -d
EOF
}

# 🔧 Default values
DOWNLOADS=false

# 🔍 Parse options
while getopts ":dh" opt; do
  case ${opt} in
    d)
        DOWNLOADS=true
        ;;
    h)
      show_help
      exit 0
      ;;
    \?)
      echo "❌ Invalid option: -$OPTARG" >&2
      show_help
      exit 1
      ;;
    :)
      echo "❌ Option -$OPTARG requires an argument." >&2
      show_help
      exit 1
      ;;
  esac
done


pwd_current=$(pwd)
current_dir_path=$(echo "${pwd_current%/*}")
current_dir=$(echo "${pwd_current##*/}")

DIR_NAME=bloxbox-launcher

if [ "$current_dir" == "$DIR_NAME" ];then
    tar --exclude="$DIR_NAME/.git" -czvf ../bloxbox-roblox-launcher.tgz ../$DIR_NAME
else
    echo "  Not $current_dir looking for $DIR_NAME"
    mv ../$current_dir ../$DIR_NAME
    tar --exclude="$DIR_NAME/.git" -czvf ../bloxbox-roblox-launcher.tgz ../$DIR_NAME
fi

if [ "$DOWNLOADS" == true ];then
    cp -v ../bloxbox-roblox-launcher.tgz ~/Downloads
fi
