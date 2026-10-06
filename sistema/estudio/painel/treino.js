"use strict";

// Treino por tentativa: define (cenario aberto + programa + variaveis +
// orcamento), acompanha as tentativas e lida com o campeao. O servidor
// (treino.py) faz o trabalho; aqui so' formulario, lista e andamento.
// Usa $, $$, el, avisar (app.js), pedirJson, mjEstado (mujoco.js), formatarTempo.

const TR_SONDA_MS = 500;

const TR = { variaveis: [], programas: [], paramsProg: [], aberto: null, timer: null, lista: [] };

const trSecao = () => $("section[data-vista=treino]");
const trNum = (v, casas = 3) => Number(v).toLocaleString("pt-BR", { maximumFractionDigits: casas });

/* ---------- formulario ---------- */

async function trCarregarBases() {
  try {
    const [vars, progs] = await Promise.all([pedirJson("/api/treino/variaveis", "GET"), pedirJson("/api/programas", "GET")]);
    TR.variaveis = vars; TR.programas = progs;
  } catch (err) { avisar("Treino: " + err.message, true); return; }
  const sel = $("#tr-programa"), atual = sel.value;
  sel.replaceChildren(el("option", { value: "", text: "(nenhum: só o Começa do cenário)" }),
    ...TR.programas.map(p => el("option", { value: p.nome, text: p.nome })));
  if (TR.programas.some(p => p.nome === atual)) sel.value = atual;
  trRenderVariaveis();
  trCarregarParamsProg();
}

function trRenderVariaveis() {
  $("#tr-variaveis").replaceChildren(...TR.variaveis.map(v => {
    const cx = el("input", { type: "checkbox", "data-var": v.id });
    const mn = el("input", { type: "number", step: "any", value: String(v.min), "data-min": v.id, "aria-label": "mínimo" });
    const mx = el("input", { type: "number", step: "any", value: String(v.max), "data-max": v.id, "aria-label": "máximo" });
    return el("div", { class: "tr-var" },
      el("label", {}, cx, el("span", { text: v.nome }), el("span", { class: "unidade", text: ` ${trNum(v.padrao)}${v.unidade ? " " + v.unidade : ""}` })),
      el("span", { class: "tr-faixa" }, mn, el("span", { class: "unidade", text: "a" }), mx));
  }));
}

async function trCarregarParamsProg() {
  const nome = $("#tr-programa").value;
  const caixa = $("#tr-params-prog");
  if (!nome) { TR.paramsProg = []; caixa.replaceChildren(el("p", { class: "insp-vazio", text: "Sem programa, o robô só faz o Começa do cenário; varie ajustes do controlador." })); return; }
  try { TR.paramsProg = await pedirJson("/api/programas/" + encodeURIComponent(nome) + "/parametros", "GET"); }
  catch (err) { TR.paramsProg = []; caixa.replaceChildren(el("p", { class: "insp-vazio", text: "Não li o programa: " + err.message })); return; }
  if (!TR.paramsProg.length) {
    caixa.replaceChildren(el("p", { class: "insp-vazio", text: "Este programa não declara treino.parametro(...); só os ajustes do controlador vão variar." }));
    return;
  }
  caixa.replaceChildren(...TR.paramsProg.map(p => el("div", { class: "tr-var fixa" },
    el("span", { text: p.nome }),
    el("span", { class: "unidade", text: `${trNum(p.padrao)} · ${p.min == null ? "faixa automática" : trNum(p.min) + " a " + trNum(p.max)} · linha ${p.linha}` }))));
}

function trLerForm() {
  const variaveis = [];
  for (const cx of $$("#tr-variaveis input[data-var]:checked")) {
    const id = cx.dataset.var;
    variaveis.push({ id, min: Number($(`#tr-variaveis input[data-min="${id}"]`).value), max: Number($(`#tr-variaveis input[data-max="${id}"]`).value) });
  }
  return {
    nome: $("#tr-nome").value.trim(), programa: $("#tr-programa").value || null,
    tentativas: Number($("#tr-tentativas").value), tempo_max: Number($("#tr-tempo").value),
    velocidade: Number($("#tr-velocidade").value), semente: Number($("#tr-semente").value) || 1, variaveis,
  };
}

async function trIniciar() {
  const f = trLerForm();
  if (!f.nome) { $("#tr-nome").focus(); avisar("Dê um nome ao treino.", true); return; }
  if (!f.variaveis.length && !TR.paramsProg.length) { avisar("Escolha ao menos uma variável.", true); return; }
  try {
    const e = await pedirJson("/api/treino", "POST", f);
    TR.aberto = e.treino.id;
    trAplicarEstado(e);
    trAgendar();
    avisar(`Treino iniciado: ${e.treino.nome}.`);
    trCarregarLista();
  } catch (err) {
    avisar("Treino: " + err.message, true);
  }
}

async function trParar() {
  try { trAplicarEstado(await pedirJson("/api/treino", "DELETE")); trAgendar(); avisar("Parar pedido."); }
  catch (err) { avisar("Treino: " + err.message, true); }
}

/* ---------- andamento ---------- */

function trValores(vals) {
  return Object.entries(vals || {}).map(([k, v]) => `${k.replace(/^prog\./, "")}=${trNum(v)}`).join("  ");
}

function trRenderTreino(t, est) {
  const caixa = $("#tr-andamento");
  if (!t) { caixa.hidden = true; $("#tr-apagar").disabled = true; return; }
  caixa.hidden = false;
  $("#tr-tit").textContent = t.nome;
  $("#tr-meta").textContent = `${t.cenario.nome} · ${t.programa ? "programa " + t.programa : "sem programa"} · ${t.velocidade}× · até ${trNum(t.tempo_max, 0)} s por tentativa`;
  const rodando = est?.rodando && est.fase === "treino";
  let linha;
  if (rodando) linha = `tentativa ${est.tentativa} de ${t.tentativas} · ${trValores(est.valores_atuais)}`;
  else if (est?.rodando && est.fase === "campeao") linha = `mostrando o campeão (tentativa ${est.tentativa}) a 1×`;
  else if (t.estado === "concluido") linha = `concluído: ${t.resultados.length} tentativas`;
  else if (t.estado === "erro") linha = "parou com erro: " + (est?.erro || "");
  else linha = `parado em ${t.resultados.length} de ${t.tentativas}`;
  $("#tr-linha").textContent = linha;
  $("#tr-linha").classList.toggle("erro", t.estado === "erro");

  const m = t.melhor != null ? t.resultados[t.melhor] : null;
  $("#tr-melhor").textContent = m ? `tentativa ${m.n} · ${m.pontos} pts · ${m.fim || "sem fim"} · ${trNum(m.tempo, 1)} s · ${m.quedas} quedas` : "ainda sem tentativa concluída";
  $("#tr-melhor-vals").textContent = m ? trValores(m.valores) : "";
  $("#tr-campeao").disabled = !m || Boolean(est?.rodando);
  $("#tr-campeao-prog").disabled = !m || !t.programa;
  $("#tr-campeao-usar").disabled = !m || !Object.keys(m.valores).some(k => !k.startsWith("prog."));
  $("#tr-iniciar").disabled = Boolean(est?.rodando);
  $("#tr-parar").disabled = !est?.rodando;
  $("#tr-apagar").disabled = !TR.aberto || Boolean(est?.rodando);

  const maxp = Math.max(1, ...t.resultados.map(r => Math.abs(r.pontos)));
  $("#tr-tabela tbody").replaceChildren(...t.resultados.slice().reverse().map(r => {
    const barra = el("div", { class: "tr-barra" }, el("div", { class: r.pontos < 0 ? "neg" : "", style: "width:" + Math.round(Math.abs(r.pontos) / maxp * 100) + "%" }));
    return el("tr", { class: t.melhor != null && r.n === t.melhor + 1 ? "melhor" : "" },
      el("td", { text: String(r.n) }), el("td", { class: "n", text: String(r.pontos) }), el("td", {}, barra),
      el("td", { text: r.fim || "—" }), el("td", { class: "n", text: trNum(r.tempo, 1) }), el("td", { class: "n", text: String(r.quedas) }),
      el("td", { class: "vals", text: trValores(r.valores), title: r.motivo + (r.programa_fim ? " · programa " + r.programa_fim : "") }));
  }));
  $("#tr-vazio").hidden = t.resultados.length > 0;
}

function trAplicarEstado(est) {
  const t = est.treino;
  if (t && (TR.aberto === null || TR.aberto === t.id || est.rodando)) { TR.aberto = t.id; trRenderTreino(t, est); }
  else if (!t) trRenderTreino(null, est);
  for (const b of $$("#tr-lista button")) b.setAttribute("aria-pressed", String(b.dataset.id === TR.aberto));
  $("#tr-iniciar").disabled = Boolean(est.rodando);
  $("#tr-parar").disabled = !est.rodando;
  if (est.erro && !est.rodando) avisar("Treino: " + est.erro, true);
}

async function trSondar() {
  TR.timer = null;
  let est;
  try { est = await pedirJson("/api/treino", "GET"); } catch { return; }
  trAplicarEstado(est);
  if (est.rodando && !trSecao().hidden) trAgendar();
  else if (!est.rodando) trCarregarLista();
}

function trAgendar() { if (!TR.timer) TR.timer = setTimeout(trSondar, TR_SONDA_MS); }

/* ---------- gravados ---------- */

let trListaSeq = 0;

async function trCarregarLista() {
  const seq = ++trListaSeq;
  let lista;
  try { lista = await pedirJson("/api/treinos", "GET"); } catch { lista = []; }
  if (seq !== trListaSeq) return;        // chegou outra mais nova; esta esta' velha
  TR.lista = lista;
  const caixa = $("#tr-lista");
  caixa.replaceChildren(...TR.lista.map(t => {
    const b = el("button", { class: "item-prog", type: "button", "data-id": t.id, "aria-pressed": String(t.id === TR.aberto), title: `${t.cenario}${t.programa ? " · " + t.programa : ""}` },
      el("span", { class: "nome", text: t.nome }),
      el("span", { class: "meta", text: `${t.feitas}/${t.tentativas}${t.melhor_pontos != null ? " · " + t.melhor_pontos + " pts" : ""}` }));
    b.addEventListener("click", () => trAbrir(t.id));
    return b;
  }));
  if (!TR.lista.length) caixa.append(el("p", { class: "insp-vazio", text: "Nenhum gravado." }));
}

async function trAbrir(id) {
  try {
    const t = await pedirJson("/api/treinos/" + id, "GET");
    TR.aberto = id;
    const est = await pedirJson("/api/treino", "GET").catch(() => null);
    trRenderTreino(t, est?.treino?.id === id ? est : null);
    for (const b of $$("#tr-lista button")) b.setAttribute("aria-pressed", String(b.dataset.id === id));
  } catch (err) { avisar("Treino: " + err.message, true); }
}

async function trApagar() {
  const t = TR.lista.find(x => x.id === TR.aberto);
  if (!t || !confirm(`Apagar o treino "${t.nome}"? Não dá para desfazer.`)) return;
  try {
    await pedirJson("/api/treinos/" + t.id, "DELETE");
    TR.aberto = null; trRenderTreino(null, null);
    avisar(`Apagado: ${t.nome}`); trCarregarLista();
  } catch (err) { avisar("Não apaguei: " + err.message, true); }
}

async function trCampeao(acao) {
  if (!TR.aberto) return;
  try {
    if (acao === "ver") { trAplicarEstado(await pedirJson("/api/treino/campeao", "POST", { id: TR.aberto })); trAgendar(); avisar("Mostrando o campeão a 1×."); }
    else if (acao === "programa") { const r = await pedirJson("/api/treino/campeao/programa", "POST", { id: TR.aberto }); avisar(`Programa gravado: ${r.nome}.py (abra em Programação).`); if (typeof prCarregarLista === "function") prCarregarLista(); }
    else if (acao === "usar") { const v = await pedirJson("/api/treino/campeao/usar", "POST", { id: TR.aberto }); avisar("Ajustes aplicados até reiniciar o estúdio: " + trValores(v)); }
  } catch (err) { avisar("Campeão: " + err.message, true); }
}

/* ---------- partida ---------- */

function treinoMostrou() {
  $("#tr-cenario").textContent = mjEstado?.cenario?.nome || "—";
  trCarregarBases();
  trCarregarLista();
  trSondar();
}

function treinoIniciar() {
  $("#tr-programa").addEventListener("change", trCarregarParamsProg);
  $("#tr-iniciar").addEventListener("click", trIniciar);
  $("#tr-parar").addEventListener("click", trParar);
  $("#tr-apagar").addEventListener("click", trApagar);
  $("#tr-campeao").addEventListener("click", () => trCampeao("ver"));
  $("#tr-campeao-prog").addEventListener("click", () => trCampeao("programa"));
  $("#tr-campeao-usar").addEventListener("click", () => trCampeao("usar"));
  mjOuvintes.push(estado => {
    if (trSecao().hidden) return;
    $("#tr-cenario").textContent = estado?.cenario?.nome || "—";
  });
}
