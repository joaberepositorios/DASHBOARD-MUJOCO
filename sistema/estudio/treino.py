"""Treino por tentativa ("jeito 2": sem rede neural).

Um treino e': um cenario com regras (o que vale ponto), um programa da
secao Programacao (o que o robo tenta fazer) e variaveis a experimentar --
as que o programa declara com treino.parametro(...) e/ou ajustes do
controlador de marcha. O estudio repete tentativas variando os valores,
pontua cada uma pelo placar do cenario e guarda tudo em treinos/<id>.json
conforme acontece; a melhor tentativa e' o "campeao".

A busca e' simples e sem dependencias: a primeira tentativa usa os valores
padrao, um terco explora ao acaso dentro dos limites, o resto refina em
volta do melhor com passos cada vez menores.
"""

import json
import math
import os
import random
import re
import threading
import time
import traceback

import acoes as A
import cenario as C
import controle
import materiais as M
import programa as P

AQUI = os.path.dirname(os.path.abspath(__file__))
import dados
PASTA = dados.pasta("treinos")
VELOCIDADES = (1, 2, 4, 10, 20)
PASSO = 0.05                   # s reais entre conferencias de uma tentativa
MAX_TENTATIVAS = 500

# Ajustes do controlador que o treino pode variar: id, nome, minimo, maximo, unidade.
VARIAVEIS = [
    ("marcha.T", "Período do passo", 0.40, 1.00, "s"),
    ("marcha.duty", "Fração do passo em apoio", 0.60, 0.95, ""),
    ("marcha.balanco", "Altura do balanço do pé", 0.04, 0.14, "m"),
    ("marcha.altura", "Altura do corpo", 0.20, 0.32, "m"),
    ("marcha.abertura", "Abertura lateral das pernas", 0.00, 0.12, "m"),
    ("ctrl.kp", "Rigidez das juntas (kp)", 40.0, 160.0, ""),
    ("ctrl.kd", "Amortecimento das juntas (kd)", 0.5, 5.0, ""),
    ("ctrl.kr", "Ganho de velocidade (kr)", 0.10, 0.60, ""),
    ("ctrl.ki", "Integral de velocidade (ki)", 0.0, 0.60, ""),
    ("ctrl.krp", "Correção de inclinação (krp)", 0.20, 1.20, ""),
    ("acoes.rumo_ganho", "Ganho de rumo ao andar", 0.5, 2.5, ""),
]
POR_ID = {v[0]: v for v in VARIAVEIS}

def padroes():
    saida = {}
    for vid, *_ in VARIAVEIS:
        grupo, chave = vid.split(".", 1)
        if grupo == "marcha":
            saida[vid] = controle.PARAM_MARCHA[chave]
        elif grupo == "ctrl":
            saida[vid] = controle.PARAM_CTRL[chave]
        else:
            saida[vid] = A.RUMO_GANHO if chave == "rumo_ganho" else None
    return saida

def ajustes_atuais(mundo):
    saida = {}
    for vid, *_ in VARIAVEIS:
        grupo, chave = vid.split(".", 1)
        if grupo == "marcha":
            saida[vid] = mundo.motor.prm[chave]
        elif grupo == "ctrl":
            saida[vid] = mundo.motor.p[chave]
        else:
            saida[vid] = A.RUMO_GANHO
    return saida

def aplicar_ajustes(mundo, valores):
    for vid, v in valores.items():
        if vid not in POR_ID:
            raise ValueError("ajuste desconhecido: %r (os nomes: %s)" % (vid, ", ".join(POR_ID)))
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError("%s precisa ser um numero" % vid)
        grupo, chave = vid.split(".", 1)
        with mundo.trava:
            if grupo == "marcha":
                mundo.motor.prm[chave] = float(v)
            elif grupo == "ctrl":
                mundo.motor.p[chave] = float(v)
            elif chave == "rumo_ganho":
                A.RUMO_GANHO = float(v)

def variaveis_publicas(mundo=None):
    pad = ajustes_atuais(mundo) if mundo is not None and mundo.pronto else padroes()
    return [{"id": vid, "nome": nome, "min": mn, "max": mx, "unidade": un, "padrao": pad[vid]}
            for vid, nome, mn, mx, un in VARIAVEIS]

# ---------- busca ----------

class Busca:
    def __init__(self, variaveis, total, semente):
        self.vars = variaveis            # [{id, padrao, min, max}]
        self.total = total
        self.rng = random.Random(semente)
        self.explora = max(1, total // 3)

    def proxima(self, i, melhor):
        if i == 0 or not self.vars:
            return {v["id"]: v["padrao"] for v in self.vars}
        if i <= self.explora or melhor is None:
            return {v["id"]: self._arred(self.rng.uniform(v["min"], v["max"]), v) for v in self.vars}
        frac = (i - self.explora) / max(1, self.total - self.explora)
        sigma = 0.25 * (1.0 - frac) + 0.04
        saida = {}
        for v in self.vars:
            largura = v["max"] - v["min"]
            x = melhor.get(v["id"], v["padrao"]) + self.rng.gauss(0.0, sigma * largura)
            saida[v["id"]] = self._arred(min(v["max"], max(v["min"], x)), v)
        return saida

    @staticmethod
    def _arred(x, v):
        largura = abs(v["max"] - v["min"]) or 1.0
        casas = max(0, 3 - int(math.floor(math.log10(largura)))) if largura > 0 else 3
        return round(x, casas)

def melhor_que(a, b):
    """Ordem das tentativas: mais pontos; depois menos quedas; depois menos tempo."""
    if b is None:
        return True
    return (a["pontos"], -a["quedas"], -a["tempo"]) > (b["pontos"], -b["quedas"], -b["tempo"])

# ---------- o treino ----------

class Treino:
    def __init__(self, mundo, programa):
        self.mundo = mundo
        self.programa = programa
        self.trava = threading.Lock()
        self.parar_pedido = threading.Event()
        self.thread = None
        self.doc = None            # o treino aberto (definicao + resultados)
        self.fase = None           # None, "treino", "campeao"
        self.tentativa = 0
        self.valores_atuais = {}
        self.erro = ""

    @property
    def rodando(self):
        return self.thread is not None and self.thread.is_alive()

    # --- definicao ---

    def _definir(self, p):
        mundo = self.mundo
        if not mundo.pronto:
            raise RuntimeError("o MuJoCo ainda nao esta pronto")
        if mundo.cen["base"] != "chao":
            raise ValueError("o treino precisa de uma simulacao no chao livre")
        nome = str(p.get("nome", "")).strip()[:60] or "Treino"
        try:
            total = int(p.get("tentativas", 20))
            tempo_max = float(p.get("tempo_max", 60))
            velocidade = int(p.get("velocidade", 10))
            semente = int(p.get("semente", 1))
        except (TypeError, ValueError):
            raise ValueError("tentativas, tempo e velocidade precisam ser numeros")
        if not 1 <= total <= MAX_TENTATIVAS:
            raise ValueError("tentativas: de 1 a %d" % MAX_TENTATIVAS)
        if not 5 <= tempo_max <= 600:
            raise ValueError("tempo maximo por tentativa: de 5 a 600 s")
        if velocidade not in VELOCIDADES:
            raise ValueError("velocidade: uma de %s" % (VELOCIDADES,))

        programa = p.get("programa") or None
        codigo = None
        variaveis = []
        if programa:
            codigo = P.carregar(programa)["codigo"]      # FileNotFoundError -> 404
            for pp in P.parametros_do_programa(codigo):
                mn, mx = pp["min"], pp["max"]
                if mn is None or mx is None:
                    mn, mx = (0.0, 1.0) if pp["padrao"] == 0 else sorted((pp["padrao"] * 0.5, pp["padrao"] * 1.5))
                variaveis.append({"id": "prog." + pp["nome"], "nome": pp["nome"], "origem": "programa",
                                  "padrao": pp["padrao"], "min": float(mn), "max": float(mx), "unidade": ""})
        pad = padroes()
        for v in p.get("variaveis") or []:
            vid = str(v.get("id", ""))
            if vid not in POR_ID:
                raise ValueError("variavel desconhecida: %r" % vid)
            _, nomev, mn0, mx0, un = POR_ID[vid]
            try:
                mn, mx = float(v.get("min", mn0)), float(v.get("max", mx0))
            except (TypeError, ValueError):
                raise ValueError("limites de %s precisam ser numeros" % vid)
            if not (math.isfinite(mn) and math.isfinite(mx)) or mn >= mx:
                raise ValueError("limites de %s: minimo < maximo" % vid)
            variaveis.append({"id": vid, "nome": nomev, "origem": "controlador",
                              "padrao": min(mx, max(mn, pad[vid])), "min": mn, "max": mx, "unidade": un})
        if not variaveis:
            raise ValueError("escolha ao menos uma variavel (treino.parametro no programa ou um ajuste do controlador)")

        cen = json.loads(json.dumps(mundo.cen))
        doc = {"id": id_livre(nome), "nome": nome, "criado": time.time(),
               "cenario": cen, "programa": programa, "codigo": codigo,
               "tentativas": total, "tempo_max": tempo_max, "velocidade": velocidade, "semente": semente,
               "variaveis": variaveis, "resultados": [], "melhor": None, "estado": "rodando"}
        return doc

    # --- rodar ---

    def iniciar(self, p):
        with self.trava:
            if self.rodando:
                raise ValueError("ja ha um treino rodando; pare-o antes")
            if self.programa.rodando:
                raise ValueError("ha um programa rodando na secao Programacao; pare-o antes")
            doc = self._definir(p)
            gravar(doc)
            self.doc = doc
            self.erro = ""
            self.parar_pedido.clear()
            self.fase = "treino"
            self.programa.reservado = self
            self.thread = threading.Thread(target=self._rodar, name="treino", daemon=True)
            self.thread.start()
        return self.estado()

    def parar(self):
        if self.rodando:
            self.parar_pedido.set()
            self.programa.parar()
        return self.estado()

    def _rodar(self):
        doc = self.doc
        mundo = self.mundo
        antes = ajustes_atuais(mundo)
        busca = Busca(doc["variaveis"], doc["tentativas"], doc["semente"])
        try:
            mundo.velocidade = doc["velocidade"]
            melhor_vals = doc["resultados"][doc["melhor"]]["valores"] if doc["melhor"] is not None else None
            for i in range(len(doc["resultados"]), doc["tentativas"]):
                if self.parar_pedido.is_set():
                    break
                self.tentativa = i + 1
                valores = busca.proxima(i, melhor_vals)
                self.valores_atuais = valores
                res = self._tentativa(doc, valores)
                if res is None:
                    break
                res["n"] = i + 1
                doc["resultados"].append(res)
                if melhor_que(res, doc["resultados"][doc["melhor"]] if doc["melhor"] is not None else None):
                    doc["melhor"] = i
                    melhor_vals = valores
                gravar(doc)
            doc["estado"] = "concluido" if len(doc["resultados"]) >= doc["tentativas"] else "parado"
        except Exception as e:
            traceback.print_exc()
            self.erro = "%s: %s" % (type(e).__name__, e)
            doc["estado"] = "erro"
        finally:
            mundo.velocidade = 1
            self.programa.reservado = None
            self.fase = None
            try:
                aplicar_ajustes(mundo, antes)
                gravar(doc)
            except Exception as e:
                traceback.print_exc()
                self.erro = self.erro or "%s: %s" % (type(e).__name__, e)

    def _tentativa(self, doc, valores, gravar_saida=True):
        """Uma tentativa com `valores`. Devolve o resultado, ou None se o
        treino foi parado no meio."""
        mundo, prog = self.mundo, self.programa
        aplicar_ajustes(mundo, {k: v for k, v in valores.items() if not k.startswith("prog.")})
        vals_prog = {k[5:]: v for k, v in valores.items() if k.startswith("prog.")}
        mundo.comandar({"modo": "testar"})        # reposiciona e zera o placar
        if doc["codigo"]:
            prog.iniciar(doc["codigo"], doc["nome"], vals_prog, dono=self)
        motivo = ""
        while True:
            time.sleep(PASSO)
            if self.parar_pedido.is_set():
                prog.parar()
                return None
            with mundo.trava:
                fim = mundo.placar.fim
                tempo = mundo.tempo
                fila_vazia = mundo.atual is None and not mundo.fila
            if fim:
                motivo = "teste: " + fim
                break
            if tempo >= doc["tempo_max"]:
                motivo = "tempo esgotado"
                break
            if doc["codigo"] and not prog.rodando and fila_vazia:
                motivo = "programa terminou"
                break
        if prog.rodando:
            prog.parar()
            while prog.rodando:
                time.sleep(PASSO)
        with mundo.trava:
            pl = mundo.placar.estado()
            x, y = float(mundo.d.qpos[0]), float(mundo.d.qpos[1])
            quedas = mundo.quedas
        return {"valores": valores, "pontos": pl["pontos"], "fim": pl["fim"], "tempo": round(tempo, 1),
                "quedas": quedas, "motivo": motivo, "programa_fim": prog.fim if doc["codigo"] else None,
                "pos": [round(x, 2), round(y, 2)], "eventos": pl["eventos"][-4:]}

    # --- campeao ---

    def campeao(self, tid):
        """Roda a melhor tentativa de novo, a 1x, sem gravar."""
        doc = carregar(tid)
        if doc["melhor"] is None:
            raise ValueError("este treino ainda nao tem campeao")
        with self.trava:
            if self.rodando:
                raise ValueError("ja ha um treino rodando; pare-o antes")
            if self.programa.rodando:
                raise ValueError("ha um programa rodando; pare-o antes")
            cen = C.validar(doc["cenario"], M.por_id())
            if cen["id"] != (self.mundo.cen or {}).get("id") or C.assinatura(cen) != self.mundo.assinatura:
                self.mundo.aplicar(cen)
            self.doc = doc
            self.erro = ""
            self.parar_pedido.clear()
            self.fase = "campeao"
            self.programa.reservado = self
            self.thread = threading.Thread(target=self._rodar_campeao, name="campeao", daemon=True)
            self.thread.start()
        return self.estado()

    def _rodar_campeao(self):
        doc = self.doc
        antes = ajustes_atuais(self.mundo)
        try:
            self.tentativa = doc["melhor"] + 1
            valores = doc["resultados"][doc["melhor"]]["valores"]
            self.valores_atuais = valores
            self.mundo.velocidade = 1
            self._tentativa(doc, valores)
        except Exception as e:
            traceback.print_exc()
            self.erro = "%s: %s" % (type(e).__name__, e)
        finally:
            self.programa.reservado = None
            self.fase = None
            aplicar_ajustes(self.mundo, antes)

    def usar_campeao(self, tid):
        """Aplica ao controlador os ajustes da melhor tentativa."""
        doc = carregar(tid)
        if doc["melhor"] is None:
            raise ValueError("este treino ainda nao tem campeao")
        vals = {k: v for k, v in doc["resultados"][doc["melhor"]]["valores"].items() if not k.startswith("prog.")}
        if not vals:
            raise ValueError("o campeao nao tem ajustes do controlador; so' valores do programa")
        aplicar_ajustes(self.mundo, vals)
        return vals

    def esquecer(self, tid):
        """Depois de apagar do disco: o estado nao deve mostrar o treino."""
        if self.doc and self.doc["id"] == tid and not self.rodando:
            self.doc = None

    # --- estado ---

    def estado(self):
        doc = self.doc
        return {"rodando": self.rodando, "fase": self.fase, "erro": self.erro,
                "tentativa": self.tentativa, "valores_atuais": self.valores_atuais,
                "treino": publico(doc) if doc else None}

def publico(doc):
    """O treino sem o cenario e o codigo inteiros (a pagina pede a parte)."""
    saida = {k: v for k, v in doc.items() if k not in ("cenario", "codigo")}
    saida["cenario"] = {"id": doc["cenario"]["id"], "nome": doc["cenario"]["nome"]}
    return saida

# ---------- campeao em programa ----------

def programa_campeao(tid):
    """Grava um .py com os valores da melhor tentativa no lugar dos padroes
    de treino.parametro e, se houver ajustes do controlador, uma linha
    robo.ajustar(...) no comeco. Devolve o nome do programa gravado."""
    doc = carregar(tid)
    if doc["melhor"] is None:
        raise ValueError("este treino ainda nao tem campeao")
    if not doc["codigo"]:
        raise ValueError("este treino nao usa programa; use 'Usar ajustes do campeao'")
    valores = doc["resultados"][doc["melhor"]]["valores"]
    linhas = doc["codigo"].split("\n")
    trocas = []
    for pp in P.parametros_do_programa(doc["codigo"]):
        v = valores.get("prog." + pp["nome"])
        if v is None:
            continue
        l1, c1, l2, c2 = pp["col_padrao"]
        if l1 == l2:
            trocas.append((l1, c1, c2, repr(v)))
    for l1, c1, c2, novo in sorted(trocas, key=lambda t: (t[0], t[1]), reverse=True):
        linha = linhas[l1 - 1]
        linhas[l1 - 1] = linha[:c1] + novo + linha[c2:]
    ctrl = {k.replace(".", "_", 1): v for k, v in valores.items() if not k.startswith("prog.")}
    cabeca = ["# campeao do treino %r (tentativa %d, %s pontos)"
              % (doc["nome"], doc["melhor"] + 1, doc["resultados"][doc["melhor"]]["pontos"])]
    if ctrl:
        cabeca.append("robo.ajustar(%s)" % ", ".join("%s=%r" % kv for kv in ctrl.items()))
    codigo = "\n".join(cabeca + [""] + linhas)
    nome = P.nome_limpo("%s campeao de %s" % (doc["programa"], doc["nome"]))
    return P.gravar(nome, codigo)

# ---------- disco ----------

def _caminho(tid):
    return os.path.join(PASTA, tid + ".json")

def id_livre(nome):
    base = C.slug(nome) if C.slug(nome) != "simulacao" else "treino"
    tid, n = base, 2
    while os.path.exists(_caminho(tid)):
        tid = "%s-%d" % (base, n)
        n += 1
    return tid

def gravar(doc):
    """Grava inteiro num .tmp e troca, para nunca deixar um JSON pela
    metade. O OneDrive segura o arquivo de destino por instantes enquanto
    sincroniza (PermissionError no replace): tenta de novo por ate' 2 s."""
    os.makedirs(PASTA, exist_ok=True)
    tmp = _caminho(doc["id"]) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fp:
        json.dump(doc, fp, ensure_ascii=False, indent=1)
    for i in range(20):
        try:
            os.replace(tmp, _caminho(doc["id"]))
            return
        except PermissionError:
            if i == 19:
                raise
            time.sleep(0.1)

def carregar(tid):
    if not re.fullmatch(r"[a-z0-9-]{1,48}", tid or ""):
        raise FileNotFoundError(tid)
    with open(_caminho(tid), encoding="utf-8") as fp:
        return json.load(fp)

def listar():
    os.makedirs(PASTA, exist_ok=True)
    saida = []
    for arq in os.listdir(PASTA):
        if not arq.endswith(".json"):
            continue
        try:
            with open(os.path.join(PASTA, arq), encoding="utf-8") as fp:
                doc = json.load(fp)
        except (OSError, ValueError):
            continue
        melhor = doc["resultados"][doc["melhor"]] if doc.get("melhor") is not None else None
        saida.append({"id": doc["id"], "nome": doc["nome"], "estado": doc.get("estado"),
                      "cenario": doc["cenario"]["nome"], "programa": doc.get("programa"),
                      "feitas": len(doc["resultados"]), "tentativas": doc["tentativas"],
                      "melhor_pontos": melhor["pontos"] if melhor else None,
                      "modificado": os.path.getmtime(os.path.join(PASTA, arq))})
    saida.sort(key=lambda t: -t["modificado"])
    return saida

def apagar(tid):
    if not re.fullmatch(r"[a-z0-9-]{1,48}", tid or ""):
        raise FileNotFoundError(tid)
    os.remove(_caminho(tid))
