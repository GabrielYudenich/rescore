# Conjunto de dados supervisionado

O ReScore aprende com pares de entrada e resposta:

```text
imagem da partitura + localização dos compassos
                    ↓
MusicXML revisado + metadados musicais
```

Guardar apenas imagens não é suficiente. O modelo precisa saber quais notas,
durações, claves, vozes, instrumentos e quiálteras eram corretos. O MusicXML
revisado funciona como verdade de referência; o manifesto explica exatamente que
trecho foi conferido.

## Estrutura

```text
data/meu-conjunto/
  rescore-dataset.json
  items/
    identificador/
      source/
        page-0001.png
      annotation/
        ground-truth.musicxml
        source.mscz
      alignment/
        measure-regions.json
        page-0001-overlay.jpg
        review.html
        staff-regions.json
        page-0001-staff-overlay.jpg
        staff-review.html
  public-catalog.json
```

`data/` é ignorado pelo Git. Cada arquivo possui SHA-256 no manifesto para detectar
alterações acidentais. O esquema formal está em
[`schemas/rescore-dataset-v1.schema.json`](../schemas/rescore-dataset-v1.schema.json).

## Criar e alimentar

```powershell
rescore dataset-init data/rescore-local

rescore dataset-add data/rescore-local `
  --id exemplo-pagina-1 `
  --images scans/pagina-1.png `
  --score revisoes/exemplo.mscz `
  --composer "Compositor" `
  --work "Obra" `
  --source-type handwritten `
  --visibility private `
  --rights-status "verificação pendente" `
  --source-license "não definida" `
  --measure-start 1 `
  --measure-end 8 `
  --verification human-transcribed `
  --alignment-status inferred `
  --writer "Nome do copista"

rescore dataset-validate data/rescore-local
rescore dataset-public-catalog data/rescore-local `
  --output data/rescore-local/public-catalog.json
```

Ao receber MSCZ ou MXL, o importador conserva a fonte e pede ao MuseScore uma cópia
MusicXML. O arquivo editável nunca substitui a referência original.

## Alinhar compassos

Depois de importar o par, o alinhador pode propor caixas para cada compasso:

```powershell
rescore dataset-align data/rescore-local `
  --id exemplo-pagina-1 `
  --page-measures 8,8
```

`--page-measures` informa quantos compassos verificados existem em cada imagem.
Quando a divisão é uniforme, o argumento pode ser omitido. O alinhador:

- reduz temporariamente a página para detectar geometria sem perder o original;
- localiza segmentos verticais longos;
- agrupa linhas coincidentes;
- escolhe uma sequência estrutural compatível com a contagem declarada;
- grava caixas em pixels e coordenadas normalizadas;
- produz imagens com numeração e um `review.html`.

O resultado nasce com `review_status=machine-proposed`. Uma validação estrutural
garante cobertura e ordem, mas não significa que uma pessoa aprovou as caixas:

```powershell
rescore alignment-validate `
  data/rescore-local/items/exemplo-pagina-1/alignment/measure-regions.json
```

As imagens de sobreposição devem ser conferidas antes do treino. O algoritmo
prefere o início real do sistema para que o primeiro compasso conserve clave,
armadura e fórmula de compasso, evitando começar sobre uma haste alinhada.

## Alinhar pautas e instrumentos

Com os compassos alinhados, a segunda passagem subdivide a página em pautas e
cria uma célula para cada par `compasso × pauta`:

```powershell
rescore dataset-align-staffs data/rescore-local `
  --id exemplo-pagina-1 `
  --profile auto

rescore staff-alignment-validate `
  data/rescore-local/items/exemplo-pagina-1/alignment/staff-regions.json
```

Os perfis atuais cobrem `menina-opening` e `choros9-opening`. Eles preservam
pautas impressas vazias como `unassigned`, permitem que uma pauta condensada
aponte para várias partes MusicXML e distinguem as duas pautas de instrumentos
como celesta, harpa e piano. No Choros, a linha de percussão é mantida como
`one-line`, em vez de ser confundida com a celesta.

O arquivo `staff-regions.json` continua com `review_status=machine-proposed`.
Os nomes e alvos são hipóteses estruturais do perfil e precisam ser conferidos
no `staff-review.html`; eles ainda não são anotações musicais aprovadas.

## Exportar exemplos de treino

Depois das duas etapas de alinhamento, o exportador gera uma imagem PNG sem perdas
para cada célula `compasso × pauta` e associa os eventos MusicXML correspondentes:

```powershell
rescore dataset-export-training data/rescore-local `
  --id exemplo-pagina-1

rescore training-export-validate `
  data/rescore-local/items/exemplo-pagina-1/training/samples.jsonl
```

O `samples.jsonl` conserva simultaneamente eventos estruturados e uma sequência
determinística de tokens. A versão inicial inclui alturas, pausas, posição rítmica,
duração, voz, tipo, pontos, acordes, notas de adorno, quiálteras, ligaduras de
duração, articulações, tremolos e letras Unicode por caractere. Relações possíveis:

- `single-target`: uma pauta visual e uma pauta MusicXML;
- `equivalent-targets`: vários músicos possuem conteúdo idêntico;
- `multi-target`: a pauta condensada aponta para fluxos diferentes;
- `unassigned`: papel pautado vazio, sem instrumento atribuído;
- `missing-target-events`: o alvo não contém eventos suficientes para uso seguro.

Gerar o arquivo não autoriza treino. `training_eligible` somente se torna verdadeiro
quando o gabarito é humano e os alinhamentos de compassos e pautas estão marcados
como `human-reviewed`. Os demais exemplos continuam úteis para a fila de revisão,
mas não entram silenciosamente no modelo.

## Registrar revisão humana

Depois de conferir integralmente os dois HTMLs de revisão, uma pessoa pode aprovar
as camadas completas com identificação explícita:

```powershell
rescore dataset-review data/rescore-local `
  --id exemplo-pagina-1 `
  --reviewer "Nome do revisor" `
  --approve-measures `
  --approve-staffs `
  --note "Conferido compasso por compasso e pauta por pauta"
```

O comando valida os arquivos antes de alterá-los, grava revisor, instante UTC e
observação em `reviews.jsonl`, atualiza checksums e marca qualquer exportação de
treino anterior como obsoleta. Depois da aprovação, execute novamente
`dataset-export-training --force`. Aprovar pautas exige que os compassos já estejam
aprovados ou sejam aprovados na mesma chamada.

Esse comando aprova a camada inteira. Se houver uma única caixa ou associação
duvidosa, não a aprove ainda; a revisão granular será uma etapa posterior.

## Corrigir trechos suspeitos

Para uma correção musical localizada, não é necessário aprovar nem reescrever a
página inteira. Primeiro gere a lista legível de suspeitas e o arquivo de trabalho:

```powershell
rescore detect-issues output/leitura.musicxml `
  --output output/revisao/issues

rescore review-pack output/leitura.musicxml `
  --issues output/revisao/issues/issues.jsonl `
  --output output/revisao/pack
```

`detect-issues` verifica, entre outros casos, vozes que ultrapassam ou não completam
o compasso, início negativo, altura ausente e duração fracionária irregular sem
quiáltera declarada. Uma suspeita não é automaticamente um erro musical; ela é uma
tarefa prioritária para o revisor. O relatório HTML apresenta compasso, parte,
instrumento provável, pauta, voz, instante e duração.

`review-pack` seleciona somente os compassos e partes afetados. Ele recompõe os
atributos herdados necessários para o trecho abrir isoladamente, substitui a leitura
suspeita por pausas de compasso válidas e gera MusicXML, MuseScore, PDF A4 paisagem,
auditoria métrica e um manifesto. As notas quebradas nunca são copiadas para o
formulário. Cada
compasso de revisão possui um código visível `RS-REVIEW-NNNN`. Esse código deve
permanecer no arquivo corrigido, pois impede que uma mudança de ordem seja aplicada
ao compasso errado.

Depois de conferir o manuscrito ou a edição fonte no MuseScore, salve o arquivo e
importe a resposta humana:

```powershell
rescore dataset-fix data/rescore-local `
  --id exemplo-pagina-1 `
  --pack output/revisao/pack/review-pack.json `
  --corrected output/revisao/pack/review-pack.mscz `
  --reviewer "Nome do revisor" `
  --note "Alturas, ritmo e quiáltera conferidos"
```

Antes de alterar o manifesto, o comando confirma:

- hashes do pacote original, da lista de problemas e da auditoria métrica;
- identidade exata entre a partitura-base do pacote e o gabarito do item;
- quantidade de compassos;
- permanência e posição de todos os identificadores;
- correspondência inequívoca das partes por ID ou nome;
- existência das partes e compassos originais no gabarito do item.

Cada execução cria `items/<id>/corrections/correction-<UTC>/` com o `.mscz` recebido,
MusicXML exportado, pacote preservado, problemas originais, diferenças por fluxo e
`overrides.json`. O gabarito de base nunca é sobrescrito. Correções novas são
acrescentadas ao histórico e a mais recente prevalece apenas para a combinação
`compasso × parte × pauta` corrigida, incluindo todas as vozes dessa pauta para
preservar sua relação polifônica. `dataset-export-training` aplica esses
overrides e registra `correction_id` no alvo supervisionado, mantendo a origem de
cada resposta auditável. A cópia do manifesto também remove caminhos absolutos da
máquina do revisor antes de entrar no dataset.

A exportação anterior é marcada como obsoleta. Rode novamente:

```powershell
rescore dataset-export-training data/rescore-local --id exemplo-pagina-1 --force
rescore dataset-validate data/rescore-local
```

Não use `dataset-fix` para uma sugestão ainda não conferida. A importação declara
que o conteúdo corrigido foi comparado por uma pessoa com a fonte musical.

## Campos importantes

- `source_type`: `printed`, `handwritten` ou `mixed`;
- `visibility`: `private` ou `public`;
- `rights.status`: situação textual da revisão de direitos;
- `rights.source_license`: licença da imagem/edição;
- `rights.redistributable`: autorização explícita para redistribuir;
- `alignment.measure_start` e `measure_end`: único intervalo que a amostra afirma
  representar;
- `alignment.status`: `verified`, `inferred` ou `unassigned`;
- `alignment.review_status`: proposta da máquina ou revisão humana;
- `alignment.regions_file`: caixas de compassos e métricas geométricas;
- `alignment.staff_regions_file`: pautas, alvos MusicXML e células compasso × pauta;
- `training.index`: índice JSONL dos recortes e alvos supervisionados;
- `training.eligible_sample_count`: quantidade liberada pela política de revisão;
- `corrections`: histórico imutável das correções musicais localizadas;
- `verification`: quanto da transcrição foi revisado;
- `writer`: copista ou mão, quando conhecida;
- `checksums`: integridade dos arquivos.

Um MSCZ pode conter compassos adicionais incompletos. Isso não os torna verdade de
referência: o intervalo do manifesto é soberano.

## Níveis de revisão

- `human-transcribed`: digitado manualmente a partir da fonte;
- `human-reviewed`: produzido por máquina e conferido integralmente;
- `partially-reviewed`: somente parte dos símbolos foi conferida;
- `machine-generated`: sem validação humana; não deve ser usado como alvo confiável.

O nível descreve o processo, não garante perfeição. Correções futuras precisam
criar nova versão e novos hashes.

## Alinhamento

No início, basta alinhar imagem/página a um intervalo de compassos. A próxima
camada terá caixas delimitadoras para sistema, pauta, compasso e símbolo. O plano
é derivar automaticamente uma proposta de alinhamento, abri-la em uma interface de
correção e guardar cada ajuste humano.

Não misture páginas de obras diferentes no mesmo item. Se uma página contém dois
sistemas que continuam um ao outro, ambos pertencem ao mesmo fluxo musical, mas
devem ter regiões próprias.

## Divisão de treino

As divisões `train`, `validation` e `test` devem ocorrer por obra, edição e mão do
copista. Separar páginas adjacentes da mesma partitura entre treino e teste cria
vazamento: o modelo memoriza aparência, instrumentação e caligrafia e parece melhor
do que realmente é.

O conjunto de teste deve conter:

- impressão digital limpa;
- impressão histórica escaneada;
- manuscrito a tinta;
- manuscrito a lápis;
- grades com instrumentos omitidos;
- polifonia, mudanças de clave, quiálteras e letras.

## Segurança de publicação

Itens privados são copiados para o conjunto local, mas são totalmente excluídos do
catálogo público. Para um item público, os três campos precisam concordar:

```text
visibility = public
rights.redistributable = true
rights.source_license = licença explícita
```

O validador rejeita combinações inseguras e caminhos que escapem da raiz do
conjunto. Consulte também [`DATA_POLICY.md`](../DATA_POLICY.md).
