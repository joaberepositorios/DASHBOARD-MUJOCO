"""Importa o MuJoCo tolerando um plugin que o Windows bloqueie.

O pacote carrega todos os plugins da pasta mujoco/plugin ao ser importado e
desiste se um falhar. O Smart App Control do Windows (politica "verificado e
confiavel") passou a bloquear o sdf_plugin.dll, que o estudio nao usa. Aqui o
carregador ignora esse bloqueio, so' para arquivos dessa pasta, e segue.

Uso:  from mujoco_carga import mujoco
"""

import ctypes
import os

_original = ctypes.CDLL
BLOQUEIO_WINDOWS = 4551   # ERROR_SYSTEM_INTEGRITY_POLICY_VIOLATION

def _tolerante(nome, *args, **kwargs):
    try:
        return _original(nome, *args, **kwargs)
    except OSError as e:
        texto = str(nome)
        if os.sep + "plugin" + os.sep in texto and getattr(e, "winerror", None) == BLOQUEIO_WINDOWS:
            print("  MuJoCo ..... o Windows bloqueou o plugin %s; seguindo sem ele"
                  % os.path.basename(texto))
            return None
        raise

ctypes.CDLL = _tolerante
try:
    import mujoco
except ImportError:
    mujoco = None
finally:
    ctypes.CDLL = _original
