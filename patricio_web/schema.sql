-- Patricio — esquema de persistencia (MySQL 8+)
-- Crear la base antes de importar: CREATE DATABASE patricio_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS usuario (
    id              INT UNSIGNED NOT NULL AUTO_INCREMENT,
    nombre_usuario  VARCHAR(80) NOT NULL,
    correo          VARCHAR(255) NULL,
    hash_contrasena VARCHAR(255) NOT NULL COMMENT '-hash seguro (p. ej. bcrypt)',
    rol             ENUM('admin', 'educador', 'familia') NOT NULL DEFAULT 'familia',
    activo          TINYINT(1) NOT NULL DEFAULT 1,
    creado_en       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actualizado_en  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_usuario_nombre (nombre_usuario),
    UNIQUE KEY uq_usuario_correo (correo),
    KEY ix_usuario_rol (rol),
    KEY ix_usuario_activo (activo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS historico_juegos (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    usuario_id      INT UNSIGNED NULL COMMENT 'NULL si es sesión anónima / sistema',
    nombre_juego    VARCHAR(64) NOT NULL COMMENT 'pilla_pilla, escondite, etc.',
    resultado       VARCHAR(64) NULL,
    estado          VARCHAR(64) NULL COMMENT 'en_curso, finalizado_ok, abortado…',
    detalles_json   JSON NULL COMMENT 'poses, duración, puntuación, metadatos',
    iniciado_en     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finalizado_en   TIMESTAMP NULL DEFAULT NULL,
    PRIMARY KEY (id),
    KEY ix_historico_usuario (usuario_id),
    KEY ix_historico_juego (nombre_juego),
    KEY ix_historico_iniciado (iniciado_en),
    CONSTRAINT fk_historico_usuario
        FOREIGN KEY (usuario_id) REFERENCES usuario(id)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS incidencias (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    usuario_id      INT UNSIGNED NULL COMMENT 'quien reporta, si aplica',
    tipo            VARCHAR(64) NOT NULL COMMENT 'Caída, Batería baja, conexion_robot…',
    estado          ENUM('abierta', 'revisada', 'cerrada') NOT NULL DEFAULT 'abierta',
    severidad       ENUM('info', 'aviso', 'critico') NOT NULL DEFAULT 'aviso',
    titulo          VARCHAR(200) NOT NULL,
    mensaje         TEXT NOT NULL,
    contexto_json   JSON NULL COMMENT 'payload para diagnóstico',
    resuelta        TINYINT(1) NOT NULL DEFAULT 0,
    creado_en       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    cerrada_en      TIMESTAMP NULL DEFAULT NULL,
    PRIMARY KEY (id),
    KEY ix_incidencias_usuario (usuario_id),
    KEY ix_incidencias_tipo (tipo),
    KEY ix_incidencias_estado (estado),
    KEY ix_incidencias_severidad (severidad),
    KEY ix_incidencias_resuelta (resuelta),
    KEY ix_incidencias_creado (creado_en),
    CONSTRAINT fk_incidencias_usuario
        FOREIGN KEY (usuario_id) REFERENCES usuario(id)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
