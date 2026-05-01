#!/bin/bash
cd "$(dirname "$0")"

# 🧾 Help text
show_help() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Options:
  -d             Copy the tar to the downloads directory
  -i             Runs the install-BloxBox.sh script after creating the tar file
  -h             Show this help message

Example:
  $0 -i
EOF
}

# 🔧 Default values
DOWNLOADS=false

# 🔍 Parse options
while getopts ":idh" opt; do
  case ${opt} in
    d)
        DOWNLOADS=true
        ;;
    i)
        INSTALL=true
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

if [ "$INSTALL" == true ];then
    echo "Running....  sudo ./install-BloxBox.sh ../bloxbox-roblox-launcher.tgz"
    sudo ./install-BloxBox.sh ../bloxbox-roblox-launcher.tgz
fi