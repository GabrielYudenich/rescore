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
- `scan.py`: reforça barras confirmadas, recorta compassos e amplia tentativas;
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
6. reunião dos candidatos em um único MusicXML.

O recorte por compasso reduz a quantidade de linhas concorrentes que o reconhecedor
precisa interpretar. Ele não inventa a posição de uma barra: uma separação só é
usada quando a estrutura visual oferece evidência suficiente.

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
