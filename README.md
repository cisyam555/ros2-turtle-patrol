# ROS2 巡逻小车学习项目

基于 ROS 2 Humble、Python 和 turtlesim 的独立巡逻系统。当前版本：**客户端自动巡逻、超时与 Ctrl+C 取消、学习容器会话清理**。

## 已实现

- 独立的 `patrol_interfaces` 接口包和 `patrol_robot` 节点包。
- 自定义 `Patrol.action`：航点列表、当前航点与剩余距离反馈、完成状态与实际到达数量。
- 服务端订阅 `/turtle1/pose`，通过 `/turtle1/cmd_vel` 控制海龟。
- 多航点顺序导航：转向对准、直行、持续修正方向、到达后停车。
- 角度差归一化，航点非空及坐标范围检查；坐标 x、y 须有限且在 0.5～10.5 内。
- Action 实时反馈；取消时先发布零速度，再返回 `CANCELED`，未到达的航点不计数。
- 客户端自动发送三个默认航点，打印进度和最终结果。
- 客户端在服务端接受任务后 10 秒请求取消；按 Ctrl+C 也会请求取消并等待结果再退出。
- 同一 Linux 用户和 ROS 通信域内，服务端使用文件锁防止重复启动。
- 学习容器入口增加会话清理：关闭终端后停止本会话的子进程并回收退出记录。

当前是**取消任务**，未实现暂停后继续。速度、默认路线和超时时间目前仍写在代码里；尚未实现参数配置、Launch 一键启动和本项目完整巡逻 bag 验收。

## 项目结构

```text
ros2_ws/src/
├── patrol_interfaces/action/Patrol.action
└── patrol_robot/
    ├── setup.py
    └── patrol_robot/
        ├── patrol_server.py
        └── patrol_client.py
tools/learning-container/       学习容器入口及会话清理脚本备份
```

## 环境与构建

需要 Linux、ROS 2 Humble、Python 3、colcon，以及 `ament_cmake`、`ament_python`、`rclpy`、`rosidl_default_generators`、`geometry_msgs`、`action_msgs` 和 `turtlesim`。可使用原生 Humble 环境；仓库不提供预构建的课程 Docker 镜像。

在仓库根目录执行：

```bash
source /opt/ros/humble/setup.bash
cd ros2_ws
colcon build --symlink-install --packages-up-to patrol_robot
source install/setup.bash
ros2 pkg executables patrol_robot
```

应包含 `patrol_server` 和 `patrol_client` 两个入口。

## 三个终端运行

所有终端使用同一 ROS 通信域，只启动一个模拟器和一个服务端。下面把 `/absolute/path/to/patrol_project` 替换为仓库路径；当前学习容器里为 `/learning/patrol_project`。

终端1：海龟模拟器，保持运行。

```bash
source /opt/ros/humble/setup.bash
ros2 run turtlesim turtlesim_node
```

终端2：巡逻服务端，保持运行。

```bash
source /opt/ros/humble/setup.bash
source /absolute/path/to/patrol_project/ros2_ws/install/setup.bash
ros2 run patrol_robot patrol_server
```

终端3：巡逻客户端。

```bash
source /opt/ros/humble/setup.bash
source /absolute/path/to/patrol_project/ros2_ws/install/setup.bash
ros2 run patrol_robot patrol_client
```

客户端自动发送 `(2, 2) → (8, 2) → (8, 8)`。当前固定 10 秒超时，通常会在完整路线结束前取消，这是本阶段的测试行为。

### 超时取消验收

不按键，等待 10 秒：客户端应请求取消，服务端停车，最终打印状态码 `5`（CANCELED）、`completed=False` 和实际已到达数量。客户端仍保持运行，可按 Ctrl+C 退出。

### Ctrl+C 取消验收

重启客户端，在“服务端已接受任务”后 2～3 秒，在**终端3**按一次 Ctrl+C。客户端应请求取消，等待最终结果后返回命令提示符。海龟停止前进和转动，终端1、终端2继续运行。

若服务端失联，客户端最多等待接单回复 5 秒、任务结果 5 秒，超时后报告状态未确认；不能把客户端退出当作收到停车确认。

### 完整巡逻验收

如需绕过客户端固定的 10 秒超时，可在终端3使用命令行发送任务（不要同时运行客户端）：

```bash
ros2 action send_goal /patrol patrol_interfaces/action/Patrol "{waypoints: [{x: 2.0, y: 2.0, z: 0.0}, {x: 8.0, y: 2.0, z: 0.0}, {x: 8.0, y: 8.0, z: 0.0}]}" --feedback
```

预期最终状态为 `SUCCEEDED`（状态码 `4`）、`completed=True`、`visited_count=3`。

## 重复节点与关闭终端

`ros2 run` 启动器和实际 Python 节点通常各占一行，不能只按进程行数判断服务端数量。

```bash
ros2 action info /patrol
ps -eo pid,ppid,args | grep -E '[p]atrol_server|[p]atrol_client|[t]urtlesim_node'
```

应只有一个 Action 服务端。文件锁只覆盖同一用户、同一通信域内通过本入口启动的服务端。

学习容器的修复脚本见 [tools/learning-container](tools/learning-container/README.md)。新入口负责清理所属会话，旧的直接 docker-exec 会话不受管理。建议先 Ctrl+C，等提示符返回，再输入 `exit`。`<defunct>` 是已退出而未回收的记录，不是活跃节点；旧容器 PID 1 留下的记录可能需要一次容器重启才能清除。

## 验证记录

- 人工验证：海龟依次到达三个航点，客户端实时显示进度，返回 `SUCCEEDED`、完成数 3。
- 人工验证：10 秒超时请求取消，返回 `CANCELED`、完成数 1。
- 隔离 ROS 通信域集成验证：客户端收到 SIGINT 后请求取消，服务端返回 `CANCELED`、发布零速度并清理任务，客户端正常退出。
- PTY 终端测试：客户端 Ctrl+C、服务端 Ctrl+C、直接关闭服务端终端后，均未留下节点或僵尸进程。
- Python 导入/语法检查、Shell 语法检查通过。这些检查不代表完成了全部课程验收。

## 尚未完成的三大项

1. **参数配置**：线速度、角速度、默认航点及取消超时时间；客户端超时逻辑已有，但“通过参数指定超时”仍待实现。
2. **Launch**：一条命令启动 turtlesim、服务端和客户端，并提供慢速/快速模式。
3. **rosbag 项目验收**：录制完整巡逻的 `/turtle1/cmd_vel`、`/turtle1/pose`，检查 bag，停止原控制节点，从相同初始位姿回放并验证轨迹。

多任务抢占、双龟巡逻、超时返航、轨迹对比属于可选挑战，不计入上述三项。

## 许可证

Apache-2.0，见 [LICENSE](LICENSE)。当前实现用于 turtlesim 学习，未完成真实底盘的安全控制与传感器异常处理。
