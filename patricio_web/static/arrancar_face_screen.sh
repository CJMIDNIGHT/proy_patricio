#!/bin/bash

export ROS_DOMAIN_ID=7
export ROS_LOCALHOST_ONLY=0

source ~/turtlebot3_ws/install/setup.bash

# TERMINAL 1: ROSBRIDGE
gnome-terminal -- bash -c "
echo '📡 Lanzando rosbridge...';

source ~/turtlebot3_ws/install/setup.bash;

export ROS_DOMAIN_ID=7;

ros2 launch rosbridge_server rosbridge_websocket_launch.xml;

exec bash"

# TERMINAL 2: WEB SERVER
gnome-terminal -- bash -c "
echo '🌐 Lanzando servidor web...';

cd ~/turtlebot3_ws/src/patricio/patricio_web;

python3 -m http.server 8000;

exec bash"

# ESPERAR
sleep 5

# ABRIR WEB
echo '🤖 Abriendo Face Screen...'

firefox http://localhost:8000/face_screen.html &