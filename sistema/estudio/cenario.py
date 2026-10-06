"""O cenario: objetos, zonas e regras que o usuario monta, e a cena do MuJoCo
que sai disso.

Um cenario e' um dicionario (vai e volta como JSON):

  {"id", "nome", "base": "chao"|"bancada", "modelo": "go2",
   "comeca": "parado"|"frente"|"girando", "acoes": [...],
   "chao": {"material": id},
   "objetos": [{"id", "tipo", "nome", "pos": [x,y,z], "giro": graus,
                "tam": [...], "material", "fixo", "massa",
                "atrito", "elasticidade"}],
   "zonas":   [{"id", "tipo", "nome", "pos": [x,y], "tam": [cx,cy], "giro"}],
   "regras":  [{"id", "quando", "alvo", "valor", "pontos", "fim", "uma_vez"}]}

Medidas em metros, massas em kg, angulos em graus na interface (radianos so'
dentro do MuJoCo).
"""

import json
import math
import os
import re

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
import dados
PASTA_SIMULACOES = dados.pasta("simulacoes")

BASES = ("chao", "bancada")
COMECOS = ("parado", "frente", "girando")
ACOES = ("andar", "girar", "sentar", "deitar", "reconhecer")

Z_BANCADA = 0.55
LARG_MAX, ALT_MAX = 1280, 960

# tam = medidas inteiras (comprimento, largura, altura), nunca "meias".
TIPOS = {
    "caixa":    dict(nome="Caixa",    tam=[0.40, 0.40, 0.20], fixo=True),
    "rampa":    dict(nome="Rampa",    tam=[1.20, 0.80, 0.25], fixo=True),
    "cilindro": dict(nome="Cilindro", tam=[0.30, 0.30, 0.15], fixo=True),   # diametro, -, altura
    "esfera":   dict(nome="Esfera",   tam=[0.20, 0.20, 0.20], fixo=False),  # diametro
    "barra":    dict(nome="Barra",    tam=[0.06, 0.80, 0.12], fixo=True),   # diametro, comprimento, altura do chao
    "escada":   dict(nome="Escada",   tam=[0.90, 0.80, 0.30], fixo=True, degraus=3),
    "parede":   dict(nome="Parede",   tam=[1.50, 0.06, 0.50], fixo=True),
    "relevo":   dict(nome="Relevo",   tam=[2.00, 2.00, 0.08], fixo=True, rugosidade=0.5, semente=1),
}
TIPOS_ZONA = {
    "partida":    dict(nome="Partida",    cor=[0.30, 0.55, 0.95, 0.45]),
    "checkpoint": dict(nome="Checkpoint", cor=[0.95, 0.65, 0.15, 0.45]),
    "chegada":    dict(nome="Chegada",    cor=[0.20, 0.70, 0.35, 0.45]),
    "proibida":   dict(nome="Proibida",   cor=[0.86, 0.15, 0.15, 0.40]),
}
QUANDOS = ("entrar_zona", "sair_zona", "tocar_objeto", "cair", "tempo", "pontos")
FINS = (None, "sucesso", "falha")

MASSA_MIN, MASSA_MAX = 0.01, 200.0
LIMITE_POS = 25.0
MEDIDA_MIN, MEDIDA_MAX = 0.02, 10.0

class CenarioInvalido(ValueError):
    pass

# ---------- validacao ----------

def _num(v, nome, lo=-1e9, hi=1e9):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise CenarioInvalido("%s precisa ser um numero" % nome)
    return float(min(hi, max(lo, v)))

def _texto(v, nome, max_=60):
    if not isinstance(v, str):
        raise CenarioInvalido("%s precisa ser texto" % nome)
    return v.strip()[:max_]

def _id(v, nome):
    v = _texto(v, nome, 40)
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", v):
        raise CenarioInvalido("%s tem id invalido: %r" % (nome, v))
    return v

def _lista(v, nome, n):
    if not isinstance(v, list) or len(v) != n:
        raise CenarioInvalido("%s precisa ter %d numeros" % (nome, n))
    return v

def validar(cru, materiais):
    if not isinstance(cru, dict):
        raise CenarioInvalido("esperava um objeto")
    cen = {
        "id": _id(cru.get("id", "novo"), "id"),
        "nome": _texto(cru.get("nome", ""), "nome") or "Sem nome",
        "base": cru.get("base", "chao"),
        "modelo": "go2",
        "comeca": cru.get("comeca", "parado"),
        "acoes": [a for a in (cru.get("acoes") or []) if a in ACOES],
        "chao": {"material": cru.get("chao", {}).get("material", "concreto")},
        "objetos": [], "zonas": [], "regras": [],
    }
    if cen["base"] not in BASES:
        raise CenarioInvalido("base invalida")
    if cen["comeca"] not in COMECOS:
        raise CenarioInvalido("comeca invalido")
    if cen["chao"]["material"] not in materiais:
        cen["chao"]["material"] = "concreto"

    vistos = set()
    for i, o in enumerate(cru.get("objetos") or []):
        if not isinstance(o, dict):
            raise CenarioInvalido("objeto %d invalido" % i)
        tipo = o.get("tipo")
        if tipo not in TIPOS:
            raise CenarioInvalido("objeto %d: tipo desconhecido %r" % (i, tipo))
        padrao = TIPOS[tipo]
        oid = _id(o.get("id", "o%d" % i), "objeto %d" % i)
        if oid in vistos:
            raise CenarioInvalido("id repetido: %s" % oid)
        vistos.add(oid)
        pos = _lista(o.get("pos", [0, 0, 0]), "posicao de %s" % oid, 3)
        tam = _lista(o.get("tam", padrao["tam"]), "tamanho de %s" % oid, 3)
        limpo = {
            "id": oid, "tipo": tipo,
            "nome": _texto(o.get("nome", padrao["nome"]), "nome") or padrao["nome"],
            "pos": [_num(pos[0], "x", -LIMITE_POS, LIMITE_POS),
                    _num(pos[1], "y", -LIMITE_POS, LIMITE_POS),
                    _num(pos[2], "z", 0.0, LIMITE_POS)],
            "giro": _num(o.get("giro", 0), "giro", -360, 360),
            "tam": [_num(t, "tamanho", MEDIDA_MIN, MEDIDA_MAX) for t in tam],
            "material": o.get("material", "concreto"),
            "fixo": bool(o.get("fixo", padrao["fixo"])),
            "massa": _num(o.get("massa", 2.0), "massa", MASSA_MIN, MASSA_MAX),
            "atrito": _num(o.get("atrito", 0.8), "atrito", 0.0, 3.0),
            "elasticidade": _num(o.get("elasticidade", 0.05), "elasticidade", 0.0, 1.0),
        }
        if limpo["material"] not in materiais:
            limpo["material"] = "concreto"
        if tipo == "escada":
            limpo["degraus"] = int(_num(o.get("degraus", 3), "degraus", 1, 12))
        if tipo == "relevo":
            limpo["rugosidade"] = _num(o.get("rugosidade", 0.5), "rugosidade", 0.0, 1.0)
            limpo["semente"] = int(_num(o.get("semente", 1), "semente", 0, 9999))
            limpo["fixo"] = True
        cen["objetos"].append(limpo)

    for i, z in enumerate(cru.get("zonas") or []):
        if not isinstance(z, dict):
            raise CenarioInvalido("zona %d invalida" % i)
        tipo = z.get("tipo")
        if tipo not in TIPOS_ZONA:
            raise CenarioInvalido("zona %d: tipo desconhecido %r" % (i, tipo))
        zid = _id(z.get("id", "z%d" % i), "zona %d" % i)
        if zid in vistos:
            raise CenarioInvalido("id repetido: %s" % zid)
        vistos.add(zid)
        pos = _lista(z.get("pos", [0, 0]), "posicao de %s" % zid, 2)
        tam = _lista(z.get("tam", [0.6, 0.6]), "tamanho de %s" % zid, 2)
        cen["zonas"].append({
            "id": zid, "tipo": tipo,
            "nome": _texto(z.get("nome", TIPOS_ZONA[tipo]["nome"]), "nome") or TIPOS_ZONA[tipo]["nome"],
            "pos": [_num(pos[0], "x", -LIMITE_POS, LIMITE_POS),
                    _num(pos[1], "y", -LIMITE_POS, LIMITE_POS)],
            "tam": [_num(tam[0], "tamanho", 0.1, MEDIDA_MAX), _num(tam[1], "tamanho", 0.1, MEDIDA_MAX)],
            "giro": _num(z.get("giro", 0), "giro", -360, 360),
        })

    ids_zona = {z["id"] for z in cen["zonas"]}
    ids_obj = {o["id"] for o in cen["objetos"]}
    for i, r in enumerate(cru.get("regras") or []):
        if not isinstance(r, dict):
            raise CenarioInvalido("regra %d invalida" % i)
        quando = r.get("quando")
        if quando not in QUANDOS:
            raise CenarioInvalido("regra %d: 'quando' desconhecido %r" % (i, quando))
        alvo = r.get("alvo")
        if quando in ("entrar_zona", "sair_zona") and alvo not in ids_zona:
            continue        # zona apagada: a regra cai junto
        if quando == "tocar_objeto" and alvo not in ids_obj:
            continue
        fim = r.get("fim")
        if fim not in FINS:
            raise CenarioInvalido("regra %d: 'fim' invalido" % i)
        cen["regras"].append({
            "id": _id(r.get("id", "r%d" % i), "regra %d" % i),
            "quando": quando,
            "alvo": alvo if quando in ("entrar_zona", "sair_zona", "tocar_objeto") else None,
            "valor": _num(r.get("valor", 0), "valor", 0, 1e6),
            "pontos": _num(r.get("pontos", 0), "pontos", -1e6, 1e6),
            "fim": fim,
            "uma_vez": bool(r.get("uma_vez", True)),
        })
    return cen

ACOES_PADRAO = ("andar", "girar", "sentar")   # as marcadas de inicio no formulario

def novo(nome, base="chao", comeca="parado", acoes=ACOES_PADRAO):
    cen = {"id": slug(nome), "nome": nome, "base": base, "modelo": "go2",
           "comeca": comeca, "acoes": list(acoes), "chao": {"material": "concreto"},
           "objetos": [], "zonas": [], "regras": []}
    if base == "chao":
        cen["zonas"] = [{"id": "partida", "tipo": "partida", "nome": "Partida",
                         "pos": [0.0, 0.0], "tam": [0.8, 0.8], "giro": 0.0}]
    return cen

def regras_sugeridas(zona):
    """Regras que uma zona nova costuma querer; a pagina oferece, nao impoe."""
    t = zona["tipo"]
    if t == "checkpoint":
        return [dict(quando="entrar_zona", alvo=zona["id"], pontos=50, fim=None, uma_vez=True)]
    if t == "chegada":
        return [dict(quando="entrar_zona", alvo=zona["id"], pontos=100, fim="sucesso", uma_vez=True)]
    if t == "proibida":
        return [dict(quando="entrar_zona", alvo=zona["id"], pontos=-100, fim="falha", uma_vez=True)]
    return []

# ---------- geometria compartilhada (XML e ajuste ao vivo) ----------

def _quat_yaw(graus):
    a = math.radians(graus) / 2
    return (math.cos(a), 0.0, 0.0, math.sin(a))

def _quat_mul(a, b):
    w1, x1, y1, z1 = a; w2, x2, y2, z2 = b
    return (w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2)

def geoms_do_objeto(o):
    """Lista de geoms (tipo, pos relativa ao objeto, quat, size) de um objeto.
    E' a mesma conta para escrever o XML e para ajustar o modelo ao vivo."""
    c, l, a = o["tam"]
    yaw = _quat_yaw(o["giro"])
    t = o["tipo"]
    if t == "caixa" or t == "parede":
        return [("box", (0, 0, a / 2), yaw, (c / 2, l / 2, a / 2))]
    if t == "cilindro":
        return [("cylinder", (0, 0, a / 2), yaw, (c / 2, a / 2, 0))]
    if t == "esfera":
        r = c / 2
        return [("sphere", (0, 0, r), yaw, (r, 0, 0))]
    if t == "barra":
        # deitada ao longo de y, apoiada em dois pes; c = diametro, a = altura do chao
        r = c / 2
        deitar = (math.sqrt(0.5), math.sqrt(0.5), 0.0, 0.0)   # 90 graus em x
        return [("cylinder", (0, 0, a + r), _quat_mul(yaw, deitar), (r, l / 2, 0)),
                ("box", _girar((0, l / 2, (a + r) / 2), o["giro"]), yaw, (0.02, 0.02, (a + r) / 2)),
                ("box", _girar((0, -l / 2, (a + r) / 2), o["giro"]), yaw, (0.02, 0.02, (a + r) / 2))]
    if t == "rampa":
        # sobe ao longo de x: comprimento c no chao, altura a na ponta
        hip = math.hypot(c, a)
        ang = math.atan2(a, c)
        esp = 0.04
        inclinar = (math.cos(-ang / 2), 0.0, math.sin(-ang / 2), 0.0)   # em y
        centro = _girar((0, 0, a / 2 - esp * math.cos(ang) / 2), o["giro"])
        return [("box", centro, _quat_mul(yaw, inclinar), (hip / 2, l / 2, esp / 2)),
                ("box", _girar((c / 2 - 0.02, 0, a / 2), o["giro"]), yaw, (0.02, l / 2, a / 2))]
    if t == "escada":
        n = o.get("degraus", 3)
        prof, alt = c / n, a / n
        saida = []
        for i in range(n):
            x = -c / 2 + prof * (i + 0.5)
            z = alt * (i + 1) / 2
            saida.append(("box", _girar((x, 0, z), o["giro"]), yaw, (prof / 2, l / 2, alt * (i + 1) / 2)))
        return saida
    return []

def _girar(p, graus):
    a = math.radians(graus)
    x, y, z = p
    return (x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a), z)

def relevo_alturas(o, n=64):
    rng = np.random.default_rng(o.get("semente", 1))
    total = np.zeros((n, n))
    for esc, peso in ((4, 0.5), (8, 0.3), (16, 0.2)):
        grade = rng.random((esc + 1, esc + 1))
        ys = np.linspace(0, esc, n, endpoint=False)
        y0 = np.floor(ys).astype(int); f = ys - y0
        f = f * f * (3 - 2 * f)
        a = grade[y0][:, y0]; b = grade[y0][:, y0 + 1]
        c = grade[y0 + 1][:, y0]; d = grade[y0 + 1][:, y0 + 1]
        fx, fy = f[None, :], f[:, None]
        total += peso * ((a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy)
    rug = o.get("rugosidade", 0.5)
    suave = total.mean() + (total - total.mean()) * (0.4 + 0.6 * rug)
    # borda vai a zero para nao ter degrau no encontro com o chao
    ys = np.linspace(-1, 1, n)
    borda = np.clip(1.2 - np.maximum(abs(ys)[:, None], abs(ys)[None, :]) * 1.2, 0, 1)
    return np.clip(suave * borda, 0, 1)

# ---------- XML ----------

_CABECA = """<mujoco model="estudio go2">
  <include file="go2.xml"/>
  <statistic center="0 0 0.3" extent="2.0"/>
  <visual>
    <global offwidth="{larg}" offheight="{alt}" azimuth="140" elevation="-18"/>
    <headlight diffuse="0.62 0.62 0.62" ambient="0.44 0.44 0.45" specular="0.08 0.08 0.08"/>
    <rgba haze="0.95 0.95 0.96 1"/>
    <map znear="0.01"/>
    <quality offsamples="4"/>
  </visual>
"""

def _f(v):
    return "%.5g" % v

def _vec(vs):
    return " ".join(_f(v) for v in vs)

def _xml_txt(t):
    return (t.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;"))

def gerar_xml(cen, materiais):
    """O MJCF da cena. Todos os materiais entram sempre, para trocar de
    material ao vivo sem recompilar."""
    partes = [_CABECA.format(larg=LARG_MAX, alt=ALT_MAX), "  <asset>\n",
              '    <texture type="skybox" builtin="gradient" rgb1="1 1 1" rgb2="0.90 0.90 0.92" width="256" height="256"/>\n']
    for m in materiais.values():
        if m.get("arquivo"):
            # Os arquivos vem pelo dicionario de assets (VFS), nunca do disco: o
            # MuJoCo nao abre caminhos com acento no Windows. Cada material tem
            # duas versoes: "2d" (chao e relevo, repete por metro) e "cube"
            # (objetos solidos; a 2d escorre pelas faces laterais).
            partes.append('    <texture name="tx_%s" type="2d" file="tx_%s.png"/>\n' % (m["id"], m["id"]))
            partes.append('    <material name="mt_%s" texture="tx_%s" texuniform="true" texrepeat="%s %s" '
                          'reflectance="%s" shininess="%s" rgba="1 1 1 1"/>\n'
                          % (m["id"], m["id"], _f(m["repetir"]), _f(m["repetir"]),
                             _f(m["reflexo"]), _f(m["brilho"])))
            partes.append('    <texture name="tc_%s" type="cube" file="tc_%s.png"/>\n' % (m["id"], m["id"]))
            partes.append('    <material name="mc_%s" texture="tc_%s" reflectance="%s" shininess="%s" rgba="1 1 1 1"/>\n'
                          % (m["id"], m["id"], _f(m["reflexo"]), _f(m["brilho"])))
        else:
            # textura ainda nao baixada (sem rede): fica a cor de reserva
            for pref in ("mt", "mc"):
                partes.append('    <material name="%s_%s" reflectance="%s" shininess="%s" rgba="%s 1"/>\n'
                              % (pref, m["id"], _f(m["reflexo"]), _f(m["brilho"]), _vec(m["cor"])))
    partes.append('    <material name="suporte" rgba="0.74 0.74 0.77 1"/>\n')
    for o in cen["objetos"]:
        if o["tipo"] == "relevo":
            partes.append('    <hfield name="hf_%s" nrow="64" ncol="64" size="%s %s %s 0.001"/>\n'
                          % (o["id"], _f(o["tam"][0] / 2), _f(o["tam"][1] / 2), _f(o["tam"][2])))
    partes.append("  </asset>\n  <worldbody>\n")
    partes.append('    <light pos="0 0 4" dir="0 0 -1" directional="true" diffuse="0.45 0.45 0.45" castshadow="false"/>\n')
    partes.append('    <light pos="2 -2 3" dir="-1 1 -1" diffuse="0.22 0.22 0.22" castshadow="false"/>\n')
    chao = materiais[cen["chao"]["material"]]
    partes.append('    <geom name="floor" type="plane" size="0 0 0.05" material="mt_%s" friction="%s" solref="0.02 %s"/>\n'
                  % (chao["id"], _f(chao["atrito"]), _f(_amort(chao["elasticidade"]))))

    if cen["base"] == "bancada":
        # o suporte so' existe na bancada; no chao livre ele colidiria com o robo
        alt_poste = Z_BANCADA - 0.03
        partes.append('    <geom name="suporte_base" type="cylinder" size="0.13 0.016" pos="0 0 0.016" material="suporte"/>\n')
        partes.append('    <geom name="suporte_poste" type="cylinder" size="0.045 %s" pos="0 0 %s" material="suporte"/>\n'
                      % (_f(alt_poste / 2), _f(0.032 + alt_poste / 2)))
        partes.append('    <geom name="suporte_prato" type="box" size="0.11 0.075 0.014" pos="0 0 %s" material="suporte"/>\n'
                      % _f(Z_BANCADA - 0.014))

    for o in cen["objetos"]:
        mat = materiais[o["material"]]
        fis = 'material="%s_%s" friction="%s" solref="0.02 %s"' % (
            "mt" if o["tipo"] == "relevo" else "mc", mat["id"], _f(o["atrito"]), _f(_amort(o["elasticidade"])))
        if o["tipo"] == "relevo":
            partes.append('    <geom name="obj_%s_0" type="hfield" hfield="hf_%s" pos="%s" quat="%s" %s/>\n'
                          % (o["id"], o["id"], _vec(o["pos"]), _vec(_quat_yaw(o["giro"])), fis))
            continue
        geoms = geoms_do_objeto(o)
        if o["fixo"]:
            for i, (tipo, p, q, s) in enumerate(geoms):
                partes.append('    <geom name="obj_%s_%d" type="%s" pos="%s" quat="%s" size="%s" %s/>\n'
                              % (o["id"], i, tipo, _vec(_soma(o["pos"], p)), _vec(q), _vec(s), fis))
        else:
            partes.append('    <body name="obj_%s" pos="%s">\n      <freejoint/>\n' % (o["id"], _vec(o["pos"])))
            massa = o["massa"] / max(1, len(geoms))
            for i, (tipo, p, q, s) in enumerate(geoms):
                partes.append('      <geom name="obj_%s_%d" type="%s" pos="%s" quat="%s" size="%s" mass="%s" %s/>\n'
                              % (o["id"], i, tipo, _vec(p), _vec(q), _vec(s), _f(massa), fis))
            partes.append("    </body>\n")

    for z in cen["zonas"]:
        cor = TIPOS_ZONA[z["tipo"]]["cor"]
        partes.append('    <geom name="zona_%s" type="box" pos="%s %s 0.006" quat="%s" size="%s %s 0.006" '
                      'rgba="%s" contype="0" conaffinity="0" group="4"/>\n'
                      % (z["id"], _f(z["pos"][0]), _f(z["pos"][1]), _vec(_quat_yaw(z["giro"])),
                         _f(z["tam"][0] / 2), _f(z["tam"][1] / 2), _vec(cor)))
    partes.append("  </worldbody>\n</mujoco>\n")
    return "".join(partes)

def _soma(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])

def _amort(elasticidade):
    # solref: (tempo, amortecimento). 1.0 = critico (nao quica); menor quica mais.
    return 1.0 - 0.85 * elasticidade

def assinatura(cen):
    """O que exige recompilar quando muda. O resto ajusta ao vivo."""
    itens = [cen["base"]]
    for o in cen["objetos"]:
        extra = ""
        if o["tipo"] == "escada":
            extra = str(o["degraus"])
        if o["tipo"] == "relevo":
            extra = "%s|%s|%s" % (o["semente"], o["rugosidade"], _vec(o["tam"]))
        itens.append("%s:%s:%d:%s" % (o["id"], o["tipo"], o["fixo"], extra))
    for z in cen["zonas"]:
        itens.append("z:%s:%s" % (z["id"], z["tipo"]))
    return "\n".join(itens)

# ---------- disco ----------

def slug(texto):
    import unicodedata
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", texto.lower().strip()).strip("-")
    return s[:40] or "simulacao"

def _caminho(cid):
    return os.path.join(PASTA_SIMULACOES, cid + ".json")

def listar():
    os.makedirs(PASTA_SIMULACOES, exist_ok=True)
    saida = []
    for nome in sorted(os.listdir(PASTA_SIMULACOES)):
        if not nome.endswith(".json"):
            continue
        try:
            with open(os.path.join(PASTA_SIMULACOES, nome), encoding="utf-8") as fp:
                cen = json.load(fp)
        except (OSError, ValueError):
            continue
        cid = nome[:-5]
        saida.append({"id": cid, "nome": cen.get("nome", cid), "base": cen.get("base", "chao"),
                      "comeca": cen.get("comeca", "parado"),
                      "objetos": len(cen.get("objetos") or []), "zonas": len(cen.get("zonas") or []),
                      "regras": len(cen.get("regras") or []),
                      "modificado": os.path.getmtime(os.path.join(PASTA_SIMULACOES, nome)),
                      "miniatura": os.path.isfile(os.path.join(PASTA_SIMULACOES, cid + ".jpg"))})
    saida.sort(key=lambda s: -s["modificado"])
    return saida

def carregar(cid):
    with open(_caminho(cid), encoding="utf-8") as fp:
        return json.load(fp)

def gravar(cen, miniatura=None):
    os.makedirs(PASTA_SIMULACOES, exist_ok=True)
    with open(_caminho(cen["id"]), "w", encoding="utf-8") as fp:
        json.dump(cen, fp, ensure_ascii=False, indent=1)
    if miniatura:
        with open(os.path.join(PASTA_SIMULACOES, cen["id"] + ".jpg"), "wb") as fp:
            fp.write(miniatura)

def id_livre(nome):
    base = slug(nome)
    cid, n = base, 2
    while os.path.exists(_caminho(cid)):
        cid = "%s-%d" % (base, n)
        n += 1
    return cid

def apagar(cid):
    os.remove(_caminho(cid))
    try:
        os.remove(os.path.join(PASTA_SIMULACOES, cid + ".jpg"))
    except OSError:
        pass

def caminho_miniatura(cid):
    p = os.path.join(PASTA_SIMULACOES, cid + ".jpg")
    return p if os.path.isfile(p) else None
