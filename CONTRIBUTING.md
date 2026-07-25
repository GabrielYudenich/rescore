# Como contribuir

O ReScore aceita contribuições de código, documentação, testes, anotações musicais
e conjuntos de dados. A prioridade é produzir resultados verificáveis, não apenas
mais notas.

## Ambiente

```powershell
py -3.11 -m venv venv
.\venv\Scripts\python.exe -m pip install -e .
.\venv\Scripts\python.exe -m pip install pytest ruff
.\venv\Scripts\python.exe -m pytest
```

No Linux ou macOS, use `python3.11` e `venv/bin/python`.

## Código

- Preserve a duração exata de cada compasso.
- Não corrija um erro de reconhecimento aumentando a fórmula de compasso.
- Não invente alturas, vozes ou quiálteras para preencher lacunas.
- Registre incerteza e procedência em formatos legíveis por máquina.
- Inclua testes para regressões estruturais.
- Mantenha arquivos gerados, partituras e modelos fora do Git.

Antes de enviar:

```powershell
ruff check src tests
ruff format --check src tests
python -m pytest
python -m compileall -q src run.py
```

## Dados musicais

Uma contribuição de dados deve usar o manifesto descrito em
[`docs/DATASET.md`](docs/DATASET.md). Ao contribuir, você declara que:

- informou corretamente a origem do material;
- possui permissão para oferecer os arquivos sob a licença declarada;
- não incluiu material comprado, confidencial ou restrito;
- informou quais compassos foram realmente revisados por uma pessoa;
- aceita que erros possam ser corrigidos ou que a amostra seja removida.

Não abra uma pull request contendo PDFs, fotos, MSCZ ou MusicXML brutos. Primeiro
envie apenas o manifesto proposto e a documentação da licença. A equipe indicará o
repositório de dados adequado depois da revisão.

## Transcrições

Uma transcrição humana útil precisa preservar:

- ordem e identidade dos instrumentos;
- claves e mudanças de clave;
- fórmulas de compasso e mudanças métricas;
- vozes independentes;
- grupos irregulares com sua razão exata;
- notas, pausas, acidentes e ligaduras;
- associação entre sílabas e notas, quando houver voz.

Layout editorial, quebras de página e espaçamento visual podem ser simplificados.

## Commits

Prefira commits pequenos e descritivos. Nunca use um commit para misturar código
com material musical. Ao enviar uma contribuição, confirme no texto da pull request
quais testes foram executados e se existem mudanças de dados.
