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

Execuções posteriores usam o manifesto e as miniaturas privadas como cache. Um
documento é reutilizado somente quando hash, páginas amostradas e miniaturas
coincidem. No primeiro corpus público, a repetição caiu de aproximadamente 290
segundos para menos de 6 segundos, reutilizando 964 documentos.

Valide sempre um currículo antes de usá-lo:

```powershell
rescore corpus-curriculum-validate `
  data/visual-curriculum/visual-curriculum.json
```

Descubra fontes potenciais de supervisão e execute probes por estilo:

```powershell
rescore corpus-discover-pairs alimentar --output data/supervised-discovery
rescore corpus-omr-probe `
  --curriculum data/visual-curriculum/visual-curriculum.json `
  --private-map data/visual-curriculum/private-map.json `
  --output data/omr-probes
```

Os probes são retomáveis e usam a página original, não a miniatura. Antes do OMR,
o pipeline detecta pautas predominantemente verticais e corrige páginas giradas
90 graus. O primeiro benchmark reconheceu 9 de 12 estilos; grade muito reduzida,
impressão degradada e manuscrito permanecem como regressões explícitas.

Consolide e audite os resultados públicos:

```powershell
rescore corpus-benchmark `
  --curriculum data/visual-curriculum/visual-curriculum.json `
  --pairs data/supervised-discovery/supervised-candidates.json `
  --probes data/omr-probes/omr-probes.json `
  --output data/benchmark-v1.json
rescore privacy-audit data/benchmark-v1.json
```

`unlabeled-visual` e `self-supervised-only` significam que a página ensina
diversidade visual, mas não fornece notas corretas. Um resultado automático do
Audiveris não vira gabarito. O treinamento supervisionado de notas continua
exigindo MusicXML/MSCZ revisado ou transcrito por uma pessoa.

O currículo publicado é um artefato derivado distribuído nos mesmos termos
AGPL-3.0-or-later do projeto. Ele não inclui PDFs, fotos, miniaturas, títulos,
autores, nomes de arquivos ou caminhos locais.
