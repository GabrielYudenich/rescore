# Arquitetura

## Visão geral

O ReScore separa reconhecimento visual, interpretação musical e validação. Essa
separação permite substituir ou corrigir uma etapa sem repetir todo o OMR.

```text
PDF
 └─ renderização por página
     ├─ pré-processamento opcional para digitalização
     └─ Audiveris
         ├─ projeto .omr
         └─ MusicXML bruto
             ├─ associação de pautas e instrumentos
             ├─ normalização de vozes, compassos e quiálteras
             ├─ auditoria métrica
             └─ MuseScore
                 ├─ .mscz editável
                 ├─ PDF de conferência
                 └─ validação da representação importada
```

## Módulos

- `pages.py`: interpreta intervalos e listas de páginas;
- `pdf.py`: consulta e renderiza PDF;
- `scan.py`: filtra anotações externas, reforça barras confirmadas, recorta
  compassos e amplia tentativas;
- `pipeline.py`: coordena ferramentas, cache, artefatos e validações;
- `musicxml.py`: lê, canoniza e compara MusicXML/MXL;
- `normalize.py`: regras de estrutura, vozes, métricas, claves e instrumentos;
- `choros9.py`: perfil experimental para grades orquestrais escaneadas;
- `mscz.py`: inspeciona e valida a estrutura interna do arquivo MuseScore;
- `dataset.py`: importa pares supervisionados e impede vazamento de itens privados;
- `alignment.py`: detecta barras, propõe regiões de compassos e gera revisão visual;
- `staff_alignment.py`: detecta a extensão do sistema, divide pautas físicas e
  associa perfis condensados às partes MusicXML sem reconhecer notas;
- `training_export.py`: recorta células compasso × pauta, serializa alvos MusicXML
  e impede que propostas não revisadas sejam usadas como verdade de treino;
- `review.py`: promove camadas completas após revisão humana, registra auditoria
  e invalida exportações supervisionadas antigas;
- `tooling.py`: localiza Audiveris e MuseScore.

## Alinhamento supervisionado

O alinhador trabalha sobre o número de compassos confirmado no manifesto. Ele não
infere a quantidade pela densidade de notas. Linhas verticais são detectadas em uma
cópia reduzida, agrupadas e avaliadas por suporte, regularidade e cobertura da
página. As coordenadas selecionadas são convertidas de volta para a resolução
original.

Cada região recebe número de compasso, caixa em pixels e caixa normalizada. Uma
imagem transparente de sobreposição e um HTML local permitem verificar a proposta.
O estado inicial é sempre `machine-proposed`; passar nas verificações geométricas
não equivale a revisão musical humana.

A etapa seguinte encontra a espinha vertical contínua de uma barra já confirmada,
estima o espaçamento entre as cinco linhas e cria bandas sem depender da densidade
das notas. Perfis explícitos representam instrumentos condensados com vários
alvos, pautas de teclado por número e linhas de percussão de uma linha. A grade
resultante contém uma célula normalizada para cada `compasso × pauta`.

O exportador supervisionado usa essa grade sem redimensionar ou recomprimir a
fonte: cada célula vira PNG e recebe eventos/tokens determinísticos. Pautas
condensadas preservam todos os fluxos de destino; alvos equivalentes são
identificados por hash, mas não são apagados. Checksums cobrem imagem e alvo.

## PDF digital

Em um PDF digital limpo, a página é renderizada em alta resolução e enviada
diretamente ao Audiveris. Quando existe uma referência revisada, o resultado bruto
pode ser comparado e reorganizado de acordo com a estrutura instrumental do modelo.

## Grade escaneada

Uma página escaneada passa por tentativas adicionais:

1. detecção de linhas de pauta e barras verticais longas;
2. reforço apenas de barras sustentadas pela geometria da página;
3. OMR da página completa;
4. se necessário, isolamento dos compassos detectados;
5. nova tentativa ampliada por compasso;
6. releitura vertical ampliada das famílias mais densas;
7. reunião dos candidatos em um único MusicXML;
8. reconstrução posicional de linhas densas cuja soma de durações excede o compasso.

O recorte por compasso reduz a quantidade de linhas concorrentes que o reconhecedor
precisa interpretar. Ele não inventa a posição de uma barra: uma separação só é
usada quando a estrutura visual oferece evidência suficiente.

No perfil do Choros 9, a geometria das 24 pautas localizadas permite criar dois
recortes adicionais a 200%: teclas/harpas e cordas. Esses recortes conservam todos
os compassos da página e reduzem a concorrência vertical. Só substituem a família
correspondente quando o OMR devolve exatamente a quantidade esperada de pautas e
compassos; caso contrário, o candidato anterior é preservado.

Depois do OMR integral, a quantidade de compassos é comparada ao número de
intervalos entre barras confirmadas. Um resultado curto é rejeitado e ativa o
recorte isolado. Se apenas o último recorte falhar, mas a leitura integral tiver
preservado o compasso final entre a última barra interna e a barra dupla, somente
esse último compasso é reaproveitado. Pautas omitidas em um recorte são alinhadas
pelas abreviações legíveis e pela ordem orquestral; a posição ausente recebe um
compasso vazio em vez de deslocar os instrumentos abaixo dela.

O MusicXML do Audiveris preserva a coordenada horizontal de cada cabeça de nota.
Quando uma linha rápida possui espaçamento visual regular, mas uma duração
evidentemente impossível desloca as notas seguintes, o perfil escaneado quantiza
essas coordenadas em uma grade de semicolcheias ou fusas. Alturas não são criadas.
Linhas sustentadas e quiálteras reconhecidas ficam fora desse ajuste. O relatório de
normalização registra quantos eventos foram reposicionados e qualquer símbolo
impossível descartado.

### Anotações externas

O filtro de digitalização não decide pela aparência isolada de um símbolo. Uma
cunha só é classificada como anotação externa quando possui dois traços
diagonais contínuos, inclinações opostas, ápice comum e abertura superior a
seis espaços de pauta. Isso separa a grande marca manuscrita da página 7 de
hairpins, acentos, ligaduras, indicações de quiáltera e marcas de ensaio.
Linhas horizontais da edição são restauradas depois da limpeza.

## Normalização métrica

MusicXML representa a duração com divisões inteiras. Quiálteras, várias vozes e
mudanças de fórmula tornam perigoso somar valores arredondados. O ReScore mantém
frações durante a auditoria e verifica cada combinação de parte, pauta, compasso e
voz.

Uma fórmula fornecida pelo usuário funciona como restrição estrutural. O programa
não deve alongar um compasso para acomodar eventos excedentes. Eventos ambíguos são
registrados para revisão.

## Associação instrumental

A associação considera nome, abreviação, ordem vertical, clave e contexto do sistema.
Em grades condensadas, uma pauta visual pode representar mais de um executante.
Partes monofônicas podem ser separadas durante a normalização, enquanto instrumentos
polifônicos preservam acordes e múltiplas vozes.

Duplicações entre famílias orquestrais são tratadas como uma pista de consistência.
Uma semelhança rítmica ou melódica isolada não autoriza copiar automaticamente o
conteúdo de uma pauta para outra.

### Calibração por referência manual

Uma pequena transcrição revisada pode definir a estrutura instrumental sem se
tornar uma regra fixa de notas. Na abertura escaneada do Choros 9, a referência:

- expande 24 pautas visuais para 35 partes e 37 pautas reais;
- identifica uníssonos confirmados entre executantes;
- registra quais partes usam quiálteras;
- mede separadamente coincidência rítmica e coincidência de altura;
- preserva somente os compassos explicitamente marcados como verificados.

Compassos incompletos posteriores da referência são removidos da cópia de trabalho
e listados no relatório. Para páginas novas, a referência fornece a estrutura da
orquestra, mas não autoriza copiar material musical antigo.

As páginas continuam sendo reconhecidas isoladamente para permitir retomada, mas a
publicação não é fragmentada. O montador contínuo acrescenta cada bloco de compassos
ao modelo de 35 partes, separa acordes de pautas monofônicas entre os executantes,
valida todas as vozes em 4/4 e exporta `.mscz` e PDF A3 horizontal. Quebras de página
são decisões de visualização; não criam novas partituras nem reiniciam a contagem.

## Ciclo de correção humana

A saída musical pode entrar em um ciclo auditável sem substituir a transcrição
inteira:

```text
MusicXML candidato
  → detector estrutural → issues.jsonl + issues.html
  → seletor de trechos  → review-pack.mscz + mapa de origem
  → edição no MuseScore → resposta humana identificada
  → dataset-fix         → override versionado
  → exportação de treino aplica somente os fluxos corrigidos
```

O pacote carrega atributos herdados, mas contém apenas partes e compassos afetados.
Eventos suspeitos não são copiados: cada pauta nasce como um compasso de pausas
exatamente completo e passa por auditoria antes e depois da importação no MuseScore.
Um identificador curto e visível associa o compasso isolado à origem. Na importação,
hashes, contagem, identificadores, partes e limites do dataset são verificados antes
de gravar qualquer histórico. O conteúdo de base é imutável; a correção mais recente
prevalece somente na chave `compasso × parte × pauta`, carregando em conjunto suas
vozes. Isso conserva tanto a
previsão anterior quanto a resposta humana para aprendizado ativo e auditoria.

## Artefatos e retomada

Cada etapa grava seus próprios artefatos e logs. Uma execução posterior reutiliza o
MusicXML já reconhecido, salvo quando `--force` é solicitado. Isso torna possível
melhorar a normalização sem executar novamente a etapa mais demorada.

O manifesto registra caminhos, ferramentas, páginas, parâmetros e resumo de
qualidade. Os relatórios de auditoria explicam por que um arquivo foi aceito ou
rejeitado.

## Limite do sistema

O objetivo atual é produzir um rascunho estruturalmente válido e reduzir o trabalho
manual. Não existe promessa de transcrição automática perfeita. A validação métrica
garante consistência temporal, mas não prova que alturas, articulações, letras ou
instrumentos foram reconhecidos corretamente.
