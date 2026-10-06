import argparse
import json
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import acoes as A
import cenario as C
import materiais as M
import programa as P
import treino as T
from mundo import Mundo

AQUI = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(AQUI, "painel")

TIPOS = {".html": "text/html; charset=utf-8",
         ".js": "application/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8",
         ".svg": "image/svg+xml",
         ".png": "image/png",
         ".jpg": "image/jpeg"}

ESPERA_QUADRO = 2.0

def versao_mujoco():
    try:
        import mujoco
    except Exception:
        return None
    return getattr(mujoco, "__version__", "?")

LIMITE_CORPO = 64 * 1024 * 1024   # pacotes de textura 2K passam de 10 MB

def ler_corpo(manip, limite):
    """O corpo e' lido uma vez so' e guardado: quem nao usa tambem precisa
    consumi-lo, senao sobra no socket e vira lixo no proximo pedido."""
    if not hasattr(manip, "_corpo"):
        n = int(manip.headers.get("Content-Length") or 0)
        if n > LIMITE_CORPO:
            raise ValueError("corpo grande demais")
        manip._corpo = manip.rfile.read(n) if n > 0 else b""
    if not manip._corpo or len(manip._corpo) > limite:
        raise ValueError("corpo vazio ou grande demais")
    return manip._corpo

def ler_json(manip, limite=512 * 1024):
    dado = json.loads(ler_corpo(manip, limite).decode("utf-8"))
    if not isinstance(dado, dict):
        raise ValueError("esperava um objeto")
    return dado

class Manipulador(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "EstudioGo2"

    def log_message(self, formato, *args):
        pass

    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass    # a aba fechou no meio de um pedido: nao e' erro do estudio

    def handle_one_request(self):
        # o mesmo objeto atende varios pedidos na mesma conexao: o corpo
        # guardado por ler_corpo nao pode vazar de um pedido para o outro
        if hasattr(self, "_corpo"):
            del self._corpo
        super().handle_one_request()

    def _erro(self, codigo, texto):
        corpo = texto.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _json(self, obj, codigo=200):
        corpo = json.dumps(obj).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _arquivo(self, pasta, nome):
        return self._caminho(os.path.join(pasta, os.path.basename(nome)))

    def _caminho(self, alvo):
        if not alvo or not os.path.isfile(alvo):
            return self._erro(404, "nao encontrado")
        with open(alvo, "rb") as fp:
            corpo = fp.read()
        ext = os.path.splitext(alvo)[1].lower()
        self.send_response(200)
        self.send_header("Content-Type", TIPOS.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _video(self, consulta):
        # MJPEG: uma resposta que nao termina, um JPEG atras do outro. O <img>
        # do navegador entende sozinho, sem JavaScript.
        try:
            larg = int(consulta.get("w", "960"))
            alt = int(consulta.get("h", "540"))
        except ValueError:
            larg, alt = 960, 540
        mundo = self.server.mundo
        if not mundo.pronto:
            return self._erro(503, "o MuJoCo ainda nao esta pronto")
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=quadro")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        mundo.entrar_visor(larg, alt)
        try:
            visto = -1
            while mundo.pronto:
                jpeg, visto = mundo.quadro.esperar(visto, ESPERA_QUADRO)
                if jpeg is None:
                    continue
                self.wfile.write(b"--quadro\r\nContent-Type: image/jpeg\r\n"
                                 b"Content-Length: %d\r\n\r\n" % len(jpeg))
                self.wfile.write(jpeg)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
        except OSError:
            pass    # a aba fechou ou saiu da secao
        finally:
            mundo.sair_visor()

    def do_GET(self):
        caminho, _, cru = self.path.partition("?")
        consulta = dict(p.split("=", 1) for p in cru.split("&") if "=" in p)

        if caminho in ("/", "/index.html"):
            return self._arquivo(APP, "index.html")
        if caminho.startswith("/app/"):
            return self._arquivo(APP, caminho)

        if caminho == "/api/estado":
            mundo = self.server.mundo.estado()
            mundo["programa"] = self.server.programa.resumo()
            return self._json({"mujoco": self.server.mujoco, "mundo": mundo})
        if caminho == "/api/mujoco/video":
            return self._video(consulta)

        if caminho == "/api/acoes":
            cen = self.server.mundo.cen
            return self._json(A.publico(cen["acoes"] if cen else None))
        if caminho == "/api/cenario":
            cen = self.server.mundo.cen
            if cen is None:
                return self._json({"erro": "o MuJoCo ainda nao esta pronto"}, 503)
            return self._json(cen)
        if caminho == "/api/materiais":
            return self._json([M.publico(m) for m in M.catalogo()])
        if caminho == "/api/materiais/buscar":
            from urllib.parse import unquote
            return self._responder(lambda: M.buscar(unquote(consulta.get("q", ""))))
        partes = caminho.strip("/").split("/")
        if len(partes) == 4 and partes[:2] == ["api", "materiais"] and partes[3] == "miniatura.png":
            return self._caminho(M.caminho_miniatura(partes[2]))

        if caminho == "/api/programa":
            try:
                desde = int(consulta.get("desde", "0"))
            except ValueError:
                desde = 0
            return self._json(self.server.programa.estado(desde))
        if caminho == "/api/programa/referencia":
            return self._json({"funcoes": P.referencia(), "exemplo": P.EXEMPLO})
        if caminho == "/api/programas":
            return self._json(P.listar())
        if len(partes) == 3 and partes[:2] == ["api", "programas"]:
            from urllib.parse import unquote
            return self._responder(lambda: P.carregar(unquote(partes[2])))
        if len(partes) == 4 and partes[:2] == ["api", "programas"] and partes[3] == "parametros":
            from urllib.parse import unquote
            return self._responder(lambda: P.parametros_do_programa(P.carregar(unquote(partes[2]))["codigo"]))

        if caminho == "/api/treino":
            return self._json(self.server.treino.estado())
        if caminho == "/api/treino/variaveis":
            return self._json(T.variaveis_publicas(self.server.mundo))
        if caminho == "/api/treino/ajustes":
            return self._json(self.server.mundo.ajustes)
        if caminho == "/api/treinos":
            return self._json(T.listar())
        if len(partes) == 3 and partes[:2] == ["api", "treinos"]:
            return self._responder(lambda: T.publico(T.carregar(partes[2])))

        if caminho == "/api/simulacoes":
            return self._json(C.listar())
        if len(partes) == 3 and partes[:2] == ["api", "simulacoes"]:
            try:
                return self._json(C.carregar(partes[2]))
            except OSError:
                return self._erro(404, "simulacao nao encontrada")
        if len(partes) == 4 and partes[:2] == ["api", "simulacoes"] and partes[3] == "miniatura.jpg":
            return self._caminho(C.caminho_miniatura(partes[2]))

        return self._erro(404, "nao encontrado")

    def _responder(self, fn):
        """Roda um pedido e traduz erros em codigos HTTP."""
        try:
            try:
                ler_corpo(self, LIMITE_CORPO)   # consome o corpo mesmo que fn nao use
            except ValueError:
                pass
            return self._json(fn())
        except (ValueError, TypeError, KeyError, C.CenarioInvalido) as e:
            return self._json({"erro": str(e)}, 400)
        except M.SemRede as e:
            return self._json({"erro": str(e)}, 502)
        except FileNotFoundError:
            return self._json({"erro": "nao encontrado"}, 404)
        except RuntimeError as e:
            return self._json({"erro": str(e)}, 503)

    def do_POST(self):
        caminho, _, cru = self.path.partition("?")
        consulta = dict(p.split("=", 1) for p in cru.split("&") if "=" in p)
        mundo = self.server.mundo
        partes = caminho.strip("/").split("/")

        if caminho == "/api/mujoco":
            return self._responder(lambda: mundo.comandar(ler_json(self)))

        if caminho == "/api/acoes":
            def enfileirar():
                p = ler_json(self)
                return mundo.enfileirar(str(p.get("id", "")), p.get("parametros") or {}).estado()
            return self._responder(enfileirar)

        if caminho == "/api/programa":
            def rodar():
                p = ler_json(self)
                return self.server.programa.iniciar(p.get("codigo"), str(p.get("nome", "")))
            return self._responder(rodar)

        if caminho == "/api/treino":
            return self._responder(lambda: self.server.treino.iniciar(ler_json(self)))
        if caminho == "/api/treino/campeao":
            return self._responder(lambda: self.server.treino.campeao(str(ler_json(self).get("id", ""))))
        if caminho == "/api/treino/campeao/programa":
            return self._responder(lambda: T.programa_campeao(str(ler_json(self).get("id", ""))))
        if caminho == "/api/treino/ajustes":
            def ajustar():
                T.aplicar_ajustes(self.server.mundo, ler_json(self), gravar=True)
                return self.server.mundo.ajustes
            return self._responder(ajustar)
        if caminho == "/api/treino/campeao/usar":
            return self._responder(lambda: self.server.treino.usar_campeao(str(ler_json(self).get("id", ""))))

        if caminho == "/api/cenario/apontar":
            def apontar():
                p = ler_json(self)
                x, y = float(p.get("x", 0.5)), float(p.get("y", 0.5))
                return mundo.apontar(min(1.0, max(0.0, x)), min(1.0, max(0.0, y)))
            return self._responder(apontar)

        if caminho == "/api/materiais/baixar":
            def baixar():
                p = ler_json(self)
                return M.publico(M.baixar(str(p.get("fonte", ""))))
            return self._responder(baixar)

        if caminho == "/api/materiais":
            def enviar():
                from urllib.parse import unquote
                nome = unquote(consulta.get("nome", "textura"))
                tipo = self.headers.get("Content-Type", "")
                dados = ler_corpo(self, LIMITE_CORPO)
                return M.publico(M.enviar(nome, dados, tipo))
            return self._responder(enviar)

        if caminho == "/api/simulacoes":
            def criar():
                p = ler_json(self)
                cen = C.novo(str(p.get("nome", "")).strip()[:60] or "Sem nome",
                             p.get("base", "chao"), p.get("comeca", "parado"),
                             p["acoes"] if isinstance(p.get("acoes"), list) else C.ACOES_PADRAO)
                cen["id"] = C.id_livre(cen["nome"])
                cen = C.validar(cen, M.por_id())
                C.gravar(cen)
                mundo.modo = "editar"
                mundo.aplicar(cen)
                return cen
            return self._responder(criar)

        if caminho == "/api/simulacoes/importar":
            def importar():
                cen = C.validar(ler_json(self, 2 * 1024 * 1024), M.por_id())
                cen["id"] = C.id_livre(cen["nome"])
                C.gravar(cen)
                return cen
            return self._responder(importar)

        if len(partes) == 4 and partes[:2] == ["api", "simulacoes"] and partes[3] == "abrir":
            def abrir():
                cen = C.validar(C.carregar(partes[2]), M.por_id())
                cen["id"] = partes[2]
                mundo.modo = "editar"
                mundo.aplicar(cen)
                return cen
            return self._responder(abrir)

        return self._erro(404, "nao encontrado")

    def do_PUT(self):
        caminho, _, cru = self.path.partition("?")
        consulta = dict(p.split("=", 1) for p in cru.split("&") if "=" in p)
        mundo = self.server.mundo
        partes = caminho.strip("/").split("/")

        if caminho == "/api/cenario":
            def aplicar():
                cen = C.validar(ler_json(self), M.por_id())
                reconstruido = mundo.aplicar(cen)
                return {"reconstruido": reconstruido, "estado": mundo.estado()}
            return self._responder(aplicar)

        if len(partes) == 3 and partes[:2] == ["api", "programas"]:
            def gravar():
                from urllib.parse import unquote
                p = ler_json(self)
                return P.gravar(unquote(partes[2]), p.get("codigo"))
            return self._responder(gravar)

        if len(partes) == 3 and partes[:2] == ["api", "simulacoes"]:
            def salvar():
                cen = C.validar(ler_json(self), M.por_id())
                cen["id"] = partes[2]
                if consulta.get("novo") == "1" and not os.path.isfile(C._caminho(cen["id"])):
                    cen["id"] = C.id_livre(cen["nome"])   # primeira gravacao: id pelo nome
                mini = mundo.quadro.jpeg if mundo.visores else None
                C.gravar(cen, mini)
                return {"id": cen["id"], "miniatura": bool(mini)}
            return self._responder(salvar)

        return self._erro(404, "nao encontrado")

    def do_DELETE(self):
        caminho = self.path.partition("?")[0]
        partes = caminho.strip("/").split("/")
        if caminho == "/api/acoes":
            return self._responder(lambda: (self.server.mundo.parar_acoes(), self.server.mundo.estado())[1])
        if caminho == "/api/programa":
            return self._responder(self.server.programa.parar)
        if caminho == "/api/treino":
            return self._responder(self.server.treino.parar)
        if caminho == "/api/treino/ajustes":
            return self._responder(lambda: (T.definir_ajustes(self.server.mundo, {}, gravar=True), {})[1])
        if len(partes) == 3 and partes[:2] == ["api", "treinos"]:
            return self._responder(lambda: (T.apagar(partes[2]), self.server.treino.esquecer(partes[2]), {"ok": True})[2])
        if len(partes) == 3 and partes[:2] == ["api", "programas"]:
            from urllib.parse import unquote
            return self._responder(lambda: (P.apagar(unquote(partes[2])), {"ok": True})[1])
        if len(partes) == 3 and partes[:2] == ["api", "simulacoes"]:
            return self._responder(lambda: (C.apagar(partes[2]), {"ok": True})[1])
        if len(partes) == 3 and partes[:2] == ["api", "materiais"]:
            return self._responder(lambda: (M.remover(partes[2]), {"ok": True})[1])
        return self._erro(404, "nao encontrado")

def principal():
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Estudio do Go2")
    ap.add_argument("--porta", type=int, default=8791)
    ap.add_argument("--aberto", action="store_true",
                    help="aceita conexoes de outras maquinas (senao, so localhost)")
    ap.add_argument("--sem-navegador", action="store_true",
                    help="nao abre o navegador sozinho")
    args = ap.parse_args()

    endereco = "0.0.0.0" if args.aberto else "127.0.0.1"
    try:
        servidor = ThreadingHTTPServer((endereco, args.porta), Manipulador)
    except OSError as e:
        print("\n  nao consegui subir na porta %d: %s" % (args.porta, e))
        print("  tente outra:  python estudio.py --porta %d\n" % (args.porta + 1))
        return 1
    servidor.daemon_threads = True
    import dados
    dados.migrar()
    servidor.mujoco = versao_mujoco()
    servidor.mundo = Mundo()
    servidor.programa = P.Programa(servidor.mundo)
    servidor.treino = T.Treino(servidor.mundo, servidor.programa)
    servidor.mundo.ao_pronto = lambda: T.carregar_ajustes(servidor.mundo)

    url = "http://localhost:%d/" % args.porta
    print("")
    print("  Estudio do Go2")
    print("  painel ..... %s" % url)
    print("  dados ...... %s" % dados.RAIZ)
    if servidor.mujoco:
        print("  MuJoCo ..... %s instalado; montando a cena..." % servidor.mujoco)
    else:
        print("  MuJoCo ..... nao encontrado  (pip install mujoco)")
    if args.aberto:
        print("  na rede .... http://<ip-desta-maquina>:%d/" % args.porta)
    else:
        print("  (somente esta maquina; use --aberto para liberar na rede)")
    print("  Ctrl+C para encerrar")
    print("")

    servidor.mundo.iniciar()
    if not args.sem_navegador:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\n  encerrando...")
        servidor.mundo.parar.set()
        servidor.shutdown()
    return 0

if __name__ == "__main__":
    sys.exit(principal())
