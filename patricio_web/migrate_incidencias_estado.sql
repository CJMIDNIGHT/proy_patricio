-- Ejecutar solo si tu tabla incidencias se creó sin la columna `estado`
-- antes de usar el flujo de alertas admin.
--
-- mysql -u usuario -p patricio_db < migrate_incidencias_estado.sql
--
-- Si MySQL devuelve "Duplicate column name 'estado'", no hace falta hacer nada.

ALTER TABLE incidencias
  ADD COLUMN estado ENUM('abierta', 'revisada', 'cerrada') NOT NULL DEFAULT 'abierta' AFTER tipo,
  ADD KEY ix_incidencias_estado (estado);
