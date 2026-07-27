# ReScore Community Learning Hub

## Princípios

O hub recebe somente contribuições explicitamente autorizadas. A instalação nasce
com sincronização desativada; caminhos locais, nomes de usuário, PDFs e projetos
privados nunca fazem parte de um pacote. Toda contribuição mostra uma prévia e
exige consentimento, licença redistribuível e correção humana identificada.

## Fluxo

```text
correção humana → fila local opt-in → pacote por hash → API de quarentena
→ validação de esquema/direitos → revisão → versão imutável do dataset
→ treino e benchmark reproduzíveis → manifesto assinado do modelo
→ download e verificação local → ativação com rollback
```

Contribuições não alteram imediatamente modelos em outras máquinas. Quarentena,
deduplicação e benchmark evitam envenenamento, regressões e vazamentos.

## Protocolo inicial

- esquemas e API versionados independentemente;
- blobs endereçados por SHA-256 e enviados apenas após aceitação dos metadados;
- idempotência por identificador de contribuição;
- procedência, licença da fonte, licença da anotação e prova de consentimento;
- estados `queued`, `quarantined`, `accepted`, `rejected` e `withdrawn`;
- catálogos e releases assinados, com hashes de todos os artefatos;
- clientes mantêm modelo anterior para rollback.

## Licenciamento

AGPL protege o serviço e suas modificações, mas permite cobrar por distribuição ou
serviço. Uma cláusula que proíba uso comercial do dataset não é compatível com a
definição usual de dados abertos. Portanto código, dados, pesos e marca devem ter
licenças separadas, e a escolha final do dataset precisa de revisão jurídica antes
de aceitar contribuições públicas. Até lá, o servidor opera em modo de quarentena
e não publica blobs.

## Implantação

O serviço será portátil: API ASGI, banco relacional e armazenamento de objetos.
SQLite e disco atendem desenvolvimento; PostgreSQL e armazenamento compatível com
S3 atendem produção. Nenhum provedor gratuito será requisito do protocolo.

## Executar localmente

```powershell
python -m pip install -e ".[hub]"
$env:RESCORE_HUB_ADMIN_TOKEN = "gere-um-segredo-longo"
uvicorn rescore_hub.app:app --host 127.0.0.1 --port 8000
```

Ou em container:

```powershell
docker build -f Dockerfile.hub -t rescore-hub .
docker run --rm -p 8000:8000 -v rescore-hub-data:/data `
  -e RESCORE_HUB_ADMIN_TOKEN="gere-um-segredo-longo" rescore-hub
```

Preparar não envia nada; o envio é um segundo comando deliberado:

```powershell
rescore community-prepare --output data/fila/exemplo `
  --file image=recorte.png --file target=resposta.musicxml `
  --source-license CC0-1.0 --annotation-license CC-BY-4.0 `
  --verification human-reviewed --confirm-share

rescore community-submit data/fila/exemplo --endpoint http://127.0.0.1:8000
```
