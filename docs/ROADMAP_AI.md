# Roteiro da IA de reconhecimento musical

## Objetivo

Construir um reconhecedor local, aberto e treinável que transforme partituras
impressas ou manuscritas em uma representação musical editável. O sistema deve
reduzir radicalmente o trabalho de digitação sem esconder incertezas.

Ele não será um chatbot e não depende de Ollama. A tarefa combina visão
computacional, reconhecimento sequencial, regras de notação e um decodificador
musical com restrições.

## Arquitetura proposta

```text
PDF/foto
  → correção geométrica e normalização da página
  → detecção de sistemas, pautas, barras e regiões não musicais
  → reconhecimento por pauta/compasso em alta resolução
  → tokens musicais com coordenadas e confiança
  → associação de instrumentos e vozes
  → decodificador restrito por métrica, clave e tessitura
  → MusicXML intermediário
  → validação estrutural e comparação visual
  → MuseScore/PDF para revisão
  → correções humanas retornam ao conjunto de dados
```

O modelo visual deve ver recortes, não a grade inteira reduzida. Uma página
orquestral pode ter dezenas de pautas; reduzir tudo ao tamanho de uma imagem comum
apaga exatamente os detalhes necessários para separar cabeça de nota, acidente e
linha suplementar.

## Componentes

### 1. Analisador de página

Detecta orientação, perspectiva, sistemas, pautas, barras, nomes de instrumento,
texto, manchas e marcas de maestro. A saída são regiões com coordenadas estáveis.
Uma marca grande atravessando pautas deve ser classificada como anotação, sem apagar
acentos, ligaduras ou crescendos legítimos.

### 2. Reconhecedor musical

Recebe uma pauta ou pequeno grupo de pautas em resolução alta. A primeira versão
pode partir de um encoder visual pré-treinado e um decoder de tokens musicais. Os
tokens precisam representar, no mínimo:

- clave, armadura e fórmula de compasso;
- notas, pausas, acidentes e pontos;
- hastes, feixes, acordes e vozes;
- quiálteras e `time-modification`;
- ligaduras, tremolos e articulações;
- letras e associação silábica.

### 3. Grafo da partitura

Tokens visuais não bastam. O ReScore precisa montar relações: esta cabeça pertence
a esta haste; este número define esta quiáltera; esta sílaba pertence a esta nota;
estas duas pautas formam piano ou harpa; esta abreviação identifica este
instrumento.

### 4. Decodificador com restrições

Cada voz deve terminar exatamente no compasso. A regra não força a máquina a
inventar conteúdo: quando não existe solução confiável, ela preserva uma lacuna e
emite uma tarefa de revisão. Tessitura e capacidade instrumental são sinais de
confiança, nunca provas absolutas.

### 5. Aprendizado ativo

O revisor abre os trechos de menor confiança primeiro. Cada correção grava:

- imagem e coordenadas;
- previsão anterior;
- resposta corrigida;
- identidade anônima ou declarada do revisor;
- versão do modelo e do esquema.

Assim o esforço humano melhora diretamente as versões seguintes.

## Fases

### Fase 0 — fundação de dados

- esquema versionado;
- importação segura de imagem + MSCZ/MusicXML;
- hashes e procedência;
- catálogo público sem vazamento de itens privados;
- conjunto-semente local.

### Fase 1 — alinhador

- localizar barras e compassos da fonte em alta resolução;
- propor correspondências numeradas e coordenadas normalizadas;
- gerar sobreposições e uma página local de revisão;
- renderizar MusicXML revisado de volta para imagem;
- localizar pautas da fonte e da referência;
- editor simples para confirmar ou corrigir;
- exportar recortes pareados.

Os três primeiros incrementos já existem. `dataset-align` cobre o alinhamento
página–compasso; `dataset-align-staffs` subdivide cada compasso por pauta física,
preserva linhas vazias e registra relações condensadas com partes MusicXML;
`dataset-export-training` produz os pares visuais/tokens com checksums. Todos
mantêm a proposta da máquina separada de uma confirmação humana. O próximo
incremento é ampliar o vocabulário de notação e criar divisões por obra/copista.

A aprovação auditável de camadas completas também está disponível em
`dataset-review`. A primeira revisão musical granular também está disponível:
`detect-issues` cria a fila estrutural, `review-pack` produz um `.mscz` compacto com
identificadores persistentes e `dataset-fix` registra a resposta humana como um
override versionado. Uma dúvida isolada já pode ser corrigida sem substituir o
gabarito inteiro. Ainda faltam edição geométrica de caixas individuais e incerteza
produzida diretamente pelo futuro modelo neural, em vez de apenas regras musicais.

### Fase 2 — modelo-base por pauta

- vocabulário de tokens;
- carregador PyTorch com aumento de ruído, inclinação e contraste;
- treino em impressão limpa e escaneada;
- métricas de símbolo, nota, ritmo e compasso;
- exportação ONNX para inferência local.

### Fase 3 — manuscritos e orquestra

- adaptação por copista;
- múltiplas pautas e instrumentos condensados;
- associação de vozes;
- letras;
- aprendizagem por duplicações orquestrais confirmadas.

### Fase 4 — aplicativo comunitário

- interface de revisão lado a lado;
- fila de baixa confiança;
- pacotes de dados assinados e versionados;
- ficha de modelo e benchmark reproduzível;
- instaladores para Windows, Linux e macOS.

## Métricas

“O arquivo abriu” não é suficiente. Cada versão deve medir:

- taxa de notas corretas por altura e início;
- erro de duração;
- fórmulas, claves e armaduras corretas;
- precisão de vozes e quiálteras;
- compassos estruturalmente válidos;
- associação correta de instrumentos;
- sílabas corretamente ligadas;
- tempo de revisão humana por página.

A métrica principal do produto será tempo humano economizado mantendo a partitura
editável e estruturalmente válida.

## Hardware

O desenvolvimento deve funcionar sem GPU. Inferência e alinhamento precisam ter
modo CPU. Uma GPU NVIDIA de 4 GB consegue executar modelos compactos e pequenos
ajustes com recortes de pauta, lote pequeno, precisão mista e acumulação de
gradiente. O treino de um modelo geral exigirá GPUs comunitárias ou infraestrutura
temporária maior.

Os comandos de diagnóstico não enviam dados:

```powershell
rescore hardware
```

O relatório mostra CPU, RAM, GPUs, VRAM, disco e uma recomendação conservadora.

## Critério para a primeira versão útil

O primeiro modelo público não precisa transcrever uma ópera inteira sozinho. Ele
precisa superar de forma mensurável o OMR genérico em um conjunto de teste
publicável, produzir compassos válidos e reduzir o tempo de correção. Qualquer
material que não possa ser auditado ou redistribuído fica fora desse benchmark.
