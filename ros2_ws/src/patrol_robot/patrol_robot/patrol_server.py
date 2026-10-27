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

        
        self.motion_future = None
        self.target_point = None      #保存目标的 x、y，前进时需要不断计算剩余距离
        self.motion_state = 'idle'    #'IDLE'表示空闲，暂时没有运动任务
                                      #motion_state记录当前在等待、转向还是前进

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
        if self.pose is None or self.target_point is None:
            return

        dx = self.target_point.x - self.pose.x
        dy = self.target_point.y - self.pose.y
        distance = math.hypot(dx, dy)

        target_angle = math.atan2(dy, dx)
        angle_error = target_angle - self.pose.theta
        angle_error = math.atan2(
            math.sin(angle_error),
            math.cos(angle_error),
        )

        if distance < 0.10:
            self.stop_turtle()
            self.target_point = None
            self.motion_state = 'idle'

            self.get_logger().info('已到达目标航点，停车')

            if self.motion_future is not None:
                if not self.motion_future.done():
                    self.motion_future.set_result(True)
            return

        cmd = Twist()

        if self.motion_state == 'turn':
            if abs(angle_error) < 0.03:
                self.motion_state = 'drive'
                self.get_logger().info('方向已对准，开始前进')
            else:
                cmd.angular.z = max(
                    -1.0, min(1.0, 2.0 * angle_error)
                )

        elif self.motion_state == 'drive':
            if abs(angle_error) > 0.30:
                self.motion_state = 'turn'
            else:
                cmd.linear.x = min(1.0, distance)
                cmd.angular.z = max(
                    -1.0, min(1.0, 2.0 * angle_error)
                )

        self.cmd_vel_publisher.publish(cmd)


    async def execute_callback(self, goal_handle):
        waypoints = goal_handle.request.waypoints

        result = Patrol.Result()
        result.completed = False
        result.visited_count = 0

        if self.motion_future is not None:
            self.get_logger().warn('正在执行运动，本次任务不执行')
            goal_handle.abort()
            return result

        if self.pose is None:
            self.get_logger().warn('尚未收到海龟位置')
            goal_handle.abort()
            return result

        if len(waypoints) != 1:
            self.get_logger().warn('当前阶段只支持一个航点')
            goal_handle.abort()
            return result

        target = waypoints[0]

        if not (
            math.isfinite(target.x)
            and math.isfinite(target.y)
            and 0.5 <= target.x <= 10.5
            and 0.5 <= target.y <= 10.5
        ):
            self.get_logger().warn('目标无效，请将 x、y 设在 0.5～10.5 内')
            goal_handle.abort()
            return result

        self.motion_future = Future()
        self.target_point = target
        self.motion_state = 'turn'

        self.get_logger().info(
            f'开始前往航点：({target.x:.2f}, {target.y:.2f})'
        )

        try:
            await self.motion_future

            result.completed = True
            result.visited_count = 1
            goal_handle.succeed()

            self.get_logger().info('单航点任务完成')
            return result
        finally:
            self.target_point = None
            self.motion_state = 'idle'
            self.motion_future = None
            self.stop_turtle()
            

def main(args=None):
    rclpy.init(args=args)
    node = PatrolServer()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():
            node.stop_turtle()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()