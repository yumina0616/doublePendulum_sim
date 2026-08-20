cmake_minimum_required(VERSION 3.8)
project(double_pendulum_eval)

find_package(ament_cmake REQUIRED)

install(
  PROGRAMS disturbance.py run_experiment.py
  DESTINATION lib/${PROJECT_NAME}
)
install(
  FILES metrics.py
  DESTINATION lib/${PROJECT_NAME}
)

install(
  DIRECTORY scenarios
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
