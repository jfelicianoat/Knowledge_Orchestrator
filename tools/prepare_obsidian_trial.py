"""Prepara una bóveda nueva de ensayo; no abre Obsidian ni activa el complemento."""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import uuid
from pathlib import Path

PACKAGE_FILES = ('manifest.json', 'main.js', 'bridge-core.cjs', 'server.cjs', 'journal.cjs')
CASES = {
    '01_aplicacion.md': 'Aplicar una propuesta y comprobar el recibo y el contenido.',
    '02_conflicto.md': 'Editar en Obsidian tras preparar la propuesta; debe conservar la edición y dar conflicto.',
    '03_recibo.md': 'Repetir la misma petición después de editar; no debe volver a escribir.',
    '04_reinicio.md': 'Interrumpir después de aplicar y recuperar tras reiniciar sin duplicar el cambio.',
    '05_reversion.md': 'Restaurar la revisión anterior y conservar ambas versiones en el historial.',
}


def prepare(project: Path) -> Path:
    project = project.resolve()
    package = project / 'obsidian-bridge'
    # Verify inputs before making a new, isolated trial. Never update an existing vault.
    originals = {name: (package / name).read_bytes() for name in PACKAGE_FILES}
    identifier = uuid.uuid4().hex
    # The task's temporary directory is writable even when the checkout's .local
    # folder has a restrictive ACL. mkdtemp creates a new directory exclusively.
    vault = Path(tempfile.mkdtemp(prefix='ko-obsidian-trial-'))
    plugin = vault / '.obsidian' / 'plugins' / 'knowledge-orchestrator-bridge'
    plugin.mkdir(parents=True)
    for name, content in originals.items():
        with (plugin / name).open('xb') as output:
            output.write(content)
    (plugin / 'data.json').write_text(json.dumps({'enabled': False, 'secretName': '', 'port': 8767}),
                                    encoding='utf-8')
    (vault / '.obsidian' / 'community-plugins.json').write_text('[]\n', encoding='utf-8')
    notes = {}
    for index, (name, purpose) in enumerate(CASES.items(), 1):
        content = f'# Ensayo {index}\n\nLa versión de Producto Ensayo es 1.0.\n'
        (vault / name).write_bytes(content.encode('utf-8'))
        notes[name] = {'purpose': purpose, 'base_hash': hashlib.sha256(content.encode()).hexdigest(),
                       'status': 'NOT_RUN'}
    manifest = {'schema': 1, 'trial_id': identifier, 'status': 'PREPARED_NOT_EXECUTED',
                'synthetic_content_only': True, 'plugin_enabled': False, 'cases': notes,
                'plugin_hashes': {name: hashlib.sha256(content).hexdigest() for name, content in originals.items()}}
    (vault / 'trial-manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    shutil.copyfile(package / 'README.md', vault / 'Guia_del_puente.md')
    (vault / 'EMPEZAR_AQUI.md').write_text(
        '# Bóveda de ensayo del puente Obsidian\n\n'
        'Esta carpeta contiene únicamente documentos de prueba. No es tu bóveda de conocimiento.\n\n'
        'El complemento está copiado, pero desactivado. No contiene ninguna credencial. '
        'Ninguno de los escenarios está ejecutado ni verificado.\n\n'
        '## Preparación\n\n'
        '1. Abrir esta carpeta como bóveda en Obsidian.\n'
        '2. Activar Knowledge Orchestrator Bridge y configurar una credencial exclusiva de ensayo, '
        'distinta de la del Broker.\n'
        '3. Conectar el Orchestrator de ensayo a esta bóveda y comprobar su identidad.\n'
        '4. Ejecutar los cinco escenarios de `trial-manifest.json` y registrar resultados reales.\n\n'
        'La prueba de edición debe hacerse dentro del editor de Obsidian, incluida una nota abierta '
        'con cambios recientes. Una escritura de Python no acredita ese caso.\n\n'
        'Los recibos y hashes no sustituyen la observación visual. La prueba completa con el Broker '
        'y la revisión de pantallas siguen siendo verificaciones independientes.\n\n'
        'Consulta [[Guia_del_puente]] para el contrato y los límites de recuperación.\n',
        encoding='utf-8',
    )
    # Verify the actual staged package and fixtures, without loading executable plugin code.
    for name, content in originals.items():
        if (plugin / name).read_bytes() != content:
            raise RuntimeError('El paquete de ensayo no coincide con el código del proyecto')
    for name, record in notes.items():
        if hashlib.sha256((vault / name).read_bytes()).hexdigest() != record['base_hash']:
            raise RuntimeError('Una nota de ensayo no coincide con su base')
    return vault


if __name__ == '__main__':
    print(prepare(Path(__file__).resolve().parents[1]))
