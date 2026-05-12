#!/usr/bin/env python3

"""
Nodo ROS2 para el juego del Calamar — "Luz Roja, Luz Verde".
"""

import random
import threading
import time

import cv2
import numpy as np
from cv_bridge import CvBridge

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String

ESTADO_ESPERA = 'ESPERA'
ESTADO_VERDE  = 'LUZ_VERDE'
ESTADO_ROJO   = 'LUZ_ROJA'

MOTION_PERCENT_THRESHOLD = 1.5   # % of frame pixels that must change to fire


class JuegoCalamarNode(Node):

    def __init__(self):
        super().__init__('juego_calamar_node')

        self.declare_parameter('motion_threshold', 3000)   # legacy, ignored
        self.declare_parameter('verde_min_sec', 3.0)
        self.declare_parameter('verde_max_sec', 6.0)
        self.declare_parameter('rojo_min_sec',  3.0)
        self.declare_parameter('rojo_max_sec',  5.0)

        self.verde_min = self.get_parameter('verde_min_sec').get_parameter_value().double_value
        self.verde_max = self.get_parameter('verde_max_sec').get_parameter_value().double_value
        self.rojo_min  = self.get_parameter('rojo_min_sec').get_parameter_value().double_value
        self.rojo_max  = self.get_parameter('rojo_max_sec').get_parameter_value().double_value

        self.estado         = ESTADO_ESPERA
        self.stop_requested = False
        self._detecting     = False
        self._game_thread   = None
        self._state_lock    = threading.Lock()

        self._bridge       = CvBridge()
        self._latest_frame = None
        self._frame_lock   = threading.Lock()
        self._frame_event  = threading.Event()

        self.status_pub = self.create_publisher(String, '/patricio/calamar/status', 10)
        self.alerta_pub = self.create_publisher(String, '/patricio/alerta_juego',   10)
        self.cmd_sub    = self.create_subscription(
            String, '/patricio/calamar/cmd',  self.cmd_callback,    10)
        self.image_sub  = self.create_subscription(
            Image,  '/camera/real',            self._image_callback, 10)

        self.publish_status(ESTADO_ESPERA)
        self.get_logger().info('juego_calamar_node listo.')

    # ── Imagen ───────────────────────────────────────────

    def _image_callback(self, msg):
        try:
            frame = self._bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
            with self._frame_lock:
                self._latest_frame = frame
            self._frame_event.set()
        except Exception as e:
            self.get_logger().warn(f'Error convirtiendo imagen: {e}')

    def _get_frame(self, timeout=0.5):
        """Wait for a new frame and return it. Returns None on timeout."""
        self._frame_event.wait(timeout=timeout)
        self._frame_event.clear()
        with self._frame_lock:
            return self._latest_frame.copy() if self._latest_frame is not None else None

    def _flush_and_get_stable_baseline(self, n_warmup=4):
        """
        Discards all queued frames, then collects n_warmup fresh frames
        and returns the last one as a stable baseline for comparison.

        This must be called:
          1. When red light first starts.
          2. After each infraction, once the anti-spam sleep finishes.

        Without this, stale frames from before the red phase (or from
        the moment of movement) get compared against the new baseline
        and trigger false positives in a loop.
        """
        # Step 1 — flush: clear the event and discard whatever is in _latest_frame
        self._frame_event.clear()
        with self._frame_lock:
            self._latest_frame = None

        # Step 2 — wait for n_warmup genuinely new frames from the camera
        baseline = None
        collected = 0
        while collected < n_warmup:
            if not self._detecting:   # bail out if red light was cancelled
                return None
            frame = self._get_frame(timeout=1.0)
            if frame is None:
                self.get_logger().warn('Esperando frame para baseline...')
                continue
            gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            baseline = cv2.GaussianBlur(gris, (21, 21), 0)
            collected += 1

        return baseline   # the last of the n_warmup frames is the baseline

    # ── Comandos ─────────────────────────────────────────

    def cmd_callback(self, msg):
        cmd = msg.data.strip().upper()
        self.get_logger().info(f'Comando recibido: {cmd}')
        if   cmd == 'START_AUTO':      self._iniciar_auto()
        elif cmd == 'CAMBIAR_A_VERDE': self._set_manual(ESTADO_VERDE)
        elif cmd == 'CAMBIAR_A_ROJO':  self._set_manual(ESTADO_ROJO)
        elif cmd == 'STOP':            self._detener()

    # ── Modo automático ───────────────────────────────────

    def _iniciar_auto(self):
        with self._state_lock:
            if self.estado != ESTADO_ESPERA:
                self.get_logger().warn('Juego ya en marcha, ignorando START_AUTO.')
                return
            self.stop_requested = False

        self.get_logger().info('Esperando frames de /camera/real...')
        if self._get_frame(timeout=5.0) is None:
            self.get_logger().error('No llegan frames. Comprueba webcam_publisher_linux.')
            return

        self._game_thread = threading.Thread(target=self._bucle_auto, daemon=True)
        self._game_thread.start()

    def _bucle_auto(self):
        self.get_logger().info('Modo automático iniciado.')
        while not self.stop_requested:
            # ── Verde — detección OFF ─────────────────────
            dur_verde = random.uniform(self.verde_min, self.verde_max)
            self._detecting = False
            self._cambiar_estado(ESTADO_VERDE)
            self.get_logger().info(f'LUZ VERDE {dur_verde:.1f}s')
            self._esperar(dur_verde)
            if self.stop_requested:
                break

            # ── Rojo — detección ON ───────────────────────
            dur_roja = random.uniform(self.rojo_min, self.rojo_max)
            self._detecting = True
            self._cambiar_estado(ESTADO_ROJO)
            self.get_logger().info(f'LUZ ROJA {dur_roja:.1f}s')
            self._detectar_movimiento(dur_roja)

        self._detecting = False
        self._cambiar_estado(ESTADO_ESPERA)
        self.get_logger().info('Modo automático detenido.')

    # ── Modo manual ───────────────────────────────────────

    def _set_manual(self, nuevo_estado):
        self._detecting = False
        time.sleep(0.15)

        with self._state_lock:
            self.stop_requested = False

        self._cambiar_estado(nuevo_estado)

        if nuevo_estado == ESTADO_ROJO:
            self._detecting = True
            self._game_thread = threading.Thread(
                target=self._detectar_movimiento, args=(None,), daemon=True)
            self._game_thread.start()

    # ── Detección de movimiento ───────────────────────────

    def _detectar_movimiento(self, duracion_seg):
        """
        Motion detection loop. Only runs while self._detecting is True
        and estado == LUZ_ROJA.

        Key design:
          - _flush_and_get_stable_baseline() is called at the START and
            AFTER EACH INFRACTION. This prevents the loop from comparing
            a stale/mid-movement frame against a new one and firing again
            immediately, which was the cause of the infinite detection trap.
          - The loop itself only does one thing per iteration: compare the
            current frame against the last known-stable frame. If movement
            is found, it sleeps, then rebuilds the baseline from scratch
            before resuming comparison.
        """
        t_inicio = time.time()
        self.get_logger().info('Detección iniciada — construyendo baseline...')

        # Build initial stable baseline
        frame_anterior = self._flush_and_get_stable_baseline(n_warmup=4)
        if frame_anterior is None:
            self.get_logger().warn('Baseline cancelado, saliendo.')
            return

        self.get_logger().info('Baseline listo. Detectando movimiento.')

        while self._detecting and not self.stop_requested:
            with self._state_lock:
                if self.estado != ESTADO_ROJO:
                    break

            if duracion_seg is not None and (time.time() - t_inicio) >= duracion_seg:
                break

            frame = self._get_frame(timeout=0.5)
            if frame is None:
                continue

            gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gris = cv2.GaussianBlur(gris, (21, 21), 0)

            diff = cv2.absdiff(frame_anterior, gris)
            _, thresh = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)

            total_pixeles   = thresh.shape[0] * thresh.shape[1]
            pixeles_activos = int(np.sum(thresh) / 255)
            porcentaje      = (pixeles_activos / total_pixeles) * 100.0

            self.get_logger().debug(
                f'Movimiento: {porcentaje:.2f}% (umbral: {MOTION_PERCENT_THRESHOLD}%)')

            if porcentaje > MOTION_PERCENT_THRESHOLD:
                self.get_logger().info(f'¡INFRACCIÓN! {porcentaje:.2f}% píxeles')
                self._publicar_infraccion()

                # Anti-spam sleep — person finishes moving
                time.sleep(2.0)

                if not self._detecting:
                    break

                # Rebuild baseline from scratch AFTER movement has stopped.
                # This is the critical fix: without this, the next comparison
                # uses a mid-movement frame as baseline and fires again.
                self.get_logger().info('Reconstruyendo baseline tras infracción...')
                frame_anterior = self._flush_and_get_stable_baseline(n_warmup=4)
                if frame_anterior is None:
                    break
                self.get_logger().info('Baseline reconstruido. Reanudando detección.')
                continue

            # No movement — update baseline gradually (rolling average)
            # This handles slow lighting changes without resetting fully.
            frame_anterior = gris

        self.get_logger().info('Detección finalizada.')

    def _publicar_infraccion(self):
        msg = String()
        msg.data = 'INFRACCION'
        self.alerta_pub.publish(msg)
        self.status_pub.publish(msg)

    # ── Helpers ───────────────────────────────────────────

    def _cambiar_estado(self, nuevo):
        with self._state_lock:
            self.estado = nuevo
        self.publish_status(nuevo)
        self.get_logger().info(f'Estado → {nuevo}')

    def _detener(self):
        self._detecting     = False
        self.stop_requested = True
        with self._state_lock:
            self.estado = ESTADO_ESPERA
        self.publish_status(ESTADO_ESPERA)
        self.get_logger().info('Juego detenido.')

    def _esperar(self, segundos):
        t_fin = time.time() + segundos
        while not self.stop_requested and time.time() < t_fin:
            time.sleep(0.1)

    def publish_status(self, text):
        msg = String()
        msg.data = text
        self.status_pub.publish(msg)


def main(args=None):
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