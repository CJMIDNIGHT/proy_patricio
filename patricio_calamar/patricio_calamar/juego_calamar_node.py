#!/usr/bin/env python3

"""
Nodo ROS2 para el juego del Calamar — "Luz Roja, Luz Verde".

Estados:
  ESPERA      — nodo idle, esperando comando de inicio
  LUZ_VERDE   — movimiento permitido (no se procesa cámara)
  LUZ_ROJA    — detección activa mediante OpenCV (diferencia de frames)

Tópicos:
  Suscribe : /patricio/calamar/cmd    (std_msgs/String)
             Comandos: START_AUTO | CAMBIAR_A_VERDE | CAMBIAR_A_ROJO | STOP
  Publica  : /patricio/calamar/status (std_msgs/String)
             Estados: ESPERA | LUZ_VERDE | LUZ_ROJA | INFRACCION
           : /patricio/alerta_juego   (std_msgs/String)
             Publica "INFRACCION" cuando se detecta movimiento en LUZ_ROJA
"""

import random
import threading
import time

import cv2
import numpy as np

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


# ── Constantes de estado ──────────────────────────────────
ESTADO_ESPERA = 'ESPERA'
ESTADO_VERDE = 'LUZ_VERDE'
ESTADO_ROJO = 'LUZ_ROJA'


class JuegoCalamarNode(Node):
    """
    Nodo principal del Juego del Calamar.

    Gestiona la máquina de estados, la detección de movimiento
    por OpenCV y la comunicación con la interfaz web vía ROS 2.
    """

    def __init__(self):
        """Inicializa el nodo, parámetros, publishers y subscribers."""
        super().__init__('juego_calamar_node')

        # ── Parámetros configurables ──────────────────────
        self.declare_parameter('motion_threshold', 3000)
        self.declare_parameter('camera_index', 0)
        self.declare_parameter('verde_min_sec', 2.0)
        self.declare_parameter('verde_max_sec', 5.0)
        self.declare_parameter('rojo_min_sec', 2.0)
        self.declare_parameter('rojo_max_sec', 4.0)

        self.motion_threshold = (
            self.get_parameter('motion_threshold')
            .get_parameter_value()
            .integer_value
        )
        self.camera_index = (
            self.get_parameter('camera_index')
            .get_parameter_value()
            .integer_value
        )
        self.verde_min = (
            self.get_parameter('verde_min_sec')
            .get_parameter_value()
            .double_value
        )
        self.verde_max = (
            self.get_parameter('verde_max_sec')
            .get_parameter_value()
            .double_value
        )
        self.rojo_min = (
            self.get_parameter('rojo_min_sec')
            .get_parameter_value()
            .double_value
        )
        self.rojo_max = (
            self.get_parameter('rojo_max_sec')
            .get_parameter_value()
            .double_value
        )

        # ── Estado interno ────────────────────────────────
        self.estado = ESTADO_ESPERA
        self.stop_requested = False
        self._game_thread = None
        self._cap = None          # cv2.VideoCapture handle
        self._state_lock = threading.Lock()

        # ── ROS publishers ────────────────────────────────
        self.status_pub = self.create_publisher(
            String, '/patricio/calamar/status', 10)
        self.alerta_pub = self.create_publisher(
            String, '/patricio/alerta_juego', 10)

        # ── ROS subscriber ────────────────────────────────
        self.cmd_sub = self.create_subscription(
            String, '/patricio/calamar/cmd', self.cmd_callback, 10)

        self.publish_status(ESTADO_ESPERA)
        self.get_logger().info('juego_calamar_node listo.')

    # ── Comando entrante ──────────────────────────────────

    def cmd_callback(self, msg):
        """
        Procesa comandos recibidos desde la interfaz web.

        Args:
            msg (String): START_AUTO | CAMBIAR_A_VERDE | CAMBIAR_A_ROJO | STOP
        """
        cmd = msg.data.strip().upper()
        self.get_logger().info(f'Comando recibido: {cmd}')

        if cmd == 'START_AUTO':
            self._iniciar_auto()

        elif cmd == 'CAMBIAR_A_VERDE':
            self._set_estado_manual(ESTADO_VERDE)

        elif cmd == 'CAMBIAR_A_ROJO':
            self._set_estado_manual(ESTADO_ROJO)

        elif cmd == 'STOP':
            self._detener()

    # ── Inicio modo automático ────────────────────────────

    def _iniciar_auto(self):
        """Arranca el bucle automático en un hilo separado."""
        with self._state_lock:
            if self.estado != ESTADO_ESPERA:
                self.get_logger().warn('Juego ya en marcha, ignorando START_AUTO.')
                return
            self.stop_requested = False

        self._abrir_camara()
        if self._cap is None:
            self.get_logger().error('No se pudo abrir la cámara. Abortando.')
            return

        self._game_thread = threading.Thread(
            target=self._bucle_automatico, daemon=True)
        self._game_thread.start()

    def _bucle_automatico(self):
        """
        Bucle principal del modo automático.

        Alterna aleatoriamente entre LUZ_VERDE y LUZ_ROJA hasta
        recibir STOP.
        """
        self.get_logger().info('Modo automático iniciado.')

        while not self.stop_requested:
            # ── Fase VERDE ────────────────────────────────
            duracion_verde = random.uniform(self.verde_min, self.verde_max)
            self._cambiar_estado(ESTADO_VERDE)
            self.get_logger().info(
                f'LUZ VERDE durante {duracion_verde:.1f}s')
            self._esperar(duracion_verde)

            if self.stop_requested:
                break

            # ── Fase ROJA ─────────────────────────────────
            duracion_roja = random.uniform(self.rojo_min, self.rojo_max)
            self._cambiar_estado(ESTADO_ROJO)
            self.get_logger().info(
                f'LUZ ROJA durante {duracion_roja:.1f}s')
            self._detectar_movimiento(duracion_roja)

        self._cerrar_camara()
        self._cambiar_estado(ESTADO_ESPERA)
        self.get_logger().info('Modo automático detenido.')

    # ── Modo manual ───────────────────────────────────────

    def _set_estado_manual(self, nuevo_estado):
        """
        Cambia el estado en modo manual.

        Abre/cierra la cámara según sea necesario y lanza o detiene
        el hilo de detección.

        Args:
            nuevo_estado (str): ESTADO_VERDE | ESTADO_ROJO
        """
        with self._state_lock:
            if self.estado == ESTADO_ESPERA:
                # Primera vez que se usa manual: abrir cámara
                self._abrir_camara()
            self.stop_requested = False

        self._cambiar_estado(nuevo_estado)

        if nuevo_estado == ESTADO_ROJO:
            # Lanzar detección sin límite de tiempo (hasta próximo comando)
            self._game_thread = threading.Thread(
                target=self._detectar_movimiento,
                args=(None,),   # None = sin timeout, hasta STOP o cambio
                daemon=True
            )
            self._game_thread.start()

    # ── Detección OpenCV ──────────────────────────────────

    def _detectar_movimiento(self, duracion_seg):
        """
        Captura frames y detecta movimiento por diferencia absoluta.

        Solo activo cuando el estado es LUZ_ROJA.
        Publica INFRACCION en /patricio/alerta_juego si supera umbral.

        Args:
            duracion_seg (float | None): Segundos máximos de detección.
                                         None = infinito (modo manual).
        """
        if self._cap is None:
            self.get_logger().error('Cámara no disponible para detección.')
            return

        frame_anterior = None
        t_inicio = time.time()

        while not self.stop_requested:
            # Verificar estado actual
            with self._state_lock:
                if self.estado != ESTADO_ROJO:
                    break

            # Verificar timeout (modo auto)
            if duracion_seg is not None:
                if time.time() - t_inicio >= duracion_seg:
                    break

            ret, frame = self._cap.read()
            if not ret:
                self.get_logger().warn('No se pudo leer frame de cámara.')
                time.sleep(0.1)
                continue

            # Convertir a escala de grises y difuminar
            gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gris = cv2.GaussianBlur(gris, (21, 21), 0)

            if frame_anterior is None:
                frame_anterior = gris
                continue

            # Diferencia absoluta entre frames consecutivos
            diff = cv2.absdiff(frame_anterior, gris)
            _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
            pixeles_movimiento = int(np.sum(thresh) / 255)

            self.get_logger().debug(
                f'Píxeles en movimiento: {pixeles_movimiento} '
                f'(umbral: {self.motion_threshold})')

            if pixeles_movimiento > self.motion_threshold:
                self.get_logger().info(
                    f'¡INFRACCIÓN detectada! Píxeles: {pixeles_movimiento}')
                self._publicar_infraccion()
                # Pequeña pausa para no saturar con alertas repetidas
                time.sleep(1.0)
                frame_anterior = None   # reset para siguiente comparación
                continue

            frame_anterior = gris
            time.sleep(0.05)    # ~20 fps de análisis

    def _publicar_infraccion(self):
        """Publica mensaje de infracción en ambos tópicos."""
        msg = String()
        msg.data = 'INFRACCION'
        self.alerta_pub.publish(msg)
        self.status_pub.publish(msg)

    # ── Control de estado ─────────────────────────────────

    def _cambiar_estado(self, nuevo):
        """
        Actualiza el estado interno y publica en el tópico de status.

        Args:
            nuevo (str): Nuevo estado
        """
        with self._state_lock:
            self.estado = nuevo
        self.publish_status(nuevo)
        self.get_logger().info(f'Estado → {nuevo}')

    def _detener(self):
        """Para el juego, cierra la cámara y vuelve a ESPERA."""
        self.stop_requested = True
        self._cerrar_camara()
        with self._state_lock:
            self.estado = ESTADO_ESPERA
        self.publish_status(ESTADO_ESPERA)
        self.get_logger().info('Juego detenido.')

    def _esperar(self, segundos):
        """
        Espera activa que respeta stop_requested.

        Args:
            segundos (float): Tiempo a esperar
        """
        t_fin = time.time() + segundos
        while not self.stop_requested and time.time() < t_fin:
            time.sleep(0.1)

    # ── Cámara ────────────────────────────────────────────

    def _abrir_camara(self):
        """Abre la captura de video si no está ya abierta."""
        if self._cap is not None and self._cap.isOpened():
            return
        self._cap = cv2.VideoCapture(self.camera_index)
        if not self._cap.isOpened():
            self.get_logger().error(
                f'No se pudo abrir cámara índice {self.camera_index}')
            self._cap = None
        else:
            self.get_logger().info(
                f'Cámara {self.camera_index} abierta.')

    def _cerrar_camara(self):
        """Libera la captura de video."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            self.get_logger().info('Cámara liberada.')

    # ── Publisher helper ──────────────────────────────────

    def publish_status(self, text):
        """
        Publica el estado actual en /patricio/calamar/status.

        Args:
            text (str): Texto de estado
        """
        msg = String()
        msg.data = text
        self.status_pub.publish(msg)


# ── Entry point ───────────────────────────────────────────

def main(args=None):
    """Función principal que inicializa el nodo ROS2."""
    rclpy.init(args=args)
    node = JuegoCalamarNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node._detener()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()