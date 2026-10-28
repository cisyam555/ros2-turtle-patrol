# 学习容器会话清理脚本备份

本目录保存实际用于学习环境的脚本，便于在 GitHub 跟踪容器残留问题的修复。它们不是 ROS 节点，也不需要 colcon 编译。

## 作用

- `ros2_learning.sh`：进入容器时为每个终端生成独立会话；主机终端退出/关闭时通知会话管理程序清理。
- `config/learning_session.py`：作为 Linux child subreaper，管理该终端的 shell、ROS 启动器和节点，先中断、再对未退出子进程升级终止，并回收退出记录。
- `config/learning.bashrc`：课程环境、通信域 43 和终端提示符。
- 新创建容器使用 `--init`。已有容器无需删除重建，会话管理程序也能回收自己的后代进程。

正常 Ctrl+C 只中断前台程序，进入脚本和交互 shell 保持可用。关闭终端时清理所属会话，不按节点名称批量终止其他终端的程序。

## 实际部署位置

本目录是备份。实际学习环境的文件布局为：

```text
ROS2实战/
├── ros2_learning.sh
├── config/
│   ├── learning_session.py
│   └── learning.bashrc
└── patrol_project/              本 Git 仓库
```

脚本将整个 `ROS2实战` 挂载到容器 `/learning`，硬编码配置文件位置为 `/learning/config`。恢复时按上述布局放置脚本；不要直接在本备份子目录运行入口，否则挂载路径不符合预期。

现有环境在主机执行：

```bash
cd '/home/cisyam/文档/ChatGPT/ROS2实战'
bash ros2_learning.sh enter
```

需要 Docker、主机 Python 3、容器内 Python 3 和本地镜像 `ros2-practice:humble-course`。镜像未随仓库发布，不应把本目录理解为可独立构建的完整 Docker 环境。ROS 节点也可以直接在原生 Humble 环境构建运行。

修复只适用于新入口管理的会话。旧入口留下的活跃节点需要先停止；旧 PID 1 不回收的 `<defunct>` 记录需重启容器清除。一次关闭所有终端时，客户端可能无法收到已退出服务端的取消回复，应以日志明确区分“收到取消结果”和“状态未确认”。
