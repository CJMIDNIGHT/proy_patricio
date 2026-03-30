import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, DeclareLaunchArgument
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

def generate_launch_description():

    pkg_gazebo_ros = get_package_share_directory('turtlebot3_gazebo')
    world_file = os.path.join(
        get_package_share_directory('patricio_nav_punto'),
        'worlds',
        'prueba_mundo.world')

    use_sim_time = LaunchConfiguration('use_sim_time', default='true')

    return LaunchDescription([

        DeclareLaunchArgument(
            'use_sim_time',
            default_value='true',
            description='Usar reloj de Gazebo'),

        # Gazebo server
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(pkg_gazebo_ros, 'launch', 'gzserver.launch.py')),
            launch_arguments={'world': world_file}.items(),
        ),

        # Gazebo client (interfaz visual)
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(pkg_gazebo_ros, 'launch', 'gzclient.launch.py')),
        ),

        # Spawn TurtleBot3 en el centro
        Node(
            package='gazebo_ros',
            executable='spawn_entity.py',
            arguments=[
                '-entity', 'turtlebot3_burger',
                '-file', os.path.join(
                    get_package_share_directory('turtlebot3_description'),
                    'urdf', 'turtlebot3_burger.urdf'),
                '-x', '0.0',
                '-y', '0.0',
                '-z', '0.01',
            ],
            output='screen'
        ),
    ])
