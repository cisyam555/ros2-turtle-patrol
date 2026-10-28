import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from patrol_interfaces.action import Patrol
from geometry_msgs.msg import Point

class PatrolClient(Node):
    def __init__(self):
        super().__init__('patrol_client')

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

    def feedback_callback(self, feedback_msg):
        feedback = feedback_msg.feedback

        self.get_logger().info(
            f'前往航点 {feedback.current_waypoint}/3，'
            f'剩余距离 {feedback.remaining_distance:.2f}'
        )

    def result_callback(self, future):
        response = future.result()
        result = response.result

        self.get_logger().info(
            f'任务结束：状态码={response.status}，'
            f'全部完成={result.completed}，'
            f'已到达航点数={result.visited_count}'
        )
def main(args=None):
    rclpy.init(args=args)
    node = PatrolClient()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()