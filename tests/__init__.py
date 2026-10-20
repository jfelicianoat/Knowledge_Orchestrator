import os
import tempfile

# Core deja URL y token de cada app en %LOCALAPPDATA%/AIOSCore/conexion: los tests no la ven
os.environ["AI_OS_CONNECT_DIR"] = tempfile.mkdtemp(prefix="ko_tests_conexion_")
