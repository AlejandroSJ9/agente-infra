#!/bin/bash
set -eux
timedatectl set-timezone America/Bogota
apt-get update
apt-get upgrade -y
curl -fsSL https://get.docker.com | sh
usermod -aG docker ubuntu