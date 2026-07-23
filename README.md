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
- exportação para MusicXML, `.mscz` e PDF de conferência;
- preservação do projeto `.omr` para correções no Audiveris;
- associação e normalização de pautas orquestrais;
- suporte a referências MusicXML/MSCZ para comparação;
- bloqueio opcional da fórmula de compasso;
- auditoria de compassos e vozes antes de entregar o arquivo;
- relatórios JSON com artefatos, métricas e avisos;
- reaproveitamento de resultados intermediários em novas execuções.

Todo o processamento é local. O ReScore não envia a partitura para um serviço
externo.

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
rescore inspect-mscz arquivo.mscz
rescore canonicalize arquivo.mxl --output partitura.json
rescore normalize-scherzo candidato.mxl modelo.musicxml
```

Use `rescore --help` ou `rescore <comando> --help` para ver todos os argumentos.

## Assistente `run.py`

O arquivo `run.py` oferece um fluxo interativo e perfis experimentais para os casos
orquestrais usados durante o desenvolvimento:

```powershell
python run.py --pdf "partitura.pdf" --pages 3 --meter 4/4
python run.py --profile choros9 --pdf "grade-escaneada.pdf" --pages 3-10
```

Sem `--pages`, ele pergunta o intervalo. O perfil de digitalização processa as
páginas separadamente para que uma página difícil não interrompa o lote inteiro.
Não fixe `--meter` em um intervalo que contenha mudanças de fórmula.

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
