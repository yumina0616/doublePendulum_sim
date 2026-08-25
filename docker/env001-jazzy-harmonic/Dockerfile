# ENV-001: Ubuntu 24.04 + ROS2 Jazzy + Gazebo Sim (Harmonic) -- the
# OFFICIAL pairing, unlike this project's primary environment (Ubuntu
# 22.04 + ROS2 Humble + Gazebo Harmonic, which needed gz_ros2_control
# built from source because apt's Humble build targets Gazebo Fortress).
# Used to test whether PHYS-001's ~4.45 degree ROS2/DDS-layer variance is
# specific to the unofficial Humble+Harmonic combination.
FROM osrf/ros:jazzy-desktop

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ros-jazzy-ros-gz \
    ros-jazzy-gz-ros2-control \
    ros-jazzy-xacro \
    ros-jazzy-ros2-control \
    ros-jazzy-ros2-controllers \
    ros-jazzy-joint-state-publisher \
    python3-scipy \
    python3-sympy \
    python3-numpy \
    python3-yaml \
    python3-colcon-common-extensions \
    curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /ws/src

# only the project's own packages -- gz_ros2_control is NOT vendored here
# since ros-jazzy-gz-ros2-control provides it directly via apt (the whole
# point of this comparison: an officially-packaged combination needs no
# source build at all).
COPY double_pendulum_description double_pendulum_description
COPY double_pendulum_control double_pendulum_control
COPY double_pendulum_eval double_pendulum_eval

WORKDIR /ws
RUN /bin/bash -c "source /opt/ros/jazzy/setup.bash && colcon build --symlink-install"

RUN echo "source /opt/ros/jazzy/setup.bash" >> /root/.bashrc && \
    echo "source /ws/install/setup.bash" >> /root/.bashrc

CMD ["/bin/bash"]
