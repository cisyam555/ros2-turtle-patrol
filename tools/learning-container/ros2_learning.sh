#!/usr/bin/env bash
# 文件用途：在电脑端创建、进入、安装或停止 ROS2 实战容器；/learning 映射到本项目目录。
set -eo pipefail
TASK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TASK_CONTAINER=ros2-practice-learning
TASK_IMAGE=ros2-practice:humble-course

case "${1:-enter}" in
  start|enter)
    if ! docker container inspect "$TASK_CONTAINER" >/dev/null 2>&1; then
      TASK_AUTHORITY="${XAUTHORITY:-/run/user/$(id -u)/gdm/Xauthority}"
      TASK_GUI_ARGS=()
      if [[ -d /tmp/.X11-unix && -f "$TASK_AUTHORITY" ]]; then
        TASK_GUI_ARGS+=(--env "DISPLAY=${DISPLAY:-:1}" --env XAUTHORITY=/tmp/.Xauthority
          --volume /tmp/.X11-unix:/tmp/.X11-unix:ro
          --volume "$TASK_AUTHORITY:/tmp/.Xauthority:ro")
      fi
      if [[ -d /dev/dri ]]; then
        TASK_GUI_ARGS+=(--device /dev/dri)
        for TASK_DEVICE_GROUP in $(stat -c '%g' /dev/dri/* | sort -u); do
          TASK_GUI_ARGS+=(--group-add "$TASK_DEVICE_GROUP")
        done
      fi
      if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
        TASK_GUI_ARGS+=(--gpus all --env NVIDIA_DRIVER_CAPABILITIES=all)
      fi
      docker run -d --init --name "$TASK_CONTAINER" --network bridge --ipc private \
        --workdir /learning --env ROS_DOMAIN_ID=43 --env ROS_LOCALHOST_ONLY=1 \
        --env TURTLEBOT3_MODEL=burger --env QT_X11_NO_MITSHM=1 \
        --volume "$TASK_ROOT:/learning" "${TASK_GUI_ARGS[@]}" \
        "$TASK_IMAGE" sleep infinity
    elif [[ "$(docker inspect -f '{{.State.Running}}' "$TASK_CONTAINER")" != true ]]; then
      docker start "$TASK_CONTAINER"
    fi
    if [[ "${1:-enter}" == enter ]]; then
      # A closed host terminal does not reliably stop docker-exec children.
      # A unique supervisor cleans only this terminal's process tree.
      TASK_SESSION_TOKEN="$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
      cleanup_learning_session() {
        trap '' HUP TERM
        docker exec "$TASK_CONTAINER" python3 /learning/config/learning_session.py \
          "$TASK_SESSION_TOKEN" --stop </dev/null >/dev/null 2>&1 || true
      }
      trap cleanup_learning_session EXIT
      trap 'exit 129' HUP
      trap 'exit 143' TERM
      docker exec -it "$TASK_CONTAINER" python3 /learning/config/learning_session.py \
        "$TASK_SESSION_TOKEN" </dev/tty &
      TASK_EXEC_PID=$!
      wait "$TASK_EXEC_PID"
    fi
    ;;
  install)
    bash "$TASK_ROOT/ros2_learning.sh" start
    docker exec -u root "$TASK_CONTAINER" bash -c 'apt-get update && apt-get install -y ros-humble-turtlesim python3-colcon-common-extensions'
    ;;
  stop) docker stop "$TASK_CONTAINER" ;;
  *) echo '用法：bash ros2_learning.sh [start|enter|install|stop]' >&2; exit 2 ;;
esac
