from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.parameter_descriptions import ParameterValue

def generate_launch_description():

    mode_argument = DeclareLaunchArgument(
        'mode',
        default_value='slow',
        choices=['slow', 'fast'],
        description='巡逻速度模式'
    )

    mode = LaunchConfiguration('mode')

    speed = ParameterValue(
        PythonExpression([
            "0.5 if '", mode, "' == 'slow' else 1.0"
        ]),
        value_type=float
    )

    turtlesim_node = Node(
        package='turtlesim',
        executable='turtlesim_node',
        output='screen'
    )

    patrol_server = Node(
        package='patrol_robot',
        executable='patrol_server',
        output='screen',
        parameters=[{
            'linear_speed': speed,
            'angular_speed': speed,
        }]
    )

    patrol_client = Node(
        package='patrol_robot',
        executable='patrol_client',
        output='screen',
        parameters=[{
            'cancel_timeout': 120.0,
            'waypoints': [2.0, 2.0, 8.0, 2.0, 8.0, 8.0],
        }]
    )

    return LaunchDescription([
        mode_argument,
        turtlesim_node,
        patrol_server,
        patrol_client,
    ])