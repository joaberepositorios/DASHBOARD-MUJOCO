"""Onde ficam os dados do usuario: simulacoes, programas, treinos, materiais.

Fora da pasta do codigo de proposito. O codigo vive no OneDrive, e o
OneDrive segura arquivos por instantes enquanto sincroniza -- ruim para o
que muda a cada segundo (o treino grava a cada tentativa). Por padrao os
dados ficam em ~/EstudioGo2; a variavel de ambiente ESTUDIO_DADOS troca.

Na primeira abertura depois desta mudanca, o que estava nas pastas antigas
(ao lado do codigo) e' movido para ca'.
"""

import os
import shutil

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.environ.get("ESTUDIO_DADOS") or os.path.join(os.path.expanduser("~"), "EstudioGo2")
PASTAS = ("simulacoes", "programas", "treinos", "materiais")

def pasta(nome):
    return os.path.join(RAIZ, nome)

def migrar(avisar=print):
    """Move o conteudo das pastas antigas (junto do codigo) para a raiz de
    dados. Nao sobrescreve: se o arquivo ja existe no destino, o antigo
    fica onde esta'."""
    os.makedirs(RAIZ, exist_ok=True)
    for nome in PASTAS:
        antiga = os.path.join(AQUI, nome)
        if not os.path.isdir(antiga) or os.path.abspath(antiga) == os.path.abspath(pasta(nome)):
            continue
        nova = pasta(nome)
        os.makedirs(nova, exist_ok=True)
        movidos = 0
        for item in os.listdir(antiga):
            origem, destino = os.path.join(antiga, item), os.path.join(nova, item)
            if os.path.exists(destino):
                continue
            try:
                shutil.move(origem, destino)
                movidos += 1
            except OSError as e:
                avisar("  dados ...... nao movi %s: %s" % (origem, e))
        if movidos:
            avisar("  dados ...... %d itens de %s/ movidos para %s" % (movidos, nome, nova))
        try:
            os.rmdir(antiga)          # so' se ficou vazia
        except OSError:
            pass
