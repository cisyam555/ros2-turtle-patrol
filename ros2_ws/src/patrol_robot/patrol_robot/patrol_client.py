import signal

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from patrol_interfaces.action import Patrol
from geometry_msgs.msg import Point
from rclpy.signals import SignalHandlerOptions

class PatrolClient(Node):
    def __init__(self):
        super().__init__('patrol_client')
        self.cancel_timer = None
        self.goal_handle = None
        self.result_future = None
        self.result_reported = False
        self.send_goal_future = None
        self.cancel_future = None
        self.exiting = False
        self.action_client = ActionClient(
            self,
            Patrol,
            'patrol'
        )

        self.wait_timer = self.create_timer(
            1.0,
            self.check_server
        )

        self.get_logger().info('巡逻客户端已启动，等待服务端')

    def check_server(self):
        if not self.action_client.server_is_ready():
            self.get_logger().info('尚未找到 /patrol 服务端')
            return

        self.wait_timer.cancel()
        self.get_logger().info('已找到服务端，准备发送巡逻任务')
        self.send_patrol_goal()

    def send_patrol_goal(self):
        goal = Patrol.Goal()
        goal.waypoints = [
            Point(x=2.0, y=2.0, z=0.0),
            Point(x=8.0, y=2.0, z=0.0),
            Point(x=8.0, y=8.0, z=0.0),
        ]

        self.get_logger().info('发送巡逻任务，共3个航点')

        self.send_goal_future = self.action_client.send_goal_async(
            goal,
            feedback_callback=self.feedback_callback
        )
        self.send_goal_future.add_done_callback(
            self.goal_response_callback
        )

    def goal_response_callback(self, future):
        self.goal_handle = future.result()

        if not self.goal_handle.accepted:
            self.get_logger().warn('服务端拒绝了任务')
            return

        self.get_logger().info('服务端已接受任务')

        self.result_future = self.goal_handle.get_result_async()
        self.result_future.add_done_callback(
            self.result_callback
        )
        if not self.exiting:
            self.cancel_timer = self.create_timer(
                10.0,
                self.cancel_patrol
            )

    def feedback_callback(self, feedback_msg):
        feedback = feedback_msg.feedback

        self.get_logger().info(
            f'前往航点 {feedback.current_waypoint}/3，'
            f'剩余距离 {feedback.remaining_distance:.2f}'
        )

    def cancel_patrol(self, reason='执行超过10秒'):
        if self.cancel_timer is not None:
            self.cancel_timer.cancel()

        if self.goal_handle is None:
            return

        if self.result_future is None or self.result_future.done():
            return

        if self.cancel_future is not None:
            return

        self.get_logger().info(f'{reason}，请求取消巡逻')

        self.cancel_future = self.goal_handle.cancel_goal_async()
        self.cancel_future.add_done_callback(
            self.cancel_response_callback
        )

    def cancel_response_callback(self, future):
        response = future.result()

        if response.goals_canceling:
            self.get_logger().info('服务端已同意取消，等待最终结果')
        else:
            self.get_logger().warn('没有任务进入取消流程，请查看最终结果')

    def result_callback(self, future):
        if self.result_reported:
            return
        self.result_reported = True
        if self.cancel_timer is not None:
            self.cancel_timer.cancel()

        response = future.result()
        result = response.result

        self.get_logger().info(
            f'任务结束：状态码={response.status}，'
            f'全部完成={result.completed}，'
            f'已到达航点数={result.visited_count}'
        )

def main(args=None):
    # 保留 ROS 通信，让 Ctrl+C 后仍能发送取消并接收结果。
    rclpy.init(args=args, signal_handler_options=SignalHandlerOptions.NO)
    node = PatrolClient()
    exit_requested = False

    def request_exit(signum, frame):
        nonlocal exit_requested
        exit_requested = True

    previous_handler = signal.signal(signal.SIGINT, request_exit)

    try:
        # 信号处理器只设置标记，避免打断底层消息转换。
        while rclpy.ok() and not exit_requested:
            rclpy.spin_once(node, timeout_sec=0.1)
        if exit_requested:
            raise KeyboardInterrupt
    except KeyboardInterrupt:
        node.exiting = True
        node.wait_timer.cancel()
        if node.cancel_timer is not None:
            node.cancel_timer.cancel()

        try:
            # 如果刚发出任务就按下 Ctrl+C，先等接单回复，再取消。
            if node.send_goal_future is not None:
                if not node.send_goal_future.done():
                    rclpy.spin_until_future_complete(
                        node, node.send_goal_future, timeout_sec=5.0
                    )
                # 处理接单回调，使 goal_handle 和 result_future 就绪。
                rclpy.spin_once(node, timeout_sec=0.0)
                if not node.send_goal_future.done():
                    node.get_logger().warn(
                        '等待接单回复超时，无法确认任务状态，请检查服务端'
                    )

            node.cancel_patrol(reason='收到 Ctrl+C')

            if node.result_future is not None:
                rclpy.spin_until_future_complete(
                    node, node.result_future, timeout_sec=5.0
                )
                # 处理最终结果日志回调。
                rclpy.spin_once(node, timeout_sec=0.0)
                if node.result_future.done():
                    node.result_callback(node.result_future)
                else:
                    node.get_logger().warn(
                        '等待任务结果超时，尚未确认停车，请检查服务端'
                    )
        except KeyboardInterrupt:
            node.get_logger().warn('再次收到 Ctrl+C，立即退出，任务状态未确认')
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        signal.signal(signal.SIGINT, previous_handler)
