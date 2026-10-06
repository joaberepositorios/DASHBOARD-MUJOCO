"use strict";

// Programacao: um editor de Python na pagina. O servidor roda o codigo
// (programa.py) e esta pagina so' manda, pergunta e mostra a saida.
// Usa $, $$, el, avisar (app.js) e pedirJson (mujoco.js).

const PR_SONDA_MS = 250;          // enquanto roda, pergunta a saida nesse passo
const PR_RASCUNHO = "programa-rascunho";
const PR_INDENTA = "    ";

const PR = {
  nome: "", aberto: null,         // aberto = nome do arquivo em disco que esta' no editor
  salvo: "", lista: [], exemplo: "",
  desde: 0, timer: null, rodando: false, linha: 0, linhaErro: 0,
  timerRascunho: null,
};

const prCodigo = () => $("#pr-codigo");
const prSecao = () => $("section[data-vista=programacao]");
const prSujo = () => prCodigo().value !== PR.salvo;

/* ---------- editor de texto ---------- */

function prInserir(ta, texto) {
  // execCommand mantem o desfazer nativo do navegador; se nao der, troca na mao
  ta.focus();
  if (!document.execCommand || !document.execCommand("insertText", false, texto)) {
    ta.setRangeText(texto, ta.selectionStart, ta.selectionEnd, "end");
    ta.dispatchEvent(new Event("input", { bubbles: true }));
  }
}

function prTeclasCodigo(e) {
  const ta = e.currentTarget, v = ta.value;
  if (e.key === "Tab") {
    e.preventDefault();
    let [a, b] = [ta.selectionStart, ta.selectionEnd];
    if (a === b && !e.shiftKey) { prInserir(ta, PR_INDENTA); return; }
    if (b > a && v[b - 1] === "\n") b -= 1;             // selecao acabou no fim da linha
    const ini = v.lastIndexOf("\n", a - 1) + 1;
    let fim = v.indexOf("\n", b); if (fim < 0) fim = v.length;
    const novas = v.slice(ini, fim).split("\n").map(l => e.shiftKey ? l.replace(/^ {1,4}/, "") : PR_INDENTA + l).join("\n");
    ta.setSelectionRange(ini, fim);
    prInserir(ta, novas);
    ta.setSelectionRange(ini, ini + novas.length);
    return;
  }
  if (e.key === "Enter" && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
    e.preventDefault();
    const a = ta.selectionStart;
    const linha = v.slice(v.lastIndexOf("\n", a - 1) + 1, a);
    let ind = (linha.match(/^ */) || [""])[0];
    if (/:\s*$/.test(linha)) ind += PR_INDENTA;
    prInserir(ta, "\n" + ind);
  }
}

function prRenderNumeros() {
  const ta = prCodigo(), g = $("#pr-numeros");
  const n = ta.value.split("\n").length;
  if (g.childElementCount !== n) g.replaceChildren(...Array.from({ length: n }, (_, i) => el("span", { text: String(i + 1) })));
  let i = 0;
  for (const s of g.children) {
    i += 1;
    s.className = PR.rodando && i === PR.linha ? "atual" : !PR.rodando && i === PR.linhaErro ? "erro" : "";
  }
  g.scrollTop = ta.scrollTop;
}

function prRenderTopo() {
  $("#pr-sujo").hidden = !prSujo();
  $("#pr-apagar").disabled = !PR.aberto;
  for (const b of $$("#pr-lista button")) b.setAttribute("aria-pressed", String(b.dataset.nome === PR.aberto));
}

/* ---------- rascunho no navegador ---------- */

function prGuardarRascunho() {
  clearTimeout(PR.timerRascunho);
  PR.timerRascunho = setTimeout(() => {
    try { localStorage.setItem(PR_RASCUNHO, JSON.stringify({ nome: PR.nome, aberto: PR.aberto, codigo: prCodigo().value })); } catch {}
  }, 300);
}

function prLerRascunho() {
  try { return JSON.parse(localStorage.getItem(PR_RASCUNHO) || "null"); } catch { return null; }
}

/* ---------- programas gravados ---------- */

function prColocar(nome, aberto, codigo, salvo) {
  PR.nome = nome; PR.aberto = aberto; PR.salvo = salvo;
  $("#pr-nome").value = nome;
  prCodigo().value = codigo;
  PR.linhaErro = 0;
  prRenderNumeros();
  prRenderTopo();
  prGuardarRascunho();
}

async function prCarregarLista() {
  try { PR.lista = await pedirJson("/api/programas", "GET"); } catch { PR.lista = []; }
  const caixa = $("#pr-lista");
  caixa.replaceChildren(...PR.lista.map(p => {
    const b = el("button", { class: "item-prog", type: "button", title: p.nome, "data-nome": p.nome },
      el("span", { class: "nome", text: p.nome }), el("span", { class: "meta", text: p.linhas + " l" }));
    b.addEventListener("click", () => prAbrir(p.nome));
    return b;
  }));
  if (!PR.lista.length) caixa.append(el("p", { class: "insp-vazio", text: "Nenhum gravado." }));
  prRenderTopo();
}

async function prAbrir(nome) {
  if (prSujo() && !confirm("O programa no editor tem mudanças não salvas. Descartar?")) return;
  try {
    const p = await pedirJson("/api/programas/" + encodeURIComponent(nome), "GET");
    prColocar(p.nome, p.nome, p.codigo, p.codigo);
    avisar(`Aberto: ${p.nome}.py`);
  } catch (err) {
    avisar("Não abri: " + err.message, true);
  }
}

function prNovo() {
  if (prSujo() && !confirm("O programa no editor tem mudanças não salvas. Descartar?")) return;
  prColocar("", null, "", "");
  $("#pr-nome").focus();
}

async function prSalvar() {
  const nome = $("#pr-nome").value.trim();
  if (!nome) { $("#pr-nome").focus(); avisar("Dê um nome ao programa.", true); return; }
  const outro = PR.lista.find(p => p.nome.toLowerCase() === nome.toLowerCase() && p.nome !== PR.aberto);
  if (outro && !confirm(`Já existe "${outro.nome}.py". Substituir?`)) return;
  try {
    const r = await pedirJson("/api/programas/" + encodeURIComponent(nome), "PUT", { codigo: prCodigo().value });
    PR.nome = r.nome; PR.aberto = r.nome; PR.salvo = prCodigo().value;
    $("#pr-nome").value = r.nome;
    avisar(`Salvo: ${r.nome}.py`);
    prGuardarRascunho();
    await prCarregarLista();
  } catch (err) {
    avisar("Não salvei: " + err.message, true);
  }
}

async function prApagar() {
  if (!PR.aberto || !confirm(`Apagar "${PR.aberto}.py"? Não dá para desfazer.`)) return;
  try {
    await pedirJson("/api/programas/" + encodeURIComponent(PR.aberto), "DELETE");
    avisar(`Apagado: ${PR.aberto}.py`);
    PR.aberto = null; PR.salvo = prCodigo().value;   // o texto continua no editor
    prGuardarRascunho();
    await prCarregarLista();
  } catch (err) {
    avisar("Não apaguei: " + err.message, true);
  }
}

/* ---------- executar ---------- */

function prFormatar(t) {
  return t.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

function prLimparSaida() {
  $("#pr-saida").replaceChildren();
  PR.desde = 0;
}

function prAplicarEstado(est) {
  if (est.total < PR.desde) prLimparSaida();     // outro programa comecou (noutra aba)
  PR.rodando = est.rodando;
  PR.linha = est.linha;
  PR.linhaErro = est.fim === "erro" ? est.linha_erro : 0;

  const caixa = $("#pr-saida");
  if (est.saida.length) {
    const noFim = caixa.scrollHeight - caixa.scrollTop - caixa.clientHeight < 24;
    for (const [n, t, tipo, texto] of est.saida) {
      caixa.append(el("div", { class: "l-" + tipo }, el("time", { text: prFormatar(t) + " s" }), el("span", { text: texto })));
      PR.desde = n;
    }
    while (caixa.childElementCount > 2000) caixa.firstChild.remove();
    if (noFim) caixa.scrollTop = caixa.scrollHeight;
  }

  const s = $("#pr-estado");
  let txt = "", cls = "";
  if (est.rodando) { txt = `rodando · linha ${est.linha} · ${prFormatar(est.duracao)} s`; cls = "rodando"; }
  else if (est.fim === "pronto") txt = `terminou em ${prFormatar(est.duracao)} s`;
  else if (est.fim === "erro") { txt = "erro" + (est.linha_erro ? " na linha " + est.linha_erro : ""); cls = "erro"; }
  else if (est.fim === "interrompido") txt = "interrompido";
  s.textContent = txt;
  s.className = "saida-estado " + cls;

  $("#pr-executar").disabled = est.rodando;
  $("#pr-parar").disabled = !est.rodando;
  $(".codigo").classList.toggle("rodando", est.rodando);
  prRenderNumeros();
}

async function prSondar() {
  PR.timer = null;
  let est;
  try { est = await pedirJson("/api/programa?desde=" + PR.desde, "GET"); }
  catch { return; }
  prAplicarEstado(est);
  if (est.rodando && !prSecao().hidden) prAgendar();
}

function prAgendar() {
  if (!PR.timer) PR.timer = setTimeout(prSondar, PR_SONDA_MS);
}

async function prExecutar() {
  const codigo = prCodigo().value;
  if (!codigo.trim()) { prCodigo().focus(); avisar("O programa está vazio.", true); return; }
  try {
    const est = await pedirJson("/api/programa", "POST", { codigo, nome: $("#pr-nome").value.trim() });
    prLimparSaida();
    prAplicarEstado(est);
    prAgendar();
    avisar("Programa iniciado.");
  } catch (err) {
    avisar("Programa: " + err.message, true);
  }
}

async function prParar() {
  try {
    const est = await pedirJson("/api/programa", "DELETE");
    prAplicarEstado(est);
    prAgendar();
    avisar("Parar pedido.");
  } catch (err) {
    avisar("Programa: " + err.message, true);
  }
}

/* ---------- referencia ---------- */

async function prCarregarReferencia() {
  try {
    const r = await pedirJson("/api/programa/referencia", "GET");
    PR.exemplo = r.exemplo;
    $("#pr-referencia").replaceChildren(...r.funcoes.map(f => {
      const b = el("button", { type: "button", title: "Inserir no código" },
        el("code", { text: f.assinatura }), el("span", { text: f.texto }));
      b.addEventListener("click", () => prInserir(prCodigo(), f.assinatura));
      return b;
    }));
  } catch (err) {
    $("#pr-referencia").replaceChildren(el("p", { class: "insp-vazio", text: "Sem referência: " + err.message }));
  }
}

/* ---------- partida ---------- */

function programaMostrou() {
  prCarregarLista();
  prSondar();
}

function prTeclas(e) {
  if (prSecao().hidden) return;
  const ctrl = e.ctrlKey || e.metaKey;
  if (ctrl && e.key === "Enter") { e.preventDefault(); if (!$("#pr-executar").disabled) prExecutar(); }
  else if (ctrl && e.key.toLowerCase() === "s") { e.preventDefault(); prSalvar(); }
}

async function programaIniciar() {
  const ta = prCodigo(), nome = $("#pr-nome");
  ta.addEventListener("keydown", prTeclasCodigo);
  ta.addEventListener("input", () => { prRenderNumeros(); prRenderTopo(); prGuardarRascunho(); });
  ta.addEventListener("scroll", () => { $("#pr-numeros").scrollTop = ta.scrollTop; });
  nome.addEventListener("input", () => { PR.nome = nome.value; prGuardarRascunho(); });
  $("#pr-novo").addEventListener("click", prNovo);
  $("#pr-salvar").addEventListener("click", prSalvar);
  $("#pr-apagar").addEventListener("click", prApagar);
  $("#pr-executar").addEventListener("click", prExecutar);
  $("#pr-parar").addEventListener("click", prParar);
  $("#pr-limpar").addEventListener("click", prLimparSaida);
  addEventListener("keydown", prTeclas);
  addEventListener("beforeunload", e => { if (prSujo()) e.preventDefault(); });
  mjOuvintes.push(estado => {
    if (estado?.programa?.rodando && !PR.timer && !prSecao().hidden) prAgendar();
  });

  await prCarregarReferencia();
  const r = prLerRascunho();
  if (r && typeof r.codigo === "string") {
    let salvo = r.codigo;
    if (r.aberto) {
      try { salvo = (await pedirJson("/api/programas/" + encodeURIComponent(r.aberto), "GET")).codigo; }
      catch { r.aberto = null; }
    }
    prColocar(r.nome || "", r.aberto || null, r.codigo, salvo);
  } else {
    prColocar("", null, PR.exemplo, PR.exemplo);
  }
}
