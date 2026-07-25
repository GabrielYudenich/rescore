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

## Campos importantes

- `source_type`: `printed`, `handwritten` ou `mixed`;
- `visibility`: `private` ou `public`;
- `rights.status`: situação textual da revisão de direitos;
- `rights.source_license`: licença da imagem/edição;
- `rights.redistributable`: autorização explícita para redistribuir;
- `alignment.measure_start` e `measure_end`: único intervalo que a amostra afirma
  representar;
- `alignment.status`: `verified`, `inferred` ou `unassigned`;
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
