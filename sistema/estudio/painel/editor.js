"use strict";

// Editor de cenario: objetos, zonas e regras. O cenario vive aqui como um
// objeto JSON; cada mudanca vai para o servidor (PUT /api/cenario), que
// ajusta o MuJoCo ao vivo ou recompila quando entra/sai um objeto.
// Usa $, $$, el, avisar (app.js) e pedirJson, mandarMuJoCo (mujoco.js).

const ED_APLICAR_MS = 120;
const ED_ARRASTO_MS = 50;
const ED_HISTORICO = 60;
const ED_PASSO = 0.05;

// medidas: rotulos das tres medidas (null = nao se edita)
const TIPOS_OBJ = {
  caixa:    { nome: "Caixa",    tam: [0.40, 0.40, 0.20], medidas: ["Comprimento", "Largura", "Altura"] },
  rampa:    { nome: "Rampa",    tam: [1.20, 0.80, 0.25], medidas: ["Comprimento", "Largura", "Altura"] },
  cilindro: { nome: "Cilindro", tam: [0.30, 0.30, 0.15], medidas: ["Diâmetro", null, "Altura"] },
  esfera:   { nome: "Esfera",   tam: [0.20, 0.20, 0.20], medidas: ["Diâmetro", null, null], fixo: false },
  barra:    { nome: "Barra",    tam: [0.06, 0.80, 0.12], medidas: ["Diâmetro", "Comprimento", "Altura do chão"] },
  escada:   { nome: "Escada",   tam: [0.90, 0.80, 0.30], medidas: ["Comprimento", "Largura", "Altura"], degraus: 3 },
  parede:   { nome: "Parede",   tam: [1.50, 0.06, 0.50], medidas: ["Comprimento", "Espessura", "Altura"] },
  relevo:   { nome: "Relevo",   tam: [2.00, 2.00, 0.08], medidas: ["Comprimento", "Largura", "Altura máx."], rugosidade: 0.5, semente: 1, sempreFixo: true },
};
const FORMAS = {
  caixa: '<rect x="2" y="5" width="12" height="9"/>',
  rampa: '<path d="M2 14h12V4z"/>',
  cilindro: '<ellipse cx="8" cy="4" rx="5" ry="2"/><path d="M3 4v8a5 2 0 0 0 10 0V4"/>',
  esfera: '<circle cx="8" cy="8" r="6"/>',
  barra: '<path d="M2 7h12M4 7v7M12 7v7"/>',
  escada: '<path d="M2 14h4v-4h4V6h4"/>',
  parede: '<rect x="2" y="3" width="12" height="11"/><path d="M2 8h12M8 3v5M5 8v6M11 8v6"/>',
  relevo: '<path d="M2 12c2-3 3-5 5-3s3 4 5 1 2-4 2-4"/>',
};
const TIPOS_ZONA = {
  partida:    { nome: "Partida",    cor: "#4d8cf2" },
  checkpoint: { nome: "Checkpoint", cor: "#f2a626" },
  chegada:    { nome: "Chegada",    cor: "#33b359" },
  proibida:   { nome: "Proibida",   cor: "#db2626" },
};
const QUANDOS = {
  entrar_zona: "entrar na zona", sair_zona: "sair da zona", tocar_objeto: "tocar o objeto",
  cair: "cair", tempo: "passar de (s)", pontos: "chegar a (pontos)",
};
const FINS = { "": "continua", sucesso: "termina: sucesso", falha: "termina: falha" };

const ED = {
  cen: null, emDisco: false, salvo: "",
  sel: null, ferramenta: null, materiais: [],
  historico: [], futuro: [], aba: "item",
  timerAplicar: null, aplicando: null,
  antes: null,           // foto do cenario antes de editar um campo
};

const clonar = o => JSON.parse(JSON.stringify(o));
const num = (v, casas = 2) => Number(v).toLocaleString("pt-BR", { maximumFractionDigits: casas });

/* ---------- servidor ---------- */

function aplicar(agora) {
  clearTimeout(ED.timerAplicar);
  const mandar = () => {
    ED.timerAplicar = null;
    if (ED.aplicando) { ED.timerAplicar = setTimeout(mandar, ED_APLICAR_MS); return; }
    ED.aplicando = pedirJson("/api/cenario", "PUT", ED.cen)
      .then(r => { if (r.reconstruido) avisar("Cena remontada."); })
      .catch(err => avisar("Cenário: " + err.message, true))
      .finally(() => { ED.aplicando = null; });
  };
  if (agora) mandar(); else ED.timerAplicar = setTimeout(mandar, ED_APLICAR_MS);
}

async function editorCarregarAtual() {
  const cen = await pedirJson("/api/cenario", "GET");
  const lista = await pedirJson("/api/simulacoes", "GET").catch(() => []);
  abrirNoEditor(cen, lista.some(s => s.id === cen.id));
}

function abrirNoEditor(cen, emDisco) {
  ED.cen = cen;
  ED.emDisco = emDisco;
  ED.salvo = JSON.stringify(cen);   // sujo = mudou desde que abriu, esteja ou nao em disco
  ED.sel = null; ED.ferramenta = null;
  ED.historico = []; ED.futuro = [];
  renderTudo();
}

async function editorSalvar() {
  if (!ED.cen) return;
  ED.cen.nome = ED.cen.nome.trim() || "Sem nome";
  try {
    const r = await pedirJson("/api/simulacoes/" + ED.cen.id + (ED.emDisco ? "" : "?novo=1"), "PUT", ED.cen);
    if (ED.cen.id !== r.id) { ED.cen.id = r.id; aplicar(true); }   // o mundo passa a conhecer o id novo
    ED.emDisco = true;
    ED.salvo = JSON.stringify(ED.cen);
    avisar(`Salvo: ${ED.cen.nome}` + (r.miniatura ? "" : " (sem miniatura: a tela não estava aberta)"));
    renderTopo();
    if (typeof renderSimulacoes === "function") renderSimulacoes();
  } catch (err) {
    avisar("Não salvou: " + err.message, true);
  }
}

async function editorNovo() {
  if (sujo() && !confirm("O cenário atual tem mudanças não salvas. Descartar?")) return;
  try {
    const cen = await pedirJson("/api/simulacoes", "POST", { nome: "Nova simulação" });
    abrirNoEditor(cen, true);
    avisar("Nova simulação criada.");
  } catch (err) {
    avisar("Não criei: " + err.message, true);
  }
}

async function abrirSimulacao(id) {
  if (sujo() && !confirm("O cenário atual tem mudanças não salvas. Descartar?")) return false;
  try {
    const cen = await pedirJson("/api/simulacoes/" + id + "/abrir", "POST", {});
    abrirNoEditor(cen, true);
    avisar(`Aberta: ${cen.nome}`);
    return true;
  } catch (err) {
    avisar("Não abriu: " + err.message, true);
    return false;
  }
}

function sujo() { return ED.cen && JSON.stringify(ED.cen) !== ED.salvo; }

/* ---------- historico ---------- */

function lembrar() {
  ED.historico.push(JSON.stringify(ED.cen));
  if (ED.historico.length > ED_HISTORICO) ED.historico.shift();
  ED.futuro = [];
}

function mudar(fn, agora) {
  lembrar();
  fn();
  renderTudo();
  aplicar(agora);
}

function desfazer() {
  if (!ED.historico.length) return;
  ED.futuro.push(JSON.stringify(ED.cen));
  ED.cen = JSON.parse(ED.historico.pop());
  conferirSelecao(); renderTudo(); aplicar(true);
}

function refazer() {
  if (!ED.futuro.length) return;
  ED.historico.push(JSON.stringify(ED.cen));
  ED.cen = JSON.parse(ED.futuro.pop());
  conferirSelecao(); renderTudo(); aplicar(true);
}

function conferirSelecao() {
  if (ED.sel && !itemSelecionado()) ED.sel = null;
}

// Campos do inspetor: a foto e' tirada quando o campo ganha foco e entra no
// historico quando o valor termina de mudar (change), uma vez por edicao.
function comecarEdicao() { ED.antes ??= JSON.stringify(ED.cen); }
function terminarEdicao() {
  if (ED.antes && ED.antes !== JSON.stringify(ED.cen)) {
    ED.historico.push(ED.antes);
    if (ED.historico.length > ED_HISTORICO) ED.historico.shift();
    ED.futuro = [];
  }
  ED.antes = null;
  renderTopo();
}

/* ---------- itens ---------- */

function itemSelecionado() {
  if (!ED.sel) return null;
  const lista = ED.sel.tipo === "objeto" ? ED.cen.objetos : ED.cen.zonas;
  return lista.find(i => i.id === ED.sel.id) || null;
}

function idLivre(base) {
  const usados = new Set([...ED.cen.objetos, ...ED.cen.zonas].map(i => i.id));
  let n = 1;
  while (usados.has(`${base}-${n}`)) n++;
  return `${base}-${n}`;
}

function nomeLivre(base) {
  const usados = new Set([...ED.cen.objetos, ...ED.cen.zonas].map(i => i.nome));
  if (!usados.has(base)) return base;
  let n = 2;
  while (usados.has(`${base} ${n}`)) n++;
  return `${base} ${n}`;
}

function novoObjeto(subtipo, pos) {
  const t = TIPOS_OBJ[subtipo];
  const o = {
    id: idLivre(subtipo), tipo: subtipo, nome: nomeLivre(t.nome),
    pos: [arred(pos[0]), arred(pos[1]), arred(pos[2] || 0)], giro: 0, tam: [...t.tam],
    material: subtipo === "relevo" ? "terra" : "concreto",
    fixo: t.fixo ?? true, massa: 2, atrito: 0.8, elasticidade: 0.05,
  };
  if (subtipo === "escada") o.degraus = t.degraus;
  if (subtipo === "relevo") { o.rugosidade = t.rugosidade; o.semente = Math.floor(Math.random() * 1000); }
  return o;
}

function novaZona(subtipo, pos) {
  const t = TIPOS_ZONA[subtipo];
  return { id: idLivre(subtipo), tipo: subtipo, nome: nomeLivre(t.nome),
           pos: [arred(pos[0]), arred(pos[1])], tam: [0.6, 0.6], giro: 0 };
}

function arred(v) { return Math.round(v * 100) / 100; }

function selecionar(tipo, id) {
  ED.sel = id ? { tipo, id } : null;
  ED.aba = "item";
  renderInspetor(); renderAbas();
}

function removerSelecionado() {
  const it = itemSelecionado();
  if (!it) return;
  mudar(() => {
    if (ED.sel.tipo === "objeto") ED.cen.objetos = ED.cen.objetos.filter(o => o.id !== it.id);
    else ED.cen.zonas = ED.cen.zonas.filter(z => z.id !== it.id);
    ED.cen.regras = ED.cen.regras.filter(r => r.alvo !== it.id);
    ED.sel = null;
  }, true);
  avisar(`Removido: ${it.nome}`);
}

function duplicarSelecionado() {
  const it = itemSelecionado();
  if (!it) return;
  mudar(() => {
    const c = clonar(it);
    c.id = idLivre(c.tipo); c.nome = nomeLivre(it.nome.replace(/ \d+$/, ""));
    c.pos[0] = arred(c.pos[0] + 0.3);
    if (ED.sel.tipo === "objeto") ED.cen.objetos.push(c); else ED.cen.zonas.push(c);
    ED.sel = { tipo: ED.sel.tipo, id: c.id };
  }, true);
}

function empurrar(dx, dy) {
  const it = itemSelecionado();
  if (!it) return;
  mudar(() => { it.pos[0] = arred(it.pos[0] + dx); it.pos[1] = arred(it.pos[1] + dy); });
}

/* ---------- ponteiro sobre o video ---------- */

function editorPonteiro(tela) {
  let arrasto = null;         // {item, tipo, dx, dy, ocupado, pendente}
  const apontar = rel => pedirJson("/api/cenario/apontar", "POST", rel);

  const pointerdown = async rel => {
    if (!ED.cen || mjEstado?.modo !== "editar") return false;
    let hit;
    try { hit = await apontar(rel); } catch { return false; }
    if (ED.ferramenta) {
      const f = ED.ferramenta;
      const base = hit.objeto && f.tipo === "objeto" && hit.ponto ? hit.ponto : hit.chao;
      if (!base) { avisar("Clique sobre o chão.", true); return true; }
      mudar(() => {
        if (f.tipo === "objeto") {
          const o = novoObjeto(f.subtipo, [base[0], base[1], hit.objeto ? base[2] : 0]);
          ED.cen.objetos.push(o); ED.sel = { tipo: "objeto", id: o.id };
        } else {
          const z = novaZona(f.subtipo, base);
          ED.cen.zonas.push(z); ED.sel = { tipo: "zona", id: z.id };
        }
        ED.ferramenta = null;
      }, true);
      return true;
    }
    const tipo = hit.objeto ? "objeto" : hit.zona ? "zona" : null;
    if (!tipo) { if (ED.sel) selecionar(null); return false; }
    selecionar(tipo, hit.objeto || hit.zona);
    const it = itemSelecionado();
    const p = hit.chao || [it.pos[0], it.pos[1]];
    arrasto = { it, dx: p[0] - it.pos[0], dy: p[1] - it.pos[1], ocupado: false, pendente: null, moveu: false };
    tela.classList.add("movendo");
    return true;
  };

  const mover = async rel => {
    if (!arrasto) return;
    if (arrasto.ocupado) { arrasto.pendente = rel; return; }
    arrasto.ocupado = true;
    try {
      const hit = await apontar(rel);
      if (arrasto && hit.chao) {
        if (!arrasto.moveu) { lembrar(); arrasto.moveu = true; }
        arrasto.it.pos[0] = arred(hit.chao[0] - arrasto.dx);
        arrasto.it.pos[1] = arred(hit.chao[1] - arrasto.dy);
        renderInspetor(); aplicar(true);
      }
    } catch { /* deixa passar */ }
    if (!arrasto) return;
    arrasto.ocupado = false;
    if (arrasto.pendente) { const p = arrasto.pendente; arrasto.pendente = null; setTimeout(() => mover(p), ED_ARRASTO_MS); }
  };

  const pointerup = () => {
    if (arrasto?.moveu) renderTopo();
    arrasto = null;
    tela.classList.remove("movendo");
  };

  tela.editor = { pointerdown, pointermove: mover, pointerup };
}

/* ---------- desenho ---------- */

function renderTudo() { renderTopo(); renderPaleta(); renderAbas(); renderInspetor(); }

function renderTopo() {
  if (!ED.cen) return;
  const nome = $("#ed-nome");
  if (document.activeElement !== nome) nome.value = ED.cen.nome;
  $("#ed-base").textContent = ED.cen.base === "bancada" ? "bancada" : "chão livre";
  $("#ed-sujo").hidden = !sujo();
  $("#ed-desfazer").disabled = !ED.historico.length;
  $("#ed-refazer").disabled = !ED.futuro.length;
  const nomePainel = $("#painel-cenario-nome");
  if (nomePainel) nomePainel.textContent = ED.cen.nome;
  for (const t of $$("[data-tela]")) t.classList.toggle("colocando", Boolean(ED.ferramenta));
  const dica = $("#paleta-dica");
  if (dica) dica.textContent = ED.ferramenta
    ? `Clique no chão para colocar ${ED.ferramenta.tipo === "objeto" ? TIPOS_OBJ[ED.ferramenta.subtipo].nome : TIPOS_ZONA[ED.ferramenta.subtipo].nome}. Esc cancela.`
    : "Escolha um item e clique no chão para colocar. Clique num objeto para selecionar; arraste para mover.";
}

function renderPaleta() {
  const objetos = $("#paleta-objetos"), zonas = $("#paleta-zonas");
  if (!objetos.childElementCount) {
    for (const [k, t] of Object.entries(TIPOS_OBJ)) {
      const b = el("button", { type: "button", "data-ferr": "objeto:" + k, "aria-pressed": "false" });
      b.innerHTML = `<svg class="forma" viewBox="0 0 16 16">${FORMAS[k]}</svg>`;
      b.append(document.createTextNode(t.nome));
      b.addEventListener("click", () => armar("objeto", k));
      objetos.append(b);
    }
    for (const [k, t] of Object.entries(TIPOS_ZONA)) {
      const b = el("button", { type: "button", "data-ferr": "zona:" + k, "aria-pressed": "false" },
        el("span", { class: "cor", style: "background:" + t.cor }), t.nome);
      b.addEventListener("click", () => armar("zona", k));
      zonas.append(b);
    }
  }
  for (const b of $$("[data-ferr]")) {
    const [tipo, sub] = b.dataset.ferr.split(":");
    b.setAttribute("aria-pressed", String(ED.ferramenta?.tipo === tipo && ED.ferramenta?.subtipo === sub));
  }
}

function armar(tipo, subtipo) {
  const mesma = ED.ferramenta?.tipo === tipo && ED.ferramenta?.subtipo === subtipo;
  ED.ferramenta = mesma ? null : { tipo, subtipo };
  if (ED.ferramenta && mjEstado?.modo === "testar") mandarMuJoCo({ modo: "editar" }).catch(() => {});
  renderPaleta(); renderTopo();
}

function renderAbas() {
  for (const b of $$("[data-aba]")) b.setAttribute("aria-selected", String(b.dataset.aba === ED.aba));
  for (const c of $$("[data-aba-corpo]")) c.hidden = c.dataset.abaCorpo !== ED.aba;
}

function campoNumero(valor, aoMudar, opts = {}) {
  const i = el("input", { type: "number", step: opts.passo ?? "0.01", value: String(valor) });
  if (opts.min !== undefined) i.min = String(opts.min);
  if (opts.max !== undefined) i.max = String(opts.max);
  i.addEventListener("focus", comecarEdicao);
  i.addEventListener("input", () => { const v = parseFloat(i.value); if (Number.isFinite(v)) { aoMudar(v); aplicar(); } });
  i.addEventListener("change", terminarEdicao);
  return i;
}

function linha(rotulo, ...conteudo) {
  return el("div", { class: "linha" }, el("span", { text: rotulo }), ...conteudo);
}

function gradeMateriais(atual, aoEscolher) {
  const g = el("div", { class: "materiais" });
  for (const m of ED.materiais) {
    const amostra = m.textura
      ? el("img", { src: `/api/materiais/${m.id}/miniatura.png`, alt: "" })
      : el("div", { class: "lisa", style: `background: rgb(${m.cor.map(c => Math.round(c * 255)).join(",")})` });
    const b = el("button", { type: "button", "aria-pressed": String(m.id === atual),
                             title: m.nome + (m.fonte ? ` (${m.fonte}, ambientCG)` : "") + (m.textura ? "" : " — sem textura, cor lisa") },
      amostra, el("span", { text: m.nome }));
    b.addEventListener("click", () => { mudar(() => aoEscolher(m.id)); });
    g.append(b);
  }
  return g;
}

function renderInspetor() {
  const caixa = $("#insp-item");
  caixa.replaceChildren();
  const it = itemSelecionado();
  if (!it) {
    caixa.append(el("p", { class: "insp-vazio", text: "Nada selecionado. Clique num objeto ou zona no vídeo." }));
    renderRegras(); renderGeral();
    return;
  }
  const ehObj = ED.sel.tipo === "objeto";
  const tipo = ehObj ? TIPOS_OBJ[it.tipo] : TIPOS_ZONA[it.tipo];

  const tit = el("div", { class: "insp-tit" });
  const nome = el("input", { type: "text", value: it.nome, maxlength: "60", "aria-label": "Nome" });
  nome.addEventListener("focus", comecarEdicao);
  nome.addEventListener("input", () => { it.nome = nome.value; aplicar(); });
  nome.addEventListener("change", terminarEdicao);
  tit.append(nome);
  caixa.append(tit, el("div", { class: "insp-tit" }, el("span", { class: "tipo", text: tipo.nome }), el("span", { class: "espaco" }),
    botaoPequeno("i-copiar", "Duplicar (Ctrl+D)", duplicarSelecionado),
    botaoPequeno("i-lixo", "Remover (Delete)", removerSelecionado, "perigo")));

  // posicao e giro
  const pos = el("div", { class: ehObj ? "tres-n" : "dois-n" },
    campoNumero(it.pos[0], v => { it.pos[0] = v; }),
    campoNumero(it.pos[1], v => { it.pos[1] = v; }));
  if (ehObj) pos.append(campoNumero(it.pos[2], v => { it.pos[2] = v; }, { min: 0 }));
  caixa.append(linha(ehObj ? "Posição x y z" : "Posição x y", pos));
  caixa.append(linha("Giro (°)", campoNumero(it.giro, v => { it.giro = v; }, { passo: "1", min: -360, max: 360 })));

  // medidas
  if (ehObj) {
    const meds = el("div", { class: "tres-n" });
    tipo.medidas.forEach((rot, i) => {
      if (!rot) return;
      const c = campoNumero(it.tam[i], v => {
        it.tam[i] = v;
        if (it.tipo === "esfera") it.tam = [v, v, v];
        if (it.tipo === "cilindro") it.tam[1] = v;
      }, { min: 0.02 });
      c.title = rot;
      meds.append(c);
    });
    caixa.append(linha("Medidas (m)", meds));
    caixa.append(el("div", { class: "unidade", text: tipo.medidas.filter(Boolean).join(" · ") }));
    if (it.tipo === "escada") caixa.append(linha("Degraus", campoNumero(it.degraus, v => { it.degraus = Math.max(1, Math.min(12, Math.round(v))); }, { passo: "1", min: 1, max: 12 })));
    if (it.tipo === "relevo") {
      caixa.append(linha("Rugosidade", campoNumero(it.rugosidade, v => { it.rugosidade = Math.max(0, Math.min(1, v)); }, { passo: "0.05", min: 0, max: 1 })));
      caixa.append(linha("Semente", campoNumero(it.semente, v => { it.semente = Math.round(v); }, { passo: "1", min: 0, max: 9999 })));
    }
    caixa.append(el("h3", { text: "Material" }), gradeMateriais(it.material, id => { it.material = id; }));
    caixa.append(el("h3", { text: "Física" }));
    if (!tipo.sempreFixo) {
      const fixo = el("input", { type: "checkbox" }); fixo.checked = it.fixo;
      fixo.addEventListener("change", () => mudar(() => { it.fixo = fixo.checked; }, true));
      caixa.append(linha("", el("label", { class: "marca-simples" }, fixo, "Fixo no lugar")));
      if (!it.fixo) caixa.append(linha("Massa (kg)", campoNumero(it.massa, v => { it.massa = v; }, { min: 0.01, max: 200 })));
    }
    caixa.append(linha("Atrito", campoNumero(it.atrito, v => { it.atrito = v; }, { passo: "0.05", min: 0, max: 3 })));
    caixa.append(linha("Elasticidade", campoNumero(it.elasticidade, v => { it.elasticidade = v; }, { passo: "0.05", min: 0, max: 1 })));
  } else {
    const meds = el("div", { class: "dois-n" },
      campoNumero(it.tam[0], v => { it.tam[0] = v; }, { min: 0.1 }),
      campoNumero(it.tam[1], v => { it.tam[1] = v; }, { min: 0.1 }));
    caixa.append(linha("Medidas (m)", meds));
    const sel = el("select");
    for (const [k, z] of Object.entries(TIPOS_ZONA)) sel.append(el("option", { value: k, text: z.nome }));
    sel.value = it.tipo;
    sel.addEventListener("change", () => mudar(() => { it.tipo = sel.value; }, true));
    caixa.append(linha("Tipo", sel));
    const sug = sugestoesPara(it);
    if (sug.length && !ED.cen.regras.some(r => r.alvo === it.id)) {
      const b = el("button", { class: "cmd pequeno", type: "button", text: "Criar regra sugerida" });
      b.addEventListener("click", () => mudar(() => { for (const r of sug) ED.cen.regras.push({ id: idRegra(), uma_vez: true, valor: 0, ...r }); ED.aba = "regras"; }));
      caixa.append(el("div", { class: "sugestao" }, descreverSugestao(sug[0]), b));
    }
  }
  renderRegras(); renderGeral();
}

function botaoPequeno(icone, titulo, fn, extra = "") {
  const b = el("button", { class: "cmd pequeno icone " + extra, type: "button", title: titulo, "aria-label": titulo });
  b.innerHTML = `<svg class="ic"><use href="#${icone}"/></svg>`;
  b.addEventListener("click", fn);
  return b;
}

function sugestoesPara(z) {
  if (z.tipo === "checkpoint") return [{ quando: "entrar_zona", alvo: z.id, pontos: 50, fim: null }];
  if (z.tipo === "chegada") return [{ quando: "entrar_zona", alvo: z.id, pontos: 100, fim: "sucesso" }];
  if (z.tipo === "proibida") return [{ quando: "entrar_zona", alvo: z.id, pontos: -100, fim: "falha" }];
  return [];
}

function descreverSugestao(r) {
  const fim = r.fim ? (r.fim === "sucesso" ? ", termina com sucesso" : ", termina em falha") : "";
  return `Sugestão: ao entrar, ${r.pontos > 0 ? "+" : ""}${r.pontos} pontos${fim}.`;
}

function idRegra() {
  const usados = new Set(ED.cen.regras.map(r => r.id));
  let n = 1;
  while (usados.has("r" + n)) n++;
  return "r" + n;
}

function renderRegras() {
  const caixa = $("#insp-regras");
  caixa.replaceChildren();
  const lista = el("div", { class: "regras" });
  if (!ED.cen.regras.length) lista.append(el("p", { class: "insp-vazio", text: "Sem regras. Sem elas o teste só corre o tempo." }));
  for (const r of ED.cen.regras) lista.append(cartaoRegra(r));
  const add = el("button", { class: "cmd", type: "button", text: "+ Regra" });
  add.addEventListener("click", () => mudar(() => {
    const z = ED.cen.zonas.find(z => z.tipo !== "partida");
    ED.cen.regras.push({ id: idRegra(), quando: z ? "entrar_zona" : "cair", alvo: z ? z.id : null, valor: 0, pontos: z ? 50 : -100, fim: null, uma_vez: true });
  }));
  caixa.append(lista, add);
}

function cartaoRegra(r) {
  const c = el("div", { class: "regra" });
  const l1 = el("div", { class: "regra-linha" }, "Quando ");
  const quando = el("select");
  for (const [k, t] of Object.entries(QUANDOS)) quando.append(el("option", { value: k, text: t }));
  quando.value = r.quando;
  quando.addEventListener("change", () => mudar(() => {
    r.quando = quando.value;
    if (["entrar_zona", "sair_zona"].includes(r.quando)) r.alvo = ED.cen.zonas[0]?.id ?? null;
    else if (r.quando === "tocar_objeto") r.alvo = ED.cen.objetos[0]?.id ?? null;
    else r.alvo = null;
  }));
  l1.append(quando);
  if (["entrar_zona", "sair_zona", "tocar_objeto"].includes(r.quando)) {
    const alvo = el("select");
    const fonte = r.quando === "tocar_objeto" ? ED.cen.objetos : ED.cen.zonas;
    for (const i of fonte) alvo.append(el("option", { value: i.id, text: i.nome }));
    alvo.value = r.alvo ?? "";
    alvo.addEventListener("change", () => mudar(() => { r.alvo = alvo.value; }));
    l1.append(alvo);
    if (!fonte.length) l1.append(el("span", { class: "unidade", text: r.quando === "tocar_objeto" ? "(sem objetos)" : "(sem zonas)" }));
  }
  if (["tempo", "pontos"].includes(r.quando)) {
    l1.append(campoNumero(r.valor, v => { r.valor = v; }, { passo: r.quando === "tempo" ? "1" : "10", min: 0 }));
  }
  const l2 = el("div", { class: "regra-linha" }, "então ");
  const pontos = campoNumero(r.pontos, v => { r.pontos = v; }, { passo: "10" });
  l2.append(pontos, "pontos, ");
  const fim = el("select");
  for (const [k, t] of Object.entries(FINS)) fim.append(el("option", { value: k, text: t }));
  fim.value = r.fim ?? "";
  fim.addEventListener("change", () => mudar(() => { r.fim = fim.value || null; }));
  l2.append(fim);
  const uma = el("input", { type: "checkbox" }); uma.checked = r.uma_vez;
  uma.addEventListener("change", () => mudar(() => { r.uma_vez = uma.checked; }));
  l2.append(el("label", { class: "marca-simples" }, uma, "uma vez"));
  const apagar = botaoPequeno("i-lixo", "Apagar regra", () => mudar(() => { ED.cen.regras = ED.cen.regras.filter(x => x !== r); }), "perigo apagar");
  l2.append(apagar);
  c.append(l1, l2);
  return c;
}

function renderGeral() {
  const caixa = $("#insp-geral");
  caixa.replaceChildren();
  const c = ED.cen;

  const base = el("div", { class: "segmento" });
  for (const [k, t] of [["chao", "Chão livre"], ["bancada", "Bancada"]]) {
    const i = el("input", { type: "radio", name: "ed-base", value: k }); i.checked = c.base === k;
    i.addEventListener("change", () => mudar(() => { c.base = k; }, true));
    base.append(el("label", {}, i, el("span", { text: t })));
  }
  caixa.append(linha("Base", base));

  const comeca = el("div", { class: "segmento" });
  for (const [k, t] of [["parado", "Parado"], ["frente", "Frente"], ["girando", "Girando"]]) {
    const i = el("input", { type: "radio", name: "ed-comeca", value: k }); i.checked = c.comeca === k;
    i.addEventListener("change", () => mudar(() => { c.comeca = k; }));
    comeca.append(el("label", {}, i, el("span", { text: t })));
  }
  caixa.append(linha("Começa", comeca));

  const acoes = el("div", { class: "marcas" });
  for (const [k, t] of Object.entries({ andar: "Andar", girar: "Girar", sentar: "Sentar", deitar: "Deitar", reconhecer: "Reconhecer" })) {
    const i = el("input", { type: "checkbox" }); i.checked = c.acoes.includes(k);
    i.addEventListener("change", () => mudar(() => { c.acoes = i.checked ? [...c.acoes, k] : c.acoes.filter(a => a !== k); }));
    acoes.append(el("label", {}, i, t));
  }
  caixa.append(el("h3", { text: "Ações liberadas" }), acoes);
  caixa.append(el("h3", { text: "Chão" }), gradeMateriais(c.chao.material, id => { c.chao.material = id; }));
  const resumo = el("p", { class: "insp-vazio", text: `${c.objetos.length} objeto(s) · ${c.zonas.length} zona(s) · ${c.regras.length} regra(s) · id ${c.id}` });
  caixa.append(resumo);
}

/* ---------- partida ---------- */

async function editorCarregarMateriais() {
  try { ED.materiais = await pedirJson("/api/materiais", "GET"); }
  catch { ED.materiais = []; }
}

function teclas(e) {
  const secao = $("section[data-vista=cenario]");
  if (!ED.cen || secao.hidden) return;
  const noCampo = /^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement?.tagName);
  const ctrl = e.ctrlKey || e.metaKey;
  if (ctrl && e.key.toLowerCase() === "s") { e.preventDefault(); editorSalvar(); return; }
  if (ctrl && e.key.toLowerCase() === "z") { if (!noCampo) { e.preventDefault(); desfazer(); } return; }
  if (ctrl && e.key.toLowerCase() === "y") { if (!noCampo) { e.preventDefault(); refazer(); } return; }
  if (noCampo) return;
  if (e.key === "Escape") { if (ED.ferramenta) { ED.ferramenta = null; renderPaleta(); renderTopo(); } else selecionar(null); }
  else if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); removerSelecionado(); }
  else if (ctrl && e.key.toLowerCase() === "d") { e.preventDefault(); duplicarSelecionado(); }
  else if (e.key.toLowerCase() === "r" && itemSelecionado()) { mudar(() => { const it = itemSelecionado(); it.giro = (it.giro + (e.shiftKey ? -15 : 15)) % 360; }); }
  else if (e.key.startsWith("Arrow") && itemSelecionado()) {
    e.preventDefault();
    const p = e.shiftKey ? ED_PASSO * 5 : ED_PASSO;
    empurrar(e.key === "ArrowRight" ? p : e.key === "ArrowLeft" ? -p : 0,
             e.key === "ArrowUp" ? p : e.key === "ArrowDown" ? -p : 0);
  }
}

async function editorIniciar() {
  const nome = $("#ed-nome");
  nome.addEventListener("focus", comecarEdicao);
  nome.addEventListener("input", () => { if (ED.cen) { ED.cen.nome = nome.value; aplicar(); renderTopo(); } });
  nome.addEventListener("change", terminarEdicao);
  $("#ed-salvar").addEventListener("click", editorSalvar);
  $("#ed-novo").addEventListener("click", editorNovo);
  $("#ed-desfazer").addEventListener("click", desfazer);
  $("#ed-refazer").addEventListener("click", refazer);
  for (const b of $$("[data-aba]")) b.addEventListener("click", () => { ED.aba = b.dataset.aba; renderAbas(); });
  for (const tela of $$("[data-tela][data-editor]")) editorPonteiro(tela);
  addEventListener("keydown", teclas);
  addEventListener("beforeunload", e => { if (sujo()) e.preventDefault(); });
  mjOuvintes.push(estado => {
    // se outro lugar trocou o cenario (outra aba), recarrega o daqui
    if (estado?.pronto && ED.cen && estado.cenario && estado.cenario.id !== ED.cen.id && !ED.aplicando && !ED.timerAplicar) {
      editorCarregarAtual().catch(() => {});
    }
  });
  await editorCarregarMateriais();
}
