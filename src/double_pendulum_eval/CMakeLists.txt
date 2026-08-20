cmake_minimum_required(VERSION 3.8)
project(double_pendulum_eval)

find_package(ament_cmake REQUIRED)

install(
  PROGRAMS disturbance.py
  DESTINATION lib/${PROJECT_NAME}
)

install(
  DIRECTORY scenarios
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
