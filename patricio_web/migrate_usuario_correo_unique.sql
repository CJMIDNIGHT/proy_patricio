-- Solo si ya tenías tabla `usuario` sin índice único en correo (instalaciones anteriores).
-- Si falla por correos repetidos o duplicados, limpia datos antes.

ALTER TABLE usuario
  ADD UNIQUE KEY uq_usuario_correo (correo);
