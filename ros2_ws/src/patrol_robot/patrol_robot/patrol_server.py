import math
import rclpy
from rclpy.node import Node
from rclpy.action import ActionServer
from patrol_interfaces.action import Patrol
from turtlesim.msg import Pose
from geometry_msgs.msg import Twist

class PatrolServer(Node):
    def __init__(self):
        super().__init__('patrol_server')

        self.pose = None

        self.cmd_vel_publisher = self.create_publisher(
            Twist,
            '/turtle1/cmd_vel',
            10,
        )
        self.pose_subscriber = self.create_subscription(
            Pose,
            '/turtle1/pose',
            self.pose_callback,
            10
        )

        self.action_server = ActionServer(
            self,
            Patrol,
            'patrol',
            self.execute_callback
        )
        self.get_logger().info('巡逻节点已启动,等待任务')


    def pose_callback(self, msg):
        first_message = self.pose is None
        self.pose = msg

        if first_message:
            self.get_logger().info(
                f'接收到turtlesim位姿信息: x={msg.x}, y={msg.y}, theta={msg.theta}'
            )

    def stop_turtle(self):
        stop_msg = Twist()
        self.cmd_vel_publisher.publish(stop_msg)

    def execute_callback(self, goal_handle):
        waypoints = goal_handle.request.waypoints

        result = Patrol.Result()
        result.completed = False
        result.visited_count = 0

        if self.pose is None:
            self.get_logger().warn('还没有收到海龟位置，无法计算')
            goal_handle.abort()
            return result

        if len(waypoints) == 0:
            self.get_logger().warn('航点列表为空')
            goal_handle.abort()
            return result

        target = waypoints[0]

        dx = target.x - self.pose.x
        dy = target.y - self.pose.y
        distance = math.hypot(dx, dy)

        target_angle = math.atan2(dy, dx)
        angle_error = target_angle - self.pose.theta

        angle_error = math.atan2(
            math.sin(angle_error),
            math.cos(angle_error),
        )

        self.get_logger().info(
            f'目标方向：{math.degrees(target_angle):.2f}度，'
            f'需要转动：{math.degrees(angle_error):.2f}度'
        )

        self.stop_turtle()
        goal_handle.abort()
        return result

def main(args=None):
    rclpy.init(args=args)
    node = PatrolServer()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()