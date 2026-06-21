# Analisador de BDGDs

Ferramenta desktop para análise de inconsistências na Base de Dados 
Geográfica da Distribuidora (BDGD) da ANEEL.

Desenvolvida como TCC de MBA em Data Science & Analytics — USP.

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