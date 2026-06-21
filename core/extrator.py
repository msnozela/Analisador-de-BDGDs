# -*- coding: utf-8 -*-
"""
core/extrator.py
Lógica de conexão com ArcGIS Online e download de BDGDs.
Sem dependência de GUI - pode ser testado isoladamente.
"""

import os
import pandas as pd


def carregar_lista_bdgds(excel_path: str) -> dict[str, str]:
    """
    Lê o Excel de referência e retorna dict {titulo: id} filtrando
    apenas itens do tipo 'File Geodatabase'.
    """
    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"Arquivo Excel não encontrado: {excel_path}")

    df = pd.read_excel(excel_path)

    if "type" not in df.columns or "title" not in df.columns or "id" not in df.columns:
        raise ValueError("Excel deve ter colunas: type, title, id")

    df_filtrado = df[df["type"] == "File Geodatabase"].copy()

    if df_filtrado.empty:
        raise ValueError("Nenhuma BDGD do tipo 'File Geodatabase' encontrada no Excel.")

    return dict(zip(df_filtrado["title"], df_filtrado["id"]))


def baixar_bdgd(bdgd_id: str, titulo: str, save_path: str,
                callback_progresso=None) -> str:
    """
    Conecta ao ArcGIS Online e baixa a BDGD indicada.

    Args:
        bdgd_id: ID do item no ArcGIS Online.
        titulo: Nome amigável (usado como nome do arquivo .zip).
        save_path: Pasta de destino.
        callback_progresso: Função opcional(mensagem: str) para feedback.

    Returns:
        Caminho completo do arquivo baixado.
    """
    from arcgis.gis import GIS

    if callback_progresso:
        callback_progresso("Conectando ao ArcGIS Online...")

    gis = GIS("https://www.arcgis.com", anonymous=True, verify_cert=False)

    if callback_progresso:
        callback_progresso("Buscando item na API...")

    item = gis.content.get(bdgd_id)

    if item is None:
        raise RuntimeError(f"Item '{bdgd_id}' não encontrado na API.")

    if callback_progresso:
        callback_progresso("Baixando arquivo...")

    os.makedirs(save_path, exist_ok=True)
    item.download(save_path, file_name=f"{titulo}.zip")

    caminho = os.path.join(save_path, f"{titulo}.zip")

    if callback_progresso:
        callback_progresso("Download concluído.")

    return caminho


def listar_bdgds_baixadas(save_path: str) -> list[str]:
    """Retorna lista de arquivos .zip disponíveis na pasta de BDGDs."""
    if not os.path.exists(save_path):
        return []
    return sorted([f for f in os.listdir(save_path) if f.endswith(".zip")])
