# Currículo visual anônimo

O comando `corpus-feed` transforma um diretório local de partituras em um mapa de
diversidade visual. Ele não transcreve cada obra nem cria arquivos MuseScore.

```powershell
rescore corpus-feed alimentar `
  --output data/visual-curriculum `
  --pages-per-document 3 `
  --clusters 12
```

Para cada documento único, o processo escolhe páginas distribuídas entre início,
meio e fim. O arquivo público contém somente identificadores anônimos, medidas
visuais numéricas, cluster e split. Caminhos e miniaturas permanecem no mapa
privado ignorado pelo Git.

As medidas atuais cobrem proporção da página, densidade de tinta, contraste,
entropia, bordas, linhas horizontais de pauta, componentes conectados e cor. O
modelo de clusters é ajustado apenas com `train`; `validation` e `test` não
participam do ajuste. Documentos do mesmo grupo nunca aparecem em splits
diferentes.

Valide sempre um currículo antes de usá-lo:

```powershell
rescore corpus-curriculum-validate `
  data/visual-curriculum/visual-curriculum.json
```

`unlabeled-visual` e `self-supervised-only` significam que a página ensina
diversidade visual, mas não fornece notas corretas. Um resultado automático do
Audiveris não vira gabarito. O treinamento supervisionado de notas continua
exigindo MusicXML/MSCZ revisado ou transcrito por uma pessoa.

O currículo publicado é um artefato derivado distribuído nos mesmos termos
AGPL-3.0-or-later do projeto. Ele não inclui PDFs, fotos, miniaturas, títulos,
autores, nomes de arquivos ou caminhos locais.
