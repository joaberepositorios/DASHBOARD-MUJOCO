"""Materiais do cenario: textura real, cor, brilho e atrito.

As texturas vem do ambientCG (https://ambientcg.com), fotografadas e
publicadas em dominio publico (CC0). Na primeira vez o estudio baixa um
conjunto inicial de dez (pacotes 1K, ~3,5 MB cada) para a pasta de dados (materiais/, ver dados.py).
Qualquer outro material do catalogo pode ser buscado e baixado pela pagina;
e uma imagem ou pacote enviado pelo usuario tambem vira material, em
materiais/enviados/ na pasta de dados.

O MuJoCo desenha so' o mapa de cor. O mapa de rugosidade do pacote e' usado
uma vez, para tirar o brilho medio do material.
"""

import io
import json
import os
import re
import time
import unicodedata
import urllib.parse
import urllib.request
import zipfile

AQUI = os.path.dirname(os.path.abspath(__file__))
import dados
PASTA = dados.pasta("materiais")
ENVIADOS = os.path.join(PASTA, "enviados")
CATALOGO_ENVIADOS = os.path.join(ENVIADOS, "catalogo.json")
CREDITOS = os.path.join(PASTA, "creditos.json")
LADO = 1024          # a textura guardada
LADO_MINI = 128

API = "https://ambientcg.com/api/v2/full_json"
BAIXAR = "https://ambientcg.com/get?file=%s_1K-JPG.zip"
PAGINA = "https://ambientcg.com/view?id=%s"
AGENTE = "EstudioGo2/0.3 (https://github.com/joaberepositorios/Isaacdashboard)"

# repetir: quantas vezes a textura cabe em 1 metro
# atrito: coeficiente de deslizamento do MuJoCo (borracha alta, azulejo baixo)
# elasticidade: 0 = amortece tudo, 1 = quica
# cor: tinta de reserva se a textura nao tiver sido baixada
FABRICA = [
    dict(id="concreto", nome="Concreto", fonte="Concrete034", repetir=0.8, reflexo=0.05,
         atrito=0.90, elasticidade=0.05, cor=[0.62, 0.62, 0.63]),
    dict(id="asfalto", nome="Asfalto", fonte="Asphalt012", repetir=1.0, reflexo=0.02,
         atrito=1.00, elasticidade=0.05, cor=[0.25, 0.25, 0.26]),
    dict(id="madeira", nome="Madeira", fonte="Planks020", repetir=1.0, reflexo=0.10,
         atrito=0.60, elasticidade=0.10, cor=[0.55, 0.38, 0.22]),
    dict(id="grama", nome="Grama", fonte="Grass004", repetir=1.5, reflexo=0.00,
         atrito=0.80, elasticidade=0.05, cor=[0.30, 0.48, 0.18]),
    dict(id="terra", nome="Terra", fonte="Ground037", repetir=1.0, reflexo=0.00,
         atrito=0.75, elasticidade=0.02, cor=[0.42, 0.32, 0.22]),
    dict(id="borracha", nome="Borracha", fonte="Rubber001", repetir=2.5, reflexo=0.02,
         atrito=1.30, elasticidade=0.30, cor=[0.15, 0.15, 0.16]),
    dict(id="metal", nome="Metal", fonte="Metal032", repetir=1.0, reflexo=0.35,
         atrito=0.40, elasticidade=0.10, cor=[0.65, 0.66, 0.68]),
    dict(id="azulejo", nome="Azulejo", fonte="Tiles074", repetir=1.0, reflexo=0.25,
         atrito=0.35, elasticidade=0.05, cor=[0.85, 0.86, 0.87]),
    dict(id="tijolo", nome="Tijolo", fonte="Bricks090", repetir=1.5, reflexo=0.03,
         atrito=0.85, elasticidade=0.05, cor=[0.62, 0.32, 0.24]),
    dict(id="tapete", nome="Tapete", fonte="Carpet013", repetir=1.5, reflexo=0.00,
         atrito=1.10, elasticidade=0.15, cor=[0.45, 0.42, 0.40]),
]

# Quem nao tem foto propria herda o atrito da categoria do ambientCG.
FISICA_POR_CATEGORIA = {
    "concrete": (0.90, 0.05), "asphalt": (1.00, 0.05), "wood": (0.60, 0.10), "planks": (0.60, 0.10),
    "woodfloor": (0.55, 0.10), "grass": (0.80, 0.05), "ground": (0.75, 0.02), "rubber": (1.30, 0.30),
    "metal": (0.40, 0.10), "tiles": (0.35, 0.05), "bricks": (0.85, 0.05), "carpet": (1.10, 0.15),
    "fabric": (1.00, 0.15), "rock": (0.80, 0.05), "gravel": (0.90, 0.02), "sand": (0.70, 0.02),
    "snow": (0.30, 0.02), "ice": (0.05, 0.02), "marble": (0.30, 0.05), "paving": (0.85, 0.05),
    "pavingstones": (0.85, 0.05), "leather": (0.70, 0.10),
}

class SemRede(RuntimeError):
    pass

# ---------- imagens ----------

def _pil():
    try:
        from PIL import Image
        return Image
    except ImportError:
        raise RuntimeError("as texturas precisam do Pillow (pip install pillow)")

def _para_png(dados, lado=LADO):
    """Qualquer imagem vira PNG RGB, no maximo `lado` px."""
    Image = _pil()
    try:
        img = Image.open(io.BytesIO(dados))
        img.load()
    except Exception:
        raise ValueError("nao consegui ler a imagem")
    img = img.convert("RGB")
    if max(img.size) > lado:
        esc = lado / max(img.size)
        img = img.resize((max(1, round(img.width * esc)), max(1, round(img.height * esc))), Image.LANCZOS)
    saida = io.BytesIO()
    img.save(saida, "PNG")
    return saida.getvalue()

def _miniatura(png, caminho):
    Image = _pil()
    img = Image.open(io.BytesIO(png)).convert("RGB")
    img.thumbnail((LADO_MINI, LADO_MINI), Image.LANCZOS)
    img.save(caminho, "PNG")

def _brilho_da_rugosidade(dados):
    """Rugosidade media do pacote (0 = espelho, 1 = fosco) vira brilho."""
    try:
        Image = _pil()
        img = Image.open(io.BytesIO(dados)).convert("L")
        img.thumbnail((64, 64))
        media = sum(img.getdata()) / (img.width * img.height * 255.0)
        # o MuJoCo exagera o brilho especular; acima de 0,5 tudo vira plastico
        return round(max(0.05, min(0.5, (1.0 - media) * 0.7)), 2)
    except Exception:
        return 0.1

def _mapa_de_cor(zipbytes):
    """No pacote (ambientCG, Poly Haven...) acha o mapa de cor e o de
    rugosidade. Devolve (cor, rugosidade ou None)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(zipbytes))
    except zipfile.BadZipFile:
        raise ValueError("o arquivo nao e' um .zip valido")
    nomes = [n for n in z.namelist() if n.lower().endswith((".jpg", ".jpeg", ".png"))]
    def achar(*chaves):
        for n in nomes:
            base = os.path.basename(n).lower()
            if any(c in base for c in chaves):
                return z.read(n)
        return None
    cor = achar("_color", "color.", "albedo", "diffuse", "_diff", "basecolor", "base_color")
    rug = achar("roughness", "_rough")
    if cor is None:
        raise ValueError("o pacote nao tem mapa de cor (Color, Albedo ou Diffuse)")
    return cor, rug

# ---------- rede ----------

def _pegar(url, tempo=60):
    pedido = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    try:
        with urllib.request.urlopen(pedido, timeout=tempo) as r:
            return r.read()
    except Exception as e:
        raise SemRede("sem acesso a %s (%s)" % (urllib.parse.urlparse(url).netloc, e))

def _api(**params):
    dados = _pegar(API + "?" + urllib.parse.urlencode(params), tempo=30)
    return json.loads(dados.decode("utf-8"))

def buscar(termo, limite=18):
    """Procura no catalogo do ambientCG. Devolve o que a pagina mostra."""
    termo = termo.strip()[:60]
    if not termo:
        return []
    r = _api(q=termo, type="Material", limit=limite, include="imageData,tagData")
    saida = []
    for a in r.get("foundAssets", []):
        img = a.get("previewImage") or {}
        saida.append({"fonte": a["assetId"], "nome": a.get("displayName") or a["assetId"],
                      "miniatura": img.get("256-PNG") or img.get("128-PNG"),
                      "tags": [t for t in (a.get("tags") or []) if not t.isdigit()][:6],
                      "pagina": PAGINA % a["assetId"]})
    return saida

def _baixar_pacote(fonte):
    if not re.fullmatch(r"[A-Za-z0-9]+", fonte or ""):
        raise ValueError("nome de textura invalido")
    return _pegar(BAIXAR % fonte, tempo=180)

def _categoria(fonte):
    return re.sub(r"\d+$", "", fonte).lower()

# ---------- de fabrica ----------

def _ler_creditos():
    try:
        with open(CREDITOS, encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, ValueError):
        return {}

def _gravar_creditos(cred):
    with open(CREDITOS, "w", encoding="utf-8") as fp:
        json.dump(cred, fp, ensure_ascii=False, indent=1)

def _instalar(fonte, destino_png, destino_mini):
    """Baixa o pacote 1K, guarda o mapa de cor como PNG e devolve o brilho."""
    pacote = _baixar_pacote(fonte)
    cor, rug = _mapa_de_cor(pacote)
    png = _para_png(cor)
    with open(destino_png, "wb") as fp:
        fp.write(png)
    _miniatura(png, destino_mini)
    return _brilho_da_rugosidade(rug) if rug else 0.1

def preparar(avisar=lambda t: None):
    """Garante as texturas de fabrica no disco. Devolve a lista das que
    faltaram (sem rede): ficam com a cor de reserva ate a proxima vez."""
    os.makedirs(ENVIADOS, exist_ok=True)
    cred = _ler_creditos()
    faltam = []
    pendentes = [m for m in FABRICA if not os.path.isfile(os.path.join(PASTA, m["id"] + ".png"))]
    for i, mat in enumerate(pendentes, 1):
        avisar("baixando texturas do ambientCG (%d de %d: %s)" % (i, len(pendentes), mat["nome"]))
        try:
            brilho = _instalar(mat["fonte"], os.path.join(PASTA, mat["id"] + ".png"),
                               os.path.join(PASTA, mat["id"] + ".mini.png"))
        except (SemRede, ValueError, RuntimeError) as e:
            print("  textura .... %s: %s" % (mat["nome"], e))
            faltam.append(mat["id"])
            continue
        cred[mat["id"]] = {"fonte": mat["fonte"], "pagina": PAGINA % mat["fonte"],
                           "licenca": "CC0", "brilho": brilho, "baixado_em": time.strftime("%Y-%m-%d")}
        _gravar_creditos(cred)
    return faltam

# ---------- catalogo ----------

def _ler_enviados():
    try:
        with open(CATALOGO_ENVIADOS, encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, ValueError):
        return []

def _gravar_enviados(lista):
    os.makedirs(ENVIADOS, exist_ok=True)
    with open(CATALOGO_ENVIADOS, "w", encoding="utf-8") as fp:
        json.dump(lista, fp, ensure_ascii=False, indent=1)

def catalogo():
    cred = _ler_creditos()
    saida = []
    for mat in FABRICA:
        arq = os.path.join(PASTA, mat["id"] + ".png")
        tem = os.path.isfile(arq)
        saida.append(dict(mat, origem="fabrica", arquivo=arq if tem else None,
                          brilho=cred.get(mat["id"], {}).get("brilho", 0.1),
                          pagina=PAGINA % mat["fonte"]))
    for mat in _ler_enviados():
        arq = os.path.join(ENVIADOS, mat["arquivo"])
        if os.path.isfile(arq):
            saida.append(dict(mat, origem=mat.get("origem", "enviado"), arquivo=arq))
    return saida

def por_id():
    return {m["id"]: m for m in catalogo()}

def caminho_miniatura(mid):
    for m in catalogo():
        if m["id"] == mid:
            pasta = PASTA if m["origem"] == "fabrica" else ENVIADOS
            p = os.path.join(pasta, mid + ".mini.png")
            return p if os.path.isfile(p) else None
    return None

def _slug(texto):
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", texto.lower().strip()).strip("-")
    return s or "material"

def _id_livre(nome, lista):
    base = _slug(nome)
    mid, n = base, 2
    ocupados = {m["id"] for m in lista} | {m["id"] for m in FABRICA}
    while mid in ocupados:
        mid = "%s-%d" % (base, n)
        n += 1
    return mid

def _registrar(nome, png, extra):
    lista = _ler_enviados()
    mid = _id_livre(nome, lista)
    os.makedirs(ENVIADOS, exist_ok=True)
    with open(os.path.join(ENVIADOS, mid + ".png"), "wb") as fp:
        fp.write(png)
    _miniatura(png, os.path.join(ENVIADOS, mid + ".mini.png"))
    mat = dict(id=mid, nome=nome.strip()[:40] or mid, arquivo=mid + ".png",
               repetir=1.0, reflexo=0.05, brilho=0.1, atrito=0.8, elasticidade=0.05,
               cor=[0.7, 0.7, 0.7], enviado_em=time.strftime("%Y-%m-%d %H:%M"))
    mat.update(extra)
    lista.append(mat)
    _gravar_enviados(lista)
    return dict(mat, arquivo=os.path.join(ENVIADOS, mat["arquivo"]))

def enviar(nome, dados, tipo):
    """Uma imagem (PNG/JPEG) ou um pacote .zip de textura vira material."""
    if len(dados) > 60 * 1024 * 1024:
        raise ValueError("arquivo grande demais (limite de 60 MB)")
    brilho = 0.1
    if dados[:2] == b"PK" or tipo in ("application/zip", "application/x-zip-compressed"):
        cor, rug = _mapa_de_cor(dados)
        png = _para_png(cor)
        if rug:
            brilho = _brilho_da_rugosidade(rug)
    elif tipo in ("image/png", "image/jpeg"):
        png = _para_png(dados)
    else:
        raise ValueError("mande uma imagem PNG/JPEG ou um pacote .zip de textura")
    return _registrar(nome, png, {"origem": "enviado", "brilho": brilho})

def baixar(fonte):
    """Baixa um material do ambientCG pelo id (ex.: Bricks054) e o registra."""
    if not re.fullmatch(r"[A-Za-z0-9]+", fonte or ""):
        raise ValueError("id de textura invalido")
    if any(m.get("fonte") == fonte for m in _ler_enviados()) or any(m["fonte"] == fonte for m in FABRICA):
        raise ValueError("essa textura ja esta na paleta")
    pacote = _baixar_pacote(fonte)
    cor, rug = _mapa_de_cor(pacote)
    png = _para_png(cor)
    atrito, elast = FISICA_POR_CATEGORIA.get(_categoria(fonte), (0.8, 0.05))
    nome = re.sub(r"(\D)(\d)", r"\1 \2", fonte)
    return _registrar(nome, png, {"origem": "ambientcg", "fonte": fonte, "pagina": PAGINA % fonte,
                                  "licenca": "CC0", "brilho": _brilho_da_rugosidade(rug) if rug else 0.1,
                                  "atrito": atrito, "elasticidade": elast})

def remover(mid):
    lista = _ler_enviados()
    resto = [m for m in lista if m["id"] != mid]
    if len(resto) == len(lista):
        raise KeyError(mid)
    for m in lista:
        if m["id"] == mid:
            for arq in (m["arquivo"], mid + ".mini.png"):
                try:
                    os.remove(os.path.join(ENVIADOS, arq))
                except OSError:
                    pass
    _gravar_enviados(resto)

def publico(mat):
    """O que a pagina precisa saber (sem caminhos do disco)."""
    saida = {k: mat.get(k) for k in ("id", "nome", "origem", "repetir", "reflexo",
                                     "brilho", "atrito", "elasticidade", "cor", "fonte", "pagina")}
    saida["textura"] = bool(mat.get("arquivo"))
    return saida
