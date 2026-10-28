source /opt/ros/humble/setup.bash
if [[ -f /learning/ros2_ws/install/setup.bash ]]; then
  source /learning/ros2_ws/install/setup.bash
fi
export ROS_DOMAIN_ID=43
export ROS_LOCALHOST_ONLY=1
export ROS_LOG_DIR=/learning/logs/ros
export PS1="[ROS2实战] \w\$ "
cd /learning
