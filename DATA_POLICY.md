# Política de dados do ReScore

Código aberto e dados abertos são decisões separadas. A licença AGPL do programa
não transforma uma partitura em material livre e não concede permissão para
redistribuir uma fotografia, uma edição musical, uma transcrição ou pesos de
modelo derivados dela.

## Princípios

1. Toda amostra precisa ter procedência explícita.
2. Material privado nunca entra no catálogo público.
3. A ausência de informação de direitos significa `private`, não `public`.
4. Uma obra em domínio público pode estar em uma edição ou digitalização ainda
   protegida. A situação da obra, da edição e da imagem deve ser verificada.
5. Permissão para estudar localmente não equivale a permissão para redistribuir.
6. Nenhuma partitura é incorporada ao Git como conveniência.
7. Pesos treinados recebem uma ficha própria com origem dos dados, limitações e
   licença compatível.

## Estados de publicação

- `private`: disponível apenas na máquina do colaborador. É o padrão seguro.
- `public`: pode aparecer no catálogo exportado, mas somente quando
  `redistributable` for verdadeiro e a licença da fonte estiver registrada.

O comando `rescore dataset-public-catalog` aplica esse filtro. Itens privados não
aparecem nem como metadados no catálogo resultante.

## O que vai para cada lugar

| Conteúdo | GitHub | Repositório de dados |
| --- | --- | --- |
| Código, testes e esquemas | Sim | Não é necessário |
| Documentação e catálogo sem arquivos privados | Sim | Opcional |
| PDFs, fotos e digitalizações | Não | Somente com direito confirmado |
| MusicXML/MSCZ de referência | Não por padrão | Somente com direito confirmado |
| Pesos de modelo | Não no histórico Git | Registro versionado próprio |
| Contexto local e anotações privadas | Nunca | Nunca |

Para conjuntos grandes, recomenda-se um repositório versionado de dados, como
Hugging Face Datasets ou Zenodo, mantendo no GitHub apenas o manifesto, o esquema e
as instruções de obtenção.

## Revisão de direitos

Antes de tornar um item público, registrar:

- título, compositor e identificador da obra;
- origem exata da imagem ou PDF;
- detentor e ano da edição ou digitalização;
- licença ou base jurídica aplicável;
- nome do colaborador e data da verificação;
- permissão para redistribuir imagem e transcrição;
- restrições de uso, se existirem.

Na dúvida, mantenha o item privado e solicite revisão. O projeto não fornece
aconselhamento jurídico.

## Remoção

Uma solicitação de remoção deve identificar o item, a fonte e o fundamento. O
catálogo público e futuras versões do conjunto serão corrigidos. Versões e pesos já
distribuídos podem não ser tecnicamente recuperáveis; por isso a verificação antes
da publicação é obrigatória.
