"""Phase 1 bringup: spawn the double pendulum in Gazebo Sim with
ros2_control loaded, so /joint_states and a raw effort command topic exist.

    ros2 launch double_pendulum_description spawn.launch.py
    ros2 launch double_pendulum_description spawn.launch.py headless:=false

Verify with:
    ros2 topic echo /joint_states
    ros2 topic pub /effort_controller/commands std_msgs/msg/Float64MultiArray \
        "{data: [5.0, 0.0]}"

GUI notes: WSLg's Intel iGPU driver has segfaulted on this machine's Ogre2
renderer before. headless:=false sets LIBGL_ALWAYS_SOFTWARE=1 (forces Mesa's
llvmpipe software rasterizer instead of the native driver) as a first
mitigation -- untested from this tool's own sandbox (it kills any gz sim
GUI process outright, sandbox-side, unrelated to the driver bug), so try it
yourself; if it still segfaults, see private/기획서 notes for fallbacks
(e.g. `ogre` render engine instead of `ogre2`, or record a video headless
and play it back instead of a live window).
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    RegisterEventHandler,
    SetEnvironmentVariable,
)
from launch.event_handlers import OnProcessExit
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import Command, LaunchConfiguration, PathJoinSubstitution, PythonExpression
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    pkg_description = get_package_share_directory("double_pendulum_description")

    headless_arg = DeclareLaunchArgument(
        "headless",
        default_value="true",
        description="true = server only (-s), no 3D window. "
        "false = also open the GUI window (needs a working WSLg/GPU setup).",
    )
    headless = LaunchConfiguration("headless")

    # only takes effect when headless=false; harmless otherwise
    force_software_render = SetEnvironmentVariable("LIBGL_ALWAYS_SOFTWARE", "1")

    xacro_path = PathJoinSubstitution(
        [FindPackageShare("double_pendulum_description"), "urdf", "double_pendulum.urdf.xacro"]
    )
    robot_description = {
        "robot_description": ParameterValue(Command(["xacro ", xacro_path]), value_type=str)
    }

    world_path = os.path.join(pkg_description, "launch", "empty_world.sdf")

    gz_sim = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                get_package_share_directory("ros_gz_sim"), "launch", "gz_sim.launch.py"
            )
        ),
        launch_arguments={
            "gz_args": PythonExpression(
                ['"-s -r ', world_path, '" if "', headless, '" == "true" else "-r ', world_path, '"']
            )
        }.items(),
    )

    robot_state_publisher = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        output="screen",
        parameters=[robot_description],
    )

    spawn_entity = Node(
        package="ros_gz_sim",
        executable="create",
        arguments=["-topic", "robot_description", "-name", "double_pendulum", "-z", "0.0"],
        output="screen",
    )

    # bridge sim clock so ROS2 nodes (controller_manager included) use sim time
    clock_bridge = Node(
        package="ros_gz_bridge",
        executable="parameter_bridge",
        arguments=["/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock"],
        output="screen",
    )

    joint_state_broadcaster_spawner = Node(
        package="controller_manager",
        executable="spawner",
        arguments=["joint_state_broadcaster"],
        output="screen",
    )

    effort_controller_spawner = Node(
        package="controller_manager",
        executable="spawner",
        arguments=["effort_controller"],
        output="screen",
    )

    # load controllers only after the entity (and its in-process
    # controller_manager, started by the gz_ros2_control plugin) exists
    delayed_controllers = RegisterEventHandler(
        event_handler=OnProcessExit(
            target_action=spawn_entity,
            on_exit=[joint_state_broadcaster_spawner, effort_controller_spawner],
        )
    )

    return LaunchDescription(
        [
            headless_arg,
            force_software_render,
            gz_sim,
            clock_bridge,
            robot_state_publisher,
            spawn_entity,
            delayed_controllers,
        ]
    )
