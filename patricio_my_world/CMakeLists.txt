cmake_minimum_required(VERSION 3.5)
project(patricio_my_world)

find_package(ament_cmake REQUIRED)

install(DIRECTORY worlds models launch maps
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
