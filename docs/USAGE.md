# Guia de uso

Antes do primeiro uso, crie o ambiente e instale o projeto com
`python -m pip install -r requirements.txt`, conforme o README. O arquivo
`requirements-dev.txt` acrescenta somente as ferramentas de desenvolvimento.

## 1. Verificar o ambiente

```powershell
rescore doctor
```

O resultado é JSON. `path: null` indica que a ferramenta correspondente não foi
encontrada. É possível informar caminhos explícitos:

```powershell
$env:RESCORE_AUDIVERIS = "C:\caminho\Audiveris.exe"
$env:RESCORE_MUSESCORE = "C:\caminho\MuseScore4.exe"
rescore doctor
```

## 2. Escolher as páginas

`--pages` aceita:

- uma página: `67`;
- um intervalo: `67-69`;
- uma lista: `67,69,72`;
- combinações: `3-10,15,18-20`.

Os números são as páginas do arquivo PDF, começando em 1, e não necessariamente a
numeração impressa na partitura.

### Interface principal do `run.py`

Para escolher um trecho sem travar a fórmula de compasso:

```powershell
python run.py --file "arquivo.pdf" --pages 1-20
python run.py --file "arquivo.pdf" --pages 40-50
```

Para uma obra completa:

```powershell
python run.py --file "arquivo.pdf" --detect-movements true
python run.py --file "arquivo.pdf" --detect-movements false
```

- `true`: procura movimentos e cria uma conversão separada para cada um;
- `false`: trata o arquivo como uma composição contínua;
- sem `--pages`, o padrão também é `false`;
- `--detect-moviments` é um alias tolerado, mas a documentação usa a grafia correta;
- se não houver evidência suficiente para os movimentos, `true` para com uma
  mensagem e recomenda `--pages` ou `false`;
- `--meter` só deve ser usado em um intervalo cuja fórmula inteira tenha sido
  confirmada. Sem ele, o ReScore preserva as fórmulas reconhecidas na fonte.

Perfis verificados atualmente:

- Sinfonia nº 10: quatro movimentos, páginas 7-41, 42-66, 67-99 e 100-200;
- Choros nº 9: obra contínua, páginas musicais 3-134.

Em PDFs digitais desconhecidos, títulos romanos centralizados (`I`, `II`, `III`...)
podem fornecer os limites. O detector exige uma sequência completa começando em I;
não cria movimentos por simples semelhança visual.

## 3. Renderizar para inspeção

```powershell
rescore render "partitura.pdf" `
  --pages 3-5 `
  --dpi 300 `
  --output output/paginas
```

Esta etapa é útil para conferir corte, resolução, rotação e legibilidade antes do
OMR.

## 4. Executar uma conversão

```powershell
rescore convert "partitura.pdf" `
  --pages 3 `
  --meter 4/4 `
  --omr-dpi 300 `
  --output output/pagina-3
```

Use `--meter` apenas quando a fórmula estiver confirmada para todo o intervalo. A
opção serve como restrição e não como palpite. Para reexecutar o OMR:

```powershell
rescore convert "partitura.pdf" --pages 3 --meter 4/4 --force
```

Sem `--force`, candidatos MusicXML existentes podem ser reaproveitados.

## 5. Usar uma referência

Uma transcrição revisada ajuda a resolver a estrutura da orquestra:

```powershell
rescore convert "partitura.pdf" `
  --pages 67 `
  --reference "modelo.musicxml" `
  --reference-mscz "modelo.mscz" `
  --output output/pagina-67
```

A referência não deve ser sobrescrita. Mantenha uma cópia de segurança fora da pasta
de saída.

## 6. Conferir o resultado

Abra primeiro:

1. `manifest.json`, para saber o que foi produzido;
2. `measure-audit.json`, para conferir a duração das vozes;
3. o PDF de visualização, para localizar erros visuais;
4. o `.mscz`, para ouvir e editar;
5. o `.omr`, se o símbolo foi interpretado incorretamente na origem.

Um arquivo metricamente válido ainda pode conter notas erradas. A revisão deve
conferir, no mínimo:

- fórmulas e quantidade de compassos;
- abreviações e ordem dos instrumentos;
- claves e transposições;
- divisão de vozes;
- quiálteras;
- acidentes e ligaduras;
- duplicações orquestrais;
- letras e sua associação às notas.

## 7. Organizar uma geração para revisão

Antes de iniciar uma nova obra, também é possível organizar uma geração existente:

```powershell
rescore project-review "Choros 9 - páginas 3 a 6" `
  --score output/choros/continuous/choros9-continuous.musicxml `
  --musescore output/choros/continuous/choros9-continuous.mscz `
  --score-pdf output/choros/continuous/choros9-continuous-A3.pdf `
  --source-pdf "Choros N9 (Grade).pdf" `
  --pages 3-6 `
  --artifacts-dir output/choros/continuous
```

A execução aparece em `projects/`, com um índice HTML, a partitura editável, o PDF,
os logs originais e um ou mais pacotes de correção. Use `--batch-size` para limitar
quantos compassos suspeitos entram em cada pacote. O PDF fonte não é duplicado.

Se `rescore` não estiver no `PATH` do PowerShell, ative o ambiente e use o executável
diretamente, por exemplo `.\.venv\Scripts\rescore.exe doctor`, ou reinstale o projeto
com `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.

Uma execução revisada pode virar a versão principal do projeto:

```powershell
rescore project-promote projects/minha-obra
```

Isso publica `partitura.mscz`, `partitura.musicxml`, `partitura.pdf` e `index.html`
na raiz do projeto. Use `project-review ... --promote` para criar e promover em uma
etapa. Uma pasta com `REPROVADO.txt` é bloqueada, e um MSCZ precisa passar pela
reexportação estrutural antes da promoção.

## 7.1. Movimentos completos da Sinfonia nº 10

```powershell
python run.py --file "partitura.pdf" --movement 1 --promote  # páginas 7-41
python run.py --file "partitura.pdf" --movement 2 --promote  # páginas 42-66
python run.py --file "partitura.pdf" --movement 3 --promote  # páginas 67-99
python run.py --file "partitura.pdf" --movement 4 --promote  # páginas 100-200
```

Retire `--promote` quando quiser apenas gerar e inspecionar a saída em `output/`.
Use `--force` somente quando quiser executar o OMR novamente. Os movimentos II e IV
usam a leitura de fórmulas da própria fonte; não se aplica uma fórmula única a todo
o intervalo.

## 7.2. Rodar novamente depois de corrigir no MuseScore

Edite a versão principal diretamente:

```text
projects/<obra>/partitura.mscz
```

Depois salve no MuseScore e execute:

```powershell
python run.py --file "arquivo.pdf" --fix ok
```

O ReScore localiza todos os projetos associados ao PDF pelo SHA-256, abre cada
`partitura.mscz` corrigido com o MuseScore, reexporta MusicXML e PDF, executa o
preflight estrutural, cria uma nova pasta imutável em `runs/` e atualiza os arquivos
`partitura.*` da raiz. Se o arquivo estiver corrompido, tiver compassos longos ou
incompletos, ou o projeto possuir `REPROVADO.txt`, a promoção é recusada.

`--fix ok` é para a partitura principal completa. Correções dos pacotes curtos de
treinamento continuam usando `rescore dataset-fix`, pois precisam preservar o mapa
compasso × pauta e o nome do revisor.

## 8. Processar uma grade escaneada

O assistente inclui um perfil experimental:

```powershell
python run.py `
  --profile choros9 `
  --file "grade-escaneada.pdf" `
  --pages 3-10 `
  --dpi 300
```

Com uma abertura transcrita manualmente:

```powershell
python run.py `
  --profile choros9 `
  --file "grade-escaneada.pdf" `
  --pages 3 `
  --reference-mscz "referencia-manual.mscz"
```

O perfil atual considera verificados apenas os três primeiros compassos dessa
referência e ignora qualquer quarto compasso inacabado.

As páginas são isoladas somente durante a recuperação, e cada falha aparece no
manifesto do lote. Se o intervalo contínuo começa na página 3, o resultado final fica
em `continuous/choros9-continuous.mscz`, acompanhado de
`continuous/choros9-continuous-A3.pdf`. O PDF usa uma página A3 horizontal por folha
fonte, com os compassos no mesmo sistema. Scans manuscritos ou muito degradados ainda
exigem consideravelmente mais revisão que uma edição digital.

Para validar a abertura confirmada em 4/4 e o filtro de anotações:

```powershell
python run.py `
  --profile choros9 `
  --file "Choros N9 (Grade).pdf" `
  --pages 3-7
```

As páginas 3-7 herdam 4/4. O relatório `scan-preprocess.json` informa se alguma
anotação externa foi detectada, sua caixa, continuidade e quantidade de pixels
removidos.

Para páginas densas, `audiveris-families/focus-report.json` registra os recortes
verticais ampliados a 200% e informa se as leituras de teclas/harpas e cordas foram
aceitas. A fórmula 4/4 e as claves fixas aparecem somente onde mudam; metadados
copiados do começo de um recorte não são repetidos na partitura contínua.

O arquivo `continuous/playability-report.json` lista acordes impossíveis encontrados
em linhas monofônicas, a nota destinada a cada executante e qualquer altura descartada
por exceder o número de músicos daquela pauta. Esse relatório deve ser conferido
junto ao PDF, pois consistência mecânica não prova que a altura reconhecida está
correta.

## Diagnóstico de problemas

### O MuseScore informa voz longa ou compasso incompleto

Confirme a fórmula, abra `measure-audit.json` e identifique parte, pauta e voz. Não
aumente o tamanho do compasso para esconder o erro. Corrija a duração, a quiáltera
ou a voz responsável.

### O instrumento está associado à pauta errada

Confira `instrument-map.json` e `instrument-map-resolved.json`. Abreviações pouco
legíveis devem ser resolvidas com a ordem vertical e a clave, nunca apenas com uma
semelhança de notas.

### Muitas notas estão erradas em uma digitalização

Confira primeiro a imagem renderizada. Aumentar DPI nem sempre melhora o resultado:
linhas engrossadas podem piorar hastes e acidentes. Compare a página completa com a
tentativa por compasso e corrija no projeto `.omr` quando necessário.
