#!/usr/bin/bash

ID=$(id -u)
if [ "$ID" != 0 ];then
    echo " RUN:  sudo $0 ../bloxbox-roblox-launcher.tgz"
    exit
else
    cd "$(dirname "$0")"
fi

pwd_current=$(pwd)
current_dir_path=$(echo "${pwd_current%/*}")
current_dir=$(echo "${pwd_current##*/}")


if [ -z "$1" ];then
    echo " RUN:  sudo $0 bloxbox-roblox-launcher.tgz"
    exit
else
    if echo "$1"|grep -q '.tgz' ;then
        echo 'Go time' 
    else    
        exit
    fi
fi
    
    SU_USER=
    DIR=/opt/bloxbox-launcher
    ETC=/etc/bloxbox
    DECKTOP_ICON_FILENAME=Roblox-Sober.desktop
    WHITELIST_FILENAME=roblox_whitelist.json
    APP_WINDOW_TITLE_NAME='BloxBox'

    echo "  Installing in at $DIR"
    echo '';read -p '      Press enter to continue...' THREE
    sleep 3

    tar -C /opt -xzvf $1
    sudo mkdir -p $ETC
   
    chmod 755 $DIR
    chmod 755 $ETC
    chmod 644 $DIR/*
    chmod 755 $DIR/*.sh
    chmod 644 $DIR/*.py
    chmod 600 $DIR/tar-up.sh
    chmod 644 $DIR/icon-roblox.png
    chmod 700 $DIR/admin.py
    chown root:root -R $DIR
    chown root:root -R $ETC
 
    if [ ! -f $ETC/config.py ];then
       echo '';echo "  INFO: Child's username will be installed into the configuration file. $ETC/config.py"
       read -p "    What is the child's username?  $> " child_USERNAME
   
        if [ ! -z $child_USERNAME ];then
            HOME_DIR=$(echo "/home/$child_USERNAME")
            if [ ! -d $HOME_DIR ];then
                echo "$HOME_DIR was not found..."
                exit
            fi
        else
          echo "ERROR: \$child_USERNAME not found"
          exit
        fi

#### CONFIG FILE
echo "from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
CHILD_USER    = \"$child_USERNAME\"               # ← change this to your son's username

CONFIG_PATH   = \"/etc/bloxbox/roblox_whitelist.json\"   # Approved games list (root-owned)
APP_WINDOW_TITLE_NAME = \"$APP_WINDOW_TITLE_NAME\"

ROBLOX_GAME_SEARCH_URL = \"https://www.roblox.com/charts?device=computer&country=us\"

# Requests file — lives in the child's home directory so they can write to it freely
# Parent reads it with: sudo cat /home/CHILDNAME/.bloxbox_requests.json
REQUESTS_PATH = f\"/home/{CHILD_USER}/.cache/bloxbox_launcher/requests.json\"

# Thumbnail cache directory — stored in child's home, safe to delete any time
CACHE_DIR     = Path.home() / \".cache\" / \"bloxbox_launcher\" / \"thumbnails\"
CLIENT_REQUESTS_PATH = Path.home() / \".cache\" / \"bloxbox_launcher\" / \"requests.json\"

# Fallback configs for testing without root (remove in production)
FALLBACK_CONFIG   = Path.home() / \".roblox_whitelist.json\"
FALLBACK_REQUESTS = Path.home() / \".bloxbox_requests.json\"" > $ETC/config.py
        chmod 644 $ETC/config.py
        chown root:root -R $ETC
   fi 
        chmod 644 $ETC/config.py
        chown root:root -R $ETC

DEFAULT_JSON() {
echo '{
  "games": [
    {
      "name": "[\ud83c\udf7c] Welcome to Bloxburg \ud83c\udfe1",
      "place_id": "185655149",
      "description": ""
    },
    {
      "name": "\ud83d\udc23 Creatures of Sonaria \ud83d\udc07 Survive Kaiju Animals",
      "place_id": "5233782396",
      "description": ""
    },
    {
      "name": "\ud83c\udfc0Basketball Legends\ud83c\udfc0",
      "place_id": "14259168147",
      "description": ""
    },
    {
      "name": "Bike of Hell",
      "place_id": "14943334555",
      "description": ""
    },
    {
      "name": "Waterpark",
      "place_id": "76731635",
      "description": ""
    },
    {
      "name": "Car Suspension Test",
      "place_id": "6816975827",
      "description": ""
    },
    {
      "name": "PET PARTY \ud83c\udf89 RP",
      "place_id": "11497119928",
      "description": ""
    },
    {
      "name": "Driving-Empire-Car-Racing",
      "place_id": "3351674303",
      "description": ""
    },
    {
      "name": "Feather Family",
      "place_id": "1365404657",
      "description": ""
    },
    {
      "name": "Car Crushers 2",
      "place_id": "654732683",
      "description": ""
    },
    {
      "name": "Brookhaven \ud83c\udfe1",
      "place_id": "4924922222",
      "description": ""
    },
    {
      "name": "Basketball: Zero",
      "place_id": "130739873848552",
      "description": ""
    },
    {
      "name": "United States Capitol [RP]",
      "place_id": "120992074793516",
      "description": ""
    }
  ]
}'       > $ETC/$WHITELIST_FILENAME
chmod 644 $ETC/$WHITELIST_FILENAME
echo "Config File placed at: $ETC/$WHITELIST_FILENAME"
ls -al $ETC/$WHITELIST_FILENAME
}


DEFAULT_DESKTOP_ICON() {
echo '[Desktop Entry]
Type=Application
Name=Roblox - Sober
Icon=/opt/bloxbox-launcher/icon-roblox.png
Exec=/opt/bloxbox-launcher/run_bloxbox_gui.sh
Terminal=false
MimeType=application/x-roblox-rbxl;application/x-roblox-rbxlx;x-scheme-handler/roblox-studio;x-scheme-handler/roblox-studio-auth
Categories=Game
X-Flatpak=org.vinegarhq.Vinegar
Name[en_US]=Roblox - Sober'       > $HOME_DIR/Desktop/$DECKTOP_ICON_FILENAME
chmod 755 $HOME_DIR/Desktop/$DECKTOP_ICON_FILENAME
chown root:root $HOME_DIR/Desktop/$DECKTOP_ICON_FILENAME
#chown $child_USERNAME:$child_USERNAME $HOME_DIR/Desktop/$DECKTOP_ICON_FILENAME
echo "Desktop Icon placed at: $HOME_DIR/Desktop/$DECKTOP_ICON_FILENAME"
ls -al $HOME_DIR/Desktop/$DECKTOP_ICON_FILENAME
}



if [ ! -f $ETC/$WHITELIST_FILENAME ];then
    sudo python3 $DIR/admin.py init
    DEFAULT_JSON
else
    echo "";echo "  WARNING: this will overwrite the current file at $ETC/$WHITELIST_FILENAME"
    read -p "     Install Default Whitelist Config of Games?   [y] $> " SAY

    if [ "$SAY" == y ];then
        DEFAULT_JSON
    fi
fi


if [ -z $child_USERNAME ];then
       echo '';read -p "    What is the child's username?  $> " child_USERNAME
   
        if [ ! -z $child_USERNAME ];then
            HOME_DIR=$(echo "/home/$child_USERNAME")
            if [ ! -d $HOME_DIR ];then
                echo "$HOME_DIR was not found..."
                exit
            fi
        else
            echo "ERROR: \$child_USERNAME not found"
            exit
        fi
fi

if [ ! -z $child_USERNAME ];then
  if [ ! -f $HOME_DIR/Desktop/$DECKTOP_ICON_FILENAME ];then
      DEFAULT_DESKTOP_ICON
  else
      echo "";echo "  WARNING: this will overwrite the current file at $HOME_DIR/Desktop/$DECKTOP_ICON_FILENAME"
      read -p "     Install Default Desktop Icon?   [y] $> " SAYyou

      if [ "$SAYyou" == y ];then
          DEFAULT_DESKTOP_ICON
      fi
  fi
fi
#sudo apt install flatpak

##### Not sure which is needed
    #sudo sysctl -w kernel.unprivileged_userns_clone=1
    #echo 'kernel.unprivileged_userns_clone=1' | sudo tee /etc/sysctl.d/99-userns.conf
    #sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
    #echo 'kernel.apparmor_restrict_unprivileged_userns=0' | sudo tee /etc/sysctl.d/99-userns.conf




#su $SU_USER -c 'flatpak install flathub org.vinegarhq.Sober'


exit
