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
- `tooling.py`: localiza Audiveris e MuseScore.

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
6. reunião dos candidatos em um único MusicXML;
7. reconstrução posicional de linhas densas cuja soma de durações excede o compasso.

O recorte por compasso reduz a quantidade de linhas concorrentes que o reconhecedor
precisa interpretar. Ele não inventa a posição de uma barra: uma separação só é
usada quando a estrutura visual oferece evidência suficiente.

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
