#!/usr/bin/env python3
"""
Flask API for Patricio web — bridges HTTP to ROS 2 via rosbridge WebSocket.
No rclpy or patricio_interfaces needed.

Endpoints:
  POST /api/juego/iniciar   → calls /start_game service via rosbridge
  POST /api/juego/detener   → publishes STOP to /patricio/pilla_pilla/cmd
  GET  /api/juego/estado    → returns last known status
  GET  /api/db/health       → comprobación SELECT 1 contra MySQL
  POST /api/db/selftest     → INSERT+SELECT en usuario/historico_juegos/incidencias (solo si ENABLE_DB_SELFTEST)
  POST /api/incidencias     → registra anomalía (robot / monitor) y notifica admin por WebSocket
  GET  /api/incidencias/pendientes → incidencias con resuelta=0 y estado=abierta
  POST /api/incidencias/<id>/revisar → marca revisada (silencia alerta)
  POST /api/guardar_juego     → nueva fila en historico_juegos (actividad finalizada)
  GET  /api/historico_dia     → juegos del día agrupados (favorito) + detalle
  POST /api/auth/login        → comprobar usuario / correo + contraseña (bcrypt)
  POST /api/auth/register      → alta familia (rol fijo familia), contraseña con política fuerte
  POST /api/juego/iniciar        → calls /start_game service via rosbridge
  POST /api/juego/detener        → publishes STOP to /patricio/pilla_pilla/cmd
  GET  /api/juego/estado         → returns last known status

  POST /api/calamar/comando      → publishes command to /patricio/calamar/cmd
                                   body: { "comando": "START_AUTO" | "CAMBIAR_A_VERDE"
                                                     | "CAMBIAR_A_ROJO" | "STOP" }
  GET  /api/calamar/estado       → returns last known calamar status + alert
"""

import json
import os
import re
import threading
import time
import uuid
import atexit
from datetime import date, datetime

import bcrypt

import websocket  # pip install websocket-client
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO
from sqlalchemy import text

from database import get_engine

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')

ROSBRIDGE_URL = 'ws://localhost:9090'
last_status = 'Descansando'
status_lock = threading.Lock()

# ── Calamar state ─────────────────────────────────────────
last_calamar_status = 'ESPERA'
last_calamar_alerta = ''
last_calamar_alerta_ts = None   # float timestamp, set when alerta fires, cleared after read
calamar_lock = threading.Lock()


# ── Rosbridge helper ──────────────────────────────────────

def rosbridge_call_service(service, service_type, args: dict, timeout=5.0):
    """
    Calls a ROS service through rosbridge and returns the response dict.
    Blocks until response arrives or timeout.
    """
    result = {'done': False, 'response': None, 'error': None}
    call_id = str(uuid.uuid4())

    def on_message(ws, message):
        msg = json.loads(message)
        if msg.get('op') == 'service_response' and msg.get('id') == call_id:
            result['response'] = msg.get('values', {})
            result['done'] = True
            ws.close()

    def on_error(ws, error):
        result['error'] = str(error)
        result['done'] = True

    def on_open(ws):
        payload = {
            'op': 'call_service',
            'id': call_id,
            'service': service,
            'type': service_type,
            'args': args
        }
        ws.send(json.dumps(payload))

    ws = websocket.WebSocketApp(
        ROSBRIDGE_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error
    )

    thread = threading.Thread(target=ws.run_forever)
    thread.daemon = True
    thread.start()
    thread.join(timeout=timeout)

    if not result['done']:
        result['error'] = 'Timeout waiting for service response'

    return result


def rosbridge_publish(topic, msg_type, data: dict):
    """
    Publishes a single message to a ROS topic via rosbridge.
    Fire and forget.
    """
    def run():
        try:
            ws = websocket.create_connection(ROSBRIDGE_URL, timeout=3)
            payload = {
                'op': 'publish',
                'topic': topic,
                'type': msg_type,
                'msg': data
            }
            ws.send(json.dumps(payload))
            ws.close()
        except Exception as e:
            print(f'rosbridge_publish error: {e}')

    threading.Thread(target=run, daemon=True).start()


def rosbridge_subscribe_status():
    """
    Runs in background thread — keeps last_status up to date
    by subscribing to /patricio/pilla_pilla/status.
    """
    global last_status

    def on_message(ws, message):
        global last_status
        msg = json.loads(message)
        if msg.get('op') == 'publish':
            with status_lock:
                last_status = msg.get('msg', {}).get('data', last_status)

    def on_open(ws):
        payload = {
            'op': 'subscribe',
            'topic': '/patricio/pilla_pilla/status',
            'type': 'std_msgs/msg/String'
        }
        ws.send(json.dumps(payload))
        print('Subscribed to /patricio/pilla_pilla/status')

    def on_error(ws, error):
        print(f'Status subscriber error: {error}')
        time.sleep(3)

    def on_close(ws, *args):
        print('Status subscriber closed, reconnecting...')
        time.sleep(3)
        rosbridge_subscribe_status()

    ws = websocket.WebSocketApp(
        ROSBRIDGE_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    ws.run_forever()


def rosbridge_subscribe_status_escondite():
    global last_status

    def on_message(ws, message):
        global last_status
        msg = json.loads(message)
        if msg.get('op') == 'publish':
            with status_lock:
                last_status = msg.get('msg', {}).get('data', last_status)

    def on_open(ws):
        payload = {
            'op': 'subscribe',
            'topic': '/patricio/escondite/status',
            'type': 'std_msgs/msg/String'
        }
        ws.send(json.dumps(payload))

    def on_close(ws, *args):
        time.sleep(3)
        rosbridge_subscribe_status_escondite()

    ws = websocket.WebSocketApp(
        ROSBRIDGE_URL,
        on_open=on_open,
        on_message=on_message,
        on_close=on_close
    )
    ws.run_forever()


# ── Incidencias (SQL + Socket.IO) ─────────────────────────

def _incidencia_row_to_dict(row) -> dict:
    d = dict(row)
    for key in ('creado_en', 'cerrada_en'):
        v = d.get(key)
        if v is not None and hasattr(v, 'isoformat'):
            d[key] = v.isoformat()
    d['resuelta'] = bool(d.get('resuelta'))
    return d


def _emit_nueva_incidencia(payload: dict) -> None:
    try:
        socketio.emit('nueva_incidencia', payload)
    except Exception as e:
        print(f'Socket emit nueva_incidencia: {e}')


def _emit_incidencia_revisada(inc_id: int) -> None:
    try:
        socketio.emit('incidencia_revisada', {'id': inc_id})
    except Exception as e:
        print(f'Socket emit incidencia_revisada: {e}')


# ── Flask routes ──────────────────────────────────────────
def rosbridge_subscribe_calamar():
    """
    Background thread — subscribes to both calamar status and alert topics.
    Keeps last_calamar_status and last_calamar_alerta up to date.
    """
    global last_calamar_status, last_calamar_alerta

    def on_message(ws, message):
        global last_calamar_status, last_calamar_alerta
        msg = json.loads(message)
        if msg.get('op') == 'publish':
            topic = msg.get('topic', '')
            data = msg.get('msg', {}).get('data', '')
            with calamar_lock:
                if topic == '/patricio/calamar/status':
                    last_calamar_status = data
                elif topic == '/patricio/alerta_juego':
                    last_calamar_alerta = data
                    if data == 'INFRACCION':
                        last_calamar_alerta_ts = time.time()

    def on_open(ws):
        for topic in ['/patricio/calamar/status', '/patricio/alerta_juego']:
            ws.send(json.dumps({
                'op': 'subscribe',
                'topic': topic,
                'type': 'std_msgs/msg/String'
            }))
        print('Subscribed to calamar topics')

    def on_error(ws, error):
        print(f'Calamar subscriber error: {error}')
        time.sleep(3)

    def on_close(ws, *args):
        print('Calamar subscriber closed, reconnecting...')
        time.sleep(3)
        rosbridge_subscribe_calamar()

    ws = websocket.WebSocketApp(
        ROSBRIDGE_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    ws.run_forever()


# ── Flask routes — juegos existentes ─────────────────────

@app.route('/api/juego/iniciar', methods=['POST'])
def iniciar_juego():
    body = request.get_json(force=True)
    game_name = body.get('game_name', 'pilla_pilla')

    if game_name != 'pilla_pilla':
        return jsonify({'started': False, 'error': 'Juego no reconocido'}), 400

    result = None
    for attempt in range(2):
        result = rosbridge_call_service(
            service='/start_game',
            service_type='patricio_interfaces/srv/StartGame',
            args={'game_name': game_name},
            timeout=10.0
        )
        if not result['error']:
            break
        print(f'Attempt {attempt + 1} failed: {result["error"]}, retrying...')
        time.sleep(1)

    if result['error']:
        return jsonify({'started': False, 'error': result['error']}), 500

    started = result['response'].get('started', False)
    return jsonify({'started': started})


@app.route('/api/juego/detener', methods=['POST'])
def detener_juego():
    rosbridge_publish(
        topic='/patricio/pilla_pilla/cmd',
        msg_type='std_msgs/msg/String',
        data={'data': 'STOP'}
    )
    return jsonify({'stopped': True})


@app.route('/api/juego/estado', methods=['GET'])
def estado_juego():
    with status_lock:
        return jsonify({'status': last_status})


# ── Histórico de juegos ───────────────────────────────────


def _historico_row_to_dict(row) -> dict:
    d = dict(row)
    for key in ('iniciado_en', 'finalizado_en'):
        v = d.get(key)
        if v is not None and hasattr(v, 'isoformat'):
            d[key] = v.isoformat()
    return d


@app.route('/api/guardar_juego', methods=['POST'])
def guardar_juego():
    """
    Registra una actividad finalizada en historico_juegos.
    JSON: nombre_juego (obligatorio), resultado, estado (default finalizado_ok),
          usuario_id (opcional), detalles (objeto opcional).
    """
    body = request.get_json(force=True, silent=True) or {}
    nombre_juego = (body.get('nombre_juego') or '').strip()
    if not nombre_juego or len(nombre_juego) > 64:
        return jsonify({'ok': False, 'error': 'nombre_juego inválido o vacío'}), 400

    resultado_raw = body.get('resultado')
    resultado = (str(resultado_raw).strip()[:64]) if resultado_raw is not None else None
    estado = (body.get('estado') or 'finalizado_ok').strip()[:64]

    usuario_id = body.get('usuario_id')
    if usuario_id is not None:
        try:
            usuario_id = int(usuario_id)
        except (TypeError, ValueError):
            usuario_id = None

    detalles = body.get('detalles')
    if detalles is not None and not isinstance(detalles, dict):
        detalles = {'valor': str(detalles)}
    det_json = json.dumps(detalles, ensure_ascii=False) if isinstance(detalles, dict) else None

    try:
        with get_engine().begin() as conn:
            if det_json is None:
                conn.execute(
                    text(
                        """INSERT INTO historico_juegos
                           (usuario_id, nombre_juego, resultado, estado, detalles_json, finalizado_en)
                           VALUES (:uid, :nombre, :res, :estado, NULL, CURRENT_TIMESTAMP)"""
                    ),
                    {
                        'uid': usuario_id,
                        'nombre': nombre_juego,
                        'res': resultado,
                        'estado': estado,
                    },
                )
            else:
                conn.execute(
                    text(
                        """INSERT INTO historico_juegos
                           (usuario_id, nombre_juego, resultado, estado, detalles_json, finalizado_en)
                           VALUES (:uid, :nombre, :res, :estado, CAST(:det AS JSON), CURRENT_TIMESTAMP)"""
                    ),
                    {
                        'uid': usuario_id,
                        'nombre': nombre_juego,
                        'res': resultado,
                        'estado': estado,
                        'det': det_json,
                    },
                )
            hid = int(conn.execute(text('SELECT LAST_INSERT_ID() AS id')).scalar_one())
            row = conn.execute(
                text(
                    """SELECT id, usuario_id, nombre_juego, resultado, estado,
                              iniciado_en, finalizado_en
                       FROM historico_juegos WHERE id = :id"""
                ),
                {'id': hid},
            ).mappings().one()

        return jsonify({'ok': True, 'registro': _historico_row_to_dict(row)}), 201
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/historico_dia', methods=['GET'])
def historico_dia():
    """
    Juegos registrados para la fecha indicada (o hoy, hora servidor).
    Query: fecha=YYYY-MM-DD (opcional), usuario_id (opcional).
    """
    fecha_str = request.args.get('fecha')
    if fecha_str:
        try:
            datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'ok': False, 'error': 'fecha debe ser YYYY-MM-DD'}), 400
    else:
        fecha_str = date.today().isoformat()

    usuario_id = request.args.get('usuario_id', type=int)

    filt_usuario = ''
    params = {'fecha': fecha_str}
    if usuario_id is not None:
        filt_usuario = ' AND usuario_id = :uid'
        params['uid'] = usuario_id

    base_where = (
        'DATE(COALESCE(finalizado_en, iniciado_en)) = :fecha' + filt_usuario
    )

    try:
        with get_engine().connect() as conn:
            detalle = conn.execute(
                text(
                    f"""SELECT id, usuario_id, nombre_juego, resultado, estado,
                               iniciado_en, finalizado_en
                        FROM historico_juegos
                        WHERE {base_where}
                        ORDER BY COALESCE(finalizado_en, iniciado_en) DESC, id DESC"""
                ),
                params,
            ).mappings().all()

            agrupado = conn.execute(
                text(
                    f"""SELECT nombre_juego, COUNT(*) AS veces
                        FROM historico_juegos
                        WHERE {base_where}
                        GROUP BY nombre_juego
                        ORDER BY veces DESC, nombre_juego ASC"""
                ),
                params,
            ).mappings().all()

        lista_detalle = [_historico_row_to_dict(r) for r in detalle]
        lista_agrupado = [
            {'nombre_juego': r['nombre_juego'], 'veces': int(r['veces'])} for r in agrupado
        ]
        veces_list = [int(x['veces']) for x in lista_agrupado]
        total = sum(veces_list)
        favorito = lista_agrupado[0]['nombre_juego'] if lista_agrupado else None

        return jsonify({
            'ok': True,
            'fecha': fecha_str,
            'total_partidas': total,
            'favorito': favorito,
            'agrupado': lista_agrupado,
            'detalle': lista_detalle,
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# ── Autenticación ─────────────────────────────────────────

_RE_PASS_STRONG = re.compile(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$')


def _hash_password_bcrypt(plain: str) -> str:
    return bcrypt.hashpw(
        plain.encode('utf-8'), bcrypt.gensalt(rounds=12)
    ).decode('ascii')


def _verify_password_bcrypt(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain.encode('utf-8'), hashed.encode('ascii')
        )
    except Exception:
        return False


def _slug_part(s: str) -> str:
    s = (s or '').strip().lower()
    s = re.sub(r'[^a-z0-9._-]+', '_', s)
    return re.sub(r'_+', '_', s).strip('_')[:72]


def _usuario_session_dict(row) -> dict:
    return {
        'id': int(row['id']),
        'nombre_usuario': row['nombre_usuario'],
        'rol': row['rol'],
        'correo': row['correo'],
    }


@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    body = request.get_json(force=True, silent=True) or {}
    ident = (body.get('nombre_usuario') or body.get('login') or '').strip()
    password = body.get('contrasena') or body.get('password') or ''

    if not ident or not password:
        return jsonify({'ok': False, 'error': 'Usuario y contraseña requeridos'}), 400

    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                text(
                    """SELECT id, nombre_usuario, rol, correo, hash_contrasena, activo
                       FROM usuario
                       WHERE (nombre_usuario = :i OR correo = :i) AND activo = 1
                       LIMIT 1"""
                ),
                {'i': ident[:255]},
            ).mappings().first()

        if row is None or not _verify_password_bcrypt(password, row['hash_contrasena']):
            return jsonify({'ok': False, 'error': 'Usuario o contraseña incorrectos'}), 401

        return jsonify({'ok': True, 'usuario': _usuario_session_dict(row)})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/auth/register', methods=['POST'])
def auth_register():
    """
    Registro público: solo rol 'familia'. Contraseña: min 8, mayúscula, minúscula, número.
    """
    body = request.get_json(force=True, silent=True) or {}
    nombre = (body.get('nombre') or '').strip()
    apellido = (body.get('apellido') or '').strip()
    correo = (body.get('correo') or body.get('email') or '').strip()[:255]
    contrasena = body.get('contrasena') or body.get('password') or ''

    if not nombre or not apellido:
        return jsonify({'ok': False, 'error': 'Nombre y apellido obligatorios'}), 400
    if not correo or '@' not in correo:
        return jsonify({'ok': False, 'error': 'Correo electrónico inválido'}), 400
    if not _RE_PASS_STRONG.match(contrasena):
        return jsonify({
            'ok': False,
            'error': 'La contraseña debe tener mínimo 8 caracteres, mayúscula, minúscula y un número',
        }), 400

    local = correo.split('@', 1)[0]
    base = _slug_part(local)
    if len(base) < 3:
        base = _slug_part(f'{nombre}_{apellido}')
    if len(base) < 3:
        base = 'familia'

    hpw = _hash_password_bcrypt(contrasena)

    try:
        with get_engine().begin() as conn:
            if conn.execute(
                text('SELECT id FROM usuario WHERE correo = :c LIMIT 1'),
                {'c': correo},
            ).first():
                return jsonify({'ok': False, 'error': 'Ese correo ya está registrado'}), 409

            for suf in range(0, 100):
                candidate = base if suf == 0 else f'{base}_{suf}'
                candidate = candidate[:80]
                if conn.execute(
                    text('SELECT id FROM usuario WHERE nombre_usuario = :u LIMIT 1'),
                    {'u': candidate},
                ).first():
                    continue
                conn.execute(
                    text(
                        """INSERT INTO usuario
                           (nombre_usuario, correo, hash_contrasena, rol, activo)
                           VALUES (:u, :c, :h, 'familia', 1)"""
                    ),
                    {'u': candidate, 'c': correo, 'h': hpw},
                )
                uid = int(conn.execute(text('SELECT LAST_INSERT_ID() AS id')).scalar_one())
                row = conn.execute(
                    text(
                        """SELECT id, nombre_usuario, rol, correo
                           FROM usuario WHERE id = :id"""
                    ),
                    {'id': uid},
                ).mappings().one()
                return jsonify({'ok': True, 'usuario': _usuario_session_dict(row)}), 201

        return jsonify({'ok': False, 'error': 'No se pudo generar un nombre de usuario único'}), 409
    except Exception as e:
        if 'Duplicate' in str(e) or '1062' in str(e):
            return jsonify({'ok': False, 'error': 'Ese correo o usuario ya está registrado'}), 409
        return jsonify({'ok': False, 'error': str(e)}), 500


# ── Persistencia MySQL (SQLAlchemy) ───────────────────────


@app.route('/api/db/health', methods=['GET'])
def db_health():
    """SELECT 1 — verifica credenciales y red sin escribir datos."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text('SELECT 1'))
        return jsonify({'ok': True, 'database': 'reachable'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 503


@app.route('/api/db/selftest', methods=['POST'])
def db_selftest():
    """
    Inserta filas de prueba en usuario, historico_juegos e incidencias,
    las lee con SELECT y las elimina en la misma transacción.
    Requiere ENABLE_DB_SELFTEST=true en .env (no usar en producción expuesta).
    """
    if os.getenv('ENABLE_DB_SELFTEST', 'false').lower() not in ('1', 'true', 'yes'):
        return jsonify({'ok': False, 'error': 'ENABLE_DB_SELFTEST desactivado'}), 403

    suffix = uuid.uuid4().hex[:12]
    nombre_usuario = f'_selftest_{suffix}'

    try:
        with get_engine().begin() as conn:
            conn.execute(
                text(
                    """INSERT INTO usuario (nombre_usuario, hash_contrasena, rol)
                       VALUES (:nombre, :hash, :rol)"""
                ),
                {'nombre': nombre_usuario, 'hash': '(selftest)', 'rol': 'familia'},
            )
            uid = int(conn.execute(text('SELECT LAST_INSERT_ID() AS id')).scalar_one())

            conn.execute(
                text(
                    """INSERT INTO historico_juegos
                       (usuario_id, nombre_juego, resultado, estado, detalles_json)
                       VALUES (:uid, :juego, :res, :estado, NULL)"""
                ),
                {
                    'uid': uid,
                    'juego': 'pilla_pilla',
                    'res': 'selftest',
                    'estado': 'ok',
                },
            )
            hid = int(conn.execute(text('SELECT LAST_INSERT_ID() AS id')).scalar_one())

            fila_historico = conn.execute(
                text(
                    """SELECT id, usuario_id, nombre_juego, resultado, estado
                       FROM historico_juegos WHERE id = :hid"""
                ),
                {'hid': hid},
            ).mappings().one()

            conn.execute(
                text(
                    """INSERT INTO incidencias
                       (usuario_id, tipo, estado, severidad, titulo, mensaje, resuelta)
                       VALUES (:uid, 'sistema', 'abierta', 'info', :tit, :msg, 0)"""
                ),
                {
                    'uid': uid,
                    'tit': 'Selftest API',
                    'msg': 'Inserción de prueba desde patricio_api',
                },
            )
            iid = int(conn.execute(text('SELECT LAST_INSERT_ID() AS id')).scalar_one())

            fila_incidencia = conn.execute(
                text(
                    """SELECT id, tipo, estado, severidad, titulo
                       FROM incidencias WHERE id = :iid"""
                ),
                {'iid': iid},
            ).mappings().one()

            conn.execute(text('DELETE FROM incidencias WHERE id = :iid'), {'iid': iid})
            conn.execute(text('DELETE FROM historico_juegos WHERE id = :hid'), {'hid': hid})
            conn.execute(text('DELETE FROM usuario WHERE id = :uid'), {'uid': uid})

        return jsonify({
            'ok': True,
            'mensaje': 'INSERT y SELECT correctos; filas de prueba eliminadas.',
            'usuario_prueba': nombre_usuario,
            'historico_insertado_y_leido': dict(fila_historico),
            'incidencia_insertada_y_leida': dict(fila_incidencia),
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/incidencias', methods=['POST'])
def api_crear_incidencia():
    """
    Cuerpo JSON: tipo (obligatorio), titulo, mensaje, severidad (info|aviso|critico),
    usuario_id (opcional), contexto (objeto JSON opcional).
    """
    body = request.get_json(force=True, silent=True) or {}
    tipo = (body.get('tipo') or '').strip()
    if not tipo:
        return jsonify({'ok': False, 'error': 'tipo requerido (ej. Caída, Batería baja)'}), 400

    titulo = (body.get('titulo') or tipo).strip()[:200]
    mensaje = (body.get('mensaje') or 'Sin detalle adicional').strip()
    severidad = body.get('severidad', 'aviso')
    if severidad not in ('info', 'aviso', 'critico'):
        severidad = 'aviso'

    usuario_id = body.get('usuario_id')
    if usuario_id is not None:
        try:
            usuario_id = int(usuario_id)
        except (TypeError, ValueError):
            usuario_id = None

    ctx = body.get('contexto')
    if ctx is not None and not isinstance(ctx, (dict, list)):
        ctx = {'valor': str(ctx)}
    ctx_json = json.dumps(ctx if ctx is not None else {}, ensure_ascii=False)

    try:
        with get_engine().begin() as conn:
            conn.execute(
                text(
                    """INSERT INTO incidencias
                       (usuario_id, tipo, estado, severidad, titulo, mensaje, contexto_json, resuelta)
                       VALUES (:uid, :tipo, 'abierta', :sev, :titulo, :msg, CAST(:ctx AS JSON), 0)"""
                ),
                {
                    'uid': usuario_id,
                    'tipo': tipo[:64],
                    'sev': severidad,
                    'titulo': titulo,
                    'msg': mensaje,
                    'ctx': ctx_json,
                },
            )
            new_id = int(conn.execute(text('SELECT LAST_INSERT_ID() AS id')).scalar_one())
            row = conn.execute(
                text(
                    """SELECT id, usuario_id, tipo, estado, severidad, titulo, mensaje,
                              resuelta, creado_en, cerrada_en
                       FROM incidencias WHERE id = :id"""
                ),
                {'id': new_id},
            ).mappings().one()

        payload = _incidencia_row_to_dict(row)
        _emit_nueva_incidencia(payload)
        return jsonify({'ok': True, 'incidencia': payload}), 201
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/incidencias/pendientes', methods=['GET'])
def api_incidencias_pendientes():
    try:
        with get_engine().connect() as conn:
            rows = conn.execute(
                text(
                    """SELECT id, usuario_id, tipo, estado, severidad, titulo, mensaje,
                              resuelta, creado_en, cerrada_en
                       FROM incidencias
                       WHERE resuelta = 0 AND estado = 'abierta'
                       ORDER BY id DESC"""
                ),
            ).mappings().all()

        lista = [_incidencia_row_to_dict(r) for r in rows]
        return jsonify({'ok': True, 'incidencias': lista})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/incidencias/<int:iid>/revisar', methods=['POST'])
def api_revisar_incidencia(iid):
    try:
        with get_engine().begin() as conn:
            r = conn.execute(
                text(
                    """UPDATE incidencias
                       SET resuelta = 1,
                           estado = 'revisada',
                           cerrada_en = CURRENT_TIMESTAMP
                       WHERE id = :id AND resuelta = 0"""
                ),
                {'id': iid},
            )
            if getattr(r, 'rowcount', 0) == 0:
                return jsonify({'ok': False, 'error': 'Incidencia no encontrada o ya revisada'}), 404

        _emit_incidencia_revisada(iid)
        return jsonify({'ok': True, 'id': iid})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/escondite/iniciar', methods=['POST'])
def iniciar_escondite():
    body = request.get_json(force=True)
    poses = body.get('poses', [])

    if not poses:
        return jsonify({'success': False, 'error': 'No se enviaron poses'}), 400

    pose_list = [
        {
            'position': {'x': p['x'], 'y': p['y'], 'z': 0.0},
            'orientation': {'x': 0.0, 'y': 0.0, 'z': 0.0, 'w': 1.0}
        }
        for p in poses
    ]

    result = rosbridge_call_service(
        service='/patricio/escondite/iniciar',
        service_type='patricio_interfaces/srv/IniciarEscondite',
        args={
            'command': 'START',
            'poses': {
                'header': {'frame_id': 'map', 'stamp': {'sec': 0, 'nanosec': 0}},
                'poses': pose_list
            }
        },
        timeout=10.0
    )

    if result['error']:
        return jsonify({'success': False, 'error': result['error']}), 500

    return jsonify({
        'success': result['response'].get('success', False),
        'message': result['response'].get('message', ''),
        'target_pose': result['response'].get('target_pose', {})
    })


@app.route('/api/escondite/detener', methods=['POST'])
def detener_escondite():
    rosbridge_call_service(
        service='/patricio/escondite/iniciar',
        service_type='patricio_interfaces/srv/IniciarEscondite',
        args={
            'command': 'STOP',
            'poses': {
                'header': {'frame_id': 'map', 'stamp': {'sec': 0, 'nanosec': 0}},
                'poses': []
            }
        },
        timeout=5.0
    )
    return jsonify({'stopped': True})


# ── Flask routes — Juego del Calamar ─────────────────────

@app.route('/api/calamar/comando', methods=['POST'])
def calamar_comando():
    """
    Envía un comando al nodo juego_calamar_node.

    Body JSON: { "comando": "START_AUTO" | "CAMBIAR_A_VERDE"
                            | "CAMBIAR_A_ROJO" | "STOP" }
    """
    body = request.get_json(force=True)
    comando = body.get('comando', '').strip().upper()

    comandos_validos = {'START_AUTO', 'CAMBIAR_A_VERDE', 'CAMBIAR_A_ROJO', 'STOP'}
    # Also allow SET_THRESHOLD:<value> for dynamic pose sensitivity updates
    if comando not in comandos_validos and not comando.startswith('SET_THRESHOLD:'):
        return jsonify({'ok': False, 'error': f'Comando no válido: {comando}'}), 400

    rosbridge_publish(
        topic='/patricio/calamar/cmd',
        msg_type='std_msgs/msg/String',
        data={'data': comando}
    )
    return jsonify({'ok': True, 'comando': comando})


@app.route('/api/calamar/estado', methods=['GET'])
def calamar_estado():
    """Devuelve el último estado y alerta del juego del calamar.
    alerta se consume al leerlo (se limpia después de enviarlo una vez)
    para que el frontend no lo procese en cada poll."""
    global last_calamar_alerta, last_calamar_alerta_ts
    with calamar_lock:
        alerta     = last_calamar_alerta
        alerta_ts  = last_calamar_alerta_ts
        # Clear after read — next poll will see alerta='' unless a new one fires
        last_calamar_alerta    = ''
        last_calamar_alerta_ts = None
        return jsonify({
            'status':    last_calamar_status,
            'alerta':    alerta,
            'alerta_ts': alerta_ts   # float or null — frontend uses this for dedup
        })


# ── Entry point ───────────────────────────────────────────

def on_shutdown():
    print('API shutting down, sending STOP...')
    rosbridge_publish(
        topic='/patricio/pilla_pilla/cmd',
        msg_type='std_msgs/msg/String',
        data={'data': 'STOP'}
    )
    rosbridge_publish(
        topic='/patricio/calamar/cmd',
        msg_type='std_msgs/msg/String',
        data={'data': 'STOP'}
    )
    rosbridge_call_service(
        service='/patricio/escondite/iniciar',
        service_type='patricio_interfaces/srv/IniciarEscondite',
        args={
            'command': 'STOP',
            'poses': {
                'header': {'frame_id': 'map', 'stamp': {'sec': 0, 'nanosec': 0}},
                'poses': []
            }
        }
    )
    time.sleep(1)


if __name__ == '__main__':
    # Status subscribers in background
    threading.Thread(target=rosbridge_subscribe_status, daemon=True).start()
    threading.Thread(target=rosbridge_subscribe_status_escondite, daemon=True).start()
    threading.Thread(target=rosbridge_subscribe_calamar, daemon=True).start()

    print('Starting Patricio API + Socket.IO on http://0.0.0.0:5000')

    atexit.register(on_shutdown)
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)