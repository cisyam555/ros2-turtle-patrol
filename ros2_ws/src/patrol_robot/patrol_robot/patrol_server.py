from rclpy.task import Future
import hashlib
import fcntl
import logging
import math
import os
import tempfile
import rclpy
from rclpy.node import Node
from rclpy.signals import SignalHandlerOptions
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from patrol_interfaces.action import Patrol
from turtlesim.msg import Pose
from geometry_msgs.msg import Point, Twist




class PatrolServer(Node):
    def __init__(self):
        super().__init__('patrol_server')

        self.declare_parameter('linear_speed', 1.0)
        self.declare_parameter('angular_speed', 1.0)
        self.declare_parameter('turtle_name', 'turtle1')
        self.declare_parameter('waypoint_timeout', 30.0)
        self.declare_parameter('return_timeout', 60.0)

        self.pose = None
        self.home_point = None          # 本次任务的出发位置，返航目标
        self.motion_start_time = None   # 当前航点开始时间
        self.returning = False          # 是否处于返航段

        
        self.motion_future = None
        self.target_point = None      #保存目标的 x、y，前进时需要不断计算剩余距离
        self.motion_state = 'idle'    #'IDLE'表示空闲，暂时没有运动任务
                                      #motion_state记录当前在等待、转向还是前进
        self.active_goal_handle = None
        self.current_waypoint = 0

        # 每次接收有效的新任务，编号递增
        self.goal_generation = 0

        # 当前拥有海龟控制权的任务编号
        self.active_generation = None

        # 通知等待的新任务：旧任务已经退出并完成清理
        self.goal_done_future = None

        self.goal_contexts = {}

        self.cmd_vel_publisher = self.create_publisher(
            Twist,
            f'/{self.get_parameter("turtle_name").value}/cmd_vel',
            10,
        )

        self.pose_subscriber = self.create_subscription(
            Pose,
            f'/{self.get_parameter("turtle_name").value}/pose',
            self.pose_callback,
            10
        )

        self.action_server = None
        self.get_logger().info('巡逻节点已启动，等待海龟位姿')

        self.control_timer = self.create_timer(
            0.05,
            self.control_loop,
        )


    def pose_callback(self, msg):
        first_message = self.pose is None
        self.pose = msg

        if first_message:
            self.get_logger().info(
                f'收到海龟位姿：x={msg.x:.2f}, '
                f'y={msg.y:.2f}, theta={msg.theta:.2f}'
            )

            self.action_server = ActionServer(
                self,
                Patrol,
                'patrol',
                self.execute_callback,
                goal_callback=self.goal_callback,
                handle_accepted_callback=self.handle_accepted_callback,
                cancel_callback=self.cancel_callback,
            )

            self.get_logger().info('巡逻服务已就绪，等待任务')

    def stop_turtle(self):
        stop_msg = Twist()
        self.cmd_vel_publisher.publish(stop_msg)

    def goal_callback(self, goal_request):
        if self.pose is None:
            self.get_logger().warn('尚未收到位姿，拒绝新任务')
            return GoalResponse.REJECT

        if len(goal_request.waypoints) == 0:
            self.get_logger().warn('航点列表为空，拒绝新任务')
            return GoalResponse.REJECT

        for point in goal_request.waypoints:
            if not (
                math.isfinite(point.x)
                and math.isfinite(point.y)
                and 0.5 <= point.x <= 10.5
                and 0.5 <= point.y <= 10.5
            ):
                self.get_logger().warn(
                    '航点无效，拒绝新任务：'
                    'x、y 必须是 0.5～10.5 内的有限数值'
                )
                return GoalResponse.REJECT

        self.get_logger().info('新任务航点检查通过，允许接收')
        return GoalResponse.ACCEPT

    def handle_accepted_callback(self, goal_handle):
        self.goal_generation += 1
        generation = self.goal_generation

        # 保存前一个任务的退出通知
        previous_done = self.goal_done_future

        # 为本任务创建独立的退出通知
        current_done = Future()
        self.goal_done_future = current_done

        # 使用 Action 的唯一任务 ID 保存对应信息
        goal_id = bytes(goal_handle.goal_id.uuid)
        self.goal_contexts[goal_id] = {
            'generation': generation,
            'previous_done': previous_done,
            'current_done': current_done,
        }

        self.get_logger().info(
            f'已接收任务 #{generation}，准备交接控制权'
        )

        # 交给执行器调度 execute_callback
        goal_handle.execute()

    def cancel_callback(self, goal_handle):
        self.get_logger().info('收到取消请求，允许取消')
        return CancelResponse.ACCEPT


    def control_loop(self):
        # 取消优先于继续运动，并唤醒等待当前航点完成的执行回调。
        if self.active_goal_handle is not None:
            if self.active_goal_handle.is_cancel_requested:
                self.stop_turtle()
                self.target_point = None
                self.motion_state = 'idle'

                if self.motion_future is not None:
                    if not self.motion_future.done():
                        self.motion_future.set_result('canceled')
                return

        # 出现更新的任务时，停止旧任务并唤醒执行回调
        if (
            self.active_generation is not None
            and self.active_generation != self.goal_generation
        ):
            self.stop_turtle()
            self.target_point = None
            self.motion_state = 'idle'

            if self.motion_future is not None:
                if not self.motion_future.done():
                    self.motion_future.set_result('preempted')
            return

        # 单个航点（含返航段）超时，唤醒执行回调由它决定返航或停车。
        if (
            self.motion_future is not None
            and not self.motion_future.done()
            and self.motion_start_time is not None
        ):
            elapsed = (
                self.get_clock().now() - self.motion_start_time
            ).nanoseconds / 1e9

            # 返航段要留出掉头时间，使用更宽松的独立超时。
            timeout = (
                self.get_parameter('return_timeout').value
                if self.returning
                else self.get_parameter('waypoint_timeout').value
            )

            if elapsed > timeout:
                self.stop_turtle()
                self.target_point = None
                self.motion_state = 'idle'
                stage = '返航' if self.returning else '航点'
                self.get_logger().warn(
                    f'{stage}超时（{elapsed:.1f} 秒），结束当前运动段'
                )
                self.motion_future.set_result('timeout')
                return

        if self.pose is None or self.target_point is None:
            return

        dx = self.target_point.x - self.pose.x
        dy = self.target_point.y - self.pose.y
        distance = math.hypot(dx, dy)

        if self.active_goal_handle is not None:
            feedback = Patrol.Feedback()
            feedback.current_waypoint = self.current_waypoint
            feedback.remaining_distance = distance
            self.active_goal_handle.publish_feedback(feedback)

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
                    self.motion_future.set_result('reached')
            return

        cmd = Twist()
        angular_speed = self.get_parameter('angular_speed').value

        if self.motion_state == 'turn':
            if abs(angle_error) < 0.03:
                self.motion_state = 'drive'
                self.get_logger().info('方向已对准，开始前进')
            else:
                cmd.angular.z = max(
                    -angular_speed,
                    min(angular_speed, 2.0 * angle_error)
                )

        elif self.motion_state == 'drive':
            if abs(angle_error) > 0.30:
                self.motion_state = 'turn'
            else:
                linear_speed = self.get_parameter('linear_speed').value
                cmd.linear.x = min(linear_speed, distance)
                cmd.angular.z = max(
                    -angular_speed,
                    min(angular_speed, 2.0 * angle_error)
                )

        self.cmd_vel_publisher.publish(cmd)


    async def execute_callback(self, goal_handle):
        waypoints = goal_handle.request.waypoints

        result = Patrol.Result()
        result.completed = False
        result.visited_count = 0

        goal_id = bytes(goal_handle.goal_id.uuid)
        context = self.goal_contexts.pop(goal_id)

        generation = context['generation']
        previous_done = context['previous_done']
        current_done = context['current_done']

        # 这个内部函数只负责判断和结束任务，不清理共享控制状态
        def finish_if_interrupted():
            if goal_handle.is_cancel_requested:
                goal_handle.canceled()
                self.get_logger().info(
                    f'任务 #{generation} 已取消，'
                    f'已到达 {result.visited_count} 个航点'
                )
                return True

            if generation != self.goal_generation:
                goal_handle.abort()
                self.get_logger().info(
                    f'任务 #{generation} 被新任务抢占，'
                    f'已到达 {result.visited_count} 个航点'
                )
                return True

            return False

        # 巡逻和返航共用同一段导航逻辑
        async def move_to_point(target, returning=False):
            self.motion_future = Future()
            self.target_point = target
            self.motion_state = 'turn'
            self.motion_start_time = self.get_clock().now()
            self.returning = returning

            return await self.motion_future

        try:
            # 必须等旧任务完成停车和清理，才能接管
            if previous_done is not None:
                if not previous_done.done():
                    self.get_logger().info(
                        f'任务 #{generation} 等待旧任务退出'
                    )
                    await previous_done

            # 等待期间可能被取消，或被更新的任务替代
            if finish_if_interrupted():
                return result

            if self.pose is None:
                goal_handle.abort()
                self.get_logger().warn('尚未收到海龟位置')
                return result

            # 从这里开始，本任务拥有共享控制状态
            self.active_generation = generation
            self.active_goal_handle = goal_handle

            self.home_point = Point(
                x=self.pose.x,
                y=self.pose.y,
                z=0.0,
            )

            self.get_logger().info(
                f'任务 #{generation} 取得控制权，'
                f'记录返航点 '
                f'({self.home_point.x:.2f}, '
                f'{self.home_point.y:.2f})'
            )

            for index, target in enumerate(waypoints):
                if finish_if_interrupted():
                    return result

                self.current_waypoint = index + 1

                self.get_logger().info(
                    f'任务 #{generation} '
                    f'前往航点 {index + 1}/{len(waypoints)}：'
                    f'({target.x:.2f}, {target.y:.2f})'
                )

                outcome = await move_to_point(target)

                # 已经实际到达的航点，即使随后发生抢占也应计数
                if outcome == 'reached':
                    result.visited_count += 1
                    self.get_logger().info(
                        f'已到达 {result.visited_count} 个航点'
                    )

                # 每次异步等待结束后，都重新检查取消和抢占
                if finish_if_interrupted():
                    return result

                if outcome == 'timeout':
                    self.get_logger().info(
                        '开始返航到任务起点'
                    )

                    return_outcome = await move_to_point(
                        self.home_point,
                        returning=True,
                    )

                    # 返航途中同样允许取消和抢占
                    if finish_if_interrupted():
                        return result

                    if return_outcome == 'reached':
                        self.get_logger().info(
                            '已返回起点，但巡逻未完成'
                        )
                    else:
                        self.get_logger().warn(
                            '返航未到达起点，已停车'
                        )

                    goal_handle.abort()
                    return result

                if outcome != 'reached':
                    goal_handle.abort()
                    self.get_logger().warn(
                        '运动未完成，任务中止'
                    )
                    return result

            result.completed = True
            goal_handle.succeed()
            self.get_logger().info(
                f'任务 #{generation} 全部航点巡逻完成'
            )
            return result

        finally:
            try:
                # 只有当前控制者，才能停车和清理共享状态
                if self.active_generation == generation:
                    self.stop_turtle()

                    self.active_goal_handle = None
                    self.active_generation = None
                    self.current_waypoint = 0

                    self.target_point = None
                    self.motion_state = 'idle'
                    self.motion_future = None
                    self.motion_start_time = None
                    self.returning = False
                    self.home_point = None
            finally:
                # 清理结束后，才允许后面的任务继续
                if not current_done.done():
                    current_done.set_result(True)
            

def main(args=None):
    rclpy.init(args=args, signal_handler_options=SignalHandlerOptions.NO)
    node = PatrolServer()

    lock_file = None
    owns_control = False

    try:
        domain = int(os.environ.get('ROS_DOMAIN_ID', '0'))

        # 使用实际发布速度的话题区分控制对象
        control_topic = node.cmd_vel_publisher.topic_name
        topic_key = hashlib.sha256(
            control_topic.encode('utf-8')
        ).hexdigest()

        lock_path = os.path.join(
            tempfile.gettempdir(),
            f'patrol_control_{os.getuid()}_{domain}_{topic_key}.lock',
        )

        lock_file = open(lock_path, 'a')

        try:
            fcntl.flock(
                lock_file,
                fcntl.LOCK_EX | fcntl.LOCK_NB
            )
        except BlockingIOError:
            node.get_logger().error(
                f'已有服务端控制 {control_topic}，本次不重复启动'
            )
            return 1

        owns_control = True

        node.get_logger().info(
            f'已取得控制权：{control_topic}'
        )

        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    finally:
        # 只有取得控制权的实例，退出时才允许发停车指令
        if owns_control and rclpy.ok():
            node.stop_turtle()

        node.destroy_node()

        # 停车和节点清理完成后，再释放控制权
        if lock_file is not None:
            lock_file.close()

        if rclpy.ok():
            rclpy.shutdown()
