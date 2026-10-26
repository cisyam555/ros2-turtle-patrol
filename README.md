# ROS2 巡逻小车学习项目

基于 ROS 2 Humble、Python 和 turtlesim 的独立巡逻项目，按小步骤实现并验证。

## 第一版：基础通信与停车验证

已完成：

- 自定义 `Patrol.action`：航点列表、执行结果和进度反馈的数据格式。
- `/patrol` Action 服务端接收航点并返回结果。
- 订阅 `/turtle1/pose`，持续保存最新位置。
- 计算到第一个航点的距离、目标方向和归一化角度差；当前日志输出目标方向及角度差。
- 向 `/turtle1/cmd_vel` 发布零速度，验证停车消息发送。

当前版本只做通信和计算验证，不执行巡逻。收到非空任务且已取得位置后，发送零速度并主动以 `ABORTED` 结束，返回 `completed: false`、`visited_count: 0`。这不是完整巡逻任务成功的标志。

后续实现：闭环转向、直行与到达判断、多航点、进度反馈、任务取消、独立客户端、参数、Launch 和 rosbag 复盘。

## 项目结构

```text
ros2_ws/src/
├── patrol_interfaces/          自定义 Action 接口包
│   └── action/Patrol.action
└── patrol_robot/               Python 节点包
    └── patrol_robot/patrol_server.py
```

## 环境与构建

需要已配置好的 ROS 2 Humble 环境，以及 `colcon`、`ament_cmake`、`ament_python`、`rclpy`、`rosidl_default_generators`、`geometry_msgs`、`action_msgs` 和 `turtlesim`。本仓库不包含原课程容器和容器进入脚本；也可以在原生 Humble 环境运行。

在仓库根目录打开终端，执行：

```bash
source /opt/ros/humble/setup.bash
cd ros2_ws
colcon build --symlink-install --packages-up-to patrol_robot
source install/setup.bash
ros2 interface show patrol_interfaces/action/Patrol
```

## 运行与验证

每个终端分别加载环境。下文 `/absolute/path/to/patrol_project` 需替换为本机实际仓库路径。在当前学习容器中是 `/learning/patrol_project`。

终端 A：启动海龟，保持运行。

```bash
source /opt/ros/humble/setup.bash
ros2 run turtlesim turtlesim_node
```

终端 B：启动服务端，保持运行。

```bash
source /opt/ros/humble/setup.bash
source /absolute/path/to/patrol_project/ros2_ws/install/setup.bash
ros2 run patrol_robot patrol_server
```

终端 C：先监听速度消息，保持运行。启动和收到位姿的日志应已在终端 B 出现。

```bash
source /opt/ros/humble/setup.bash
ros2 topic echo /turtle1/cmd_vel
```

终端 D：发送任务。

```bash
source /opt/ros/humble/setup.bash
source /absolute/path/to/patrol_project/ros2_ws/install/setup.bash
ros2 action send_goal /patrol patrol_interfaces/action/Patrol "{waypoints: [{x: 2.0, y: 2.0, z: 0.0}]}"
```

所有终端须处于同一个 ROS 通信域。请只运行一个模拟器和一个本项目服务端，避免其他控制程序同时发布速度。

预期：

- 海龟初始位姿约为 `(5.54, 5.54, 0)` 时，服务端打印目标方向和转动角度约 `-135°`。
- 终端 C 收到各分量均为零的 `Twist` 消息。
- 终端 D 收到 `completed: false`、`visited_count: 0`、`ABORTED`。
- 海龟保持静止，当前版本不发送非零速度。

空航点或尚未收到位置时，服务端也会中止测试任务并记录原因。初始代码尚未实现目标范围检查、取消处理或并发任务管理，不用于真实底盘。

## 已有验证

2026-10-26 在学习容器中完成两包构建、接口显示和人工端到端验证：接收任务、读取位姿、角度计算、返回结果、观察零速度消息。模板测试文件随建包工具生成，未据此宣称完整自动化测试已通过。

## 许可证

Apache-2.0，见根目录 `LICENSE`。
