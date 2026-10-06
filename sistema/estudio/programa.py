"""Programas em Python escritos na pagina, rodando dentro do estudio.

O codigo do usuario roda numa thread do proprio servidor, com um objeto
`robo` que enfileira as acoes da biblioteca (acoes.py) e espera cada uma
terminar. `print` vai para a saida que a pagina mostra. "Parar" levanta
`Interrompido` na proxima linha do programa (sys.settrace) e dentro de
qualquer espera do `robo`.

E' Python de verdade, com os poderes do processo do servidor: so' para quem
esta' na maquina (o estudio sobe em localhost por padrao). Os programas
gravados ficam em `programas/<nome>.py`, abertos por qualquer editor.
"""

import builtins
import inspect
import math
import os
import re
import sys
import threading
import time
import traceback

AQUI = os.path.dirname(os.path.abspath(__file__))
import dados
PASTA = dados.pasta("programas")
ARQUIVO = "<programa>"
MAX_SAIDA = 2000            # linhas guardadas
MAX_CODIGO = 200 * 1024
PASSO_ESPERA = 0.01         # s entre conferencias enquanto espera uma acao

EXEMPLO = '''# O robô obedece ao que você escrever aqui. Ctrl+Enter executa.
# Cada chamada do robo espera a ação terminar e devolve True se deu certo.

robo.levantar()
if robo.andar(1.0):
    robo.girar(90)
    robo.andar(0.5)

print("posição:", robo.posicao(), "rumo:", robo.rumo())
print("placar:", robo.placar())
'''

class Interrompido(BaseException):
    """Levantada dentro do programa quando alguem pede Parar."""

class Treino:
    """O objeto `treino` do programa. Fora de um treino, `parametro` devolve
    o padrao; dentro, o valor que a tentativa esta' experimentando."""

    def __init__(self, valores=None):
        self._valores = valores or {}
        self.ativo = valores is not None

    def parametro(self, nome, padrao, minimo=None, maximo=None):
        """Um valor que o treino pode variar entre `minimo` e `maximo`; fora do treino vale `padrao`."""
        v = self._valores.get(nome, padrao)
        if minimo is not None and maximo is not None:
            v = min(float(maximo), max(float(minimo), float(v)))
        return v

# ---------- o que o programa ve ----------

class Robo:
    """O objeto `robo` do programa. Cada metodo que move o robo so' volta
    quando a acao termina e devolve True se deu certo (False se caiu, foi
    interrompida ou o teste ja' tinha acabado). O detalhe fica em
    `robo.ultimo`."""

    def __init__(self, prog):
        self._prog = prog
        self._mundo = prog.mundo
        self.ultimo = None

    # --- espera ---

    def _checar(self):
        if self._prog.parar_pedido.is_set():
            raise Interrompido()

    def _ate(self, cond):
        while True:
            self._checar()
            with self._mundo.trava:
                r = cond()
            if r:
                return r
            time.sleep(PASSO_ESPERA)

    def _executar(self, aid, params):
        fim_teste = self.terminou()
        if fim_teste:
            self.ultimo = {"id": aid, "fim": "falhou", "detalhe": "o teste já terminou (%s)" % fim_teste}
            return False
        acao = self._mundo.enfileirar(aid, params)   # ValueError se o cenario nao libera
        self._ate(lambda: acao.fim is not None)
        self.ultimo = acao.estado()
        if acao.fim == "pronto":
            return True
        # o fim do teste corta a acao em curso: isso nao e' falha da acao
        fim_teste = self.terminou()
        if acao.detalhe == "interrompida" and fim_teste:
            self.ultimo["detalhe"] = "o teste terminou: %s" % fim_teste
            return fim_teste == "sucesso"
        return False

    # --- mover ---

    def levantar(self):
        """Levanta (de sentado ou deitado) até ficar de pé."""
        return self._executar("levantar", {})

    def ficar_de_pe(self):
        """Vai à pose de pé e segura."""
        return self._executar("ficar_de_pe", {})

    def sentar(self):
        """Senta: traseira no chão, dianteiras esticadas."""
        return self._executar("sentar", {})

    def deitar(self):
        """Deita com as quatro pernas dobradas."""
        return self._executar("deitar", {})

    def andar(self, distancia=1.0, velocidade=0.35):
        """Anda em frente `distancia` metros mantendo o rumo; velocidade negativa anda de ré."""
        return self._executar("andar", {"distancia": distancia, "velocidade": velocidade})

    def girar(self, graus=90.0, velocidade=0.6):
        """Gira no lugar `graus`: positivo à esquerda, negativo à direita."""
        return self._executar("girar", {"graus": graus, "velocidade": velocidade})

    def ir_ate(self, nome, folga=0.0):
        """Gira para a zona ou objeto `nome` e anda até ele, parando `folga` metros antes."""
        if not self.girar(self.direcao(nome)):
            return False
        d = self.distancia(nome) - folga
        return True if d < 0.1 else self.andar(d)

    def acao(self, id, **parametros):
        """Enfileira uma ação da biblioteca pelo id sem esperar, ex.: robo.acao("andar_ate_parar", velocidade=0.3)."""
        self._mundo.enfileirar(id, parametros)

    def aguardar(self):
        """Espera a fila de ações esvaziar."""
        self._ate(lambda: self._mundo.atual is None and not self._mundo.fila)

    def parar(self):
        """Interrompe a ação em curso e limpa a fila."""
        self._mundo.parar_acoes()

    def esperar(self, segundos=1.0):
        """Fica como está por `segundos` da simulação (Parar interrompe)."""
        fim = self._mundo.relogio + float(segundos)
        self._ate(lambda: self._mundo.relogio >= fim)

    def reiniciar(self):
        """Volta o robô à partida e zera o placar."""
        self._mundo.comandar({"reiniciar": True})

    def ajustar(self, padrao=False, **valores):
        """Muda ajustes do controlador e grava (valem até mudar de novo), ex.: robo.ajustar(marcha_T=0.5, ctrl_kp=110); padrao=True volta aos de fábrica."""
        import treino as T
        if padrao:
            T.definir_ajustes(self._mundo, {}, gravar=not self._prog.valores)
        if valores:
            T.aplicar_ajustes(self._mundo, {k.replace("_", ".", 1): v for k, v in valores.items()},
                              gravar=not self._prog.valores)     # dentro de um treino, nao grava
        return self.ajustes()

    def ajustes(self):
        """Os ajustes atuais do controlador (os nomes que `ajustar` aceita)."""
        import treino as T
        return {k.replace(".", "_", 1): v for k, v in T.ajustes_atuais(self._mundo).items()}

    # --- medir ---

    def posicao(self):
        """(x, y) do corpo em metros, arredondado a 1 cm."""
        with self._mundo.trava:
            return (round(float(self._mundo.d.qpos[0]), 2), round(float(self._mundo.d.qpos[1]), 2))

    def altura(self):
        """Altura do corpo em metros."""
        with self._mundo.trava:
            return round(float(self._mundo.d.qpos[2]), 3)

    def rumo(self):
        """Rumo em graus, de -180 a 180; 0 aponta para +x."""
        with self._mundo.trava:
            return round(math.degrees(self._mundo.yaw()), 1)

    def postura(self):
        """"de pe", "sentado", "deitado" ou "parcial"."""
        return self._mundo.estado()["postura"]

    def tempo(self):
        """Segundos desde o início do teste."""
        return round(self._mundo.tempo, 2)

    def quedas(self):
        """Quantas vezes o robô caiu neste teste."""
        return self._mundo.quedas

    def placar(self):
        """dict com pontos, tempo, fim ("sucesso", "falha" ou None) e eventos."""
        with self._mundo.trava:
            return self._mundo.placar.estado() if self._mundo.placar else None

    def pontos(self):
        """Pontos do placar."""
        p = self.placar()
        return p["pontos"] if p else 0

    def terminou(self):
        """Resultado do teste: "sucesso", "falha" ou None enquanto roda."""
        p = self.placar()
        return p["fim"] if p else None

    # --- cenario ---

    def zonas(self):
        """Nomes das zonas do cenário."""
        return [z["nome"] for z in self._mundo.cen["zonas"]]

    def objetos(self):
        """Nomes dos objetos do cenário."""
        return [o["nome"] for o in self._mundo.cen["objetos"]]

    def zona(self, nome):
        """A zona com esse nome: dict com tipo, pos [x, y], tam [c, l] e giro."""
        tipo, it = self._achar(nome)
        if tipo != "zona":
            raise ValueError("%r é um objeto, não uma zona" % (nome,))
        return {"nome": it["nome"], "tipo": it["tipo"], "pos": list(it["pos"]), "tam": list(it["tam"]), "giro": it["giro"]}

    def objeto(self, nome):
        """O objeto com esse nome: dict com tipo, pos [x, y, z] atual, tam e fixo."""
        tipo, it = self._achar(nome)
        if tipo != "objeto":
            raise ValueError("%r é uma zona, não um objeto" % (nome,))
        return {"nome": it["nome"], "tipo": it["tipo"], "pos": self._pos_objeto(it),
                "tam": list(it["tam"]), "fixo": it["fixo"]}

    def na_zona(self, nome):
        """True se o robô está dentro da zona."""
        z = self.zona(nome)
        x, y = self.posicao()
        a = math.radians(-z["giro"])
        dx, dy = x - z["pos"][0], y - z["pos"][1]
        lx = dx * math.cos(a) - dy * math.sin(a)
        ly = dx * math.sin(a) + dy * math.cos(a)
        return abs(lx) <= z["tam"][0] / 2 and abs(ly) <= z["tam"][1] / 2

    def distancia(self, nome):
        """Distância em metros do robô ao centro da zona ou objeto."""
        ax, ay = self._centro(nome)
        x, y = self.posicao()
        return round(math.hypot(ax - x, ay - y), 2)

    def direcao(self, nome):
        """Quanto girar (graus, -180 a 180) para apontar à zona ou objeto."""
        ax, ay = self._centro(nome)
        x, y = self.posicao()
        alvo = math.degrees(math.atan2(ay - y, ax - x))
        return round((alvo - self.rumo() + 180.0) % 360.0 - 180.0, 1)

    # --- apoio ---

    def _achar(self, nome):
        chave = str(nome).strip().lower()
        cen = self._mundo.cen
        for tipo, lista in (("zona", cen["zonas"]), ("objeto", cen["objetos"])):
            for it in lista:
                if it["nome"].lower() == chave or it["id"] == chave:
                    return tipo, it
        raise ValueError("não há zona nem objeto chamado %r" % (nome,))

    def _centro(self, nome):
        tipo, it = self._achar(nome)
        p = it["pos"] if tipo == "zona" else self._pos_objeto(it)
        return float(p[0]), float(p[1])

    def _pos_objeto(self, o):
        if o["fixo"] or o["tipo"] == "relevo":
            return [round(float(v), 2) for v in o["pos"]]
        from mujoco_carga import mujoco
        with self._mundo.trava:
            b = mujoco.mj_name2id(self._mundo.m, mujoco.mjtObj.mjOBJ_BODY, "obj_" + o["id"])
            p = self._mundo.d.xpos[b] if b >= 0 else o["pos"]
            return [round(float(v), 2) for v in p]

def referencia():
    """Os metodos publicos de `robo` e `treino`, na ordem em que estao
    escritos, para a pagina listar: nome, assinatura e a primeira linha da
    descricao."""
    saida = []
    for objeto, classe in (("robo", Robo), ("treino", Treino)):
        for nome, fn in vars(classe).items():
            if nome.startswith("_") or not inspect.isfunction(fn):
                continue
            sig = str(inspect.signature(fn)).replace("(self, ", "(").replace("(self)", "()")
            saida.append({"nome": nome, "assinatura": "%s.%s%s" % (objeto, nome, sig),
                          "texto": (fn.__doc__ or "").strip().split("\n")[0]})
    return saida

def parametros_do_programa(codigo):
    """As chamadas treino.parametro("nome", padrao, minimo, maximo) com
    valores constantes, lidas do codigo sem executa-lo."""
    import ast
    saida = []
    try:
        arvore = ast.parse(codigo)
    except SyntaxError:
        return saida
    for no in ast.walk(arvore):
        if not (isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)
                and isinstance(no.func.value, ast.Name) and no.func.value.id == "treino"
                and no.func.attr == "parametro"):
            continue
        campos = {}
        for i, a in enumerate(no.args):
            campos[("nome", "padrao", "minimo", "maximo")[i] if i < 4 else "x"] = a
        for kw in no.keywords:
            campos[kw.arg] = kw.value
        try:
            nome = campos["nome"].value
            padrao = campos["padrao"].value
            minimo = campos["minimo"].value if "minimo" in campos else None
            maximo = campos["maximo"].value if "maximo" in campos else None
        except (KeyError, AttributeError):
            continue
        if not isinstance(nome, str) or isinstance(padrao, bool) or not isinstance(padrao, (int, float)):
            continue
        if any(n is not None and (isinstance(n, bool) or not isinstance(n, (int, float))) for n in (minimo, maximo)):
            continue
        if any(p["nome"] == nome for p in saida):
            continue
        saida.append({"nome": nome, "padrao": padrao, "min": minimo, "max": maximo,
                      "linha": no.lineno, "col_padrao": [campos["padrao"].lineno, campos["padrao"].col_offset,
                                                        campos["padrao"].end_lineno, campos["padrao"].end_col_offset]})
    return saida

# ---------- execucao ----------

class Programa:
    """Um programa por vez. Guarda a saida e o estado para a pagina."""

    def __init__(self, mundo):
        self.mundo = mundo
        self.trava = threading.Lock()
        self.parar_pedido = threading.Event()
        self.thread = None
        self.nome = ""
        self.saida = []          # [n, t, tipo, texto]
        self.n = 0
        self.linha = 0
        self.fim = None          # None, "pronto", "erro", "interrompido"
        self.erro = ""
        self.linha_erro = 0
        self.inicio = None
        self.duracao = 0.0
        self.reservado = None    # quem esta' usando o programa (o treino), ou None

    @property
    def rodando(self):
        return self.thread is not None and self.thread.is_alive()

    def iniciar(self, codigo, nome="", valores=None, dono=None):
        if not self.mundo.pronto:
            raise RuntimeError("o MuJoCo ainda nao esta pronto")
        if self.reservado and dono is not self.reservado:
            raise ValueError("ha um treino rodando; pare-o antes de executar um programa")
        if not isinstance(codigo, str) or len(codigo) > MAX_CODIGO:
            raise ValueError("o programa precisa ser texto de ate %d KB" % (MAX_CODIGO // 1024))
        if not codigo.strip():
            raise ValueError("o programa esta vazio")
        with self.trava:
            if self.rodando:
                raise ValueError("ja ha um programa rodando; pare-o antes")
            self.parar_pedido.clear()
            self.saida = []
            self.n = 0
            self.linha = 0
            self.fim = None
            self.erro = ""
            self.linha_erro = 0
            self.nome = str(nome)[:60]
            self.inicio = time.monotonic()
            self.duracao = 0.0
            self.valores = valores
            self.thread = threading.Thread(target=self._rodar, args=(codigo,), name="programa", daemon=True)
            self.thread.start()
        return self.estado()

    def parar(self):
        if self.rodando:
            self.parar_pedido.set()
            self.mundo.parar_acoes()
        return self.estado()

    def escrever(self, texto, tipo="saida"):
        t = round(self.mundo.tempo, 1)
        with self.trava:
            for linha in texto.split("\n"):
                self.n += 1
                self.saida.append([self.n, t, tipo, linha])
            del self.saida[:-MAX_SAIDA]

    def _print(self, *args, sep=" ", end="\n", file=None, flush=False):
        texto = sep.join(str(a) for a in args) + end
        if texto.endswith("\n"):
            texto = texto[:-1]
        self.escrever(texto)

    def _traco(self, frame, evento, arg):
        if frame.f_code.co_filename != ARQUIVO:
            return None               # codigo de biblioteca: nao acompanha linha a linha
        if evento == "line":
            self.linha = frame.f_lineno
            if self.parar_pedido.is_set():
                raise Interrompido()
        return self._traco

    def _preparar_mundo(self):
        m = self.mundo
        if m.cen["base"] != "chao":
            raise ValueError("na bancada o robô fica preso no suporte; abra uma simulação no chão livre")
        if m.modo != "testar":
            m.comandar({"modo": "testar"})
            self.escrever("modo Testar ligado", "aviso")

    def _rodar(self, codigo):
        robo = Robo(self)
        amb = {"__name__": "__programa__", "__builtins__": builtins, "robo": robo,
               "treino": Treino(self.valores), "print": self._print}
        try:
            try:
                cod = compile(codigo, ARQUIVO, "exec")
            except SyntaxError as e:
                return self._terminar("erro", "erro de sintaxe: %s" % e.msg, e.lineno or 0)
            self._preparar_mundo()
            sys.settrace(self._traco)
            try:
                exec(cod, amb)
            finally:
                sys.settrace(None)
            self._terminar("pronto", "")
        except Interrompido:
            self._terminar("interrompido", "")
        except SystemExit:
            self._terminar("pronto", "")
        except BaseException as e:       # noqa: o erro do usuario, seja qual for
            linha = 0
            for fr in reversed(traceback.extract_tb(e.__traceback__)):
                if fr.filename == ARQUIVO:
                    linha = fr.lineno
                    break
            self._terminar("erro", "%s: %s" % (type(e).__name__, e), linha)

    def _terminar(self, fim, erro, linha=0):
        self.duracao = time.monotonic() - self.inicio
        self.fim, self.erro, self.linha_erro = fim, erro, linha
        if fim == "pronto":
            self.escrever("terminou em %.1f s" % self.duracao, "aviso")
        elif fim == "interrompido":
            self.escrever("interrompido na linha %d" % self.linha, "aviso")
        else:
            self.escrever(("linha %d: " % linha if linha else "") + erro, "erro")

    def resumo(self):
        return {"rodando": self.rodando, "nome": self.nome, "linha": self.linha, "fim": self.fim}

    def estado(self, desde=0):
        with self.trava:
            rodando = self.rodando
            return {"rodando": rodando, "nome": self.nome, "linha": self.linha,
                    "fim": self.fim, "erro": self.erro, "linha_erro": self.linha_erro,
                    "duracao": round(time.monotonic() - self.inicio if rodando else self.duracao, 1) if self.inicio else 0.0,
                    "total": self.n,
                    "saida": [l for l in self.saida if l[0] > desde]}

# ---------- disco ----------

def nome_limpo(nome):
    """Um nome de arquivo que o Windows aceita, com acentos e espacos."""
    nome = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", str(nome))
    nome = re.sub(r"\s+", " ", nome).strip(" .")[:60].strip(" .")
    if nome.lower().endswith(".py"):
        nome = nome[:-3].strip(" .")
    return nome or "programa"

def _caminho(nome):
    return os.path.join(PASTA, nome_limpo(nome) + ".py")

def listar():
    os.makedirs(PASTA, exist_ok=True)
    saida = []
    for arq in os.listdir(PASTA):
        if not arq.lower().endswith(".py"):
            continue
        caminho = os.path.join(PASTA, arq)
        try:
            with open(caminho, encoding="utf-8") as fp:
                linhas = sum(1 for _ in fp)
        except (OSError, UnicodeDecodeError):
            continue
        saida.append({"nome": arq[:-3], "linhas": linhas, "modificado": os.path.getmtime(caminho)})
    saida.sort(key=lambda p: -p["modificado"])
    return saida

def carregar(nome):
    with open(_caminho(nome), encoding="utf-8") as fp:
        return {"nome": nome_limpo(nome), "codigo": fp.read()}

def gravar(nome, codigo):
    if not isinstance(codigo, str) or len(codigo) > MAX_CODIGO:
        raise ValueError("o programa precisa ser texto de ate %d KB" % (MAX_CODIGO // 1024))
    os.makedirs(PASTA, exist_ok=True)
    nome = nome_limpo(nome)
    with open(_caminho(nome), "w", encoding="utf-8", newline="\n") as fp:
        fp.write(codigo if codigo.endswith("\n") else codigo + "\n")
    return {"nome": nome, "linhas": codigo.count("\n") + (0 if codigo.endswith("\n") else 1)}

def apagar(nome):
    os.remove(_caminho(nome))
