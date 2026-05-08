-- Usuarios de prueba: contraseña `1234` para todos (hash bcrypt).
-- Importar tras tener la tabla `usuario`:
--   mysql -u patricio -p patricio_db < seed_usuarios_prueba.sql
--
-- Re-ejecutar actualiza hash y roles si el usuario ya existía.

SET NAMES utf8mb4;

INSERT INTO usuario (nombre_usuario, correo, hash_contrasena, rol, activo)
VALUES
  ('admin',    'admin@patricio.local',
   '$2b$12$b9Y1u6yufc/DY.a7aEMacOvzrB/kj61K95mLkZ21ECAPrqQL.L6de', 'admin',    1),
  ('educador', 'educador@patricio.local',
   '$2b$12$b9Y1u6yufc/DY.a7aEMacOvzrB/kj61K95mLkZ21ECAPrqQL.L6de', 'educador', 1),
  ('familia',  'familia@patricio.local',
   '$2b$12$b9Y1u6yufc/DY.a7aEMacOvzrB/kj61K95mLkZ21ECAPrqQL.L6de', 'familia',  1)
ON DUPLICATE KEY UPDATE
  hash_contrasena = VALUES(hash_contrasena),
  correo          = VALUES(correo),
  rol             = VALUES(rol),
  activo          = 1;
