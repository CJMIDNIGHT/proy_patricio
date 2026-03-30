# Patricio — Robot Educativo para Niños

Proyecto de Robótica 2026
Nombre de repositorio : patricio

## Descripción

Patricio es un robot educativo diseñado para niños de entre 4 y 6 años de edad. Su objetivo es fomentar el aprendizaje de habilidades y conocimientos básicos mediante la interacción lúdica, integrando inteligencia artificial para una experiencia autónoma y adaptativa.

### Funcionalidades principales

- Enseñanza de matemáticas básicas y el alfabeto
- Narración de chistes y cuentos cortos
- Participación en juegos de actividad física como "pilla pilla" y "el pollito inglés"
- Baile y canto interactivo
- Expresión facial mediante pantalla integrada
- Control remoto mediante interfaz web
- Navegación autónoma del entorno
- Reconocimiento de voz 
- Detección de impactos físicos

---

## Estructura del Repositorio

```
patricio/
├── patricio/                      # Paquete principal (CMake)
├── patricio_captacion/            # Módulo de captura sensorial y percepción
├── patricio_my_world/                # Módulo de representación del entorno
├── patricio_nav_punto/            # Navegación hacia puntos específicos
└── patricio_nav_ruta/             # Planificación y seguimiento de rutas

```

---

## Dependencias

- [ROS 2](https://docs.ros.org/en/rolling/index.html) (Humble o superior recomendado)
- Python 3.10+
- CMake 3.8+
- Paquetes ROS 2 requeridos:
  - `rclpy`
  - `nav2`
  - `sensor_msgs`
  - `geometry_msgs`

---

## Instalación

### 1. Instalar ROS 2

Consulta la [guía oficial de instalación de ROS 2](https://docs.ros.org/en/humble/Installation.html) según tu sistema operativo.

### 2. Clonar el repositorio

```bash
git clone https://github.com/CJMIDNIGHT/patricio.git
cd patricio
```

### 3. Instalar dependencias

```bash
sudo apt update
rosdep update
rosdep install --from-paths src --ignore-src -r -y
```

### 4. Compilar el workspace

```bash
colcon build
source install/setup.bash
```

---

## Ejecución

### Iniciar el sistema completo

```bash
ros2 launch patricio_my_world house.launch.py
```

### Iniciar módulos de forma individual

```bash
# Módulo de captura sensorial
ros2 run patricio_captacion captacion_node

# Módulo de navegación por puntos
ros2 run patricio_nav_punto nav_punto_node

# Módulo de planificación de rutas
ros2 run patricio_nav_ruta ruta_node
```

### Interfaz web

Una vez el sistema esté en ejecución, accede al panel de control desde un navegador en:

```
http://<IP_DEL_ROBOT>:8080
```

---

## Autores

- **Adenor Buret** — [GitHub](https://github.com/CJMIDNIGHT)
- **Santiago Aguirre Crespo** — [GitHub](https://github.com/Saac04)
- **Pablo Meana** — [GitHub](https://github.com/Meana13)
- **Mari Dapcheva** — [GitHub](https://github.com/ohmarimari)
- **César Herrero** — [GitHub](https://github.com/ElCesarEse)
- **Juan Bautista** — [GitHub](https://github.com/jbperfon)

---
