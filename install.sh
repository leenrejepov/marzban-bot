#!/bin/bash

# Update package lists
sudo apt update

# Install npm
sudo apt install npm -y

# Install pm2 globally using npm
sudo npm install -g pm2

# Install python3-pip
sudo apt install python3-pip -y

# Install Python dependencies
pip3 install -r requirements.txt

# Start the main.py script using pm2
pm2 start "python3 main.py"
