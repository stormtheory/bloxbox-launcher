#!/bin/bash
cd "$(dirname "$0")"

tar --exclude='bloxbox-launcher/.git' -czvf ../bloxbox-roblox-launcher.tgz ../bloxbox-launcher/
