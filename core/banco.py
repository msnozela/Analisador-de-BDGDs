# -*- coding: utf-8 -*-
"""
core/banco.py
Lógica de leitura de File Geodatabase e criação/atualização de banco DuckDB.
Sem dependência de GUI.

NOVIDADES (requisito_modulo_banco_dados.md)
-------------------------------------------
- importar_arquivo_para_banco() : importa um .xlsx ou .csv como tabela
- carregar_pasta_dda()          : varre a pasta DDA/ e importa todos os arquivos
- verificar_dda()               : retorna status da pasta DDA (existe, lista arquivos)
"""

import os
import zipfile
import shutil
import tempfile
from pathlib import Path

import fiona
import geopandas as gpd
import duckdb
import pandas as pd


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Entidades necessárias para rodar todas as 10 regras de inconsistência
# Inclui: entidades topológicas, DDA de referência e equipamentos de regulação
ENTIDADES_MINIMAS = [
    # Topologia e rede MT/BT
    "CTMT",      # alimentadores (obrigatória)
    "SSDMT",     # segmentos MT
    "SSDBT",     # segmentos BT
    "RAMLIG",    # ramais de ligação
    # Consumidores e conexões
    "UCBT_tab",  # unidades consumidoras BT
    "UCMT_tab",  # unidades consumidoras MT
    "PIP",       # pontos de interligação/produtores
    "UNSEBT",    # unidades de subestação BT
    "UNSEMT",    # unidades de subestação MT
    # Transformadores
    "UNTRMT",    # unidades transformadoras MT
    "EQTRMT",   # equipamentos de transformador MT (R05)
    # Reguladores de tensão
    "UNREMT",    # unidades reguladoras MT
    "EQRE",     # equipamentos de regulador (R07, R10)
    # Condutores
    "SEGCON",   # catálogo de condutores (R04)
    # Tabelas de referência / DDA (normalmente carregadas pela pasta DDA)
    "TPOTAPRT", # tabela de potências aparentes (R05, R07)
    "CRVCRG",   # curvas de carga (R09)
    "TTEN",     # tabela de tensões nominais (R05 abertura)
]

PASTA_DDA = "DDA"
EXTENSOES_DDA = {".xlsx", ".csv"}


# ---------------------------------------------------------------------------
# GDB / ZIP
# ---------------------------------------------------------------------------

def extrair_gdb(zip_path: str) -> tuple[str, str]:
    """
    Extrai o arquivo ZIP em pasta temporária e localiza o .gdb interno.
    Returns: (temp_dir, gdb_path) — chamador deve apagar temp_dir após uso.
    """
    temp_dir = tempfile.mkdtemp(prefix="bdgd_")

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(temp_dir)

    gdb_path = None
    for root_dir, dirs, _ in os.walk(temp_dir):
        for d in dirs:
            if d.endswith(".gdb"):
                gdb_path = os.path.join(root_dir, d)
                break
        if gdb_path:
            break

    if not gdb_path:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError("Arquivo .gdb não encontrado dentro do ZIP.")

    return temp_dir, gdb_path


def listar_entidades_zip(zip_path: str) -> list[str]:
    """Extrai temporariamente o ZIP e retorna as camadas do .gdb."""
    temp_dir, gdb_path = extrair_gdb(zip_path)
    try:
        return sorted(fiona.listlayers(gdb_path))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def criar_ou_atualizar_banco(
    zip_path: str,
    banco_path: str,
    entidades: list[str],
    callback_progresso=None,
) -> list[str]:
    """
    Cria ou atualiza o banco DuckDB com as entidades da BDGD selecionadas.
    Entidades existentes serão sobrescritas; as demais ficam intactas.

    Returns: Lista de entidades importadas com sucesso.
    """
    temp_dir, gdb_path = extrair_gdb(zip_path)
    importadas = []

    try:
        con = duckdb.connect(banco_path)

        for i, layer in enumerate(entidades, 1):
            if callback_progresso:
                callback_progresso(f"[{i}/{len(entidades)}] Importando {layer}...")

            gdf = gpd.read_file(gdb_path, layer=layer)

            if "geometry" in gdf.columns:
                gdf = gdf.drop(columns=["geometry"])

            con.register("_temp_layer", gdf)
            con.execute(f'CREATE OR REPLACE TABLE "{layer}" AS SELECT * FROM _temp_layer')
            con.unregister("_temp_layer")
            importadas.append(layer)

        con.close()

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    if callback_progresso:
        callback_progresso(f"Concluído. {len(importadas)} entidade(s) importada(s).")

    return importadas


# ---------------------------------------------------------------------------
# Importação de arquivos externos (.xlsx / .csv)
# ---------------------------------------------------------------------------

def importar_arquivo_para_banco(
    arquivo_path: str,
    banco_path: str,
    callback_progresso=None,
) -> str:
    """
    Importa um arquivo .xlsx ou .csv como tabela no banco DuckDB.
    O nome da tabela é o nome do arquivo sem extensão.

    Args:
        arquivo_path:        Path completo do arquivo .xlsx ou .csv.
        banco_path:          Path do banco .duckdb de destino.
        callback_progresso:  Função opcional(str) para feedback.

    Returns:
        Nome da tabela criada.

    Raises:
        ValueError: extensão não suportada.
        RuntimeError: arquivo vazio ou sem colunas.
    """
    ext   = Path(arquivo_path).suffix.lower()
    nome  = Path(arquivo_path).stem  # nome sem extensão = nome da tabela

    if ext not in EXTENSOES_DDA:
        raise ValueError(f"Extensão '{ext}' não suportada. Use .xlsx ou .csv.")

    if callback_progresso:
        callback_progresso(f"Lendo {os.path.basename(arquivo_path)}...")

    if ext == ".xlsx":
        df = pd.read_excel(arquivo_path, dtype_backend="numpy_nullable")
    else:
        # Tentar detectar separador automaticamente
        try:
            df = pd.read_csv(arquivo_path, sep=None, engine="python",
                             dtype_backend="numpy_nullable")
        except Exception:
            df = pd.read_csv(arquivo_path, sep=";", dtype_backend="numpy_nullable")

    if df.empty or len(df.columns) == 0:
        raise RuntimeError(f"Arquivo '{os.path.basename(arquivo_path)}' está vazio.")

    # Limpar nomes de coluna (espaços, caracteres especiais)
    df.columns = [str(c).strip() for c in df.columns]

    if callback_progresso:
        callback_progresso(
            f"  {len(df)} linhas, {len(df.columns)} colunas → tabela '{nome}'"
        )

    con = duckdb.connect(banco_path)
    try:
        con.register("_import_temp", df)
        con.execute(f'CREATE OR REPLACE TABLE "{nome}" AS SELECT * FROM _import_temp')
        con.unregister("_import_temp")
    finally:
        con.close()

    if callback_progresso:
        callback_progresso(f"  ✔ Tabela '{nome}' criada.")

    return nome


# ---------------------------------------------------------------------------
# DDA — pasta de arquivos de referência
# ---------------------------------------------------------------------------

def verificar_dda(base_path: str) -> dict:
    """
    Verifica a pasta DDA no diretório raiz da aplicação.

    Returns dict:
        {
          "existe":   bool,
          "pasta":    str (path absoluto),
          "arquivos": list[str]  (nomes dos arquivos válidos encontrados),
        }
    """
    pasta = os.path.join(base_path, PASTA_DDA)
    existe = os.path.isdir(pasta)

    arquivos = []
    if existe:
        for f in sorted(os.listdir(pasta)):
            if Path(f).suffix.lower() in EXTENSOES_DDA:
                arquivos.append(f)

    return {
        "existe":   existe,
        "pasta":    pasta,
        "arquivos": arquivos,
    }


def carregar_pasta_dda(
    base_path: str,
    banco_path: str,
    callback_progresso=None,
) -> dict:
    """
    Varre a pasta DDA/ e importa todos os .xlsx/.csv como tabelas no banco.
    Não lança exceção se a pasta não existir — retorna status adequado.

    Returns dict:
        {
          "dda_existe":  bool,
          "importadas":  list[str],   (nomes das tabelas criadas com sucesso)
          "erros":       list[str],   (mensagens de erro por arquivo)
        }
    """
    info = verificar_dda(base_path)
    resultado = {"dda_existe": info["existe"], "importadas": [], "erros": []}

    if not info["existe"]:
        if callback_progresso:
            callback_progresso(
                "ℹ Pasta DDA não encontrada — nenhuma tabela de referência importada."
            )
        return resultado

    if not info["arquivos"]:
        if callback_progresso:
            callback_progresso("ℹ Pasta DDA encontrada, mas sem arquivos .xlsx/.csv.")
        return resultado

    total = len(info["arquivos"])
    if callback_progresso:
        callback_progresso(
            f"📂 Pasta DDA encontrada: {total} arquivo(s) a importar..."
        )

    for i, nome_arq in enumerate(info["arquivos"], 1):
        arq_path = os.path.join(info["pasta"], nome_arq)
        if callback_progresso:
            callback_progresso(f"  [{i}/{total}] {nome_arq}")
        try:
            nome_tabela = importar_arquivo_para_banco(
                arq_path, banco_path, callback_progresso
            )
            resultado["importadas"].append(nome_tabela)
        except Exception as e:
            msg = f"  ⚠ Erro em '{nome_arq}': {e}"
            resultado["erros"].append(msg)
            if callback_progresso:
                callback_progresso(msg)

    if callback_progresso:
        n_ok  = len(resultado["importadas"])
        n_err = len(resultado["erros"])
        callback_progresso(
            f"DDA concluído: {n_ok} tabela(s) importada(s)"
            + (f", {n_err} erro(s)." if n_err else ".")
        )

    return resultado


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------

def listar_bancos(duckdb_path: str) -> list[str]:
    """Retorna lista de arquivos .duckdb disponíveis."""
    if not os.path.exists(duckdb_path):
        return []
    return sorted([f for f in os.listdir(duckdb_path) if f.endswith(".duckdb")])


def listar_tabelas_banco(banco_path: str) -> list[str]:
    """Retorna as tabelas existentes em um banco DuckDB."""
    con = duckdb.connect(banco_path, read_only=True)
    tabelas = con.execute(
        "SELECT table_name FROM information_schema.tables ORDER BY table_name"
    ).fetchall()
    con.close()
    return [t[0] for t in tabelas]
