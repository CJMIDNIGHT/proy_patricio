-- Añade columna de estado operativo del flujo de incidencias.
-- Ejecutar si ya tenías una base creada sin esta columna:
--   mysql -u ... patricio_db < migrations/001_incidencias_estado.sql

ALTER TABLE incidencias
    ADD COLUMN estado ENUM('abierta', 'revisada', 'cerrada')
        NOT NULL DEFAULT 'abierta'
        AFTER tipo;

UPDATE incidencias SET estado = 'cerrada' WHERE resuelta = 1;
