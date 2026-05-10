from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():

    # ── NODO VISION ──────────────────────────────────────────────────────
    # Se suscribe a /camera/image_raw, que es el mismo tópico tanto en el
    # robot real como en Gazebo (turtlebot3_burger_cam/model.sdf).
    # No hace falta remap ni parámetro especial — ambos entornos coinciden.
    vision_node = Node(
        package='patricio_captacion',
        executable='vision_node',
        name='vision_node',
        parameters=[{
            'image_topic': '/camera/image_raw',
        }],
        output='screen',
    )

    # ── WEB VIDEO SERVER ─────────────────────────────────────────────────
    # Sirve el stream MJPEG en:
    # http://<IP_ROBOT>:8080/stream?topic=/patricio/camera_processed
    # El frontend consume exactamente esa URL.
    web_video_server_node = Node(
        package='web_video_server',
        executable='web_video_server',
        name='web_video_server',
        parameters=[{
            'port': 8080,
            'server_threads': 2,
        }],
        output='screen',
    )

    return LaunchDescription([
        vision_node,
        web_video_server_node,
    ])