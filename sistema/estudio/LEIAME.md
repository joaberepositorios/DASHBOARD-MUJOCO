# Estúdio do Go2

Monte um cenário, ponha o Go2 nele, defina as regras do que vale ponto,
programe o robô em Python, treine por tentativa e veja tudo acontecer no
MuJoCo dentro da página. Mais adiante: chat com IA.

```
python estudio.py            # abre http://localhost:8791/
python estudio.py --aberto   # libera para outras máquinas da rede
```

O servidor é só biblioteca padrão do Python. Se o Smart App Control do
Windows bloquear um plugin do MuJoCo (aconteceu com o `sdf_plugin.dll`), o
estúdio avisa e segue sem ele. A simulação precisa de
`pip install mujoco` (que traz o numpy) e de Pillow ou OpenCV para comprimir
os quadros e converter texturas. Sem eles a página abre e diz o que falta.

## Onde ficam os dados

Simulações, programas, treinos e materiais ficam em `~/EstudioGo2/`
(`C:\Users\<você>\EstudioGo2\`), fora da pasta do código. O código vive no
OneDrive, e o OneDrive segura arquivos por instantes enquanto sincroniza —
ruim para o que muda a cada segundo. A variável de ambiente `ESTUDIO_DADOS`
troca a pasta. Na primeira abertura depois dessa mudança, o que estava nas
pastas antigas (ao lado do código) é movido para lá (`dados.py`).

## As seções

| seção | o que faz |
|---|---|
| **Painel** | cria uma simulação nova (nome, base, como começa, ações liberadas) e mostra o MuJoCo ao vivo; galerias resumidas |
| **Importar** | simulação (`.json`), textura (`.png`/`.jpg`); modelo de robô ainda não |
| **Cenário** | o editor: paleta à esquerda, MuJoCo no meio, propriedades à direita |
| **Programação** | editor de Python com o módulo `robo`; o servidor executa; saída, Parar, programas gravados |
| **Treino** | repete tentativas variando valores do programa e ajustes do controlador, pontua pelas regras do cenário, guarda o campeão |
| **Simulações** | tudo o que está gravado em `simulacoes/`; abrir, testar, apagar |
| **Modelos** | os robôs; só o Go2 por enquanto |

O botão de três barras recolhe a lateral. Abaixo de 1180 px o Painel empilha
os quadros; abaixo de 900 px a lateral começa recolhida; abaixo de 640 px ela
vira barra de abas. A barra de baixo mostra a última mensagem e guarda um
registro.

## O editor de cenário

**Objetos:** caixa, rampa, cilindro, esfera, barra, escada, parede e relevo
(chão irregular gerado por ruído). Cada um com posição, giro, medidas em
metros, material, se é fixo ou solto (com massa), atrito e elasticidade.
Objetos soltos caem e rolam quando o teste começa.

**Zonas:** partida (onde o robô nasce, virado no giro da zona), checkpoint,
chegada e proibida. Zonas não colidem; são marcações no chão.

**Regras:** "quando X, então Y". X pode ser entrar ou sair de uma zona, tocar
um objeto, cair, passar de N segundos ou chegar a N pontos. Y dá ou tira
pontos e pode terminar o teste com sucesso ou falha. Cada regra dispara uma
vez ou sempre. Uma zona nova de checkpoint, chegada ou proibida oferece a
regra de costume, mas não a impõe.

**Como se edita:** escolha um item na paleta e clique no chão para colocar
(sobre um objeto, empilha). Clique num objeto ou zona para selecionar; arraste
para mover; os números ficam à direita. `R` gira 15°, setas empurram 5 cm
(`Shift` = 25 cm), `Delete` remove, `Ctrl+D` duplica, `Ctrl+Z`/`Ctrl+Y`
desfazem e refazem, `Ctrl+S` salva, `Esc` cancela. Sem nada selecionado,
arrastar gira a câmera; a roda aproxima; duplo clique recentraliza.

**Editar × Testar:** no modo editar o robô fica parado na partida e nada se
move. Testar larga o robô, liga a física e o placar. Na bancada não há teste:
o robô fica preso no suporte.

**Salvar** grava `simulacoes/<id>.json` e uma miniatura `.jpg` do que a tela
mostrava. O `.json` é o formato de importação.

## Materiais e texturas

As texturas são fotografias reais do [ambientCG](https://ambientcg.com),
publicadas em domínio público (CC0). Na primeira vez que roda, o estúdio
baixa dez materiais iniciais (concreto, asfalto, madeira, grama, terra,
borracha, metal, azulejo, tijolo, tapete), pacotes 1K de ~3,5 MB cada, para
`materiais/`. Sem internet nessa primeira vez, os materiais ficam com uma cor
lisa até a próxima abertura; a paleta avisa.

Em **Importar → Textura** dá para buscar qualquer material do catálogo do
ambientCG (em inglês: *wood*, *bricks*, *gravel*…) e baixar com um clique, ou
soltar um pacote `.zip` (ambientCG, Poly Haven) ou uma imagem sua. Do pacote
entram o mapa de cor e o brilho, tirado da rugosidade média. `creditos.json`
guarda a origem de cada textura de fábrica.

O MuJoCo só desenha o mapa de cor (não usa normal nem roughness). Cada
material entra na cena em duas versões: "2d" para chão e relevo, que repete
por metro, e "cube" para objetos sólidos, em 512 px, porque a 2d escorre pelas
faces laterais de uma caixa.

## Biblioteca de ações

`acoes.py` é um registro: cada ação tem nome, descrição, parâmetros com
limites e a classe que a executa. A mesma lista vira os botões da página e,
mais adiante, as ferramentas da IA. Hoje:

| ação | parâmetros | o que faz |
|---|---|---|
| `ficar_de_pe`, `levantar` | — | leva as juntas à pose de pé (de sentado ou deitado, mais devagar) |
| `sentar` | — | traseira no chão, dianteiras esticadas |
| `deitar` | — | as quatro pernas dobradas, corpo a 10 cm do chão |
| `andar` | distância (m), velocidade (m/s, negativa = ré) | anda mantendo o rumo; para quando chega |
| `andar_ate_parar` | velocidade | anda até receber Parar |
| `girar` | graus (+ esquerda, − direita), velocidade | gira no lugar, segurando a posição |
| `girar_ate_parar` | velocidade | gira até receber Parar |

As ações rodam em **fila**, uma por vez, só no modo testar e no chão livre.
As "ações liberadas" do cenário filtram o que pode entrar na fila (ficar de
pé e levantar são sempre permitidas). Uma queda faz a ação falhar e limpa o
resto da fila. O "Começa" do cenário vira `andar_ate_parar` ou
`girar_ate_parar` na largada.

Andar e girar são fechados em malha: o comando é proporcional ao que falta,
com um mínimo que a marcha ainda obedece (a marcha entrega cerca de metade do
giro pedido), e a ação só termina depois de 0,6 s dentro da tolerância (6 cm;
5°). Girar segura a posição com `vx`/`vy`, senão a marcha deriva uns 30 cm.
Antes de sentar ou deitar vindo da marcha, o robô fica 0,5 s parado.

Precisão medida numa cadeia sentar → levantar → andar 1 m → girar 90° →
andar 1 m → deitar → levantar: zero quedas em qualquer rumo inicial, posição
final a ~0,25 m do ideal (a deriva vem do giro e das trocas de pose). É a
precisão desta marcha escrita à mão; o treino do passo 6 é o caminho para
melhorar.

Dois defeitos do controlador herdado foram corrigidos neste passo: a
velocidade angular da junta livre vem no referencial do corpo e era tratada
como do mundo (o robô só ficava de pé andando para +x); e o integrador da
marcha, decaindo devagar depois de parar, empurrava o robô 15 cm para trás. A
marcha também passou a terminar o ciclo do passo antes de congelar, em vez de
largar o pé no ar.

Endereços: `GET /api/acoes` (registro, com `liberada` por ação), `POST
/api/acoes` com `{"id", "parametros"}` (enfileira) e `DELETE /api/acoes`
(para tudo). O estado traz `acao` (em curso, com progresso), `fila`,
`ultimas` (resultados, com posição) e `postura`.

## Programação

A seção Programação é um editor de Python ligado ao robô. O código roda
dentro do próprio servidor (`programa.py`), numa thread, com um objeto
`robo` cujos métodos enfileiram as ações da biblioteca e **esperam cada uma
terminar**, devolvendo `True` se deu certo:

```python
robo.levantar()
if robo.andar(1.0):            # metros; velocidade opcional
    robo.girar(90)             # graus; positivo à esquerda
robo.ir_ate("Chegada")         # gira para a zona ou objeto e anda até lá
print(robo.posicao(), robo.rumo(), robo.placar())
```

A referência completa aparece ao lado do editor (clicar insere no código):
mover (`levantar`, `ficar_de_pe`, `sentar`, `deitar`, `andar`, `girar`,
`ir_ate`, `acao`, `aguardar`, `parar`, `esperar`, `reiniciar`), medir
(`posicao`, `altura`, `rumo`, `postura`, `tempo`, `quedas`, `placar`,
`pontos`, `terminou`) e cenário (`zonas`, `objetos`, `zona`, `objeto`,
`na_zona`, `distancia`, `direcao`). `print` vai para o painel de saída, com
o tempo do teste em cada linha. Se o teste termina (regra com fim) no meio de
uma ação, a ação é cortada e a chamada devolve `True` em sucesso, `False` em
falha; depois disso as ações não rodam mais (`robo.reiniciar()` recomeça).

Executar (Ctrl+Enter) liga o modo Testar sozinho se preciso; o cenário tem
de ser no chão livre e só libera as ações marcadas nele. **Parar** interrompe
a ação em curso e o programa na linha seguinte — funciona até num `while
True` sem robô, porque o estúdio acompanha o programa linha a linha
(`sys.settrace`); só não entra em `time.sleep` longos, use `robo.esperar`.
Erros aparecem na saída com a linha, que fica marcada na numeração. Tab
indenta (Shift+Tab desindenta) e Enter mantém a indentação.

Salvar (Ctrl+S) grava `programas/<nome>.py`, um arquivo comum que qualquer
editor abre; a lista à esquerda abre e o ícone de lixeira apaga. O texto do
editor fica guardado no navegador entre recargas.

É Python de verdade, com os poderes do processo do servidor. É o que a tela
é para ser; por isso não exponha o estúdio na rede (`--aberto`) para quem
não deva rodar código nesta máquina.

## Treino por tentativa

É o "jeito 2": nada de rede neural. O usuário define tudo na página; o
estúdio só repete e mede.

- **Cenário**: o que está aberto no editor. As regras dele são a pontuação
  (entrar na zona +100 e termina, cair −30, tempo…). Nada é inventado: sem
  regra, toda tentativa vale zero.
- **Programa**: um `.py` da seção Programação, o que o robô tenta fazer.
  Sem programa, o robô só faz o "Começa" do cenário.
- **Variáveis**: o programa declara as suas com
  `treino.parametro("velocidade", 0.3, 0.15, 0.6)` (nome, padrão, mínimo,
  máximo; fora do treino vale o padrão); a página lê essas chamadas do
  código sem rodá-lo. Além delas, qualquer ajuste do controlador de marcha
  marcado na lista (período do passo, altura do corpo, rigidez das
  juntas…), com os limites editáveis.
- **Orçamento**: quantas tentativas, tempo máximo de cada uma (em segundos
  da simulação) e a velocidade — até 20× o tempo real; a física roda vários
  passos por período e o vídeo acompanha acelerado.

Cada tentativa reposiciona o robô, zera o placar, aplica os valores, roda o
programa e termina quando o teste termina (regra com fim), o tempo esgota
ou o programa acaba com a fila vazia. Resultado: pontos, fim, tempo,
quedas, valores. A ordem é mais pontos, depois menos quedas, depois menos
tempo. A busca: a 1.ª tentativa usa os padrões, um terço explora ao acaso
dentro dos limites, o resto perturba o melhor com passos cada vez menores
(semente fixa: o mesmo treino repete igual).

**O treino acumula.** Um treino novo no mesmo cenário com o mesmo programa
parte do campeão do treino anterior: a 1.ª tentativa usa os valores dele
(dentro dos limites), e a página diz de quem partiu. Os ajustes do
controlador marcados partem do que está em vigor, não dos padrões de
fábrica. A caixa "Evolução neste cenário" desenha a melhor pontuação de
cada treino gravado para o cenário aberto, do mais antigo ao mais novo.

Tudo vai para `treinos/<id>.json` **conforme acontece** (definição, cópia
do cenário e do código, cada tentativa, o melhor), então parar no meio não
perde nada. O campeão tem três saídas: **Ver o campeão** (roda a melhor
tentativa de novo, a 1×, no cenário gravado), **Gravar programa campeão**
(escreve um `.py` com os valores do campeão no lugar dos padrões e, se
houver, uma linha `robo.ajustar(...)` no início) e **Usar ajustes** (aplica
os ajustes do controlador do campeão e **grava** em `ajustes.json` na pasta
de dados: valem em toda abertura do estúdio, sobrevivem a recompilar a
cena, e a seção Treino mostra "em vigor" com um botão para voltar aos de
fábrica). Em Programação, `robo.ajustar(marcha_T=0.5, ctrl_kp=110)` faz o
mesmo e também grava; `robo.ajustar(padrao=True)` limpa; `robo.ajustes()`
mostra. Dentro de um treino, os valores experimentados nunca são gravados.

Enquanto um treino roda, a seção Programação não executa (o programa é do
treino). O OneDrive segura arquivos por instantes ao sincronizar; as
gravações tentam de novo por 2 s antes de desistir.

## O MuJoCo dentro da página

Nada de janela separada: o servidor roda a física e desenha fora da tela,
comprime cada quadro em JPEG e manda como vídeo contínuo (MJPEG) para um
`<img>` comum. Duas threads sobre o mesmo modelo, com uma trava:

| thread | faz | ritmo |
|---|---|---|
| física | avança a simulação e avalia as regras (modo testar) | 100 Hz |
| imagem | desenha, comprime e publica o quadro, só enquanto há visor | até 30 fps |

Nesta máquina (Intel UHD) um quadro custa ~22 ms sem sombra e ~65 ms com;
por isso a sombra fica desligada. O tamanho do quadro segue o da tela na
página, até 1280×960; só a tela visível transmite.

Mudar posição, giro, medidas ou material de um objeto ajusta o modelo em
memória (milissegundos). Incluir ou tirar objetos, ou mudar a base, recompila
a cena (~1,2 s, a maior parte decodificando e enviando as texturas à placa) e a barra
avisa "Cena remontada". Tudo é carregado em memória (malhas, texturas), porque
o MuJoCo não abre arquivos em pastas com acento no Windows.

Clicar no vídeo pergunta ao servidor o que há sob o pixel (`mjv_select`) e
onde o raio cruza o chão, para colocar e arrastar.

## Endereços

| método | endereço | faz |
|---|---|---|
| GET | `/api/estado` | versão do MuJoCo, modo, cenário, placar, fps |
| GET | `/api/mujoco/video?w=&h=` | o vídeo |
| POST | `/api/mujoco` | `{"modo"}`, `{"reiniciar"}`, `{"inicio"}`, `{"camera"}`, `{"recentrar"}`, `{"orbita": [az, el]}`, `{"zoom"}` |
| GET / PUT | `/api/cenario` | o cenário carregado; PUT aplica um editado |
| POST | `/api/cenario/apontar` | `{"x", "y"}` em 0..1 → objeto, zona, ponto, chão |
| GET / POST / DELETE | `/api/materiais[/id]` | catálogo; enviar imagem ou `.zip` (corpo cru, `?nome=`); remover |
| GET | `/api/materiais/buscar?q=` | busca no ambientCG |
| POST | `/api/materiais/baixar` | `{"fonte": "Bricks054"}` baixa do ambientCG |
| GET | `/api/materiais/<id>/miniatura.png` | miniatura |
| GET / POST | `/api/simulacoes` | lista; cria `{nome, base, comeca, acoes}` e abre |
| GET / PUT / DELETE | `/api/simulacoes/<id>` | ler; gravar (`?novo=1` na primeira vez); apagar |
| POST | `/api/simulacoes/<id>/abrir` | carrega no MuJoCo |
| POST | `/api/simulacoes/importar` | grava um `.json` recebido |
| GET / POST / DELETE | `/api/programa[?desde=n]` | estado e saída do programa (linhas após `n`); rodar `{codigo, nome}`; parar |
| GET | `/api/programa/referencia` | os métodos do `robo` e o programa de exemplo |
| GET | `/api/programas` | os `.py` gravados |
| GET / PUT / DELETE | `/api/programas/<nome>` | ler; gravar `{codigo}`; apagar |
| GET | `/api/programas/<nome>/parametros` | as chamadas `treino.parametro` do programa |
| GET / POST / DELETE | `/api/treino` | estado do treino em curso; iniciar `{nome, programa, variaveis, tentativas, tempo_max, velocidade, semente}`; parar |
| GET | `/api/treino/variaveis` | ajustes do controlador que podem variar, com o valor em vigor |
| POST | `/api/treino/campeao` · `/campeao/programa` · `/campeao/usar` | `{id}`: rodar a 1×; gravar o `.py`; aplicar e gravar os ajustes |
| GET / POST / DELETE | `/api/treino/ajustes` | os ajustes em vigor; mudar e gravar `{"marcha.T": 0.7}`; voltar aos de fábrica |
| GET | `/api/treinos` | os gravados |
| GET / DELETE | `/api/treinos/<id>` | ler (sem o cenário e o código inteiros); apagar |

## Passos

1. Esqueleto da tela — feito.
2. MuJoCo dentro da página — feito.
3. **Editor de cenário**, materiais, zonas e regras, salvar e importar — feito.
4. **Biblioteca de ações** em Python, com fila — feito.
5. **Programação**: editor de Python na página, módulo `robo`, executado
   pelo próprio servidor; saída, Parar, programas gravados — feito.
6. **Treino por tentativa** no cenário montado, pontuando pelas regras; gravação em pasta — feito.
   Complemento (05/10/2026): ajustes persistentes, treino partindo do campeão anterior, curva por cenário — feito.
7. Conversa com IA: o modelo escreve programas (passo 5) ou chama as ações.
8. Importar modelos de outros robôs.
9. Reconhecer algo: câmera do robô e modelo com visão.

Houve uma seção Interações (botões da biblioteca, fila, Parar), feita e
retirada em 01/10/2026 a pedido: a Programação já cobre o uso das ações, e
a conversa com a IA ganhará lugar no seu próprio passo.

## Arquivos

| arquivo | papel |
|---|---|
| `estudio.py` | servidor: entrega `painel/`, o vídeo e todos os endereços |
| `mundo.py` | a cena, a física, o placar, o desenho e o apontar |
| `cenario.py` | formato do cenário, validação, XML do MuJoCo, disco |
| `materiais.py` | texturas do ambientCG (fábrica, busca) e enviadas |
| `acoes.py` | a biblioteca de ações e a validação dos parâmetros |
| `programa.py` | executa o código do usuário com os módulos `robo` e `treino`; programas em disco |
| `treino.py` | o treino: variáveis, busca, tentativas, campeão, `treinos/` |
| `controle.py` | controlador PD e marcha, copiado da bancada e corrigido |
| `mujoco_carga.py` | importa o MuJoCo mesmo com um plugin bloqueado pelo Windows |
| `dados.py` | a pasta de dados do usuário (`~/EstudioGo2`) e a migração das pastas antigas |
| `painel/index.html` | as seções, os ícones e o desenho do Go2 |
| `painel/estudio.css` | cores (todas no `:root`) e layout |
| `painel/mujoco.js` | a tela do MuJoCo: vídeo, câmera, modo, placar |
| `painel/editor.js` | o editor: paleta, seleção, arrasto, propriedades, regras, histórico |
| `painel/programa.js` | a tela de programação: editor de texto, executar/parar, saída, gravados |
| `painel/treino.js` | a tela de treino: definição, andamento, campeão, gravados |
| `painel/app.js` | rotas, lateral, barra de estado, formulário, galerias, importar |
