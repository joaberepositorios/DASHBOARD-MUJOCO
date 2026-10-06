"use strict";

// A tela do MuJoCo: o servidor desenha e manda um JPEG atras do outro
// (MJPEG), que um <img> comum mostra sozinho. Daqui so' saem comandos.
// Usa $, $$ e avisar do app.js, que carrega depois deste arquivo mas antes
// de qualquer funcao daqui ser chamada.

const MJ_PASSO_ENVIO = 50;    // ms: junta arrasto e roda antes de mandar
const MJ_GIRO = 0.35;         // graus de azimute por pixel arrastado
const MJ_INCLINA = 0.25;      // graus de elevacao por pixel arrastado
const MJ_ZOOM = 1.12;         // por "clique" da roda
const MJ_REFAZER = 0.15;      // refaz o video se o quadro mudar mais que 15%
const MJ_ESPERA_ERRO = 2000;

let mjEstado;                 // ultimo estado; undefined = ainda nao perguntou, null = sem resposta
let mjVersao;                 // versao instalada; null = nao instalado
const mjOuvintes = [];        // quem quer saber do estado (o editor)

function telaVisivel(tela) {
  return !document.hidden && !tela.closest("section[data-vista]").hidden;
}

function algumaTelaVisivel() {
  return $$("[data-tela]").some(telaVisivel);
}

async function pedirJson(url, metodo, corpo) {
  const r = await fetch(url, {
    method: metodo,
    headers: corpo === undefined ? {} : { "Content-Type": "application/json" },
    body: corpo === undefined ? undefined : JSON.stringify(corpo),
  });
  const dado = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(dado.erro || "HTTP " + r.status);
  return dado;
}

async function mandarMuJoCo(pedido) {
  const estado = await pedirJson("/api/mujoco", "POST", pedido);
  pintarMundo(estado, mjVersao);
  return estado;
}

/* ---------- video ---------- */

function medidaDaTela(tela) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  return [Math.round(tela.clientWidth * dpr), Math.round(tela.clientHeight * dpr)];
}

function iniciarVideo(tela) {
  const img = $(".tela-video", tela);
  const [w, h] = medidaDaTela(tela);
  if (!w || !h) return;
  tela.dataset.medida = w + "x" + h;
  img.onload = () => { tela.classList.add("ao-vivo"); pintarTela(tela); };
  img.onerror = () => { pararVideo(tela); setTimeout(sincronizarVideo, MJ_ESPERA_ERRO); };
  img.src = `/api/mujoco/video?w=${w}&h=${h}&n=${Date.now()}`;
}

function pararVideo(tela) {
  const img = $(".tela-video", tela);
  img.onload = img.onerror = null;
  img.removeAttribute("src");   // derruba a conexao; o servidor para de desenhar
  tela.classList.remove("ao-vivo");
  delete tela.dataset.medida;
}

function sincronizarVideo() {
  for (const tela of $$("[data-tela]")) {
    const quer = Boolean(mjEstado?.pronto) && telaVisivel(tela);
    const esta = "medida" in tela.dataset;
    if (quer && !esta) iniciarVideo(tela);
    else if (!quer && esta) pararVideo(tela);
    pintarTela(tela);
  }
}

function mudouMuito(tela) {
  const [w0, h0] = tela.dataset.medida.split("x").map(Number);
  const [w, h] = medidaDaTela(tela);
  return Math.abs(w - w0) > w0 * MJ_REFAZER || Math.abs(h - h0) > h0 * MJ_REFAZER;
}

/* ---------- desenho do estado ---------- */

function pintarMundo(estado, versao) {
  mjEstado = estado;
  mjVersao = versao;
  sincronizarVideo();
  for (const f of mjOuvintes) f(estado);
}

function textoDoEstado(tela) {
  const e = mjEstado;
  if (e === undefined) return ["", "Consultando"];
  if (mjVersao === null) return ["alerta", "MuJoCo não instalado"];
  if (!e) return ["alerta", "Sem resposta"];
  if (e.erro) return ["alerta", "Erro"];
  if (!e.pronto) return ["", "Ligando"];
  if (!tela.classList.contains("ao-vivo")) return ["", "Conectando"];
  return ["vivo", e.fps ? `${Math.round(e.fps)} fps` : "Ao vivo"];
}

function avisoDoEstado() {
  const e = mjEstado;
  if (e === undefined) return ["Ligando o MuJoCo", ""];
  if (mjVersao === null) return ["MuJoCo não instalado", "pip install mujoco e reinicie o estúdio"];
  if (!e) return ["Sem resposta do servidor", "confira o estudio.py"];
  if (e.erro) return ["O MuJoCo não abriu", e.erro];
  if (!e.pronto) return ["Ligando o MuJoCo", e.situacao];
  return ["Conectando", ""];
}

function formatarTempo(t) {
  return t.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + " s";
}

function pintarTela(tela) {
  const e = mjEstado;
  const [ponto, texto] = textoDoEstado(tela);
  $(".tela-estado .ponto", tela).className = "ponto " + ponto;
  $(".tela-estado [data-txt]", tela).textContent = texto;
  const [tit, txt] = avisoDoEstado();
  $("[data-aviso-tit]", tela).textContent = tit;
  $("[data-aviso-txt]", tela).textContent = txt;

  const pronto = Boolean(e?.pronto);
  for (const b of $$("button", tela)) b.disabled = !pronto;
  for (const b of $$("[data-modo]", tela)) {
    b.setAttribute("aria-pressed", String(pronto && e.modo === b.dataset.modo));
  }
  // na bancada nao ha o que testar: o robo fica preso no suporte
  const bancada = pronto && e.base === "bancada";
  $("[data-modo=testar]", tela).disabled = !pronto || bancada;
  $("[data-modo=testar]", tela).title = bancada ? "Na bancada o robô fica preso no suporte" : "";

  const legenda = $("[data-legenda]", tela);
  legenda.hidden = !pronto;
  if (pronto) {
    let txt = e.camera + (e.modo === "testar" ? " · " + formatarTempo(e.tempo) : "");
    if (e.velocidade > 1) txt += " · " + e.velocidade + "×";
    if (e.acao) txt += " · " + e.acao.nome + (e.acao.progresso ? " " + Math.round(e.acao.progresso * 100) + "%" : "");
    else if (e.modo === "testar" && e.postura && e.postura !== "de pe") txt += " · " + e.postura;
    if (e.programa?.rodando) txt += " · programa" + (e.programa.linha ? ", linha " + e.programa.linha : "");
    legenda.textContent = txt;
  }

  const placar = $("[data-placar]", tela);
  const mostrar = pronto && e.modo === "testar" && e.placar;
  placar.hidden = !mostrar;
  if (mostrar) {
    $("[data-placar-pontos]", tela).textContent = e.placar.pontos;
    $("[data-placar-tempo]", tela).textContent = formatarTempo(e.placar.tempo);
    const fim = $("[data-placar-fim]", tela);
    fim.hidden = !e.placar.fim;
    fim.dataset.fim = e.placar.fim || "";
    fim.textContent = e.placar.fim === "sucesso" ? "Sucesso" : e.placar.fim === "falha" ? "Falha" : "";
    const ul = $("[data-placar-eventos]", tela);
    ul.replaceChildren(...e.placar.eventos.slice(-4).map(ev => {
      const li = document.createElement("li");
      const b = document.createElement("b");
      b.textContent = (ev.pontos > 0 ? "+" : "") + ev.pontos;
      li.append(document.createTextNode(ev.t.toLocaleString("pt-BR", { minimumFractionDigits: 1 }) + " s · " + ev.texto + " "), b);
      return li;
    }));
  }
}

/* ---------- controles ---------- */

function relativo(tela, e) {
  const r = tela.getBoundingClientRect();
  return { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height };
}

function ligarControles(tela) {
  const img = $(".tela-video", tela);
  let arrasto = null, timer = null, dono = null;
  let acum = { az: 0, el: 0, zoom: 1 };

  const enviar = () => {
    timer = null;
    const p = {};
    if (acum.az || acum.el) p.orbita = [acum.az, acum.el];
    if (acum.zoom !== 1) p.zoom = acum.zoom;
    acum = { az: 0, el: 0, zoom: 1 };
    if (Object.keys(p).length) mandarMuJoCo(p).catch(() => {});
  };
  const agendar = () => { timer ??= setTimeout(enviar, MJ_PASSO_ENVIO); };

  img.addEventListener("pointerdown", async e => {
    if (e.button !== 0) return;
    img.setPointerCapture(e.pointerId);
    arrasto = { x: e.clientX, y: e.clientY, moveu: false };
    dono = "decidindo";
    // O editor pode reivindicar o clique (selecionar, colocar, mover).
    let tomou = false;
    if (tela.editor) {
      try { tomou = await tela.editor.pointerdown(relativo(tela, e), e); }
      catch (err) { console.error("editor:", err); tomou = false; }
    }
    if (!arrasto) return;                 // soltou antes da resposta
    dono = tomou ? "editor" : "orbita";
    if (dono === "orbita") tela.classList.add("arrastando");
  });
  img.addEventListener("pointermove", e => {
    if (!arrasto) return;
    if (dono === "editor") { tela.editor.pointermove(relativo(tela, e), e); return; }
    if (dono !== "orbita") return;
    if (Math.abs(e.clientX - arrasto.x) + Math.abs(e.clientY - arrasto.y) > 2) arrasto.moveu = true;
    acum.az -= (e.clientX - arrasto.x) * MJ_GIRO;
    acum.el -= (e.clientY - arrasto.y) * MJ_INCLINA;
    arrasto = { ...arrasto, x: e.clientX, y: e.clientY };
    agendar();
  });
  const soltar = e => {
    if (dono === "editor") tela.editor.pointerup(relativo(tela, e), e);
    arrasto = null; dono = null;
    tela.classList.remove("arrastando");
  };
  img.addEventListener("pointerup", soltar);
  img.addEventListener("pointercancel", soltar);
  img.addEventListener("wheel", e => {
    e.preventDefault();
    acum.zoom *= e.deltaY > 0 ? MJ_ZOOM : 1 / MJ_ZOOM;
    agendar();
  }, { passive: false });
  img.addEventListener("dblclick", () => mandarMuJoCo({ recentrar: true }).catch(() => {}));

  const pedidos = { recentrar: { recentrar: true }, camera: { camera: "proxima" }, reiniciar: { reiniciar: true } };
  for (const b of $$("[data-cmd]", tela)) {
    b.addEventListener("click", () => mandarMuJoCo(pedidos[b.dataset.cmd])
      .catch(err => avisar("MuJoCo: " + err.message, true)));
  }
  for (const b of $$("[data-modo]", tela)) {
    b.addEventListener("click", () => mandarMuJoCo({ modo: b.dataset.modo })
      .then(e => avisar(e.modo === "testar" ? "Teste iniciado." : "Modo de edição."))
      .catch(err => avisar("MuJoCo: " + err.message, true)));
  }

  let espera = null;
  new ResizeObserver(() => {
    clearTimeout(espera);
    espera = setTimeout(() => {
      if ("medida" in tela.dataset && mudouMuito(tela)) { pararVideo(tela); sincronizarVideo(); }
    }, 400);
  }).observe(tela);
}

function montarTelas() {
  const molde = $("#tpl-tela");
  for (const tela of $$("[data-tela]")) {
    tela.append(molde.content.cloneNode(true));
    ligarControles(tela);
    pintarTela(tela);
  }
  document.addEventListener("visibilitychange", sincronizarVideo);
}
