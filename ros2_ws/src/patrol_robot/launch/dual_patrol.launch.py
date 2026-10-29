from launch import LaunchDescription
from launch.actions import ExecuteProcess
from launch.substitutions import FindExecutable
from launch_ros.actions import Node


def generate_launch_description():
    # 一个仿真窗口，启动时自带 turtle1
    turtlesim_node = Node(
        package='turtlesim',
        executable='turtlesim_node',
        output='screen',
    )

    # 等待 /spawn 服务可用后，创建 turtle2
    spawn_turtle2 = ExecuteProcess(
        cmd=[
            FindExecutable(name='ros2'),
            'service', 'call',
            '/spawn',
            'turtlesim/srv/Spawn',
            '{x: 2.0, y: 8.0, theta: 0.0, name: turtle2}',
        ],
        output='screen',
    )

    # 第一只海龟的服务端
    server1 = Node(
        package='patrol_robot',
        executable='patrol_server',
        namespace='robot1',
        output='screen',
        parameters=[{
            'turtle_name': 'turtle1',
            'linear_speed': 1.0,
            'angular_speed': 1.0,
        }],
    )

    # 第二只海龟的服务端
    server2 = Node(
        package='patrol_robot',
        executable='patrol_server',
        namespace='robot2',
        output='screen',
        parameters=[{
            'turtle_name': 'turtle2',
            'linear_speed': 1.0,
            'angular_speed': 1.0,
        }],
    )

    # 第一只海龟的巡逻任务
    client1 = Node(
        package='patrol_robot',
        executable='patrol_client',
        namespace='robot1',
        output='screen',
        parameters=[{
            'cancel_timeout': 120.0,
            'waypoints': [
                8.0, 2.0,
                6.0, 2.0,
                6.0, 4.0,
            ],
        }],
    )

    # 第二只海龟的巡逻任务
    client2 = Node(
        package='patrol_robot',
        executable='patrol_client',
        namespace='robot2',
        output='screen',
        parameters=[{
            'cancel_timeout': 120.0,
            'waypoints': [
                2.0, 5.0,
                2.0, 8.0,
                5.0, 8.0,
            ],
        }],
    )

    return LaunchDescription([
        turtlesim_node,
        spawn_turtle2,
        server1,
        server2,
        client1,
        client2,
    ])