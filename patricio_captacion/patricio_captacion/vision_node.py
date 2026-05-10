import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
import cv2


class VisionNode(Node):
    """
    Nodo de visión unificado para el robot Patricio.

    Se suscribe a un tópico de imagen configurable por parámetro,
    aplica un filtro OpenCV sobre cada frame y publica el resultado
    en /patricio/camera_processed para que web_video_server lo sirva
    como stream MJPEG al panel de administración.
    """

    def __init__(self):
        super().__init__('vision_node')

        # ── 1. PARÁMETRO DE TÓPICO ──────────────────────────────────────
        # Permite cambiar la fuente de imagen sin tocar el código.
        # - Robot real:  /camera/image_raw  (valor por defecto)
        # - Gazebo:      se sobreescribe desde el launch file
        self.declare_parameter('image_topic', '/camera/image_raw')
        image_topic = (
            self.get_parameter('image_topic')
            .get_parameter_value()
            .string_value
        )

        # ── 2. PUENTE ROS2 ↔ OPENCV ────────────────────────────────────
        # CvBridge traduce sensor_msgs/Image (bytes ROS2) a numpy array
        # (formato que entiende OpenCV) y viceversa.
        # Se instancia una sola vez para reutilizarla en cada callback.
        self.bridge = CvBridge()

        # ── 3. SUBSCRIBER ───────────────────────────────────────────────
        # Escucha el tópico resuelto desde el parámetro.
        # El callback se ejecuta automáticamente cada vez que llega un frame.
        # QoS = 10: cola de hasta 10 mensajes antes de descartar los más viejos.
        self.subscription = self.create_subscription(
            Image,
            image_topic,
            self.image_callback,
            10
        )

        # ── 4. PUBLISHER ────────────────────────────────────────────────
        # Publica la imagen procesada en el tópico fijo de salida.
        # web_video_server se configura para leer exactamente este tópico.
        self.publisher = self.create_publisher(
            Image,
            '/patricio/camera_processed',
            10
        )

        self.get_logger().info(
            f'VisionNode arrancado. Escuchando: {image_topic}'
        )

    # ── CALLBACK ────────────────────────────────────────────────────────
    def image_callback(self, msg: Image):
        """
        Se ejecuta una vez por cada frame recibido.

        Flujo:
          sensor_msgs/Image  →  cv2.Mat (numpy)  →  filtro  →  sensor_msgs/Image  →  publish
        """

        # Paso A: convertir mensaje ROS2 → array NumPy en formato BGR
        # 'bgr8' = 8 bits por canal, orden Blue-Green-Red (estándar OpenCV)
        # desired_encoding='bgr8' fuerza la conversión aunque la cámara
        # envíe otro encoding (ej: rgb8, mono8, yuv422).
        try:
            frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        except Exception as e:
            self.get_logger().error(f'CvBridge error al recibir imagen: {e}')
            return

        # Paso B: aplicar filtro OpenCV
        # GaussianBlur suaviza la imagen difuminando el ruido.
        # Kernel (15, 15): tamaño de la máscara en píxeles (debe ser impar).
        # sigmaX = 0: OpenCV calcula la desviación estándar automáticamente.
        # Efecto visible en la web: imagen claramente desenfocada vs original.
        processed = cv2.GaussianBlur(frame, (15, 15), 0)

        # Paso C: convertir array NumPy → mensaje ROS2
        try:
            out_msg = self.bridge.cv2_to_imgmsg(processed, encoding='bgr8')
        except Exception as e:
            self.get_logger().error(f'CvBridge error al publicar imagen: {e}')
            return

        # Paso D: copiar la cabecera original (timestamp + frame_id)
        # Esto preserva la sincronización temporal con otros sensores del robot.
        out_msg.header = msg.header

        # Paso E: publicar en /patricio/camera_processed
        self.publisher.publish(out_msg)


# ── PUNTO DE ENTRADA ────────────────────────────────────────────────────
def main(args=None):
    rclpy.init(args=args)          # Arranca el sistema ROS2
    node = VisionNode()            # Crea el nodo (ejecuta __init__)
    rclpy.spin(node)               # Bucle: procesa callbacks hasta Ctrl+C
    node.destroy_node()            # Limpia recursos del nodo
    rclpy.shutdown()               # Apaga el sistema ROS2


if __name__ == '__main__':
    main()