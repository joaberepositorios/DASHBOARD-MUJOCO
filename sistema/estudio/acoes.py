"""Biblioteca de acoes do Go2.

Cada acao do REGISTRO tem nome, descricao, parametros com limites e a classe
que a executa. A mesma lista vira os botoes da pagina e, mais adiante, as
ferramentas que a IA pode chamar.

Uma acao em execucao recebe `passo(mundo, dt)` a cada tique da fisica e
devolve o que o robo deve fazer naquele tique:

  ("marcha", vx, wz) ou ("marcha", vx, vy, wz)   anda com o controlador de marcha
  ("pose", q_des)      segura/leva as juntas a uma pose (sentar, deitar...)

e marca `fim` como "pronto" ou "falhou" quando acaba. O mundo (mundo.py) roda
uma acao por vez, em fila; "parar" limpa a fila.
"""

import math

import numpy as np

# Poses (FL, FR, RL, RR; cada perna: abducao, coxa, canela), em radianos.
POSE_PE = np.array([0.0, 0.9, -1.8] * 4)
POSE_SENTADO = np.array([0.0, 0.55, -1.25, 0.0, 0.55, -1.25, 0.0, 1.45, -2.6, 0.0, 1.45, -2.6])
POSE_DEITADO = np.array([0.0, 1.35, -2.65] * 4)

VEL_MAX = 0.6          # m/s
GIRO_MAX = 0.8         # rad/s
RUMO_GANHO = 1.5       # rad/s por radiano fora do rumo; 2.0+ derruba o robo, 1.0 nao segura
RUMO_GIRO_MAX = 0.5
TOMBADO = 0.55         # cos do angulo com a vertical abaixo do qual tombou

def _norm(a):
    return math.atan2(math.sin(a), math.cos(a))

class Acao:
    """Base: guarda parametros e o resultado."""
    id = ""
    nome = ""
    postura_final = None     # pose a segurar quando acabar (None = de pe, pela marcha)

    def __init__(self, **params):
        self.params = params
        self.fim = None          # None, "pronto" ou "falhou"
        self.detalhe = ""
        self.progresso = 0.0

    def iniciar(self, mundo):
        pass

    def passo(self, mundo, dt):
        raise NotImplementedError

    def falhar(self, motivo):
        self.fim = "falhou"
        self.detalhe = motivo

    def concluir(self, detalhe=""):
        self.fim = "pronto"
        self.detalhe = detalhe
        self.progresso = 1.0

    def estado(self):
        return {"id": self.id, "nome": self.nome, "parametros": self.params,
                "progresso": round(self.progresso, 2), "fim": self.fim, "detalhe": self.detalhe}

# ---------- poses ----------

class Postura(Acao):
    """Leva as juntas da pose atual a `alvo` numa curva suave, segura um
    pouco e termina. Falha se o corpo tombar."""
    alvo = POSE_PE
    duracao = 1.5
    segurar = 0.4
    acalmar = 0.5      # vindo da marcha, fica parado em pe antes de mudar de pose

    def iniciar(self, mundo):
        self.t = 0.0
        self.de = None
        # vindo da marcha as pernas estao no meio de um passo: espera parar
        self.espera = self.acalmar if mundo.postura is None else 0.0

    def passo(self, mundo, dt):
        if self.espera > 0:
            self.espera -= dt
            return ("marcha", 0.0, 0.0)
        if self.de is None:
            self.de = mundo.d.qpos[7:19].copy()
            # de deitado ate de pe e' mais longe: vai mais devagar
            self.dur = self.duracao * (1.0 if np.abs(self.alvo - self.de).max() < 1.2 else 1.4)
        self.t += dt
        a = min(1.0, self.t / self.dur)
        a = a * a * (3 - 2 * a)
        self.progresso = min(1.0, self.t / (self.dur + self.segurar))
        if self.t >= self.dur + self.segurar:
            self.concluir()
        return ("pose", self.de + (self.alvo - self.de) * a)

class FicarDePe(Postura):
    id, nome = "ficar_de_pe", "Ficar de pé"
    alvo = POSE_PE
    postura_final = None

class Levantar(FicarDePe):
    id, nome = "levantar", "Levantar"

class Sentar(Postura):
    id, nome = "sentar", "Sentar"
    alvo = POSE_SENTADO
    postura_final = POSE_SENTADO

class Deitar(Postura):
    id, nome = "deitar", "Deitar"
    alvo = POSE_DEITADO
    postura_final = POSE_DEITADO

# ---------- marcha ----------

ASSENTAR = 0.6         # s dentro da tolerancia antes de dar por pronto
TEMPO_MAX = 60.0       # s; passou disso, termina "aproximado"

class Marcha(Acao):
    """Base das acoes que usam o controlador de marcha. Se o robo estiver
    sentado ou deitado, a propria marcha o leva a pose de pe.

    Andar e girar sao fechados em malha: o comando e' proporcional ao que
    falta, com um minimo que a marcha ainda obedece, e a acao so' termina
    depois de ficar `ASSENTAR` segundos dentro da tolerancia."""

    def iniciar(self, mundo):
        self.x0, self.y0 = float(mundo.d.qpos[0]), float(mundo.d.qpos[1])
        self.psi0 = mundo.yaw()
        self.psi_ant = self.psi0
        self.acum = 0.0
        self.percorrido = 0.0
        self.assentado = 0.0
        self.t = 0.0
        mundo.motor.zerar_marcha()

    def medir(self, mundo, dt):
        x, y = float(mundo.d.qpos[0]), float(mundo.d.qpos[1])
        self.percorrido = (x - self.x0) * math.cos(self.psi0) + (y - self.y0) * math.sin(self.psi0)
        psi = mundo.yaw()
        self.acum += _norm(psi - self.psi_ant)
        self.psi_ant = psi
        self.t += dt

    def chegou(self, erro, tol, dt, detalhe):
        """Conta o tempo dentro da tolerancia; True quando assentou."""
        self.assentado = self.assentado + dt if abs(erro) <= tol else 0.0
        if self.assentado >= ASSENTAR:
            self.concluir(detalhe)
            return True
        if self.t > TEMPO_MAX:
            self.concluir(detalhe + " (aproximado)")
            return True
        return False

    def rumo(self, mundo):
        return max(-RUMO_GIRO_MAX, min(RUMO_GIRO_MAX, RUMO_GANHO * _norm(self.psi0 - mundo.yaw())))

    def segurar_lugar(self, mundo, ganho=1.0, vmax=0.15):
        """Girando no lugar a marcha deriva uns 30 cm; empurra de volta ao
        ponto de partida (vx, vy no referencial do corpo)."""
        dx, dy = self.x0 - float(mundo.d.qpos[0]), self.y0 - float(mundo.d.qpos[1])
        psi = mundo.yaw()
        bx = dx * math.cos(psi) + dy * math.sin(psi)
        by = -dx * math.sin(psi) + dy * math.cos(psi)
        return (max(-vmax, min(vmax, ganho * bx)), max(-vmax, min(vmax, ganho * by)))

class Andar(Marcha):
    id, nome = "andar", "Andar"
    GANHO, MINIMO, BANDA, TOL = 1.5, 0.12, 0.03, 0.06

    def passo(self, mundo, dt):
        self.medir(mundo, dt)
        vel = max(-VEL_MAX, min(VEL_MAX, float(self.params.get("velocidade", 0.35))))
        dist = self.params.get("distancia")
        if dist is None:
            return ("marcha", vel, self.rumo(mundo))
        erro = math.copysign(dist, vel) - self.percorrido
        self.progresso = min(1.0, abs(self.percorrido) / max(0.01, dist))
        if self.chegou(erro, self.TOL, dt, "%.2f m" % abs(self.percorrido)):
            return ("marcha", 0.0, 0.0)
        v = 0.0 if abs(erro) <= self.BANDA else math.copysign(min(abs(vel), max(self.MINIMO, self.GANHO * abs(erro))), erro)
        return ("marcha", v, self.rumo(mundo))

class AndarAteParar(Andar):
    id, nome = "andar_ate_parar", "Andar até parar"

    def passo(self, mundo, dt):
        self.params.pop("distancia", None)
        return super().passo(mundo, dt)

class Girar(Marcha):
    id, nome = "girar", "Girar"
    GANHO, MINIMO, BANDA, TOL = 2.0, 0.4, math.radians(3), math.radians(5)

    def passo(self, mundo, dt):
        self.medir(mundo, dt)
        vel = max(0.1, min(GIRO_MAX, float(self.params.get("velocidade", 0.6))))
        graus = self.params.get("graus")
        if graus is None:
            sentido = 1.0 if self.params.get("sentido", "esquerda") == "esquerda" else -1.0
            return ("marcha", 0.0, sentido * vel)
        alvo = math.radians(graus)
        erro = alvo - self.acum
        self.progresso = min(1.0, abs(self.acum) / max(0.01, abs(alvo)))
        if self.chegou(erro, self.TOL, dt, "%.0f°" % math.degrees(self.acum)):
            return ("marcha", 0.0, 0.0)
        wz = 0.0 if abs(erro) <= self.BANDA else math.copysign(min(vel, max(self.MINIMO, self.GANHO * abs(erro))), erro)
        vx, vy = self.segurar_lugar(mundo)
        return ("marcha", vx, vy, wz)

class GirarAteParar(Girar):
    id, nome = "girar_ate_parar", "Girar até parar"

    def passo(self, mundo, dt):
        self.params.pop("graus", None)
        return super().passo(mundo, dt)

# ---------- registro ----------

def _p(nome, minimo, maximo, padrao, unidade, texto, opcional=False):
    return {"nome": nome, "min": minimo, "max": maximo, "padrao": padrao,
            "unidade": unidade, "texto": texto, "opcional": opcional}

REGISTRO = [
    dict(id="ficar_de_pe", nome="Ficar de pé", classe=FicarDePe, liberada_por=None,
         descricao="Leva o robô à pose de pé e segura.", parametros=[]),
    dict(id="sentar", nome="Sentar", classe=Sentar, liberada_por="sentar",
         descricao="Senta: traseira no chão, dianteiras esticadas.", parametros=[]),
    dict(id="deitar", nome="Deitar", classe=Deitar, liberada_por="deitar",
         descricao="Deita com as quatro pernas dobradas.", parametros=[]),
    dict(id="levantar", nome="Levantar", classe=Levantar, liberada_por=None,
         descricao="Levanta de sentado ou deitado até ficar de pé.", parametros=[]),
    dict(id="andar", nome="Andar", classe=Andar, liberada_por="andar",
         descricao="Anda em frente uma distância, mantendo o rumo. Velocidade negativa anda de ré.",
         parametros=[_p("distancia", 0.1, 20.0, 1.0, "m", "Distância"),
                     _p("velocidade", -VEL_MAX, VEL_MAX, 0.35, "m/s", "Velocidade", True)]),
    dict(id="andar_ate_parar", nome="Andar até parar", classe=AndarAteParar, liberada_por="andar",
         descricao="Anda em frente até receber Parar.",
         parametros=[_p("velocidade", -VEL_MAX, VEL_MAX, 0.35, "m/s", "Velocidade", True)]),
    dict(id="girar", nome="Girar", classe=Girar, liberada_por="girar",
         descricao="Gira no lugar um ângulo. Positivo vira à esquerda, negativo à direita.",
         parametros=[_p("graus", -360.0, 360.0, 90.0, "°", "Ângulo"),
                     _p("velocidade", 0.1, GIRO_MAX, 0.6, "rad/s", "Velocidade", True)]),
    dict(id="girar_ate_parar", nome="Girar até parar", classe=GirarAteParar, liberada_por="girar",
         descricao="Gira no lugar até receber Parar.",
         parametros=[_p("velocidade", 0.1, GIRO_MAX, 0.6, "rad/s", "Velocidade", True)]),
]
POR_ID = {a["id"]: a for a in REGISTRO}

def publico(liberadas=None):
    """O registro como a pagina e a IA veem; `liberadas` sao as acoes que o
    cenario permite (lista de ids do formulario: andar, girar, sentar...)."""
    saida = []
    for a in REGISTRO:
        ok = a["liberada_por"] is None or liberadas is None or a["liberada_por"] in liberadas
        saida.append({"id": a["id"], "nome": a["nome"], "descricao": a["descricao"],
                      "parametros": a["parametros"], "liberada": ok})
    return saida

def criar(aid, params, liberadas=None):
    """Valida e instancia uma acao. Lanca ValueError se nao der."""
    a = POR_ID.get(aid)
    if a is None:
        raise ValueError("acao desconhecida: %r" % (aid,))
    if liberadas is not None and a["liberada_por"] is not None and a["liberada_por"] not in liberadas:
        raise ValueError("o cenario nao libera a acao %s" % a["nome"])
    if not isinstance(params, dict):
        raise ValueError("parametros precisam ser um objeto")
    limpos = {}
    for p in a["parametros"]:
        v = params.get(p["nome"])
        if v is None:
            if p["opcional"]:
                continue
            v = p["padrao"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError("%s precisa ser um numero" % p["texto"])
        limpos[p["nome"]] = float(min(p["max"], max(p["min"], v)))
    if aid == "girar_ate_parar" and params.get("sentido") in ("esquerda", "direita"):
        limpos["sentido"] = params["sentido"]
    return a["classe"](**limpos)
