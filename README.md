# ReScore

ReScore é um pipeline local em Python para transformar páginas de partituras em PDF
em um rascunho editável no formato MusicXML ou MuseScore. Ele combina renderização
de PDF, reconhecimento óptico de música (OMR), normalização musical e validação
métrica.

O programa foi pensado para grades orquestrais grandes, inclusive digitalizações
antigas. O resultado continua sendo um rascunho para revisão humana: OMR ainda pode
errar alturas, acidentes, vozes, quiálteras, letras e a associação entre pautas.

## Recursos

- processamento de uma página, intervalos ou listas como `3-10,15`;
- fluxo próprio para PDF digital e para grade escaneada;
- reconstrução conservadora de linhas rápidas pela posição horizontal registrada
  pelo OMR, quando as durações reconhecidas empurrariam notas para fora do compasso;
- exportação para MusicXML, `.mscz` e PDF de conferência;
- preservação do projeto `.omr` para correções no Audiveris;
- associação e normalização de pautas orquestrais;
- suporte a referências MusicXML/MSCZ para comparação;
- bloqueio opcional da fórmula de compasso;
- auditoria de compassos e vozes antes de entregar o arquivo;
- fila de correção assistida: detecta trechos suspeitos, cria um `.mscz` curto para
  edição humana e devolve as correções versionadas ao conjunto de dados;
- relatórios JSON com artefatos, métricas e avisos;
- reaproveitamento de resultados intermediários em novas execuções.

Todo o processamento é local. O ReScore não envia a partitura para um serviço
externo.

## Direção do projeto

O pipeline existente é a camada de produção e validação. A evolução planejada é
um sistema de reconhecimento de música treinável pela comunidade, especialmente
para manuscritos e grades orquestrais históricas. Ele não depende de Ollama nem de
um modelo de linguagem: a arquitetura usa visão computacional, modelos musicais e
restrições simbólicas próprias para partitura.

Uma imagem, sozinha, não ensina ao modelo qual era a resposta correta. Por isso o
novo formato de conjunto de dados guarda pares auditáveis de imagem e MusicXML
revisado, com alinhamento de compassos, procedência, licença, nível de revisão e
hashes. Consulte [Conjunto de dados](docs/DATASET.md) e
[Roteiro da IA](docs/ROADMAP_AI.md).

## Requisitos

- Python 3.11 ou mais recente;
- [Audiveris](https://github.com/Audiveris/audiveris) para OMR;
- [MuseScore 4](https://musescore.org/) para gerar e validar `.mscz` e PDF.

No Windows, os executáveis são procurados no `PATH`, nos locais usuais de instalação
e nas variáveis:

- `RESCORE_AUDIVERIS`;
- `RESCORE_MUSESCORE`.

## Instalação

PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\rescore.exe doctor
```

Linux ou macOS:

```bash
python3.11 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -e .
./.venv/bin/rescore doctor
```

O comando `doctor` mostra os caminhos e as versões detectadas. Se uma ferramenta não
for encontrada, defina a variável correspondente com o caminho completo do
executável.

## Uso rápido

Converter páginas com fórmula conhecida:

```powershell
rescore convert "partitura.pdf" `
  --pages 7-8 `
  --meter 4/4 `
  --output output/revisao-7-8
```

Converter usando uma transcrição de referência:

```powershell
rescore convert "partitura.pdf" `
  --pages 67 `
  --reference "referencia.musicxml" `
  --reference-mscz "referencia.mscz" `
  --output output/revisao-67
```

Renderizar páginas sem executar OMR:

```powershell
rescore render "partitura.pdf" --pages 1-3 --dpi 300
```

Comparar dois arquivos:

```powershell
rescore compare referencia.musicxml candidato.mxl `
  --output output/comparacao.json
```

Outros comandos:

```text
rescore doctor
rescore hardware
rescore inspect-mscz arquivo.mscz
rescore canonicalize arquivo.mxl --output partitura.json
rescore normalize-scherzo candidato.mxl modelo.musicxml
rescore dataset-init data/meu-conjunto
rescore dataset-validate data/meu-conjunto
rescore dataset-align data/meu-conjunto --id meu-item --page-measures 8,8
rescore alignment-validate data/meu-conjunto/items/meu-item/alignment/measure-regions.json
rescore dataset-align-staffs data/meu-conjunto --id meu-item --profile auto
rescore staff-alignment-validate data/meu-conjunto/items/meu-item/alignment/staff-regions.json
rescore dataset-export-training data/meu-conjunto --id meu-item
rescore training-export-validate data/meu-conjunto/items/meu-item/training/samples.jsonl
rescore dataset-review data/meu-conjunto --id meu-item --reviewer "Nome" --approve-measures --approve-staffs
rescore detect-issues candidato.musicxml --output output/problemas
rescore review-pack candidato.musicxml --issues output/problemas/issues.jsonl --output output/correcoes
rescore dataset-fix data/meu-conjunto --id meu-item --pack output/correcoes/review-pack.json --corrected output/correcoes/review-pack.mscz --reviewer "Nome"
```

Use `rescore --help` ou `rescore <comando> --help` para ver todos os argumentos.

## Corrigir somente os trechos duvidosos

O ReScore pode transformar problemas estruturais ou leituras suspeitas em uma
folha pequena de trabalho, sem exigir que o revisor procure o erro na grade inteira:

```powershell
rescore detect-issues output/minha-leitura/normalized.musicxml `
  --output output/minha-leitura/issues

rescore review-pack output/minha-leitura/normalized.musicxml `
  --issues output/minha-leitura/issues/issues.jsonl `
  --output output/minha-leitura/review-pack
```

O primeiro comando cria `issues.jsonl` e `issues.html`, com mensagens como
“compasso 8, pauta 4, possível fagote”. O segundo gera:

```text
review-pack/
  review-pack.mscz       arquivo que o músico corrige no MuseScore
  review-pack.pdf        conferência visual em A4 paisagem
  review-pack.musicxml   representação portátil
  review-pack.json       mapa auditável para a partitura original
  review-pack-validation.json  auditoria métrica do formulário
```

Cada compasso recebe um identificador visível como `RS-REVIEW-0001` e informa o
compasso original, instrumento provável, pauta e tipo de dúvida. O formulário é
deliberadamente limpo: contém contexto de fórmula/clave e pausas completas, mas não
copia as notas potencialmente quebradas. Não apague o texto identificador. Escreva
o compasso correto e salve o `.mscz`.

Quando a leitura pertencer a um item já cadastrado no dataset, importe o arquivo
corrigido:

```powershell
rescore dataset-fix data/rescore-local `
  --id minha-obra-pagina-1 `
  --pack output/minha-leitura/review-pack/review-pack.json `
  --corrected output/minha-leitura/review-pack/review-pack.mscz `
  --reviewer "Nome do revisor" `
  --note "Conferido contra o manuscrito"
```

O comando nunca sobrescreve o gabarito anterior. Ele cria uma correção versionada,
guarda a previsão e a resposta humana, registra hashes e revisor, e marca a
exportação de treino anterior como obsoleta. Na próxima exportação, a versão humana
mais recente substitui somente os fluxos corrigidos. Consulte
[Conjunto de dados](docs/DATASET.md#corrigir-trechos-suspeitos) para os critérios e
arquivos de auditoria.

Se a leitura automática e o gabarito usam IDs instrumentais diferentes, declare a
correspondência explicitamente. Se o MuseScore removeu todos os textos `RS-REVIEW-*`
ao substituir as pausas, `--confirm-order` registra que o revisor confirmou a ordem:

```powershell
rescore dataset-fix data/rescore-local `
  --id minha-obra-pagina-1 `
  --pack output/revisao/pack/review-pack.json `
  --corrected output/revisao/pack/review-pack.mscz `
  --reviewer "Nome do revisor" `
  --map P17:1=P29:2 `
  --confirm-order
```

Sem essas confirmações explícitas, o importador recusa bases diferentes, IDs
ausentes ou destinos ambíguos para impedir que notas sejam ensinadas ao instrumento
errado.

## Assistente `run.py`

O arquivo `run.py` oferece um fluxo interativo e perfis experimentais para os casos
orquestrais usados durante o desenvolvimento:

```powershell
python run.py --pdf "partitura.pdf" --pages 3 --meter 4/4
python run.py --profile choros9 --pdf "grade-escaneada.pdf" --pages 3-10
python run.py --profile choros9 --pdf "grade-escaneada.pdf" --pages 3 `
  --reference-mscz "referencia-manual.mscz"
```

Sem `--pages`, ele pergunta o intervalo. O perfil de digitalização recupera as
páginas separadamente para que uma página difícil não interrompa o lote, mas esse
isolamento é apenas interno. Quando o intervalo contínuo começa na página 3 e existe
uma referência manual, a entrega principal é uma única partitura com todos os
compassos e um PDF A3 horizontal. Não fixe `--meter` em um intervalo que contenha
mudanças de fórmula.

As páginas 3-7 do Choros 9 herdam a fórmula inicial 4/4. O pré-processamento
também diferencia cunhas musicais normais de anotações manuscritas gigantes:
somente pares de traços contínuos que atravessam várias pautas são removidos
antes do OMR. Marcas de ensaio, ligaduras, acentos, quiálteras e crescendos
confinados a uma pauta são preservados.

O número de compassos reconhecidos também é comparado às barras confirmadas na
imagem. Uma página curta é relida por compasso; pautas omitidas em um recorte
são preenchidas na posição correta, sem deslocar as famílias instrumentais.
Nas páginas densas do Choros 9, teclas/harpas e cordas também são relidas em
recortes verticais ampliados a 200%. Assim cada pauta recebe resolução semelhante
à visualização aproximada no leitor de PDF, sem perder a continuidade horizontal
dos compassos. O diagnóstico fica em `audiveris-families/focus-report.json`.

Quando uma referência manual é fornecida para a abertura do Choros 9, somente os
três primeiros compassos são considerados verificados. Um quarto compasso
incompleto é ignorado. O programa expande as pautas condensadas para o modelo de 35
partes, preserva literalmente os compassos confirmados e grava um relatório de
calibração por instrumento. Se existir `Choros 9.mscz` na raiz, o `run.py` o detecta
automaticamente.

Na montagem contínua, as 24 pautas condensadas do scan são expandidas para 35
partes/37 pautas. Acordes reconhecidos em pautas monofônicas de sopros e metais são
distribuídos entre os executantes disponíveis; alturas excedentes e ambíguas não
são escondidas, mas registradas em `playability-report.json`. Cordas, tímpanos,
celesta e harpa preservam sua escrita polifônica.

## Manuscrito em imagens: A Menina das Nuvens

Há um perfil experimental específico para as quatro primeiras fotos de
**A Menina das Nuvens — 1º Ato**. Ele lê cada página em dois recortes verticais,
monta as páginas em uma única sequência e sempre entrega MusicXML, MuseScore e
PDF A3 horizontal.

O perfil usa o [homr](https://github.com/liebharc/homr) em um ambiente separado:

```powershell
py -3.11 -m venv tools/homr-env
.\tools\homr-env\Scripts\python.exe -m pip install homr==0.7.0
```

Para processar a pasta com exatamente quatro imagens:

```powershell
python scripts/build_menina_draft.py "pasta-das-quatro-fotos" `
  --homr tools/homr-env/Scripts/homr.exe `
  --output output/menina-das-nuvens
```

O resultado possui 23 partes e 26 compassos contínuos: 2/4 nos compassos 1–18,
3/4 nos compassos 19–21 e novamente 2/4 nos compassos 22–26. O reconhecedor
completa cada voz somente com pausas, nunca aumentando o compasso para acomodar
um resultado impossível. Alturas fora da tessitura e compassos excessivamente
densos são descartados e registrados em `recognition-report.json`.
Depois da importação, o próprio `.mscz` é auditado em
`musescore-validation.json`; a execução é interrompida se qualquer voz ficar
curta ou longa.

Esse perfil é deliberadamente conservador e não deve ser tratado como um leitor
genérico de qualquer manuscrito. Os grupos manuscritos de 12 do compasso 22 ainda
ficam em branco quando a razão rítmica não pode ser comprovada. Articulações,
dinâmicas, ligaduras, transposição e letras precisam de revisão humana.

## Arquivos produzidos

Uma conversão pode gerar:

```text
output/conversion/
  pages/                         imagens renderizadas
  audiveris/                     projeto OMR, logs e MusicXML bruto
  candidate.mscz                 importação inicial
  normalized.musicxml            MusicXML pós-processado
  normalized.mscz                arquivo editável
  normalized.pdf                 conferência visual
  continuous/
    choros9-continuous.mscz       partitura única para revisão
    choros9-continuous-A3.pdf     PDF A3 horizontal, sempre gerado
    playability-report.json       divisões e ambiguidades instrumentais
  manifest.json                  entradas, saídas e resumo
  measure-audit.json             validação métrica
  musescore-validation.json      validação após importação
  instrument-map*.json           associação de pautas
```

Nem todos os arquivos aparecem em todos os fluxos. O `manifest.json` é a fonte
principal para descobrir os artefatos efetivamente criados.

## Validação e limites

Quando `--meter` é informado, a normalização tenta completar cada voz exatamente até
o fim do compasso e rejeita o arquivo se a validação ainda encontrar uma voz longa
ou um compasso incompleto. Isso evita corrigir um erro de OMR aumentando
silenciosamente o tamanho do compasso.

Em grades condensadas, indicações como `1. 2.`, `3. 4.`, `a2`, mudanças de
instrumento, pautas compartilhadas e acordes distribuídos entre sopros exigem
interpretação posterior. Em manuscritos e digitalizações:

- barras e pautas podem ser confundidas com hastes;
- uma duração reconhecida incorretamente pode deslocar todo o compasso;
- duplicações orquestrais são usadas apenas como evidência, nunca para copiar notas
  sem confirmação;
- letras precisam de revisão nota por nota.

Consulte [Arquitetura](docs/ARCHITECTURE.md) para entender o pipeline e
[Guia de uso](docs/USAGE.md) para os fluxos detalhados.

## Desenvolvimento

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python -m compileall -q src run.py
```

Partituras, PDFs, imagens de referência, projetos OMR/MuseScore, saídas e anotações
locais são ignorados pelo Git. Os testes que dependem de uma referência privada são
automaticamente ignorados quando ela não está presente.

## Licença e dados

O código do ReScore é distribuído sob
[GNU AGPL-3.0-or-later](LICENSE). A licença do código não concede direitos sobre
partituras, fotografias, transcrições ou pesos treinados. Cada contribuição de
dados precisa declarar sua própria procedência e permissão de redistribuição.

O GitHub deve armazenar código, esquemas, documentação e pequenos catálogos. Imagens
e MusicXML de treinamento ficam fora do histórico Git e só podem ser publicados
por um repositório de dados quando o manifesto autorizar explicitamente. Veja
[Política de dados](DATA_POLICY.md) e [Como contribuir](CONTRIBUTING.md).
