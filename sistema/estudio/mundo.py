"""O mundo do MuJoCo que o estudio mostra na pagina.

Duas threads dividem o mesmo MjModel/MjData, protegidas por uma trava:

- a da fisica avanca a simulacao a 100 Hz (so' no modo "testar");
- a da imagem desenha fora da tela (sem janela), comprime em JPEG e publica
  o quadro. So' trabalha enquanto ha alguem assistindo.

O cenario (objetos, zonas, regras) vem de cenario.py. Mudancas pequenas
(posicao, tamanho, material) sao aplicadas no modelo em memoria; incluir ou
tirar objetos recompila a cena, e a thread da imagem refaz o contexto do
OpenGL quando ve a geracao mudar.

Nesta maquina (Intel UHD) cada quadro custa ~22 ms sem sombra e ~65 ms com,
por isso a sombra fica desligada.
"""

import math
import os
import threading
import time
import traceback
import urllib.request

from mujoco_carga import mujoco
try:
    import numpy as np
except ImportError:
    np = None

import acoes as A
import cenario as C
import materiais as M

AQUI = os.path.dirname(os.path.abspath(__file__))

DT_FISICA = 0.01
FPS_ALVO = 30
LARG_MAX, ALT_MAX = C.LARG_MAX, C.ALT_MAX
VERMELHO = (0.863, 0.149, 0.149, 1.0)   # #dc2626, o acento da pagina
ALTURA_LARGADA = 0.06                   # o robo comeca um pouco acima do chao
MAX_FILA = 20
MAX_ULTIMAS = 12
VELOCIDADE_MAX = 20                     # vezes o tempo real, no treino
MODOS = ("editar", "testar")

# O "Comeca" do cenario vira uma acao enfileirada na largada.
INICIOS = {"parado": None, "frente": ("andar_ate_parar", {}), "girando": ("girar_ate_parar", {})}

# segue=True: o azimute gira junto com o robo (0 = atras dele, olhando p/ frente).
CAMERAS = [
    dict(nome="Órbita", segue=False, az=140.0, el=-22.0, dist=2.0),
    dict(nome="Cena",   segue=False, az=140.0, el=-42.0, dist=4.0),
    dict(nome="Segue",  segue=True,  az=0.0,   el=-16.0, dist=2.2),
    dict(nome="Frente", segue=True,  az=180.0, el=-10.0, dist=1.6),
    dict(nome="Lado",   segue=True,  az=90.0,  el=-8.0,  dist=1.6),
    dict(nome="Cima",   segue=False, az=90.0,  el=-89.0, dist=3.0),
]

_RAW = ("https://raw.githubusercontent.com/google-deepmind/"
        "mujoco_menagerie/main/unitree_go2")
_ARQUIVOS = [
    "go2.xml",
    "assets/base_0.obj", "assets/base_1.obj", "assets/base_2.obj",
    "assets/base_3.obj", "assets/base_4.obj",
    "assets/hip_0.obj", "assets/hip_1.obj",
    "assets/thigh_0.obj", "assets/thigh_1.obj",
    "assets/thigh_mirror_0.obj", "assets/thigh_mirror_1.obj",
    "assets/calf_0.obj", "assets/calf_1.obj",
    "assets/calf_mirror_0.obj", "assets/calf_mirror_1.obj",
    "assets/foot.obj",
]

def _candidatos():
    lar = os.path.expanduser("~")
    return [
        os.path.join(AQUI, "modelo_go2", "unitree_go2"),
        os.path.join(AQUI, "..", "cinematica", "modelo_go2", "unitree_go2"),
        os.path.join(lar, "Downloads", "go2_cinematica_ws", "unitree_go2"),
    ]

def achar_ou_baixar(avisar):
    for pasta in _candidatos():
        if os.path.isfile(os.path.join(pasta, "go2.xml")):
            return os.path.normpath(pasta)
    base = os.path.join(AQUI, "modelo_go2", "unitree_go2")
    os.makedirs(os.path.join(base, "assets"), exist_ok=True)
    for i, rel in enumerate(_ARQUIVOS, 1):
        avisar("baixando o Go2 (%d de %d)" % (i, len(_ARQUIVOS)))
        alvo = os.path.join(base, rel.replace("/", os.sep))
        if os.path.exists(alvo) and os.path.getsize(alvo) > 0:
            continue
        for tentativa in range(3):
            try:
                urllib.request.urlretrieve("%s/%s" % (_RAW, rel), alvo)
                break
            except Exception as e:
                if tentativa == 2:
                    raise RuntimeError(
                        "nao consegui baixar %s (%s). Copie a pasta unitree_go2 "
                        "do mujoco_menagerie para %s" % (rel, e, base))
                time.sleep(0.5)
    return base

def preparar_go2(pasta):
    """Copia do go2.xml sem o keyframe: o tamanho dele nao bate quando a cena
    tem corpos soltos, e o MuJoCo recusa compilar."""
    with open(os.path.join(pasta, "go2.xml"), encoding="utf-8") as fp:
        xml = fp.read()
    ini = xml.find("<keyframe")
    fim = xml.find("</keyframe>")
    if ini >= 0 and fim >= 0:
        xml = xml[:ini] + xml[fim + len("</keyframe>"):]
    alvo = os.path.join(pasta, "go2_estudio.xml")
    with open(alvo, "w", encoding="utf-8") as fp:
        fp.write(xml)
    return alvo

def _codificador():
    try:
        import cv2
        return lambda rgb: cv2.imencode(".jpg", rgb[:, :, ::-1],
                                        [cv2.IMWRITE_JPEG_QUALITY, 84])[1].tobytes()
    except ImportError:
        pass
    try:
        import io
        from PIL import Image
        def pil(rgb):
            b = io.BytesIO()
            Image.fromarray(rgb).save(b, "JPEG", quality=84)
            return b.getvalue()
        return pil
    except ImportError:
        return None

class Quadro:
    """O JPEG mais recente; quem assiste espera o proximo sem ficar perguntando."""

    def __init__(self):
        self.cond = threading.Condition()
        self.seq = 0
        self.jpeg = None

    def publicar(self, jpeg):
        with self.cond:
            self.jpeg = jpeg
            self.seq += 1
            self.cond.notify_all()

    def esperar(self, desde, espera):
        with self.cond:
            self.cond.wait_for(lambda: self.seq != desde, timeout=espera)
            return self.jpeg, self.seq

class Placar:
    """Avalia as regras do cenario a cada passo da fisica, no modo testar."""

    def __init__(self, cen):
        self.regras = cen["regras"]
        self.zonas = {z["id"]: z for z in cen["zonas"]}
        self.pontos = 0.0
        self.tempo = 0.0
        self.fim = None
        self.eventos = []
        self.disparadas = set()
        self.dentro = set()

    def _dentro(self, z, x, y):
        a = math.radians(-z["giro"])
        dx, dy = x - z["pos"][0], y - z["pos"][1]
        lx = dx * math.cos(a) - dy * math.sin(a)
        ly = dx * math.sin(a) + dy * math.cos(a)
        return abs(lx) <= z["tam"][0] / 2 and abs(ly) <= z["tam"][1] / 2

    def _disparar(self, r, texto):
        if r["uma_vez"] and r["id"] in self.disparadas:
            return
        self.disparadas.add(r["id"])
        self.pontos += r["pontos"]
        if r["fim"]:
            self.fim = r["fim"]
        self.eventos.append({"t": round(self.tempo, 1), "texto": texto,
                             "pontos": r["pontos"], "fim": r["fim"]})
        del self.eventos[:-12]

    def avaliar(self, x, y, tocados, caiu, dt):
        if self.fim:
            return
        self.tempo += dt
        agora = {zid for zid, z in self.zonas.items() if self._dentro(z, x, y)}
        entrou, saiu = agora - self.dentro, self.dentro - agora
        self.dentro = agora
        for r in self.regras:
            q = r["quando"]
            if q == "entrar_zona" and r["alvo"] in entrou:
                self._disparar(r, "entrou em %s" % self.zonas[r["alvo"]]["nome"])
            elif q == "sair_zona" and r["alvo"] in saiu:
                self._disparar(r, "saiu de %s" % self.zonas[r["alvo"]]["nome"])
            elif q == "tocar_objeto" and r["alvo"] in tocados:
                self._disparar(r, "tocou %s" % tocados[r["alvo"]])
            elif q == "cair" and caiu:
                self._disparar(r, "caiu")
            elif q == "tempo" and self.tempo >= r["valor"]:
                self._disparar(r, "%.0f s" % r["valor"])
            elif q == "pontos" and self.pontos >= r["valor"] and r["valor"] > 0:
                self._disparar(r, "%.0f pontos" % r["valor"])

    def estado(self):
        return {"pontos": round(self.pontos), "tempo": round(self.tempo, 1),
                "fim": self.fim, "eventos": self.eventos[-8:]}

class Mundo:

    def __init__(self):
        self.trava = threading.RLock()
        self.parar = threading.Event()
        self.ha_visor = threading.Event()
        self.quadro = Quadro()

        self.situacao = "iniciando"
        self.erro = None
        self.pronto = False

        self.m = self.d = self.motor = None
        self.ajustes = {}        # ajustes do controlador em vigor: "marcha.T" -> valor
        self.ao_pronto = None    # chamado uma vez quando a cena fica pronta
        self.cen = None
        self.materiais = {}
        self.mat_ids = {}
        self.assinatura = None
        self.geracao = 0
        self.modo = "editar"
        self.fila = []           # acoes a executar, em ordem
        self.atual = None        # a acao em curso
        self.postura = None      # pose a segurar parado (sentado, deitado); None = de pe
        self.ultimas = []        # resultados recentes
        self.tempo = 0.0         # do teste; zera ao reiniciar
        self.relogio = 0.0       # da simulacao; nunca zera (robo.esperar usa)
        self.velocidade = 1      # tiques da fisica por tique de tempo real
        self.quedas = 0
        self.placar = None

        self.icam = 0
        self.cam_daz = self.cam_del = 0.0
        self.cam_zoom = 1.0
        self.scn = None          # cena do desenho, usada tambem para apontar
        self.vopt = None
        self.scn_geracao = -1

        self.visores = 0
        self.tamanho = (960, 540)
        self.fps = 0.0

    # ---------- partida ----------

    def iniciar(self):
        threading.Thread(target=self._carregar, name="mundo", daemon=True).start()

    def _falhar(self, texto):
        self.erro = texto
        self.situacao = "erro"
        self.pronto = False
        print("  MuJoCo ..... %s" % texto)

    def _carregar(self):
        if mujoco is None:
            return self._falhar("o MuJoCo nao esta instalado (pip install mujoco)")
        self.codificar = _codificador()
        if self.codificar is None:
            return self._falhar("falta quem comprima a imagem (pip install pillow)")
        try:
            faltam = M.preparar(lambda t: setattr(self, "situacao", t))
            if faltam:
                print("  texturas ... sem rede; %d ficaram com cor lisa" % len(faltam))
            self.situacao = "procurando o modelo do Go2"
            self.pasta = achar_ou_baixar(lambda t: setattr(self, "situacao", t))
            preparar_go2(self.pasta)
            self.situacao = "montando a cena"
            self.reconstruir(C.novo("Nova simulação"))
        except Exception as e:
            traceback.print_exc()
            return self._falhar("nao consegui montar a cena: %s" % e)
        print("  MuJoCo ..... cena pronta (%s)" % self.pasta)
        if self.ao_pronto:
            try:
                self.ao_pronto()
            except Exception:
                traceback.print_exc()
        threading.Thread(target=self._laco_fisica, name="fisica", daemon=True).start()
        threading.Thread(target=self._laco_imagem, name="imagem", daemon=True).start()

    # ---------- cena ----------

    def reconstruir(self, cen):
        """Compila a cena inteira de novo. Custa perto de 1 s."""
        import controle
        materiais = M.por_id()
        xml = C.gerar_xml(cen, materiais)
        xml = xml.replace('<include file="go2.xml"/>', '<include file="go2_estudio.xml"/>')
        # Tudo em memoria: malhas, o go2 sem keyframe e as texturas. O MuJoCo
        # nao abre arquivos em pastas com acento no Windows, e assim nem tenta.
        ativos = dict(self._ativos_go2())
        for mat in materiais.values():
            if mat.get("arquivo"):
                with open(mat["arquivo"], "rb") as fp:
                    ativos["tx_%s.png" % mat["id"]] = fp.read()
                ativos["tc_%s.png" % mat["id"]] = self._versao_cubo(mat)
        m = mujoco.MjModel.from_xml_string(xml, ativos)
        for o in cen["objetos"]:
            if o["tipo"] == "relevo":
                hid = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_HFIELD, "hf_" + o["id"])
                adr, n = m.hfield_adr[hid], m.hfield_nrow[hid] * m.hfield_ncol[hid]
                m.hfield_data[adr:adr + n] = C.relevo_alturas(o, m.hfield_nrow[hid]).ravel()
        d = mujoco.MjData(m)
        with self.trava:
            self.m, self.d, self.cen = m, d, cen
            self.materiais = materiais
            self.assinatura = C.assinatura(cen)
            self.motor = controle.MotorDinamico(m, d)
            self._reaplicar_ajustes()      # o motor novo nasce com os padroes
            self._mapear()
            self.geracao += 1
            self._posicionar_robo()

    # ---------- ajustes do controlador ----------

    def _reaplicar_ajustes(self):
        import controle
        self.motor.prm = dict(controle.PARAM_MARCHA)
        self.motor.p = dict(controle.PARAM_CTRL)
        A.RUMO_GANHO = A.RUMO_GANHO_PADRAO
        for vid, v in self.ajustes.items():
            grupo, chave = vid.split(".", 1)
            if grupo == "marcha":
                self.motor.prm[chave] = float(v)
            elif grupo == "ctrl":
                self.motor.p[chave] = float(v)
            elif chave == "rumo_ganho":
                A.RUMO_GANHO = float(v)

    def definir_ajustes(self, valores):
        """Troca o conjunto inteiro (vazio = padroes de fabrica). Os valores
        ja' vem validados por treino.py."""
        with self.trava:
            self.ajustes = {k: float(v) for k, v in valores.items()}
            if self.motor is not None:
                self._reaplicar_ajustes()

    def aplicar_ajustes(self, valores):
        """Muda so' os ajustes dados, mantendo os outros."""
        with self.trava:
            self.ajustes.update({k: float(v) for k, v in valores.items()})
            if self.motor is not None:
                self._reaplicar_ajustes()

    def _versao_cubo(self, mat):
        """A textura dos objetos em 512 px: um cubo guarda seis faces, e dez
        materiais em 1024 encheriam a placa e demorariam para subir."""
        cache = self.__dict__.setdefault("_cubo_cache", {})
        chave = (mat["arquivo"], os.path.getmtime(mat["arquivo"]))
        if chave not in cache:
            import io
            from PIL import Image
            img = Image.open(mat["arquivo"]).convert("RGB")
            lado = min(img.size)          # o cubo exige imagem quadrada
            x0, y0 = (img.width - lado) // 2, (img.height - lado) // 2
            img = img.crop((x0, y0, x0 + lado, y0 + lado))
            img.thumbnail((512, 512), Image.LANCZOS)
            saida = io.BytesIO()
            img.save(saida, "PNG")
            cache[chave] = saida.getvalue()
        return cache[chave]

    def _ativos_go2(self):
        if not hasattr(self, "_go2_cache"):
            cache = {}
            with open(os.path.join(self.pasta, "go2_estudio.xml"), "rb") as fp:
                cache["go2_estudio.xml"] = fp.read()
            pasta = os.path.join(self.pasta, "assets")
            for nome in os.listdir(pasta):
                with open(os.path.join(pasta, nome), "rb") as fp:
                    cache["assets/" + nome] = fp.read()
            self._go2_cache = cache
        return self._go2_cache

    def _mapear(self):
        m = self.m
        for gid in range(m.ngeom):
            if m.geom_group[gid] != 2:
                continue
            corpo = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, m.geom_bodyid[gid]) or ""
            if corpo.endswith("_thigh") or corpo.endswith("_calf"):
                m.geom_matid[gid] = -1
                m.geom_rgba[gid] = VERMELHO
        base = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "base")
        self.geoms_robo = {g for g in range(m.ngeom) if m.body_rootid[m.geom_bodyid[g]] == base}
        self.geoms_obj = {}      # geom id -> objeto id
        self.geoms_por_obj = {}  # objeto id -> [geom ids]
        for o in self.cen["objetos"]:
            ids = []
            while True:
                g = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "obj_%s_%d" % (o["id"], len(ids)))
                if g < 0:
                    break
                ids.append(g)
                self.geoms_obj[g] = o["id"]
            self.geoms_por_obj[o["id"]] = ids
        self.geoms_zona = {}
        for z in self.cen["zonas"]:
            g = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "zona_" + z["id"])
            self.geoms_zona[g] = z["id"]
        self.mat_ids = {mid: mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_MATERIAL, "mt_" + mid)
                        for mid in self.materiais}
        self.mat_ids_cubo = {mid: mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_MATERIAL, "mc_" + mid)
                             for mid in self.materiais}

    def _partida(self):
        for z in self.cen["zonas"]:
            if z["tipo"] == "partida":
                return z["pos"][0], z["pos"][1], math.radians(z["giro"])
        return 0.0, 0.0, 0.0

    def _posicionar_robo(self):
        m, d = self.m, self.d
        self._limpar_fila("reiniciado")
        self.atual = None
        self.postura = None
        self.tempo = 0.0
        self.placar = Placar(self.cen)
        if self.cen["base"] == "bancada":
            mujoco.mj_resetData(m, d)
            d.qpos[0:3] = [0.0, 0.0, C.Z_BANCADA]
            d.qpos[3:7] = [1.0, 0.0, 0.0, 0.0]
            d.qpos[7:19] = [0.0, 0.9, -1.5] * 4
            mujoco.mj_forward(m, d)
            return
        x, y, psi = self._partida()
        self.motor.reiniciar(x, y, psi)
        if self.modo == "testar":
            d.qpos[2] += ALTURA_LARGADA
            mujoco.mj_forward(m, d)
            inicio = INICIOS[self.cen["comeca"]]
            if inicio:
                self.fila.append(A.criar(inicio[0], inicio[1]))

    # ---------- acoes ----------

    def yaw(self):
        return self._yaw()

    def enfileirar(self, aid, params):
        if not self.pronto:
            raise RuntimeError("o MuJoCo ainda nao esta pronto")
        with self.trava:
            if self.modo != "testar" or self.cen["base"] != "chao":
                raise ValueError("acoes so' rodam no modo testar, no chao livre")
            if len(self.fila) >= MAX_FILA:
                raise ValueError("a fila esta cheia (%d acoes)" % MAX_FILA)
            acao = A.criar(aid, params, self.cen["acoes"])
            self.fila.append(acao)
            return acao

    def parar_acoes(self):
        with self.trava:
            if self.atual is not None:
                self.atual.falhar("interrompida")
                self._encerrar_atual()
            self._limpar_fila("interrompida")

    def _limpar_fila(self, motivo):
        """Esvazia a fila marcando cada acao, para quem espera por ela saber."""
        for a in self.fila:
            a.falhar(motivo)
        self.fila = []

    def _encerrar_atual(self):
        a = self.atual
        self.ultimas.append(dict(a.estado(), t=round(self.tempo, 1),
                                 x=round(float(self.d.qpos[0]), 2), y=round(float(self.d.qpos[1]), 2),
                                 rumo=round(math.degrees(self._yaw()))))
        del self.ultimas[:-MAX_ULTIMAS]
        if a.fim == "pronto":
            self.postura = a.postura_final
        elif a.detalhe == "interrompida" and isinstance(a, A.Postura):
            self.postura = self.d.qpos[7:19].copy()   # fica onde parou
        else:
            self.postura = None
            self._limpar_fila("cancelada")   # uma falha derruba o resto da fila
        self.atual = None

    def _tique_acoes(self):
        """Um tique da fisica no modo testar: decide o que o robo faz e avanca."""
        if self.atual is None and self.fila and not self.placar.fim:
            self.atual = self.fila.pop(0)
            self.atual.iniciar(self)
        if self.atual is not None:
            cmd = self.atual.passo(self, DT_FISICA)
        elif self.postura is not None:
            cmd = ("pose", self.postura)
        else:
            cmd = ("marcha", 0.0, 0.0)

        caiu = False
        if cmd[0] == "marcha":
            vel = (cmd[1], 0.0, cmd[2]) if len(cmd) == 3 else (cmd[1], cmd[2], cmd[3])
            caiu = self.motor.passo(vel, DT_FISICA)
            if caiu:
                self.quedas += 1
                if self.atual is not None:
                    self.atual.falhar("caiu")
        else:
            if self.motor.manter_pose(cmd[1], DT_FISICA):
                caiu = True
                self.quedas += 1
                self.motor.reiniciar(float(self.d.qpos[0]), float(self.d.qpos[1]), self._yaw())
                self.postura = None
                if self.atual is not None:
                    self.atual.falhar("tombou")
        if self.atual is not None and self.atual.fim:
            self._encerrar_atual()
        return caiu

    def aplicar(self, cen):
        """Recebe o cenario editado. Ajusta ao vivo se a estrutura e' a mesma;
        senao recompila. Devolve True quando recompilou."""
        if not self.pronto:
            raise RuntimeError("o MuJoCo ainda nao esta pronto")
        precisa = (C.assinatura(cen) != self.assinatura
                   or set(M.por_id()) != set(self.materiais))
        if precisa:
            self.reconstruir(cen)
            return True
        with self.trava:
            self._ajustar_vivo(cen)
        return False

    @staticmethod
    def _rbound(tipo, s):
        if tipo == mujoco.mjtGeom.mjGEOM_BOX:
            return math.sqrt(s[0] ** 2 + s[1] ** 2 + s[2] ** 2)
        if tipo == mujoco.mjtGeom.mjGEOM_CYLINDER:
            return math.hypot(s[0], s[1])
        return s[0]

    def _ajustar_vivo(self, cen):
        m, d = self.m, self.d
        chao = self.materiais[cen["chao"]["material"]]
        piso = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "floor")
        m.geom_matid[piso] = self.mat_ids[chao["id"]]
        m.geom_friction[piso, 0] = chao["atrito"]
        m.geom_solref[piso, 1] = C._amort(chao["elasticidade"])
        for o in cen["objetos"]:
            ids = self.geoms_por_obj.get(o["id"], [])
            if o["tipo"] == "relevo":
                if ids:
                    m.geom_pos[ids[0]] = o["pos"]
                    m.geom_quat[ids[0]] = C._quat_yaw(o["giro"])
            elif o["fixo"]:
                for g, (_, p, q, s) in zip(ids, C.geoms_do_objeto(o)):
                    m.geom_pos[g] = C._soma(o["pos"], p)
                    m.geom_quat[g] = q
                    m.geom_size[g] = s
                    m.geom_rbound[g] = self._rbound(m.geom_type[g], s)
            else:
                b = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "obj_" + o["id"])
                m.body_pos[b] = o["pos"]
                if self.modo == "editar":
                    j = m.body_jntadr[b]
                    qa, va = m.jnt_qposadr[j], m.jnt_dofadr[j]
                    d.qpos[qa:qa + 3] = o["pos"]
                    d.qpos[qa + 3:qa + 7] = [1, 0, 0, 0]
                    d.qvel[va:va + 6] = 0
                for g, (_, p, q, s) in zip(ids, C.geoms_do_objeto(o)):
                    m.geom_pos[g] = p
                    m.geom_quat[g] = q
            mat = self.materiais[o["material"]]
            ids_mat = self.mat_ids if o["tipo"] == "relevo" else self.mat_ids_cubo
            for g in ids:
                m.geom_matid[g] = ids_mat[mat["id"]]
                m.geom_friction[g, 0] = o["atrito"]
                m.geom_solref[g, 1] = C._amort(o["elasticidade"])
        for z in cen["zonas"]:
            g = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "zona_" + z["id"])
            if g >= 0:
                m.geom_pos[g] = [z["pos"][0], z["pos"][1], 0.006]
                m.geom_quat[g] = C._quat_yaw(z["giro"])
                m.geom_size[g] = [z["tam"][0] / 2, z["tam"][1] / 2, 0.006]
                m.geom_rbound[g] = self._rbound(m.geom_type[g], m.geom_size[g])
        partida_antes = self._partida()
        self.cen = cen
        if self.modo == "testar":
            # regras e zonas novas valem ja'; pontos e eventos continuam
            self.placar.regras = cen["regras"]
            self.placar.zonas = {z["id"]: z for z in cen["zonas"]}
        else:
            self.placar = Placar(cen)
            if self._partida() != partida_antes:
                self._posicionar_robo()
        mujoco.mj_forward(m, d)

    # ---------- comandos (chamados pelas threads do servidor) ----------

    def comandar(self, pedido):
        if not self.pronto:
            raise RuntimeError("o MuJoCo ainda nao esta pronto")
        with self.trava:
            if "modo" in pedido:
                modo = pedido["modo"]
                if modo not in MODOS:
                    raise ValueError("modo invalido: %r" % (modo,))
                self.modo = modo
                self._posicionar_robo()
            if pedido.get("reiniciar"):
                self._posicionar_robo()
            if "inicio" in pedido:
                ini = pedido["inicio"]
                if ini not in INICIOS:
                    raise ValueError("inicio invalido: %r" % (ini,))
                if self.modo == "testar" and self.cen["base"] == "chao" and INICIOS[ini]:
                    self.fila.append(A.criar(*INICIOS[ini]))
            if "camera" in pedido:
                c = pedido["camera"]
                if c == "proxima":
                    self.icam = (self.icam + 1) % len(CAMERAS)
                elif isinstance(c, int) and not isinstance(c, bool):
                    self.icam = c % len(CAMERAS)
                else:
                    raise ValueError('camera precisa ser "proxima" ou um numero')
                self.cam_daz = self.cam_del = 0.0
                self.cam_zoom = 1.0
            if pedido.get("recentrar"):
                self.cam_daz = self.cam_del = 0.0
                self.cam_zoom = 1.0
            if "orbita" in pedido:
                o = pedido["orbita"]
                if not (isinstance(o, list) and len(o) == 2
                        and all(isinstance(v, (int, float)) and math.isfinite(v) for v in o)):
                    raise ValueError("orbita precisa ser [graus de azimute, graus de elevacao]")
                self.cam_daz = (self.cam_daz + o[0]) % 360.0
                self.cam_del = max(-80.0, min(80.0, self.cam_del + o[1]))
            if "zoom" in pedido:
                z = pedido["zoom"]
                if not (isinstance(z, (int, float)) and math.isfinite(z) and z > 0):
                    raise ValueError("zoom precisa ser um numero positivo")
                self.cam_zoom = max(0.25, min(4.0, self.cam_zoom * z))
        return self.estado()

    def estado(self):
        return {
            "pronto": self.pronto,
            "situacao": self.situacao,
            "erro": self.erro,
            "modo": self.modo,
            "base": self.cen["base"] if self.cen else None,
            "cenario": {"id": self.cen["id"], "nome": self.cen["nome"]} if self.cen else None,
            "geracao": self.geracao,
            "camera": CAMERAS[self.icam]["nome"],
            "acao": self.atual.estado() if self.atual else None,
            "fila": [a.nome for a in self.fila],
            "ultimas": self.ultimas[-6:],
            "postura": "sentado" if self.postura is A.POSE_SENTADO else "deitado" if self.postura is A.POSE_DEITADO
                       else "parcial" if self.postura is not None else "de pe",
            "tempo": round(self.tempo, 1),
            "velocidade": self.velocidade,
            "quedas": self.quedas,
            "placar": self.placar.estado() if self.placar else None,
            "fps": round(self.fps, 1),
            "visores": self.visores,
        }

    # ---------- apontar (clique sobre o video) ----------

    def apontar(self, relx, rely):
        """O que esta' sob o ponto (0..1 da esquerda, 0..1 de cima) do video."""
        if self.scn is None:
            raise RuntimeError("ainda nao ha imagem para apontar")
        # logo depois de recompilar, a thread da imagem ainda esta' refazendo
        # a cena: espera um pouco em vez de recusar o clique
        limite = time.monotonic() + 2.0
        while self.scn_geracao != self.geracao and time.monotonic() < limite:
            time.sleep(0.03)
        with self.trava:
            if self.scn_geracao != self.geracao:
                raise RuntimeError("a cena esta sendo remontada; tente de novo")
            larg, alt = self.tamanho
            ponto = np.zeros(3)
            geomid = np.array([-1], np.int32)
            flexid = np.array([-1], np.int32)
            skinid = np.array([-1], np.int32)
            mujoco.mjv_select(self.m, self.d, self.vopt, larg / alt, relx, 1.0 - rely,
                              self.scn, ponto, geomid, flexid, skinid)
            g = int(geomid[0])
            return {"objeto": self.geoms_obj.get(g), "zona": self.geoms_zona.get(g),
                    "robo": g in self.geoms_robo,
                    "ponto": [round(float(v), 4) for v in ponto] if g >= 0 else None,
                    "chao": self.ponto_no_chao(relx, rely)}

    def ponto_no_chao(self, relx, rely, z=0.0):
        """Onde o raio do pixel cruza o plano z (para arrastar sem esbarrar
        nos objetos). Usa a camera que a thread da imagem calculou."""
        if self.scn is None:
            return None
        cam0, cam1 = self.scn.camera[0], self.scn.camera[1]
        pos = (np.array(cam0.pos) + np.array(cam1.pos)) / 2
        frente = np.array(cam0.forward)
        cima = np.array(cam0.up)
        direita = np.cross(frente, cima)
        larg, alt = self.tamanho
        h = (cam0.frustum_top - cam0.frustum_bottom) / 2
        cy = (cam0.frustum_top + cam0.frustum_bottom) / 2
        w = h * larg / alt
        raio = (frente * cam0.frustum_near + cima * (cy + (1 - 2 * rely) * h)
                + direita * (cam0.frustum_center + (2 * relx - 1) * w))
        if abs(raio[2]) < 1e-9:
            return None
        t = (z - pos[2]) / raio[2]
        if t <= 0:
            return None
        p = pos + raio * t
        return [round(float(p[0]), 4), round(float(p[1]), 4), z]

    # ---------- quem assiste ----------

    def entrar_visor(self, larg, alt):
        with self.trava:
            self.visores += 1
            self.tamanho = self._limitar(larg, alt)
        self.ha_visor.set()

    def sair_visor(self):
        with self.trava:
            self.visores = max(0, self.visores - 1)
            if self.visores == 0:
                self.ha_visor.clear()

    @staticmethod
    def _limitar(larg, alt):
        larg, alt = max(160, larg), max(120, alt)
        esc = min(1.0, LARG_MAX / larg, ALT_MAX / alt)
        return (max(160, int(larg * esc) // 8 * 8), max(120, int(alt * esc) // 8 * 8))

    # ---------- laco da fisica ----------

    def _laco_fisica(self):
        prox = time.monotonic()
        while not self.parar.is_set():
            try:
                with self.trava:
                    # acima de 1x, varios tiques por periodo real: o sleep do
                    # Windows nao e' fino o bastante para encurtar o periodo
                    for _ in range(max(1, min(VELOCIDADE_MAX, int(self.velocidade)))):
                        if self.modo == "testar" and self.cen["base"] == "chao":
                            if self.placar.fim and (self.atual or self.fila):
                                self.parar_acoes()      # acabou o teste: nada mais roda
                            caiu = self._tique_acoes()
                            self.placar.avaliar(float(self.d.qpos[0]), float(self.d.qpos[1]),
                                                self._tocados(), caiu, DT_FISICA)
                            self.tempo += DT_FISICA
                            self.relogio += DT_FISICA
            except Exception:
                traceback.print_exc()
                self._falhar("a fisica parou com erro; veja o terminal")
                return
            prox += DT_FISICA
            atraso = prox - time.monotonic()
            if atraso > 0:
                time.sleep(atraso)
            elif atraso < -0.25:
                prox = time.monotonic()

    def _tocados(self):
        """Objetos em contato com o robo neste passo: id -> nome."""
        d = self.d
        saida = {}
        if not self.geoms_obj:
            return saida
        nomes = {o["id"]: o["nome"] for o in self.cen["objetos"]}
        for i in range(d.ncon):
            g1, g2 = d.contact[i].geom1, d.contact[i].geom2
            for a, b in ((g1, g2), (g2, g1)):
                if a in self.geoms_robo and b in self.geoms_obj:
                    oid = self.geoms_obj[b]
                    saida[oid] = nomes.get(oid, oid)
        return saida

    # ---------- laco da imagem ----------

    def _camera(self, cam):
        c = CAMERAS[self.icam]
        x, y, z = (float(v) for v in self.d.qpos[0:3])
        psi = math.degrees(self._yaw()) if c["segue"] else 0.0
        cam.type = mujoco.mjtCamera.mjCAMERA_FREE
        cam.lookat[:] = [x, y, max(0.2, z * 0.75)]
        cam.azimuth = psi + c["az"] + self.cam_daz
        cam.elevation = max(-89.0, min(10.0, c["el"] + self.cam_del))
        # O MuJoCo fixa o angulo vertical; num quadro estreito o robo (mais
        # largo que alto) estoura pelos lados. Afasta ate caber como em 4:3.
        larg, alt = self.tamanho
        estreito = max(1.0, 1.35 / (larg / alt))
        cam.distance = c["dist"] * self.cam_zoom * estreito

    def _yaw(self):
        w, x, y, z = self.d.qpos[3:7]
        return math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))

    def _laco_imagem(self):
        try:
            # O contexto de OpenGL pertence a esta thread: criar e usar aqui.
            ctx = mujoco.GLContext(LARG_MAX, ALT_MAX)
            ctx.make_current()
            opt = mujoco.MjvOption()
            opt.geomgroup[4] = 1      # zonas
            opt.geomgroup[5] = 0      # suporte escondido no chao livre
            pert = mujoco.MjvPerturb()
            cam = mujoco.MjvCamera()
            con = scn = None
            geracao_vista = -1
        except Exception as e:
            traceback.print_exc()
            return self._falhar("nao consegui abrir o OpenGL para desenhar: %s" % e)

        self.pronto = True
        self.situacao = "pronto"
        rgb, medida = None, (0, 0)
        janela, quadros = time.monotonic(), 0

        while not self.parar.is_set():
            if not self.ha_visor.wait(0.5):
                self.fps = 0.0
                continue
            t0 = time.monotonic()
            try:
                with self.trava:
                    if geracao_vista != self.geracao:
                        # cena nova: o contexto guarda malhas e texturas do modelo
                        if con is not None:
                            con.free()
                        con = mujoco.MjrContext(self.m, mujoco.mjtFontScale.mjFONTSCALE_100)
                        mujoco.mjr_setBuffer(mujoco.mjtFramebuffer.mjFB_OFFSCREEN, con)
                        scn = mujoco.MjvScene(self.m, maxgeom=4000)
                        self.scn, self.vopt = scn, opt
                        self.scn_geracao = geracao_vista = self.geracao
                    larg, alt = self.tamanho
                    self._camera(cam)
                    mujoco.mjv_updateScene(self.m, self.d, opt, pert, cam,
                                           mujoco.mjtCatBit.mjCAT_ALL, scn)
                scn.flags[mujoco.mjtRndFlag.mjRND_SHADOW] = 0
                scn.flags[mujoco.mjtRndFlag.mjRND_REFLECTION] = 0
                if (larg, alt) != medida:
                    rgb, medida = np.empty((alt, larg, 3), np.uint8), (larg, alt)
                vista = mujoco.MjrRect(0, 0, larg, alt)
                mujoco.mjr_render(vista, scn, con)
                mujoco.mjr_readPixels(rgb, None, vista, con)
                self.quadro.publicar(self.codificar(np.flipud(rgb)))
            except Exception:
                traceback.print_exc()
                return self._falhar("o desenho parou com erro; veja o terminal")

            quadros += 1
            agora = time.monotonic()
            if agora - janela >= 1.0:
                self.fps = quadros / (agora - janela)
                janela, quadros = agora, 0
            sobra = 1.0 / FPS_ALVO - (agora - t0)
            if sobra > 0:
                time.sleep(sobra)
