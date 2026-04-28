#!/bin/bash
cd "$(dirname "$0")"

ENV="${HOME}/.venv-bloxbox"

# 🧾 Help text
show_help() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Options:
  -d             Debug mode
  -c             Code
  -u             Bypass Lock
  -h             Show this help message

Example:
  $0 -vdl
EOF
}

# 🔧 Default values
APP=true
DEBUG=false
CODE=false
LOCK=true

# 🔍 Parse options
while getopts ":dhcu" opt; do
  case ${opt} in
    d)
        DEBUG=true
        APP=false
        LOCK=true
        ;;
    c)
        CODE=true
        APP=false
        LOCK=false
        ;;
    u)
        CODE=false
        APP=true
        LOCK=false
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



if [ $LOCK == true ];then
# CAN ONLY BE ONE!!!!
    APP_LOCK='bloxbox-gui'
    RAM_DIR='/dev/shm'
    BASENAME=$(basename $0)
    RAM_FILE="${RAM_DIR}/${APP_LOCK}-${BASENAME}.lock"
    fs_type=$(stat -f -c %T "$RAM_DIR")
    if [ -d $RAM_DIR ];then
            if [[ "$fs_type" == "tmpfs" ]] || [[ "$fs_type" == "ramfs" ]]; then
                    if [ -f $RAM_FILE ]; then
                    echo "RAM lock file exists: $RAM_FILE"
                    exit 1
                    else
                            touch $RAM_FILE
                            chmod 600 $RAM_FILE
                            # Cleanup on exit
                            trap 'rm -f "$RAM_FILE"; echo "[*] Lock released."; exit' INT TERM EXIT
                    fi
            else
                    echo "[-] '$RAM_DIR' is NOT on a RAM disk (type: $fs_type)"
            fi
    else
            echo "ERROR: $RAM_DIR not present to lock app."
    fi
fi


if [ ! -d $ENV ];then
    # Get the major.minor version of the system's default python3
    PYTHON_VERSION=$(python3 -c 'import sys; v=sys.version_info; print(f"{v.major}.{v.minor}")')
    # Validate Python version (3.7+ required)
    PY_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
    PY_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
    if [ "$PY_MAJOR" -ne 3 ] || [ "$PY_MINOR" -lt 7 ]; then
        echo "❌ Python 3.7+ is required. Found Python $PYTHON_VERSION"
        exit 1
    fi
    # Try versioned package names first
    PACKAGES="python${PYTHON_VERSION}-venv python${PYTHON_VERSION}-dev"

    if python3 -c "import tkinter; print('tkinter ok')"|grep -q 'ok';then
        echo "tkinker installed skipping"
    else
    for package in $PACKAGES; do
        if dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q "install ok installed"; then
            echo "✅ Installed... $package"
        else
            echo "⚠️  $package is not installed: $package"
            echo "➡️  Attempting to install $package"
            if ! sudo apt-get install -y "$package"; then
                echo "⚠️  Failed to install $package — trying fallback: python3-venv or python3-dev"
                fallback_pkg="python3-venv"
                [ "$package" = "python${PYTHON_VERSION}-dev" ] && fallback_pkg="python3-dev"
                sudo apt-get install -y "$fallback_pkg" || {
                    echo "❌ Failed to install fallback: $fallback_pkg"
                    exit 1
                }
            fi
        fi
    done
    fi

    packages='python3-tk'
    for package in $packages;do
            if dpkg-query -W -f='${Status}' $package 2>/dev/null | grep -q "install ok installed";then
                    echo "✅ Installed... $package"
            else
                    echo "⚠️ $package is required and must be installed from your distro."
                    sudo apt install $package
            fi
    done

    #sudo apt install python3.12-venv
    # 1. Create a virtual environment
        python3 -m venv $ENV
        if [ "$?" != 0 ];then
            echo "  ERROR: python3 -m venv $ENV did not work."
            exit
        fi
fi

if [ ! -f $ENV/.bloxbox-gui ];then

    # 2. Activate it
        source $ENV/bin/activate

    # 3. Update
        pip install --upgrade pip

    # 4. Install PySide6
        #pip install PySide6

    # Roblox
        pip install Pillow
        if [ "$?" != 0 ];then
            echo "  ERROR: pip install Pillow did not work."
            exit
        fi
        python3 -c "from PIL import Image; print('Pillow ok')"
        ### MARK GOOD
        if [ "$?" == 0 ];then
            touch $ENV/.bloxbox-gui
        fi
fi

source $ENV/bin/activate

if [ $CODE == true ];then
                export PYTHONWARNINGS="ignore"
                code
                exit 0
elif [ $DEBUG == true ];then
                export PYTHONWARNINGS="ignore"
                echo "Starting Client"
                python3 bloxbox-launcher.py -d
                exit 0
elif [ $APP == true ];then
                export PYTHONWARNINGS="ignore"
                echo "Starting Client"
                python3 bloxbox-launcher.py
                exit 0
fi
echo "ERROR! Can not run."
exit 1
