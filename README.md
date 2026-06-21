# Analisador de BDGDs

Analisador de BDGDs é uma aplicação desktop desenvolvida em Python para análise de inconsistências na Base de Dados Geográfica da Distribuidora (BDGD) da ANEEL. 

A ferramenta automatiza um pipeline completo de dados, cobrindo as etapas de extração das bases via API pública da ANEEL, importação para banco de dados DuckDB, reconstrução topológica da rede por algoritmo BFS, execução de dez regras de verificação de inconsistências, conversão para o simulador OpenDSS e simulação de fluxo de potência em modo Diário. 

Os resultados são apresentados em um Dashboard com gráficos interativos por regra e em mapas HTML autocontidos da rede MT, com visualização georreferenciada das inconsistências diretamente sobre o traçado da rede primária. Toda a ferramenta opera por meio de uma interface gráfica Tkinter, sem necessidade de programação pelo usuário.

Desenvolvida para o Trabalho de Conclusão de Curso do MBA em Data Science & Analytics para Operações — Poli USP PRO.

## Pré-requisitos

- Python 3.10 ou superior
- OpenDSS instalado (para o módulo de simulação)

## Instalação

1. Clone o repositório:
   git clone https://github.com/msnozela/Analisador-de-BDGDs.git
   cd Analisador-de-BDGDs

2. Instale as dependências:
   pip install -r requirements.txt

3. Execute a ferramenta:
   python app.py

## Estrutura do projeto

- core/     → módulos de lógica de negócio
- ui/       → interface gráfica (Tkinter)
- app.py    → ponto de entrada da aplicação

## Pastas criadas automaticamente

Ao executar a ferramenta, as seguintes pastas são criadas 
automaticamente na raiz do projeto:

- BDGDs/                  → arquivos ZIP baixados
- BDGDs Extraídas/        → GDBs extraídos
- Bancos Duckdb/          → bancos de dados DuckDB
- Mapas/                  → mapas HTML gerados
- Resultado Consultas/    → exports Excel
- DDA/                    → tabelas de referência (inserir manualmente)

## Licença

MIT License — veja o arquivo LICENSE para detalhes.
