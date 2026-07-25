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
