<div align="center"><img width="280" height="280" alt="Image" src="https://github.com/user-attachments/assets/da74118b-c19f-461c-a132-de6bd6ee7719" /></div>
<h1 align="center">BloxBox</h1>
<h3 align="center">A safer way to have your kids play. Since April 2026</h3>

The Roblox launcher that puts parents in control for Linux. Only showing approved games. The parent-controlled Roblox launcher whitelists approved games, block everything else, and let kids request new ones.

Please submit all problems/issues/sugeestions to https://github.com/stormtheory/bloxbox-launcher/issues

<img width="971" height="737" alt="Image" src="https://github.com/user-attachments/assets/4e95a691-9ff7-4231-a9d3-d985b2cf973f" />

# Package Requirements:
- Python3.7+
- Python3-tk (Future will use Pyside6 and install at runtime with pip, in a virtual env)
- pip package Pillow (installed at run time, in virtual env)

# Install and Run:
## Install Roblox
        # If not installed
                sudo apt install flatpak
        
        # As your child's user (user running Roblox)
                flatpak install flathub org.vinegarhq.Sober

        # Now run Roblox and Login as your child's Roblox account
                 flatpak run org.vinegarhq.Sober

## Maybe needed depending on your setup to run Roblox
        sudo sysctl -w kernel.unprivileged_userns_clone=1
        sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0

## Install BloxBox
        ## Create the tar file of this directory to be installed in the /opt directory.
            # -i arguments removes the need for running install-BloxBox.sh directly.
                ./tar-up.sh -i
        
        ## Installs the package in /opt/bloxbox-launcher and /etc/bloxbox
        ## If selected will install a default game config in /etc/bloxbox
                sudo ./install-BloxBox.sh ../bloxbox-roblox-launcher.tgz

## Game Manage / Approvals / Requests
        ## Use the following command and arguments:
                sudo /opt/bloxbox-launcher/admin.py init            — first-time setup
                sudo /opt/bloxbox-launcher/admin.py list            — show approved games
                sudo /opt/bloxbox-launcher/admin.py add             — approve a new game
                sudo /opt/bloxbox-launcher/admin.py remove          — remove an approved game
                sudo /opt/bloxbox-launcher/admin.py requests        — view pending requests from child
                sudo /opt/bloxbox-launcher/admin.py clear-requests  — clear all reviewed requests


## File locations
        /usr/share/applications/bloxbox.desktop
        /home/{user}/Desktop/bloxbox.desktop

        /etc/bloxbox/config.py
        /opt/bloxbox-launcher/admin.py


# User Agreement:
This project is a community-driven initiative, not a company or commercial entity.
By using this project’s code, scripts, or ideas, you are entitled to the highest degree of privacy and respect. This product does not collect, share, sell, or misuse your data. However, be aware that third parties such as GitHub may collect data independently without our control.
If you encounter any issues or vulnerabilities, please report them to the project maintainers to help improve the product for everyone.
By using this project’s resources, you agree to the terms of the GPL-2.0 License and acknowledge there is no warranty.
If you find this project useful, please consider giving us a Star on GitHub and contribute to its improvement.
Credit is appreciated but not required beyond respecting the open-source ethos.
