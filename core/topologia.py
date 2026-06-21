# -*- coding: utf-8 -*-
"""
core/topologia.py
Algoritmo BFS para reconstrução da topologia da rede elétrica a partir da BDGD.
Sem dependência de GUI.

ARQUITETURA DE CONEXÃO
----------------------
Este módulo NÃO abre conexões próprias com o DuckDB.
Todas as funções recebem um duckdb.DuckDBPyConnection já aberto pelo chamador
(ui/aba_topologia.py via GerenciadorConexao).

CORREÇÃO — ELEMENTOS ISOLADOS (correcao_sequenciamento_topologia.md)
---------------------------------------------------------------------
O BFS, por definição, só alcança elementos conectados ao PAC_INI da subestação.
Elementos eletricamente isolados (sem caminho até a raiz) nunca são visitados e,
no código anterior, eram simplesmente descartados — causando 100 % de conectividade
aparente nas consultas de auditoria.

Solução implementada em rodar_bfs_alimentador():
  1. Antes do BFS, constrói o conjunto universo_ids com TODOS os COD_IDs
     carregados do banco para aquele alimentador.
  2. Após o BFS, calcula os isolados = universo_ids - visitados.
  3. Para cada elemento isolado, insere uma linha com ORDEM = None e todos
     os campos de pai também nulos — sinalizando explicitamente que o elemento
     existe na BDGD mas não está conectado à rede principal.

Isso garante que a consulta de auditoria possa distinguir:
    ORDEM IS NOT NULL  →  elemento conectado
    ORDEM IS NULL      →  elemento isolado / inconsistência topológica
"""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from typing import Callable

import duckdb
import pandas as pd


# ---------------------------------------------------------------------------
# Configuração das entidades
# ---------------------------------------------------------------------------

ENTIDADES = [
    "SSDMT", "UCBT_tab", "UNSEBT", "UNREMT",
    "CTMT", "UNSEMT", "SSDBT", "UCMT_tab",
    "RAMLIG", "PIP", "UNTRMT",
]

ENTIDADES_TERMINAIS = {"PIP", "UCBT_tab", "UCMT_tab"}

TABELA_TOPOLOGIA = "TOPOLOGIA"


# ---------------------------------------------------------------------------
# Gerenciador de conexão centralizado
# ---------------------------------------------------------------------------

class GerenciadorConexao:
    """
    Mantém UMA ÚNICA conexão read/write com um banco DuckDB.
    Todos os módulos que precisam do banco devem obter a conexão
    através desta classe, nunca chamando duckdb.connect() diretamente.
    """

    def __init__(self):
        self._con: duckdb.DuckDBPyConnection | None = None
        self._banco_path: str | None = None
        self._lock = threading.Lock()

    @property
    def conectado(self) -> bool:
        return self._con is not None

    @property
    def banco_path(self) -> str | None:
        return self._banco_path

    @property
    def conexao(self) -> duckdb.DuckDBPyConnection:
        if self._con is None:
            raise RuntimeError("Nenhum banco aberto. Chame abrir() primeiro.")
        return self._con

    def abrir(self, banco_path: str) -> None:
        with self._lock:
            if self._con is not None and self._banco_path == banco_path:
                return  # mesmo banco — reutilizar
            self._fechar_interno()
            self._con = duckdb.connect(database=banco_path, read_only=False)
            self._banco_path = banco_path

    def fechar(self) -> None:
        with self._lock:
            self._fechar_interno()

    def _fechar_interno(self) -> None:
        if self._con is not None:
            try:
                self._con.close()
            except Exception:
                pass
            self._con = None
            self._banco_path = None


# ---------------------------------------------------------------------------
# Funções de consulta — recebem conexão aberta, não abrem própria
# ---------------------------------------------------------------------------

def listar_alimentadores(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Retorna lista de COD_ID da tabela CTMT."""
    try:
        rows = con.execute(
            "SELECT DISTINCT COD_ID FROM CTMT ORDER BY COD_ID"
        ).fetchall()
        return [r[0] for r in rows]
    except Exception as e:
        raise RuntimeError(f"Erro ao listar alimentadores (tabela CTMT): {e}") from e


def verificar_entidades(con: duckdb.DuckDBPyConnection) -> tuple[list[str], list[str]]:
    """
    Verifica quais entidades necessárias existem no banco.
    Retorna (existentes, faltantes).
    """
    tabelas = {
        r[0]
        for r in con.execute(
            "SELECT table_name FROM information_schema.tables"
        ).fetchall()
    }
    necessarias = [e for e in ENTIDADES if e != "CTMT"]
    existentes  = [e for e in necessarias if e in tabelas]
    faltantes   = [e for e in necessarias if e not in tabelas]
    return existentes, faltantes


# ---------------------------------------------------------------------------
# Algoritmo BFS principal — com inclusão de elementos isolados
# ---------------------------------------------------------------------------

def rodar_bfs_alimentador(
    con: duckdb.DuckDBPyConnection,
    alimentador: str,
    cancelar_flag: threading.Event | None = None,
) -> pd.DataFrame:
    """
    Executa o BFS para um único alimentador e retorna TODOS os elementos
    do alimentador, inclusive os isolados (ORDEM = None).

    Colunas do DataFrame retornado:
        ALIMENTADOR, ORDEM, COD_ID, TABELA, PAC_1, PAC_2, FASE,
        PAI_COD_ID, PAI_TABELA, PAI_PAC_1, PAI_PAC_2, PAI_FASE,
        ISOLADO   ← True para elementos não alcançados pelo BFS

    Args:
        con:           Conexão DuckDB já aberta (read/write).
        alimentador:   COD_ID do alimentador na tabela CTMT.
        cancelar_flag: threading.Event — quando set(), interrompe o BFS.
    """
    # ── 1. Validar alimentador ────────────────────────────────────────
    ctmt_df = con.execute(
        f"SELECT COD_ID, PAC_INI FROM CTMT WHERE COD_ID = '{alimentador}'"
    ).fetchdf()

    if ctmt_df.empty:
        raise ValueError(f"Alimentador '{alimentador}' não encontrado na CTMT.")

    pac_inicial = ctmt_df.iloc[0]["PAC_INI"]

    # ── 2. Carregar universo completo de elementos do alimentador ─────
    #       Mantém um dict COD_ID → row para uso posterior na etapa de isolados
    dfs: list[pd.DataFrame] = []

    for entidade in ENTIDADES:
        if entidade == "CTMT":
            continue

        campo_fase = "FAS_CON_P" if entidade == "UNTRMT" else "FAS_CON"

        try:
            if entidade in ENTIDADES_TERMINAIS:
                df = con.execute(f"""
                    SELECT
                        COD_ID,
                        PAC          AS PAC_1,
                        NULL         AS PAC_2,
                        {campo_fase} AS FASE,
                        '{entidade}' AS TABELA
                    FROM {entidade}
                    WHERE CTMT = '{alimentador}'
                """).fetchdf()
            else:
                df = con.execute(f"""
                    SELECT
                        COD_ID,
                        PAC_1,
                        PAC_2,
                        {campo_fase} AS FASE,
                        '{entidade}' AS TABELA
                    FROM {entidade}
                    WHERE CTMT = '{alimentador}'
                """).fetchdf()

            if not df.empty:
                dfs.append(df)

        except Exception:
            continue  # entidade ausente no banco

    if not dfs:
        return pd.DataFrame()

    elementos_df = pd.concat(dfs, ignore_index=True)

    # Universo completo de COD_IDs existentes na BDGD para este alimentador
    # (usado depois para detectar os que o BFS não alcançou)
    universo_ids: set[str] = set(elementos_df["COD_ID"].dropna().astype(str))

    # Dict COD_ID → row, para recuperar PAC_1/PAC_2/FASE/TABELA dos isolados
    universo_rows: dict[str, pd.Series] = {
        str(row["COD_ID"]): row
        for _, row in elementos_df.iterrows()
        if pd.notna(row["COD_ID"])
    }

    # ── 3. Construir grafo não-direcionado PAC → elementos ───────────
    grafo_pac: dict[str, list] = defaultdict(list)
    for _, row in elementos_df.iterrows():
        if pd.notna(row["PAC_1"]):
            grafo_pac[row["PAC_1"]].append(row)
        if pd.notna(row["PAC_2"]):
            grafo_pac[row["PAC_2"]].append(row)

    # ── 4. BFS ────────────────────────────────────────────────────────
    resultado: list[dict] = []
    visitados: set[str]   = set()
    fila: deque           = deque()

    no_raiz = {
        "COD_ID": alimentador, "TABELA": "CTMT",
        "PAC_1": None, "PAC_2": pac_inicial, "FASE": None,
    }

    # Nó raiz = CTMT (sempre conectado, ORDEM = 1)
    resultado.append({
        "ALIMENTADOR": alimentador,
        "ORDEM":       1,
        "COD_ID":      alimentador,
        "TABELA":      "CTMT",
        "PAC_1":       None,
        "PAC_2":       pac_inicial,
        "FASE":        None,
        "PAI_COD_ID":  None,
        "PAI_TABELA":  None,
        "PAI_PAC_1":   None,
        "PAI_PAC_2":   None,
        "PAI_FASE":    None,
        "ISOLADO":     False,
    })

    fila.append((pac_inicial, 2, no_raiz))

    while fila:
        if cancelar_flag is not None and cancelar_flag.is_set():
            break

        pac_atual, ordem, elemento_pai = fila.popleft()

        for elemento in grafo_pac.get(pac_atual, []):
            cod = str(elemento["COD_ID"])
            if cod in visitados:
                continue
            visitados.add(cod)

            resultado.append({
                "ALIMENTADOR": alimentador,
                "ORDEM":       ordem,
                "COD_ID":      cod,
                "TABELA":      elemento["TABELA"],
                "PAC_1":       elemento["PAC_1"],
                "PAC_2":       elemento["PAC_2"],
                "FASE":        elemento["FASE"],
                "PAI_COD_ID":  elemento_pai["COD_ID"],
                "PAI_TABELA":  elemento_pai["TABELA"],
                "PAI_PAC_1":   elemento_pai["PAC_1"],
                "PAI_PAC_2":   elemento_pai["PAC_2"],
                "PAI_FASE":    elemento_pai["FASE"],
                "ISOLADO":     False,
            })

            pacs = []
            if pd.notna(elemento["PAC_1"]):
                pacs.append(elemento["PAC_1"])
            if pd.notna(elemento["PAC_2"]):
                pacs.append(elemento["PAC_2"])

            for pac in pacs:
                fila.append((pac, ordem + 1, elemento))

    # ── 5. Anti-join: inserir elementos isolados com ORDEM = None ────
    #
    # isolados = todos os COD_IDs do banco  MENOS  os visitados pelo BFS
    # Esses elementos existem na BDGD mas não têm caminho até o PAC_INI.
    #
    isolados = universo_ids - visitados

    for cod in sorted(isolados):     # sorted para resultado determinístico
        if cancelar_flag is not None and cancelar_flag.is_set():
            break

        row_orig = universo_rows.get(cod)

        resultado.append({
            "ALIMENTADOR": alimentador,
            "ORDEM":       None,            # ← nulo = isolado / desconectado
            "COD_ID":      cod,
            "TABELA":      row_orig["TABELA"] if row_orig is not None else None,
            "PAC_1":       row_orig["PAC_1"]  if row_orig is not None else None,
            "PAC_2":       row_orig["PAC_2"]  if row_orig is not None else None,
            "FASE":        row_orig["FASE"]   if row_orig is not None else None,
            "PAI_COD_ID":  None,            # sem pai — isolado
            "PAI_TABELA":  None,
            "PAI_PAC_1":   None,
            "PAI_PAC_2":   None,
            "PAI_FASE":    None,
            "ISOLADO":     True,            # flag explícita de isolamento
        })

    df = pd.DataFrame(resultado)

    # Garantir tipagem correta da coluna ORDEM (Int64 aceita None/NaN)
    if "ORDEM" in df.columns:
        df["ORDEM"] = df["ORDEM"].astype("Int64")

    return df


# ---------------------------------------------------------------------------
# Persistência na tabela TOPOLOGIA
# ---------------------------------------------------------------------------

def _garantir_tabela_topologia(con: duckdb.DuckDBPyConnection) -> None:
    """Cria a tabela TOPOLOGIA no banco se ainda não existir."""
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABELA_TOPOLOGIA} (
            ALIMENTADOR VARCHAR,
            ORDEM       INTEGER,     -- NULL para elementos isolados
            COD_ID      VARCHAR,
            TABELA      VARCHAR,
            PAC_1       VARCHAR,
            PAC_2       VARCHAR,
            FASE        VARCHAR,
            PAI_COD_ID  VARCHAR,
            PAI_TABELA  VARCHAR,
            PAI_PAC_1   VARCHAR,
            PAI_PAC_2   VARCHAR,
            PAI_FASE    VARCHAR,
            ISOLADO     BOOLEAN      -- TRUE = elemento desconectado da rede principal
        )
    """)


def salvar_alimentador_topologia(
    con: duckdb.DuckDBPyConnection,
    df: pd.DataFrame,
    alimentador: str,
) -> None:
    """
    Persiste o resultado BFS de um alimentador na tabela TOPOLOGIA.
    Remove registros anteriores do mesmo alimentador antes de inserir.
    Inclui elementos isolados (ORDEM = NULL, ISOLADO = TRUE).
    """
    _garantir_tabela_topologia(con)

    con.execute(
        f"DELETE FROM {TABELA_TOPOLOGIA} WHERE ALIMENTADOR = ?",
        [alimentador],
    )

    if df.empty:
        return

    con.register("_df_bfs_temp", df)
    con.execute(f"INSERT INTO {TABELA_TOPOLOGIA} SELECT * FROM _df_bfs_temp")
    con.unregister("_df_bfs_temp")


# ---------------------------------------------------------------------------
# Execução em lote
# ---------------------------------------------------------------------------

def rodar_bfs_lista(
    con: duckdb.DuckDBPyConnection,
    alimentadores: list[str],
    callback_progresso: Callable[[str], None] | None = None,
    cancelar_flag: threading.Event | None = None,
) -> tuple[pd.DataFrame, int, int]:
    """
    Executa BFS para uma lista de alimentadores, salvando cada resultado
    incrementalmente na tabela TOPOLOGIA (conectados + isolados).

    Returns:
        (df_consolidado, n_ok, n_erro)
    """
    _garantir_tabela_topologia(con)

    total  = len(alimentadores)
    todos: list[pd.DataFrame] = []
    n_ok   = 0
    n_erro = 0

    for i, alim in enumerate(alimentadores, 1):
        if cancelar_flag is not None and cancelar_flag.is_set():
            if callback_progresso:
                callback_progresso("⚠ Execução cancelada pelo usuário.")
            break

        if callback_progresso:
            callback_progresso(f"[{i}/{total}] Processando {alim}...")

        try:
            df_alim = rodar_bfs_alimentador(con, alim, cancelar_flag)
            salvar_alimentador_topologia(con, df_alim, alim)

            if not df_alim.empty:
                todos.append(df_alim)

                # Log de elementos conectados vs isolados para este alimentador
                if callback_progresso and "ISOLADO" in df_alim.columns:
                    n_con  = int((~df_alim["ISOLADO"]).sum())
                    n_iso  = int(df_alim["ISOLADO"].sum())
                    total_elem = len(df_alim)
                    pct_iso = (n_iso / total_elem * 100) if total_elem > 0 else 0
                    if n_iso > 0:
                        callback_progresso(
                            f"  → {n_con} conectados | "
                            f"{n_iso} isolados ({pct_iso:.1f} %)"
                        )

            n_ok += 1

        except Exception as e:
            n_erro += 1
            if callback_progresso:
                callback_progresso(f"  ⚠ Erro em {alim}: {e}")

    df_final = pd.concat(todos, ignore_index=True) if todos else pd.DataFrame()

    if callback_progresso:
        # Resumo geral de conectividade
        if not df_final.empty and "ISOLADO" in df_final.columns:
            total_el = len(df_final)
            total_iso = int(df_final["ISOLADO"].sum())
            total_con = total_el - total_iso
            pct = (total_iso / total_el * 100) if total_el > 0 else 0
            callback_progresso(
                f"Concluído — {n_ok} alimentador(es) OK, {n_erro} erro(s) | "
                f"{total_con} conectados / {total_iso} isolados "
                f"({pct:.1f} % de isolamento) | "
                f"{total_el} elementos no total."
            )
        else:
            callback_progresso(
                f"Concluído — {n_ok} OK, {n_erro} erro(s), "
                f"{len(df_final)} elemento(s) mapeados."
            )

    return df_final, n_ok, n_erro
