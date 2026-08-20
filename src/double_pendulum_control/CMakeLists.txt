cmake_minimum_required(VERSION 3.8)
project(double_pendulum_control)

find_package(ament_cmake REQUIRED)

install(
  DIRECTORY config
  DESTINATION share/${PROJECT_NAME}
)

# controller_node.py is the ros2 run entry point; pd_controller.py is a
# plain sibling module it imports (Python adds a directly-run script's own
# directory to sys.path, so installing both to the same lib/ dir is enough
# -- no need for a full ament_python package just for this).
install(
  PROGRAMS controller_node.py lqr_node.py
  DESTINATION lib/${PROJECT_NAME}
)
install(
  FILES pd_controller.py linear_model.py lqr_controller.py
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()
