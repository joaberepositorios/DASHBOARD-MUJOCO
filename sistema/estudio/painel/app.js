"use strict";

const VISTAS = {
  painel: "Painel", importar: "Importar", cenario: "Cenário", programacao: "Programação",
  treino: "Treino", simulacoes: "Simulações", modelos: "Modelos",
};
const INICIAL = "painel";

const MODELOS = [{ id: "go2", nome: "Unitree Go2", meta: "Quadrúpede · 12 juntas" }];
const ROTULOS = {
  base: { chao: "Chão livre", bancada: "Bancada" },
  comeca: { parado: "Parado", frente: "Frente", girando: "Girando" },
};

const PAUSA_ESTADO_TELA = 1000;
const PAUSA_ESTADO = 5000;

const $  = (sel, raiz = document) => raiz.querySelector(sel);
const $$ = (sel, raiz = document) => [...raiz.querySelectorAll(sel)];

function el(tag, attrs = {}, ...filhos) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else n.setAttribute(k, v);
  }
  for (const f of filhos) n.append(f);
  return n;
}

function icone(nome, classe = "ic") {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("class", classe);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(ns, "use");
  use.setAttribute("href", "#" + nome);
  svg.append(use);
  return svg;
}

function desenhoRobo() {
  const svg = icone("robo", "");
  svg.setAttribute("viewBox", "84 60 196 110");
  const use = svg.firstChild;
  use.setAttribute("width", "320");
  use.setAttribute("height", "190");
  return svg;
}

/* ---------- barra de estado ---------- */

const registro = [];

function avisar(texto, erro = false) {
  const hora = new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  registro.push({ hora, texto, erro });
  if (registro.length > 200) registro.shift();
  const msg = $("#barra-msg");
  msg.textContent = texto;
  msg.classList.toggle("erro", erro);
  const log = $("#barra-log");
  if (!log.hidden) renderLog();
}

function renderLog() {
  $("#barra-log").replaceChildren(...registro.slice().reverse().map(r =>
    el("div", { class: r.erro ? "erro" : "" }, el("time", { text: r.hora }), el("span", { text: r.texto }))));
}

function ligarBarra() {
  const b = $("#barra-log-btn"), log = $("#barra-log");
  b.addEventListener("click", () => {
    log.hidden = !log.hidden;
    b.setAttribute("aria-expanded", String(!log.hidden));
    if (!log.hidden) renderLog();
  });
  document.addEventListener("click", e => {
    if (!log.hidden && !e.target.closest("#barra-estado")) { log.hidden = true; b.setAttribute("aria-expanded", "false"); }
  });
}

/* ---------- lateral recolhivel ---------- */

const LARGURA_TRILHO = 900;
const LARGURA_CELULAR = 640;

function preferenciaLateral() {
  try { return localStorage.getItem("lateral"); } catch { return null; }
}

function aplicarLateral(recolhida) {
  $(".casca").classList.toggle("recolhida", recolhida);
  const b = $("#alternar-lateral");
  b.setAttribute("aria-expanded", String(!recolhida));
  b.setAttribute("aria-label", recolhida ? "Expandir o menu" : "Recolher o menu");
  b.title = b.getAttribute("aria-label");
}

function ajustarLateral() {
  if (innerWidth <= LARGURA_CELULAR) { aplicarLateral(false); return; }
  const pref = preferenciaLateral();
  aplicarLateral(pref ? pref === "recolhida" : innerWidth <= LARGURA_TRILHO);
}

function ligarLateral() {
  $("#alternar-lateral").addEventListener("click", () => {
    const recolher = !$(".casca").classList.contains("recolhida");
    try { localStorage.setItem("lateral", recolher ? "recolhida" : "aberta"); } catch {}
    aplicarLateral(recolher);
  });
  addEventListener("resize", ajustarLateral);
  ajustarLateral();
}

/* ---------- rotas ---------- */

function vistaDoEndereco() {
  const id = location.hash.replace(/^#\/?/, "");
  return Object.hasOwn(VISTAS, id) ? id : INICIAL;
}

function corrigirEndereco() {
  const id = vistaDoEndereco();
  if (location.hash !== "#/" + id) history.replaceState(null, "", "#/" + id);
}

function mostrar(focar) {
  corrigirEndereco();
  const id = vistaDoEndereco();
  for (const s of $$("section[data-vista]")) s.hidden = s.dataset.vista !== id;
  for (const a of $$(".lateral a[data-ir]")) {
    if (a.dataset.ir === id) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  document.title = VISTAS[id] + " · Estúdio Go2";
  sincronizarVideo();
  if (id === "simulacoes" || id === "painel") renderSimulacoes();
  if (id === "programacao") programaMostrou();
  if (id === "treino") treinoMostrou();
  if (focar) {
    window.scrollTo(0, 0);
    $(`section[data-vista="${id}"] h1`).focus({ preventScroll: true });
  }
}

function irPara(id, depois) {
  if (vistaDoEndereco() === id) { depois?.(); return; }
  addEventListener("hashchange", () => depois?.(), { once: true });
  location.hash = "#/" + id;
}

/* ---------- estado do servidor ---------- */

function pintarEstado(servidorNoAr, versao, mundo) {
  $("#ponto-servidor").className = "ponto " + (servidorNoAr ? "vivo" : "alerta");
  $("#txt-servidor").textContent = servidorNoAr ? "Servidor no ar" : "Servidor fora do ar";
  let ponto = "", texto;
  if (!servidorNoAr)      texto = "MuJoCo: sem resposta";
  else if (!versao)       { ponto = "alerta"; texto = "MuJoCo não instalado"; }
  else if (mundo?.erro)   { ponto = "alerta"; texto = "MuJoCo " + versao + " com erro"; }
  else if (mundo?.pronto) { ponto = "vivo"; texto = "MuJoCo " + versao; }
  else                    texto = "MuJoCo " + versao + " ligando";
  $("#ponto-mujoco").className = "ponto " + ponto;
  $("#txt-mujoco").textContent = texto;
  $("#txt-servidor").parentElement.title = $("#txt-servidor").textContent;
  $("#txt-mujoco").parentElement.title = texto;
}

let editorCarregado = false;

async function lerEstado() {
  try {
    const r = await fetch("/api/estado", { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const e = await r.json();
    pintarEstado(true, e.mujoco, e.mundo);
    pintarMundo(e.mundo, e.mujoco);
    if (e.mundo?.pronto && !editorCarregado) {
      editorCarregado = true;
      editorCarregarAtual().catch(err => { editorCarregado = false; avisar("Editor: " + err.message, true); });
    }
  } catch {
    pintarEstado(false, null, null);
    pintarMundo(null, mjVersao);
  }
  setTimeout(lerEstado, algumaTelaVisivel() ? PAUSA_ESTADO_TELA : PAUSA_ESTADO);
}

/* ---------- nova simulacao (painel) ---------- */

const form = $("#criar");

function lerForm() {
  const d = new FormData(form);
  return { nome: (d.get("nome") || "").trim(), base: d.get("base"), comeca: d.get("comeca"), acoes: d.getAll("acoes") };
}

function atualizarPrevia() {
  $(".previa").dataset.base = lerForm().base;
}

async function criar(ev) {
  ev.preventDefault();
  const f = lerForm();
  if (!f.nome) { $("#nome").focus(); avisar("Dê um nome à simulação.", true); return; }
  if (sujo() && !confirm("O cenário aberto tem mudanças não salvas. Descartar?")) return;
  try {
    const cen = await pedirJson("/api/simulacoes", "POST", f);
    abrirNoEditor(cen, true);
    form.elements.nome.value = "";
    avisar(`Criada: ${cen.nome}`);
    renderSimulacoes();
    irPara("cenario");
  } catch (err) {
    avisar("Não criei: " + err.message, true);
  }
}

/* ---------- galerias ---------- */

function cartaoNovo(texto, aoClicar) {
  const b = el("button", { class: "cartao novo", type: "button" }, el("span", { class: "cartao-tit", text: texto }));
  b.addEventListener("click", aoClicar);
  return b;
}

function novaSimulacao() {
  irPara("painel", () => { const c = $("#nome"); c.scrollIntoView({ block: "center" }); c.focus({ preventScroll: true }); });
}

function cartaoSimulacao(s) {
  const img = el("div", { class: "cartao-img" });
  if (s.miniatura) img.append(el("img", { src: `/api/simulacoes/${s.id}/miniatura.jpg?t=${Math.round(s.modificado)}`, alt: "" }));
  else img.append(desenhoRobo());
  const meta = `${ROTULOS.base[s.base]} · ${s.objetos} obj · ${s.zonas} zonas · ${s.regras} regras`;
  const abrir = el("button", { class: "cartao-abrir", type: "button", "aria-label": `Abrir ${s.nome} no editor` }, img,
    el("div", { class: "cartao-corpo" }, el("span", { class: "cartao-tit", text: s.nome, title: s.nome }), el("span", { class: "cartao-meta", text: meta })));
  abrir.addEventListener("click", async () => { if (await abrirSimulacao(s.id)) irPara("cenario"); });
  const testar = el("button", { class: "cmd pequeno", type: "button", text: "Testar", title: "Abrir e testar no Painel" });
  testar.addEventListener("click", async e => {
    e.stopPropagation();
    if (!(await abrirSimulacao(s.id))) return;
    if (s.base === "chao") mandarMuJoCo({ modo: "testar" }).catch(() => {});
    irPara("painel");
  });
  const apagar = el("button", { class: "cmd pequeno icone perigo", type: "button", title: "Apagar", "aria-label": `Apagar ${s.nome}` });
  apagar.innerHTML = '<svg class="ic"><use href="#i-lixo"/></svg>';
  apagar.addEventListener("click", async e => {
    e.stopPropagation();
    if (!confirm(`Apagar "${s.nome}"? Não dá para desfazer.`)) return;
    try { await pedirJson("/api/simulacoes/" + s.id, "DELETE"); avisar(`Apagada: ${s.nome}`); renderSimulacoes(); }
    catch (err) { avisar("Não apaguei: " + err.message, true); }
  });
  return el("article", { class: "cartao abrivel" }, abrir, el("div", { class: "cartao-acoes" }, testar, apagar));
}

async function renderSimulacoes() {
  let lista = [];
  try { lista = await pedirJson("/api/simulacoes", "GET"); } catch { /* servidor fora */ }
  $("#sims-painel").replaceChildren(...lista.slice(0, 3).map(cartaoSimulacao),
    cartaoNovo(lista.length ? "Nova" : "Nenhuma ainda", novaSimulacao));
  $("#sims-todas").replaceChildren(cartaoNovo("Nova simulação", novaSimulacao), ...lista.map(cartaoSimulacao));
}

function cartaoModelo(m) {
  const img = el("div", { class: "cartao-img" }, desenhoRobo(), el("span", { class: "selo", text: "Padrão" }));
  return el("article", { class: "cartao" }, img,
    el("div", { class: "cartao-corpo" }, el("span", { class: "cartao-tit", text: m.nome }), el("span", { class: "cartao-meta", text: m.meta })));
}

function renderModelos() {
  $("#modelos-painel").replaceChildren(...MODELOS.map(cartaoModelo));
  $("#modelos-todos").replaceChildren(...MODELOS.map(cartaoModelo));
  $("#modelo").replaceChildren(...MODELOS.map(m => el("option", { value: m.id, text: m.nome })));
}

/* ---------- importar ---------- */

async function importarSimulacao(arq, info) {
  try {
    const cen = JSON.parse(await arq.text());
    const r = await pedirJson("/api/simulacoes/importar", "POST", cen);
    info.textContent = `Importada como "${r.nome}".`;
    avisar(`Importada: ${r.nome}`);
    renderSimulacoes();
  } catch (err) {
    info.textContent = "Não importei: " + err.message;
    avisar("Importar: " + err.message, true);
  }
}

async function importarTextura(arq, info) {
  const zip = /\.zip$/i.test(arq.name);
  const tipo = zip ? "application/zip" : (arq.type === "image/jpeg" || arq.type === "image/png" ? arq.type : null);
  if (!tipo) { info.textContent = `"${arq.name}" não é PNG, JPEG nem .zip.`; return; }
  info.textContent = `Lendo "${arq.name}"…`;
  const nome = arq.name.replace(/\.[^.]+$/, "").replace(/_\d+K-(JPG|PNG)$/i, "");
  try {
    const r = await fetch("/api/materiais?nome=" + encodeURIComponent(nome), { method: "POST", headers: { "Content-Type": tipo }, body: arq });
    const dado = await r.json();
    if (!r.ok) throw new Error(dado.erro || "HTTP " + r.status);
    info.textContent = `"${dado.nome}" entrou na paleta de materiais.`;
    avisar(`Textura: ${dado.nome}`);
    await editorCarregarMateriais();
    if (ED.cen) renderInspetor();
  } catch (err) {
    info.textContent = "Não importei: " + err.message;
    avisar("Textura: " + err.message, true);
  }
}

async function buscarTexturas(ev) {
  ev.preventDefault();
  const termo = $("#busca-termo").value.trim();
  const caixa = $("#busca-achados");
  if (!termo) return;
  caixa.replaceChildren(el("p", { class: "vazio", text: "Buscando…" }));
  try {
    const achados = await pedirJson("/api/materiais/buscar?q=" + encodeURIComponent(termo), "GET");
    if (!achados.length) { caixa.replaceChildren(el("p", { class: "vazio", text: "Nada com esse nome. Tente em inglês: wood, bricks, grass, metal." })); return; }
    caixa.replaceChildren(...achados.map(a => {
      const b = el("button", { class: "cmd pequeno", type: "button", text: "Baixar", title: a.tags.join(", ") });
      b.addEventListener("click", async () => {
        b.disabled = true; b.textContent = "Baixando…";
        try {
          const m = await pedirJson("/api/materiais/baixar", "POST", { fonte: a.fonte });
          b.textContent = "Na paleta";
          avisar(`Textura baixada: ${m.nome}`);
          await editorCarregarMateriais();
          if (ED.cen) renderInspetor();
        } catch (err) { b.disabled = false; b.textContent = "Baixar"; avisar("Textura: " + err.message, true); }
      });
      const img = el("img", { src: a.miniatura, alt: "" });
      const link = el("a", { href: a.pagina, target: "_blank", rel: "noopener", class: "nome", text: a.nome, title: "Abrir no ambientCG" });
      return el("div", { class: "achado" }, img, link, b);
    }));
  } catch (err) {
    caixa.replaceChildren(el("p", { class: "vazio", text: "Não consegui buscar: " + err.message }));
  }
}

function ligarImportar() {
  $("#busca-textura").addEventListener("submit", buscarTexturas);
  for (const zona of $$("[data-soltar]")) {
    const tipo = zona.dataset.soltar;
    const entrada = $("input", zona);
    const info = $("[data-info]", zona.parentElement);
    const tratar = arquivos => {
      for (const arq of arquivos) {
        if (tipo === "simulacao") importarSimulacao(arq, info);
        else if (tipo === "textura") importarTextura(arq, info);
      }
    };
    entrada.addEventListener("change", () => tratar(entrada.files));
    for (const ev of ["dragenter", "dragover"]) zona.addEventListener(ev, e => { e.preventDefault(); if (!entrada.disabled) zona.classList.add("sobre"); });
    for (const ev of ["dragleave", "drop"]) zona.addEventListener(ev, () => zona.classList.remove("sobre"));
    zona.addEventListener("drop", e => { e.preventDefault(); if (!entrada.disabled) tratar(e.dataTransfer.files); });
  }
}

/* ---------- partida ---------- */

async function iniciar() {
  ligarBarra();
  ligarLateral();
  montarTelas();
  renderModelos();
  ligarImportar();
  form.addEventListener("input", atualizarPrevia);
  form.addEventListener("submit", criar);
  atualizarPrevia();
  await editorIniciar();
  programaIniciar();
  treinoIniciar();
  addEventListener("hashchange", () => mostrar(true));
  mostrar(false);
  lerEstado();
}

iniciar();
