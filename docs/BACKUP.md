# Backup e migração

O ambiente virtual e os resultados intermediários podem ser reconstruídos. Para
levar o ReScore a outro computador sem copiar vários gigabytes, guarde:

- o repositório Git, ou confirme que todos os commits estão no GitHub;
- `data/`, quando houver exemplos, alinhamentos ou correções ainda não publicados;
- `projects/`, com as partituras principais e o histórico de revisão;
- PDFs, imagens, MusicXML e MuseScore particulares mantidos fora do Git;
- arquivos locais de contexto, configuração e anotações que estejam ignorados pelo Git.

Estas pastas normalmente **não precisam** entrar no backup enxuto:

- `.venv/` e `venv/`: são recriados pelo `requirements.txt`;
- `tools/*-env/`: ambientes auxiliares também podem ser reinstalados;
- `tmp/`: arquivos temporários;
- `output/`: resultados reproduzíveis, desde que nenhuma correção exista somente ali;
- caches como `__pycache__/` e `.pytest_cache/`.

Antes de apagar `output/`, verifique se há algum `.mscz`, `.musicxml`, relatório ou
correção que ainda não foi promovido para `projects/` ou incorporado em `data/`.
Audiveris e MuseScore são programas externos e não são instalados pelo `pip`.
Reinstale-os no computador novo ou guarde seus instaladores. Pesos de modelos e
ferramentas auxiliares grandes também devem ser baixados novamente, salvo quando
for importante preservar exatamente uma versão local.

## Restaurar no Windows

Depois de copiar ou clonar a pasta:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\rescore.exe doctor
```

Para desenvolver e executar as verificações adicionais:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
```

Se `doctor` não encontrar os programas externos, configure `RESCORE_AUDIVERIS` e
`RESCORE_MUSESCORE` com os novos caminhos.
