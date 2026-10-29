"""读取两轮 turtlesim bag，按首次非零速度命令对齐并比较位置。"""
import argparse
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import rosbag2_py
from geometry_msgs.msg import Twist
from rclpy.serialization import deserialize_message
from turtlesim.msg import Pose


def read_run(bag_path):
    reader = rosbag2_py.SequentialReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=str(bag_path), storage_id='sqlite3'),
        rosbag2_py.ConverterOptions(
            input_serialization_format='cdr',
            output_serialization_format='cdr',
        ),
    )
    poses = []
    commands = []
    while reader.has_next():
        topic, data, timestamp = reader.read_next()
        if topic == '/turtle1/pose':
            pose = deserialize_message(data, Pose)
            poses.append((timestamp, pose.x, pose.y, pose.theta))
        elif topic == '/turtle1/cmd_vel':
            cmd = deserialize_message(data, Twist)
            values = [cmd.linear.x, cmd.linear.y, cmd.linear.z,
                      cmd.angular.x, cmd.angular.y, cmd.angular.z]
            if not np.all(np.isfinite(values)):
                raise ValueError(f'速度含非有限值：{bag_path}')
            commands.append((timestamp, any(abs(v) > 1e-6 for v in values)))

    if len(poses) < 2:
        raise ValueError(f'位姿消息不足：{bag_path}')
    poses.sort(key=lambda row: row[0])
    commands.sort(key=lambda row: row[0])
    active = [stamp for stamp, moving in commands if moving]
    if not active:
        raise ValueError(f'未录到非零速度命令：{bag_path}')

    # 零时刻包含原地转向；不能用第一条位姿，因为录制等待时间不同。
    start_ns = active[0]
    final_stops = [stamp for stamp, moving in commands
                   if stamp > active[-1] and not moving]
    if not final_stops:
        raise ValueError(f'未录到最终停车命令，请确认录制完整：{bag_path}')
    stop_ns = final_stops[0]
    if poses[0][0] > start_ns or poses[-1][0] < stop_ns:
        raise ValueError(f'位姿未覆盖完整命令运动区间：{bag_path}')

    # 先用整数时间戳相减，再转秒，避免大时间戳丢失精度。
    times = np.array([(row[0] - start_ns) / 1e9 for row in poses])
    xy = np.array([[row[1], row[2]] for row in poses], dtype=float)
    if not np.all(np.isfinite(xy)):
        raise ValueError(f'位姿含非有限值：{bag_path}')
    # 同一个时间戳有多条消息时保留最后一条，供线性插值使用。
    keep = np.r_[np.diff(times) > 0, True]
    times, xy = times[keep], xy[keep]
    if len(times) < 2:
        raise ValueError(f'不同时间戳的位姿消息不足：{bag_path}')
    return {
        'path': str(bag_path), 'times': times, 'xy': xy,
        'start_ns': start_ns, 'stop_ns': stop_ns,
        'duration': (stop_ns - start_ns) / 1e9,
        'pose_count': len(poses), 'command_count': len(commands),
        'initial_theta': float(poses[0][3]),
    }


def compare_positions(run1, run2, step):
    if not np.isfinite(step) or step <= 0:
        raise ValueError('采样间隔必须是正的有限数值')
    # 仅比较双方都覆盖的运动时间，禁止外推较短的一轮。
    start = max(0.0, run1['times'][0], run2['times'][0])
    end = min(run1['duration'], run2['duration'],
              run1['times'][-1], run2['times'][-1])
    if end - start < step:
        raise ValueError('公共运动时间不足，无法对比')
    grid = start + np.arange(int(np.floor((end - start) / step)) + 1) * step
    aligned = []
    for run in [run1, run2]:
        aligned.append(np.column_stack([
            np.interp(grid, run['times'], run['xy'][:, axis])
            for axis in [0, 1]
        ]))
    errors = np.linalg.norm(aligned[0] - aligned[1], axis=1)
    return grid, aligned[0], aligned[1], errors


def main():
    project_dir = Path(__file__).resolve().parents[1]
    bags_dir = project_dir / 'bags'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bag1', type=Path, default=bags_dir / 'compare_run_01_retry')
    parser.add_argument('--bag2', type=Path, default=bags_dir / 'compare_run_02')
    parser.add_argument('--output', type=Path, default=bags_dir / 'compare_results')
    parser.add_argument('--step', type=float, default=0.05, help='公共采样间隔，秒')
    args = parser.parse_args()
    run1, run2 = read_run(args.bag1), read_run(args.bag2)
    grid, xy1, xy2, errors = compare_positions(run1, run2, args.step)
    output = args.output
    output.mkdir(parents=True, exist_ok=True)

    report = {
        'alignment': 'First recorded nonzero cmd_vel is t=0 (includes turning).',
        'units': 'turtlesim coordinate units; seconds',
        'interpolation': 'Linear XY interpolation; common motion interval only; no extrapolation.',
        'step_seconds': args.step,
        'common_start_seconds': float(grid[0]),
        'common_end_seconds': float(grid[-1]),
        'aligned_samples': len(grid),
        'position_error_mean': float(np.mean(errors)),
        'position_error_rmse': float(np.sqrt(np.mean(errors ** 2))),
        'position_error_max': float(np.max(errors)),
        'initial_position_difference': float(np.linalg.norm(run1['xy'][0] - run2['xy'][0])),
        'initial_heading_difference_rad': float(np.arctan2(
            np.sin(run1['initial_theta'] - run2['initial_theta']),
            np.cos(run1['initial_theta'] - run2['initial_theta']))),
        # 末位置差单独比较，不把它误当成同一相对时刻的误差。
        'final_recorded_position_difference': float(np.linalg.norm(run1['xy'][-1] - run2['xy'][-1])),
        'runs': [{key: value for key, value in run.items()
                  if key not in ['times', 'xy']} for run in [run1, run2]],
    }
    (output / 'metrics.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    with (output / 'aligned_positions.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['time_s', 'run1_x', 'run1_y', 'run2_x', 'run2_y', 'position_error'])
        writer.writerows(zip(grid, xy1[:, 0], xy1[:, 1], xy2[:, 0], xy2[:, 1], errors))

    fig, ax = plt.subplots(figsize=(7, 7))
    for run, style, label in [(run1, '-', 'Run 1'), (run2, '--', 'Run 2')]:
        ax.plot(run['xy'][:, 0], run['xy'][:, 1], style, label=label)
        ax.scatter(*run['xy'][0], marker='o')
        ax.scatter(*run['xy'][-1], marker='s')
    ax.set(title='Two patrol runs: XY trajectories', xlabel='X (turtlesim units)',
           ylabel='Y (turtlesim units)')
    ax.set_aspect('equal', adjustable='box')
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output / 'trajectory_xy.png', dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(grid, errors)
    ax.set(title='Position difference at aligned relative times',
           xlabel='Seconds since first nonzero command', ylabel='Position error (turtlesim units)')
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(output / 'position_error.png', dpi=180)
    plt.close(fig)

    for i, run in enumerate([run1, run2], 1):
        print(f"第{i}轮：位姿{run['pose_count']}条，速度{run['command_count']}条，"
              f"命令运动区间{run['duration']:.3f}秒")
    print(f'公共对比区间：{grid[0]:.3f}～{grid[-1]:.3f}秒，共{len(grid)}个采样点')
    print(f"平均位置误差：{report['position_error_mean']:.6f}")
    print(f"位置误差 RMSE：{report['position_error_rmse']:.6f}")
    print(f"最大位置误差：{report['position_error_max']:.6f}")
    print(f"最终记录位置差：{report['final_recorded_position_difference']:.6f}")
    print('以上位置数值单位均为 turtlesim 坐标单位。')
    print(f'图片、JSON统计和CSV对齐数据已保存：{output}')
    print('结果包含控制与消息调度差异，不代表真实机器人的定位精度。')


if __name__ == '__main__':
    main()
