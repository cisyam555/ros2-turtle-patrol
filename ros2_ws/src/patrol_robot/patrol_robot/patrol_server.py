from rclpy.task import Future
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

        self.turn_target = None
        self.turn_future = None

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

        self.control_timer = self.create_timer(
            0.05,
            self.control_loop,
        )


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


    def control_loop(self):
        if self.pose is None or self.turn_target is None:
            return

        angle_error = self.turn_target - self.pose.theta
        angle_error = math.atan2(
            math.sin(angle_error),
            math.cos(angle_error),
        )

        if abs(angle_error) < 0.03:
            self.stop_turtle()
            self.turn_target = None

            self.get_logger().info('已对准目标方向，停止转动')

            if self.turn_future is not None:
                if not self.turn_future.done():
                    self.turn_future.set_result(True)
            return

        cmd = Twist()
        cmd.angular.z = max(-1.0, min(1.0, 2.0 * angle_error))
        self.cmd_vel_publisher.publish(cmd)


    async def execute_callback(self, goal_handle):
        waypoints = goal_handle.request.waypoints

        result = Patrol.Result()
        result.completed = False
        result.visited_count = 0

        if self.turn_future is not None:
            self.get_logger().warn('正在转向，本次任务不执行')
            goal_handle.abort()
            return result


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


        self.turn_future = Future()
        self.turn_target = target_angle

        self.get_logger().info('开始原地转向')

        try:
            await self.turn_future

            self.get_logger().info('转向测试完成，尚未执行前进')
            goal_handle.abort()
            return result
        finally:
            self.turn_target = None
            self.turn_future = None
            self.stop_turtle()
            

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