# Guia de uso

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

## 7. Processar uma grade escaneada

O assistente inclui um perfil experimental:

```powershell
python run.py `
  --profile choros9 `
  --pdf "grade-escaneada.pdf" `
  --pages 3-10 `
  --dpi 300
```

Com uma abertura transcrita manualmente:

```powershell
python run.py `
  --profile choros9 `
  --pdf "grade-escaneada.pdf" `
  --pages 3 `
  --reference-mscz "referencia-manual.mscz"
```

O perfil atual considera verificados apenas os três primeiros compassos dessa
referência e ignora qualquer quarto compasso inacabado.

As páginas são isoladas e cada falha aparece no manifesto do lote. Esse modo é mais
resiliente, porém scans manuscritos ou muito degradados exigem consideravelmente mais
revisão que uma edição digital.

Para validar a abertura confirmada em 4/4 e o filtro de anotações:

```powershell
python run.py `
  --profile choros9 `
  --pdf "Choros N9 (Grade).pdf" `
  --pages 3-7
```

As páginas 3-7 herdam 4/4. O relatório `scan-preprocess.json` informa se alguma
anotação externa foi detectada, sua caixa, continuidade e quantidade de pixels
removidos.

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
