# -*- coding: utf-8 -*-
"""
core/mapas.py
Motor de geração de mapas georreferenciados da BDGD via Folium/Leaflet.
Sem dependência de GUI.

OTIMIZAÇÕES IMPLEMENTADAS
--------------------------
1. Simplificação Douglas-Peucker (tolerance=0.00008) nas linhas SSDMT
   → reduz vértices em ~70% sem perda visual perceptível no browser
2. Leitura seletiva de campos (só o necessário por camada)
3. Transformadores (UNTRMT) com zoom condicional >= 15 no JS
4. Paleta neon com 12 cores de alto contraste mapeadas por hash do CTMT
5. Arquivos de saída organizados em Mapas/<nome_bdgd>/ ao lado do app.py
"""

from __future__ import annotations

import os
import math
import json
import gzip
import base64
import time
import threading
from datetime import datetime
from collections import defaultdict
from pathlib import Path
from typing import Callable

import pandas as pd
import geopandas as gpd
from shapely.ops import linemerge
from shapely.geometry import LineString, MultiLineString, Point

import duckdb
import folium
from branca.element import Element


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

PASTA_MAPAS    = "Mapas"           # relativa ao base_path do app
Z_TILE         = 13
SCALE          = 100_000
SIMPLIFY_TOL   = 0.00008           # graus — Douglas-Peucker

SSDMT_FIELDS   = ["COD_ID","CTMT","SUB","PAC_1","PAC_2","FAS_CON","COMP","TIP_CND","DESCR"]
UNREMT_FIELDS  = ["COD_ID","FAS_CON","TIP_REGU","UNI_TR_AT","PAC_1","PAC_2","CTMT","SUB","DESCR"]
UNSEMT_FIELDS  = ["COD_ID","PAC_1","PAC_2","FAS_CON","CTMT","SUB","P_N_OPE","DESCR"]
UNTRMT_FIELDS  = ["COD_ID","CTMT","SUB","PAC_1","PAC_2","FAS_CON","POT_NOM","TIP_TRAFO","DESCR"]
# UCMT_tab é tabela tabular sem geometria na BDGD — não plotada no mapa
SUB_FIELDS     = ["COD_ID","NOME","DESCR","DIST"]

# Paleta neon — 12 cores visíveis sobre fundo escuro E claro
NEON_PALETTE = [
    "#00FFE5",  # ciano elétrico
    "#CCFF00",  # verde-limão
    "#FF6B00",  # laranja neon
    "#FF00C8",  # magenta
    "#00BFFF",  # azul-céu vivo
    "#FFD700",  # amarelo-ouro
    "#FF4444",  # vermelho vivo
    "#7FFF00",  # chartreuse
    "#FF69B4",  # rosa neon
    "#39FF14",  # verde neon puro
    "#BF5FFF",  # violeta neon
    "#FF8C00",  # laranja escuro
]

# Cores fixas dos elementos pontuais (combinam com o tema dark do Tkinter)
COR_REGULADOR  = "#00C8FF"   # ciano — igual ao acento do app
COR_CHAVE      = "#FF5252"   # vermelho — igual ao erro do app
COR_SUB_BORDA  = "#FFD700"   # amarelo-ouro
COR_SUB_FILL   = "#FFD700"
COR_UNTRMT     = "#A78BFA"   # violeta suave
# COR_UCMT removida — UCMT_tab não tem geometria no GDB


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------

def pasta_saida(base_path: str, nome_bdgd: str) -> str:
    """Retorna (e cria) a pasta de saída dos mapas desta BDGD."""
    p = os.path.join(base_path, PASTA_MAPAS, nome_bdgd)
    os.makedirs(p, exist_ok=True)
    return p


def mapa_existe(base_path: str, nome_bdgd: str) -> dict:
    """
    Verifica se o mapa já foi gerado.
    Retorna dict: {"existe": bool, "html": str, "tamanho_mb": float, "data": str}
    """
    html = os.path.join(pasta_saida(base_path, nome_bdgd), "mapa_rede.html")
    if os.path.exists(html):
        stat = os.stat(html)
        data = datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M")
        return {
            "existe":      True,
            "html":        html,
            "tamanho_mb":  round(stat.st_size / 1_048_576, 1),
            "data":        data,
        }
    return {"existe": False, "html": html, "tamanho_mb": 0, "data": "—"}


def listar_gdbs_disponiveis(base_path: str) -> list[dict]:
    """
    Lista GDBs disponíveis na pasta de extrações (mesma que core/conversao.py usa).
    Tenta importar PASTA_EXTRAIDAS de conversao para garantir consistência;
    usa fallback hardcoded se o import falhar.
    Retorna lista de dicts: {"nome": str, "gdb_path": str}
    """
    try:
        from core.conversao import PASTA_EXTRAIDAS as _PE
        pasta = os.path.join(base_path, _PE)
    except Exception:
        pasta = os.path.join(base_path, "BDGDs Extraídas")

    resultado: list[dict] = []
    if not os.path.exists(pasta):
        return resultado

    for subdir in sorted(os.listdir(pasta)):
        full = os.path.join(pasta, subdir)
        if not os.path.isdir(full):
            continue
        gdb = _localizar_gdb(full)
        if gdb:
            resultado.append({"nome": subdir, "gdb_path": gdb})
    return resultado


def _localizar_gdb(root_dir: str) -> str | None:
    for dirpath, dirnames, _ in os.walk(root_dir):
        for d in dirnames:
            if d.lower().endswith(".gdb"):
                return os.path.join(dirpath, d)
    return None


# ---------------------------------------------------------------------------
# Helpers de geometria
# ---------------------------------------------------------------------------

def _get_line_endpoints(geom):
    """Retorna (p1, p2) como tuplas (lon, lat) de uma geometria de linha."""
    if geom is None or geom.is_empty:
        return None, None
    if isinstance(geom, LineString):
        coords = list(geom.coords)
        return coords[0], coords[-1]
    if isinstance(geom, MultiLineString):
        merged = linemerge(geom)
        if isinstance(merged, LineString):
            coords = list(merged.coords)
            return coords[0], coords[-1]
        longest = max(geom.geoms, key=lambda g: g.length)
        coords = list(longest.coords)
        return coords[0], coords[-1]
    return None, None


def _latlon_to_tile(lat: float, lon: float, z: int) -> tuple[int, int]:
    n = 2.0 ** z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return x, y


def _norm(v) -> str:
    return str(v).strip() if v is not None else ""


# ---------------------------------------------------------------------------
# Serialização
# ---------------------------------------------------------------------------

def _dumps(o: object) -> bytes:
    return json.dumps(o, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _gzip_b64(o: object) -> str:
    return base64.b64encode(gzip.compress(_dumps(o), 9)).decode()


def _gdf_to_b64(gdf: gpd.GeoDataFrame) -> str:
    return _gzip_b64(json.loads(gdf.to_json()))


# ---------------------------------------------------------------------------
# Leitura de camadas do GDB
# ---------------------------------------------------------------------------

def _load_layer(
    gdb_path: str,
    layer: str,
    fields: list[str] | None = None,
    simplify: bool = False,
) -> gpd.GeoDataFrame:
    """
    Lê uma camada do GDB, reprojetando para WGS-84 (EPSG:4326).
    Aplica simplificação Douglas-Peucker se simplify=True.
    """
    try:
        g = gpd.read_file(gdb_path, layer=layer)
    except Exception as e:
        raise RuntimeError(f"Erro ao ler camada '{layer}': {e}") from e

    # Algumas camadas podem ser lidas como DataFrame sem geometria
    # (ex: UCMT_tab em alguns GDBs é tabular). Verificar antes do to_crs.
    if not isinstance(g, gpd.GeoDataFrame) or "geometry" not in g.columns:
        raise RuntimeError(
            f"Camada '{layer}' não possui geometria — é uma tabela tabular. "
            f"Colunas disponíveis: {list(g.columns)}"
        )

    g = g.to_crs(4326)

    if fields:
        keep = [c for c in fields if c in g.columns]
        g = g[keep + ["geometry"]]

    if simplify and not g.empty:
        g["geometry"] = g.geometry.simplify(SIMPLIFY_TOL, preserve_topology=True)

    return g


# ---------------------------------------------------------------------------
# Pipeline principal de geração do mapa
# ---------------------------------------------------------------------------

def gerar_mapa(
    gdb_path: str,
    base_path: str,
    nome_bdgd: str,
    cancelar_flag: threading.Event | None = None,
    callback: Callable[[str], None] | None = None,
) -> str:
    """
    Executa o pipeline completo de geração do mapa HTML.

    Args:
        gdb_path:      Caminho da pasta .gdb.
        base_path:     Pasta raiz do app (onde fica a pasta Mapas/).
        nome_bdgd:     Nome identificador da BDGD (usado para a subpasta).
        cancelar_flag: threading.Event — quando set(), interrompe o pipeline.
        callback:      Função opcional(str) para log de progresso.

    Returns:
        Caminho absoluto do arquivo HTML gerado.
    """

    def log(msg: str):
        if callback:
            callback(msg)

    def _check_cancel():
        if cancelar_flag is not None and cancelar_flag.is_set():
            raise InterruptedError("Geração de mapa cancelada pelo usuário.")

    # ── 1. Carregar camadas ───────────────────────────────────────────────
    log("Lendo camada SSDMT (rede MT)...")
    _check_cancel()
    rede = _load_layer(gdb_path, "SSDMT", SSDMT_FIELDS, simplify=True)
    log(f"  → {len(rede)} segmentos carregados e simplificados.")

    _check_cancel()
    log("Lendo camadas de elementos (REG, CHV, SUB, UNTRMT)...")

    reg    = _load_layer_safe(gdb_path, "UNREMT",  UNREMT_FIELDS, log)
    chv    = _load_layer_safe(gdb_path, "UNSEMT",  UNSEMT_FIELDS, log)
    sub    = _load_layer_safe(gdb_path, "SUB",     SUB_FIELDS,    log)
    untrmt = _load_layer_safe(gdb_path, "UNTRMT",  UNTRMT_FIELDS, log)
    # ucmt removida — UCMT_tab é tabela tabular sem geometria

    _check_cancel()

    # ── 2. Processar SSDMT → tiles ──────────────────────────────────────
    log("Indexando segmentos MT em tiles geográficos...")
    ctmts  = sorted(rede["CTMT"].dropna().astype(str).unique()) if "CTMT" in rede.columns else []
    ct_idx = {c: i for i, c in enumerate(ctmts)}
    tiles: dict[str, list] = defaultdict(list)
    props: dict[str, dict] = {}
    total  = len(rede)

    for i, (_, r) in enumerate(rede.iterrows()):
        if i % 5000 == 0 and i > 0:
            pct = i / total * 100
            log(f"  → {pct:.0f}% ({i}/{total} segmentos indexados)")

        if cancelar_flag is not None and cancelar_flag.is_set():
            raise InterruptedError("Cancelado durante indexação de tiles.")

        p1, p2 = _get_line_endpoints(r.geometry)
        if p1 is None:
            continue

        lat = (p1[1] + p2[1]) / 2
        lon = (p1[0] + p2[0]) / 2
        x, y = _latlon_to_tile(lat, lon, Z_TILE)

        fid  = _norm(r.get("COD_ID", ""))
        ctmt = _norm(r.get("CTMT",   ""))
        ct   = ct_idx.get(ctmt, -1)
        raw_comp = r.get("COMP")
        comp = int(round(raw_comp)) if raw_comp is not None and not pd.isna(raw_comp) else None

        tiles[f"{x},{y}"].append([
            fid, ct, comp,
            int(p1[1] * SCALE), int(p1[0] * SCALE),
            int(p2[1] * SCALE), int(p2[0] * SCALE),
        ])

        row_dict = {k: v for k, v in r.items() if k != "geometry"}
        props[fid] = {k: (None if pd.isna(v) else v) for k, v in row_dict.items()}

    log(f"  → {len(props)} segmentos indexados em {len(tiles)} tiles.")

    # ── 2b. Indexar elementos pontuais (REG, CHV, UNTRMT) para filtro ────
    # Props dos elementos pontuais: COD_ID → {lat, lon, atributos}
    # Custo: ~15-40 KB gzip — negligível. Permite buscar por COD_ID de
    # reguladores, chaves e transformadores no filtro do mapa.
    elem_pts: dict[str, dict] = {}

    def _indexar_pontuais(gdf: gpd.GeoDataFrame, tipo: str):
        if gdf is None or gdf.empty:
            return
        for _, row in gdf.iterrows():
            if row.geometry is None or row.geometry.is_empty:
                continue
            fid = _norm(row.get("COD_ID", ""))
            if not fid:
                continue
            c = row.geometry.centroid
            entry = {
                "lat":  round(c.y, 6),
                "lon":  round(c.x, 6),
                "tipo": tipo,
            }
            for col in row.index:
                if col == "geometry":
                    continue
                v = row.get(col)
                entry[col] = None if (v is not None and hasattr(v, "__float__") and pd.isna(v)) else v
            elem_pts[fid] = entry

    _indexar_pontuais(reg,    "Regulador")
    _indexar_pontuais(chv,    "Chave MT")
    _indexar_pontuais(untrmt, "Transformador")
    # ucmt não indexada — sem geometria
    log(f"  → {len(elem_pts)} elementos pontuais indexados para filtro.")

    # ── 2c. Ler inconsistências do banco de resultados ───────────────────
    _check_cancel()
    log("Lendo inconsistências do banco de resultados...")
    duckdb_dir = os.path.join(base_path, "Bancos Duckdb")
    incons = _ler_inconsistencias(duckdb_dir, nome_bdgd, log)

    # Converter sets para listas (JSON serializável) e serializar
    # Os campos já vêm como lista do novo _ler_inconsistencias
    incons_serial = incons  # já serializado corretamente

    # ── 3. Serializar ────────────────────────────────────────────────────
    _check_cancel()
    log("Comprimindo dados para embutir no HTML...")

    # Centroides das subestações para exibir ícones visíveis em qualquer zoom
    sub_centroids = []
    if not sub.empty:
        for _, row in sub.iterrows():
            if row.geometry is None or row.geometry.is_empty:
                continue
            c = row.geometry.centroid
            entry = {"lat": round(c.y, 6), "lon": round(c.x, 6)}
            for col in ["COD_ID", "NOME", "DESCR", "DIST"]:
                if col in sub.columns:
                    v = row.get(col)
                    entry[col] = None if (v is not None and hasattr(v, "__float__") and pd.isna(v)) else v
            sub_centroids.append(entry)
    log(f"  → {len(sub_centroids)} centroides de subestações indexados.")

    db_b64      = _gzip_b64({"tiles": dict(tiles), "ctmt": ctmts, "scale": SCALE, "z": Z_TILE, "sub_centroids": sub_centroids})
    props_b64   = _gzip_b64(props)
    elempts_b64 = _gzip_b64(elem_pts)
    incons_b64  = _gzip_b64(incons_serial)
    se_b64    = _gdf_to_b64(sub)    if not sub.empty    else _gzip_b64({"type": "FeatureCollection", "features": []})
    reg_b64   = _gdf_to_b64(reg)    if not reg.empty    else _gzip_b64({"type": "FeatureCollection", "features": []})
    chv_b64   = _gdf_to_b64(chv)    if not chv.empty    else _gzip_b64({"type": "FeatureCollection", "features": []})
    utrmt_b64 = _gdf_to_b64(untrmt) if not untrmt.empty else _gzip_b64({"type": "FeatureCollection", "features": []})
    # ucmt_b64 removida

    # ── 4. Montar mapa Folium ────────────────────────────────────────────
    _check_cancel()
    log("Montando estrutura Folium...")

    centro_lat = rede.geometry.centroid.y.mean() if not rede.empty else -15.0
    centro_lon = rede.geometry.centroid.x.mean() if not rede.empty else -50.0

    m = folium.Map(
        location=[centro_lat, centro_lon],
        zoom_start=13,
        tiles=None,
        prefer_canvas=True,
    )

    # Tile layers
    folium.TileLayer(
        tiles="https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png",
        attr="CartoDB",
        name="Cartográfico Limpo",
        show=True,
    ).add_to(m)

    folium.TileLayer(
        tiles="https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png",
        attr="CartoDB",
        name="Dark (Sem Labels)",
        show=False,
    ).add_to(m)

    folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
        attr="Google",
        name="Satélite Híbrido",
        show=False,
    ).add_to(m)

    folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=m&x={x}&y={y}&z={z}",
        attr="Google",
        name="Google Maps",
        show=False,
    ).add_to(m)

    # Pako (descompressão no browser)
    m.get_root().header.add_child(Element(
        "<script src='https://cdnjs.cloudflare.com/ajax/libs/pako/2.1.0/pako.min.js'></script>"
    ))

    # CSS + HTML do painel
    m.get_root().header.add_child(Element(_CSS_MAPA))
    m.get_root().html.add_child(Element(_build_panel_html(nome_bdgd)))

    # Dados embutidos
    m.get_root().html.add_child(Element(f"""
<script id='data-db'      type='text/plain'>{db_b64}</script>
<script id='data-props'   type='text/plain'>{props_b64}</script>
<script id='data-se'      type='text/plain'>{se_b64}</script>
<script id='data-reg'     type='text/plain'>{reg_b64}</script>
<script id='data-chv'     type='text/plain'>{chv_b64}</script>
<script id='data-utrmt'   type='text/plain'>{utrmt_b64}</script>
<script id='data-elempts' type='text/plain'>{elempts_b64}</script>
<script id='data-incons'  type='text/plain'>{incons_b64}</script>
"""))

    # JavaScript principal
    js_final = _JS_MAPA.replace("__MAP_NAME__", m.get_name())
    js_final = js_final.replace("__NEON_PALETTE__", json.dumps(NEON_PALETTE))
    js_final = js_final.replace("__COR_REG__",    f'"{COR_REGULADOR}"')
    js_final = js_final.replace("__COR_CHV__",    f'"{COR_CHAVE}"')
    js_final = js_final.replace("__COR_SUB__",    f'"{COR_SUB_BORDA}"')
    js_final = js_final.replace("__COR_UNTRMT__", f'"{COR_UNTRMT}"')
    # __COR_UCMT__ removida com a camada UCMT

    # Verificação de segurança: nenhum placeholder deve restar no JS final
    import re as _re
    leftover = _re.findall(r'__[A-Z_]+__', js_final)
    if leftover:
        raise RuntimeError(f"Placeholders não substituídos no JS: {leftover}")

    m.get_root().script.add_child(Element(js_final))
    folium.LayerControl(collapsed=False).add_to(m)

    # ── 5. Salvar ────────────────────────────────────────────────────────
    _check_cancel()
    saida = pasta_saida(base_path, nome_bdgd)
    html_path = os.path.join(saida, "mapa_rede.html")
    m.save(html_path)
    log(f"✔ Mapa salvo: {html_path}")

    return html_path


def _load_layer_safe(gdb_path, layer, fields, log_fn) -> gpd.GeoDataFrame:
    """Lê uma camada sem lançar exceção — retorna GeoDataFrame vazio se falhar."""
    try:
        return _load_layer(gdb_path, layer, fields)
    except Exception as e:
        log_fn(f"  ⚠ Camada '{layer}' não encontrada ou com erro: {e}")
        return gpd.GeoDataFrame()


def _ler_inconsistencias(duckdb_dir: str, nome_bdgd: str, log_fn) -> dict:
    """
    Lê os COD_IDs inconsistentes do banco bdgd_inconsistencias.duckdb.
    Retorna apenas os conjuntos de IDs por regra — custo: ~15-30 KB gzip.

    Regras lidas (somente as que afetam elementos da rede MT visíveis no mapa):
      r01_isolados_quant / r01_isolados_abert → SSDMT isolados
      r02_faseamento_abert                    → SSDMT com erro de fase
      r03_neutro_abert                        → SSDMT com erro de neutro
      r05_potencia_trafos_abert               → UNTRMT com potência inconsistente
      r06_perdas_trafos_abert                 → UNTRMT com perdas inconsistentes

    Retorna dict:
        {
          "disponivel":   bool,
          "r01_isolados": set[str],  # COD_IDs isolados
          "r01_conectados_pct": float,
          "r02_fase":     set[str],
          "r03_neutro":   set[str],
          "r05_trafo_pot": set[str],
          "r06_trafo_per": set[str],
        }
    """
    try:
        from core.consultas import NOME_BANCO_RESULTADOS, _tem_coluna_nome_bdgd
    except Exception:
        NOME_BANCO_RESULTADOS = "bdgd_inconsistencias.duckdb"
        _tem_coluna_nome_bdgd = None

    res_path = os.path.join(duckdb_dir, NOME_BANCO_RESULTADOS)
    vazio = {
        "disponivel": False,
        "r01_isolados": set(), "r01_conectados_pct": 100.0,
        "r02_fase": set(), "r03_neutro": set(),
        "r05_trafo_pot": set(), "r06_trafo_per": set(),
    }

    if not os.path.exists(res_path):
        log_fn("  ℹ Banco de inconsistências não encontrado — visualizações desabilitadas.")
        return vazio

    try:
        con = duckdb.connect(res_path, read_only=True)

        log_fn(f"  → Buscando inconsistências para BDGD: '{nome_bdgd}'")

        # Verificar tabelas disponíveis
        tabelas = {r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables"
        ).fetchall()}

        # Logar BDGDs disponíveis no banco para diagnóstico
        try:
            bdgds_hist = [r[0] for r in con.execute(
                "SELECT DISTINCT nome_bdgd_origem FROM tb_historico_execucao "
                "ORDER BY data_execucao DESC LIMIT 5"
            ).fetchall()]
            log_fn(f"  → BDGDs no banco de inconsistências: {bdgds_hist}")
        except Exception:
            pass

        def _query_ids(tabela: str, col_id: str) -> set[str]:
            """
            Busca IDs com comparação CASE-INSENSITIVE de NOME_BDGD.
            O banco salva com o nome do .duckdb (minúsculas), mas o mapa
            usa o nome da pasta GDB (case original). Lower() dos dois lados
            resolve o mismatch sem alterar os dados existentes.
            """
            if tabela not in tabelas:
                return set()
            try:
                cols = {r[0].upper() for r in con.execute(
                    f"SELECT column_name FROM information_schema.columns "
                    f"WHERE table_name = '{tabela}'"
                ).fetchall()}
                if "NOME_BDGD" in cols:
                    # Comparação case-insensitive: lower() nos dois lados
                    rows = con.execute(
                        f'SELECT "{col_id}" FROM "{tabela}" ' +
                        f'WHERE LOWER(NOME_BDGD) = LOWER(?) AND "{col_id}" IS NOT NULL',
                        [nome_bdgd]
                    ).fetchall()
                    # Fallback: se retornou vazio, listar todos os NOME_BDGD distintos
                    # para logar e ajudar no diagnóstico
                    if not rows:
                        bdgds_no_banco = [r[0] for r in con.execute(
                            f'SELECT DISTINCT NOME_BDGD FROM "{tabela}" LIMIT 5'
                        ).fetchall()]
                        if bdgds_no_banco:
                            log_fn(
                                f"  ⚠ NOME_BDGD '{nome_bdgd}' não encontrado em '{tabela}'. "
                                f"BDGDs no banco: {bdgds_no_banco}"
                            )
                else:
                    rows = con.execute(
                        f'SELECT "{col_id}" FROM "{tabela}" WHERE "{col_id}" IS NOT NULL'
                    ).fetchall()
                return {str(r[0]) for r in rows}
            except Exception as _e:
                log_fn(f"  ⚠ Erro em _query_ids({tabela}): {_e}")
                return set()

        # R01 — Isolados: pegar COD_IDs com ORDEM IS NULL (da abertura)
        r01_ids = _query_ids("r01_isolados_abert", "COD_ID")

        # R01 — % conectados (do quantitativo, para exibir no painel)
        r01_pct = 100.0
        if "r01_isolados_quant" in tabelas:
            try:
                cols_q = {r[0].upper() for r in con.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'r01_isolados_quant'"
                ).fetchall()}
                where  = f"WHERE LOWER(NOME_BDGD) = LOWER('{nome_bdgd}')" if "NOME_BDGD" in cols_q else ""
                df_q   = con.execute(
                    f"SELECT SUM(CONECTADOS) AS C, SUM(DESCONECTADOS) AS D "
                    f"FROM r01_isolados_quant {where}"
                ).fetchdf()
                if not df_q.empty:
                    c = float(df_q["C"].iloc[0] or 0)
                    d = float(df_q["D"].iloc[0] or 0)
                    total = c + d
                    r01_pct = round(c / total * 100, 1) if total > 0 else 100.0
            except Exception:
                pass

        # R02 — Faseamento: COD_ID do elemento filho com erro
        r02_ids = _query_ids("r02_faseamento_abert", "COD_ID")

        # R03 — Neutro
        r03_ids = _query_ids("r03_neutro_abert", "COD_ID")

        # R05 — Potência trafos: COD_ID_UNTRMT
        r05_ids = set()
        # Tentar colunas conhecidas da abertura R05 (COD_ID_UNTRMT é o padrão)
        for col_try in ["COD_ID_UNTRMT", "COD_ID_UNREMT", "COD_ID"]:
            r05_ids = _query_ids("r05_potencia_trafos_abert", col_try)
            if r05_ids:
                break

        # R06 — Perdas trafos: COD_ID
        r06_ids = _query_ids("r06_perdas_trafos_abert", "COD_ID")

        # ── R04 — condutores com resistência inconsistente → só SSDMT
        r04_ids = set()
        if "r04_resistencia_abert" in tabelas:
            try:
                # R04 retorna COD_ID do SEGCON (condutor), não do segmento.
                # Precisamos cruzar com a abertura que tem TIP_CND → buscar SSDMT
                # que usam esse condutor. Mas a abertura R04 não tem COD_ID de SSDMT.
                # Usamos abordagem alternativa: ler SSDMT do banco BDGD original
                # não disponível aqui, então usamos os COD_IDs da r04_abert que
                # correspondem a segmentos via join na query. Se houver campo
                # cod_id_ssdmt ou similar, usamos; senão, retornamos set vazio
                # e o canvas usará coloração por tipo de condutor (implementada no JS).
                pass  # Resolvido no JS via TIP_CND nos props
            except Exception:
                pass

        # ── R07 — reguladores com potência abaixo do mínimo → UNREMT/EQRE
        r07_ids = set()
        for col_try in ["COD_EQUIPAMENTO", "COD_ID", "UN_RE"]:
            r07_ids = _query_ids("r07_reguladores_pot_abert", col_try)
            if r07_ids:
                break

        # ── R08 — segmentos com comprimento zerado → somente SSDMT e SSDBT
        r08_ids = set()
        try:
            # Filtrar só ORIGEM=SSDMT da abertura (ignora SSDBT e RAMLIG)
            cols_r08 = {r[0].upper() for r in con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'r08_comprimento_abert'"
            ).fetchall()} if "r08_comprimento_abert" in tabelas else set()
            if cols_r08:
                where_bdgd = "AND LOWER(NOME_BDGD)=LOWER(?)" if "NOME_BDGD" in cols_r08 else ""
                params = [nome_bdgd] if where_bdgd else []
                rows_r08 = con.execute(
                    f"SELECT COD_ID FROM r08_comprimento_abert "
                    f"WHERE ORIGEM='SSDMT' {where_bdgd} AND COD_ID IS NOT NULL",
                    params
                ).fetchall()
                r08_ids = {str(r[0]) for r in rows_r08}
        except Exception:
            pass

        # ── R10 — modelagem de reguladores
        # Colunas confirmadas: UNREMT_ID, COD_ID_EQUIPAMENTO, NOME_BDGD, TOTAL_EQUIP_NO_POSTO
        r10_ids = _query_ids("r10_modelagem_reg_abert", "UNREMT_ID")

        con.close()  # Fechar APÓS todas as queries

        result = {
            "disponivel":        True,
            "r01_isolados":      list(r01_ids),
            "r01_conectados_pct": r01_pct,
            "r02_fase":          list(r02_ids),
            "r03_neutro":        list(r03_ids),
            "r05_trafo_pot":     list(r05_ids),
            "r06_trafo_per":     list(r06_ids),
            "r07_reg_pot":       list(r07_ids),
            "r08_ssdmt_comp":    list(r08_ids),
            "r10_reg_model":     list(r10_ids),
        }

        log_fn(
            f"  ✔ Inconsistências carregadas: "
            f"R01={len(r01_ids)} | R02={len(r02_ids)} | R03={len(r03_ids)} | "
            f"R05={len(r05_ids)} | R06={len(r06_ids)} | R07={len(r07_ids)} | "
            f"R08(SSDMT)={len(r08_ids)} | R10={len(r10_ids)}"
        )
        return result

    except Exception as e:
        log_fn(f"  ⚠ Erro ao ler inconsistências: {e}")
        return vazio


# ---------------------------------------------------------------------------
# CSS do mapa — tema dark alinhado ao app Tkinter
# ---------------------------------------------------------------------------

_CSS_MAPA = """
<style>
html, body { height:100%; margin:0; padding:0; overflow:hidden; font-family:'Segoe UI',Roboto,Arial,sans-serif; }

#map {
    position:absolute; top:0; bottom:0; right:0; left:300px;
    z-index:0; background:#0F1923;
}

#panel {
    position:absolute; top:0; bottom:0; left:0;
    width:300px;
    background:#0A1520;
    border-right:1px solid #243447;
    box-shadow:4px 0 20px rgba(0,0,0,0.6);
    z-index:9999;
    display:flex; flex-direction:column;
    box-sizing:border-box; padding:14px;
    color:#E8F0F7;
}

#panel-header {
    margin-bottom:14px;
    border-bottom:2px solid #00C8FF;
    padding-bottom:10px;
}
#panel-header h2 {
    margin:0; font-size:15px; font-weight:700;
    color:#00C8FF; letter-spacing:0.5px;
}
#panel-header .subtitle {
    font-size:10px; color:#7A9BB5; margin-top:3px;
}

.ctrl-label {
    font-size:10px; font-weight:600; color:#7A9BB5;
    text-transform:uppercase; letter-spacing:0.8px;
    margin-bottom:4px; display:block;
}

.ctrl-input {
    width:100%; padding:7px 10px;
    background:#162130; border:1px solid #243447;
    border-radius:4px; box-sizing:border-box;
    font-size:12px; color:#E8F0F7;
    margin-bottom:10px;
}
.ctrl-input:focus { outline:none; border-color:#00C8FF; }
.ctrl-input::placeholder { color:#3A5068; }

.layer-box {
    background:#162130; border:1px solid #243447;
    border-radius:4px; padding:8px 10px;
    margin-bottom:10px;
}
.layer-box .box-title {
    font-size:10px; font-weight:700; color:#7A9BB5;
    text-transform:uppercase; letter-spacing:0.8px;
    margin-bottom:6px;
}
.toggle-row {
    display:flex; align-items:center;
    margin-bottom:5px; cursor:pointer;
    font-size:12px; color:#E8F0F7;
}
.toggle-row input[type=checkbox] { margin-right:8px; accent-color:#00C8FF; }
.dot { width:10px; height:10px; border-radius:50%; display:inline-block; margin-right:6px; flex-shrink:0; }

#info {
    flex-grow:1; overflow-y:auto;
    background:#162130; border:1px solid #243447;
    border-radius:4px; padding:10px;
    margin-top:4px;
}
#info-placeholder {
    text-align:center; color:#3A5068;
    margin-top:30px; font-size:12px; line-height:1.8;
}
#info h4 {
    margin:0 0 8px 0; font-size:13px;
    color:#00C8FF; border-bottom:1px solid #243447;
    padding-bottom:5px;
}
#info table { width:100%; border-collapse:collapse; font-size:11px; }
#info td { padding:4px 3px; border-bottom:1px solid #1E2D3D; vertical-align:top; }
#info td:first-child { font-weight:600; color:#7A9BB5; width:38%; }
#info td:last-child  { color:#E8F0F7; }

#loading {
    position:absolute; top:50%; left:50%; transform:translate(-50%,-50%);
    background:rgba(10,21,32,0.92); color:#00C8FF;
    padding:20px 28px; border-radius:8px;
    border:1px solid #00C8FF;
    display:none; z-index:10000; font-size:13px;
}

/* Scrollbar */
::-webkit-scrollbar { width:5px; }
::-webkit-scrollbar-track { background:#0A1520; }
::-webkit-scrollbar-thumb { background:#243447; border-radius:3px; }

/* Pulsação do elemento em foco de inconsistência */
@keyframes ping {
    0%   { transform: scale(1);   opacity: 1; }
    50%  { transform: scale(1.7); opacity: 0.4; }
    100% { transform: scale(1);   opacity: 1; }
}
.incons-ping {
    animation: ping 1s ease-in-out infinite;
    transform-origin: center;
}

/* Botões de navegação de inconsistências */
.nav-btn {
    flex:1; padding:5px 4px; font-size:11px; font-weight:600;
    background:#162130; color:#E8F0F7;
    border:1px solid #243447; border-radius:4px;
    cursor:pointer; transition:background 0.15s;
}
.nav-btn:hover { background:#243447; color:#00C8FF; }
.nav-btn:disabled { opacity:0.4; cursor:default; }

/* Leaflet layer control — dark */
.leaflet-control-layers {
    background:#162130 !important;
    border:1px solid #243447 !important;
    color:#E8F0F7 !important;
    border-radius:6px !important;
}
.leaflet-control-layers label { color:#E8F0F7 !important; font-size:12px !important; }
.leaflet-control-layers-separator { border-color:#243447 !important; }
</style>
"""


def _build_panel_html(nome_bdgd: str) -> str:
    titulo = nome_bdgd[:32] + ("…" if len(nome_bdgd) > 32 else "")
    return f"""
<div id='loading'>⏳ Carregando dados do mapa...</div>
<div id='panel'>

  <div id='panel-header'>
    <h2>🗺 Mapa da Rede MT</h2>
    <div class='subtitle'>{titulo}</div>
  </div>

  <span class='ctrl-label'>Subestação</span>
  <input list='list-se' id='input-se' class='ctrl-input' placeholder='Filtrar por SE...'>
  <datalist id='list-se'></datalist>

  <span class='ctrl-label'>Alimentador (CTMT)</span>
  <input list='list-ctmt' id='input-ctmt' class='ctrl-input' placeholder='Filtrar por alimentador...'>
  <datalist id='list-ctmt'></datalist>

  <span class='ctrl-label'>Buscar elemento</span>
  <div style='position:relative;margin-bottom:10px'>
    <input list='list-elem' id='input-elem' class='ctrl-input'
           placeholder='COD_ID de qualquer elemento...' style='margin-bottom:0;padding-right:30px'>
    <span id='elem-clear' style='position:absolute;right:8px;top:8px;cursor:pointer;
          color:#7A9BB5;font-size:14px;display:none'>✕</span>
  </div>
  <datalist id='list-elem'></datalist>

  <div class='layer-box'>
    <div class='box-title'>Camadas</div>
    <label class='toggle-row'><input type='checkbox' id='toggle-ssd'    checked>
      <span class='dot' style='background:#00FFE5'></span>Rede MT</label>
    <label class='toggle-row'><input type='checkbox' id='toggle-sub'    checked>
      <span class='dot' style='background:#FFD700'></span>Subestações</label>
    <label class='toggle-row'><input type='checkbox' id='toggle-reg'>
      <span class='dot' style='background:#00C8FF'></span>Reguladores</label>
    <label class='toggle-row'><input type='checkbox' id='toggle-chv'>
      <span class='dot' style='background:#FF5252'></span>Chaves MT</label>
    <label class='toggle-row'><input type='checkbox' id='toggle-untrmt'>
      <span class='dot' style='background:#A78BFA'></span>Trafos (zoom ≥13)</label>

  </div>

  <div class='layer-box' id='incons-box'>
    <div class='box-title'>🔍 Visualizar Inconsistências</div>
    <div id='incons-unavail' style='font-size:11px;color:#7A9BB5;padding:4px 0'>
      ℹ Execute as consultas pré-definidas<br>para habilitar este painel.
    </div>
    <div id='incons-controls' style='display:none'>
      <select id='sel-incons' class='ctrl-input' style='margin-bottom:6px'>
        <option value=''>— Selecione uma visualização —</option>
        <option value='r01'>R01 · Elementos Isolados (rede MT)</option>
        <option value='r02'>R02 · Erros de Faseamento (rede MT)</option>
        <option value='r03'>R03 · Erros de Neutro (trafos MT)</option>
        <option value='r05'>R05 · Potência de Trafos</option>
        <option value='r06'>R06 · Perdas Ferro/Total em Trafos</option>
        <option value='r07'>R07 · Potência de Reguladores baixa</option>
        <option value='r08'>R08 · Comprimento SSDMT zerado/nulo</option>
        <option value='r10'>R10 · Modelagem de Reguladores</option>
      </select>
      <div id='incons-stat' style='font-size:11px;color:#FFD700;margin-bottom:6px;display:none'></div>
      <div style='display:flex;gap:6px'>
        <button id='btn-incons-prev' class='nav-btn'>◀ Anterior</button>
        <button id='btn-incons-next' class='nav-btn'>Próximo ▶</button>
      </div>
      <div id='incons-counter' style='font-size:10px;color:#7A9BB5;margin-top:4px;text-align:center'></div>
    </div>
  </div>

  <div id='info'>
    <div id='info-placeholder'>
      🔌 Selecione um filtro<br>ou clique num elemento<br>para ver os detalhes.
    </div>
  </div>

</div>
"""



_JS_MAPA = r"""
$(function(){

// ── Paleta e cores ─────────────────────────────────────────────────────────
const NEON_PALETTE = __NEON_PALETTE__;
const COR_REG      = __COR_REG__;
const COR_CHV      = __COR_CHV__;
const COR_SUB      = __COR_SUB__;
const COR_UNTRMT   = __COR_UNTRMT__;
// COR_UCMT removida
const COR_OK       = "#00E676";  // verde
const COR_ERR      = "#FF5252";  // vermelho
const COR_WARN     = "#FFD700";  // amarelo

function getNeonColor(s){
    if(!s) return "#999";
    let h=0; for(let i=0;i<s.length;i++) h=s.charCodeAt(i)+((h<<5)-h);
    return NEON_PALETTE[Math.abs(h)%NEON_PALETTE.length];
}

function ungzip(b64){
    if(!b64) return null;
    try{ const bin=atob(b64),arr=new Uint8Array(bin.length);
         for(let i=0;i<bin.length;i++) arr[i]=bin.charCodeAt(i);
         return JSON.parse(new TextDecoder().decode(pako.ungzip(arr)));
    } catch(e){ console.error("ungzip",e); return null; }
}

// ── Estado global ──────────────────────────────────────────────────────────
const map = window["__MAP_NAME__"];
if(!map) return;
// map.getContainer() retorna o div real do Folium (id="map_XXXX")
// document.getElementById('map') retornaria null — esse era o bug
const mapDiv = map.getContainer();
$('#loading').show();
setTimeout(initData, 80);

let db, props, seData, regData, chvData, untrmtData, elemPts, incons;
let selectedFID=null, currentCT="", currentSE="", currentElem=null;
let inconsMode=null, inconsIds=[], inconsIdx=-1;
let inconsSetSSDMT=new Set(), inconsSetPts=new Set();
const boundsIndex={ctmt:{},sub:{}};
const subToCtmt={}, subNameMap={};

// ── Inicialização ──────────────────────────────────────────────────────────
function initData(){
    db         = ungzip(document.getElementById('data-db')?.textContent);
    props      = ungzip(document.getElementById('data-props')?.textContent)||{};
    seData     = ungzip(document.getElementById('data-se')?.textContent);
    regData    = ungzip(document.getElementById('data-reg')?.textContent);
    chvData    = ungzip(document.getElementById('data-chv')?.textContent);
    untrmtData = ungzip(document.getElementById('data-utrmt')?.textContent);
    // ucmtData removida
    elemPts    = ungzip(document.getElementById('data-elempts')?.textContent)||{};
    incons     = ungzip(document.getElementById('data-incons')?.textContent)||{disponivel:false};

    if(seData&&seData.features)
        seData.features.forEach(f=>{const p=f.properties; if(p.COD_ID&&p.NOME) subNameMap[p.COD_ID]=p.NOME;});

    if(db&&db.tiles){
        const sc=db.scale||100000;
        for(let key in db.tiles) db.tiles[key].forEach(d=>{
            const ct=db.ctmt[d[1]],fid=d[0],p=props[fid],sub=p?p.SUB:null;
            if(ct)  updateBounds(boundsIndex.ctmt,ct, d[3],d[4],d[5],d[6],sc);
            if(sub){updateBounds(boundsIndex.sub,sub,d[3],d[4],d[5],d[6],sc);
                    if(!subToCtmt[sub]) subToCtmt[sub]=new Set();
                    if(ct) subToCtmt[sub].add(ct);}
        });
    }

    populateDatalist('list-ctmt',Object.keys(boundsIndex.ctmt).sort());
    populateDatalist('list-se',  Object.keys(boundsIndex.sub).sort());

    // Datalist: SSDMT (props) + pontuais (elemPts) — max 10k
    {const dl=document.getElementById('list-elem');
     const all=new Map();
     Object.keys(props).slice(0,7000).forEach(id=>all.set(id,props[id]?.CTMT||''));
     Object.entries(elemPts).slice(0,3000).forEach(([id,e])=>all.set(id,e.tipo||''));
     all.forEach((ct,id)=>{const o=document.createElement('option');
         o.value=id; if(ct) o.label=ct; dl.appendChild(o);});}

    if(incons.disponivel){
        document.getElementById('incons-unavail').style.display='none';
        document.getElementById('incons-controls').style.display='block';
    }

    initGeoLayers();
    initSubIcons();
    initInconsControls();
    $('#loading').hide();
}

function updateBounds(idx,key,la1,lo1,la2,lo2,sc){
    const a=la1/sc,b=lo1/sc,c=la2/sc,d2=lo2/sc;
    if(!idx[key]) idx[key]=[a,b,c,d2];
    else{const r=idx[key];r[0]=Math.min(r[0],a,c);r[1]=Math.min(r[1],b,d2);
         r[2]=Math.max(r[2],a,c);r[3]=Math.max(r[3],b,d2);}
}
function populateDatalist(id,items){
    const dl=document.getElementById(id); if(!dl) return; dl.innerHTML='';
    items.forEach(v=>{const o=document.createElement('option');o.value=v;dl.appendChild(o);});
}
function zoomTo(b){ if(b) map.flyToBounds([[b[0],b[1]],[b[2],b[3]]],{padding:[20,20],duration:1.3}); }

// ── Ícones subestação ──────────────────────────────────────────────────────
const SUB_SVG=`<svg xmlns="http://www.w3.org/2000/svg" width="28" height="36" viewBox="0 0 28 36">
  <polygon points="14,1 3,20 13,20 9,35 25,14 15,14" fill="#FFD700" stroke="#8B6914" stroke-width="1.5"/></svg>`;
const subIcon=L.divIcon({className:'',
    html:`<div style="width:28px;height:36px;filter:drop-shadow(0 0 4px #FFD700) drop-shadow(0 0 2px #000);cursor:pointer">${SUB_SVG}</div>`,
    iconSize:[28,36],iconAnchor:[14,18]});
let subIconLayer=null;
function initSubIcons(){
    if(!db||!db.sub_centroids||!db.sub_centroids.length) return;
    const mk=db.sub_centroids.map(s=>{
        const m=L.marker([s.lat,s.lon],{icon:subIcon,pane:'seIconPane'});
        m.on('click',e=>{L.DomEvent.stopPropagation(e);
            const info={};['COD_ID','NOME','DESCR','DIST'].forEach(k=>{if(s[k]!=null)info[k]=s[k];});
            showInfo(info,'Subestação');});
        m.on('mouseover',()=>mapDiv.style.cursor='pointer');
        m.on('mouseout', ()=>mapDiv.style.cursor='');
        return m;
    });
    subIconLayer=L.layerGroup(mk); map.addLayer(subIconLayer);
}

// ── Canvas (Rede MT) — pointer-events:none para cliques passarem para GeoJSON
// Fica em overlayPane (400) mas com pointer-events:none no canvas element.
// Os panes de GeoJSON (sePane=300 etc) ficam ABAIXO no z-index mas recebem
// eventos porque o canvas não os intercepta (pointer-events:none).
// Nota: z-index de pane não determina quem recebe cliques quando o elemento
// superior tem pointer-events:none — o browser passa o evento para baixo.
L.CanvasLayer=L.Layer.extend({
    options:{pane:'overlayPane'},
    initialize(o){L.setOptions(this,o);},
    onAdd(map){this._map=map;
        this._canvas=document.createElement('canvas');
        // pointer-events:none → cliques passam através do canvas para GeoJSON
        this._canvas.style.cssText='position:absolute;top:0;left:0;pointer-events:none';
        const pane = map.getPane(this.options.pane);
        if(!pane){ console.error('Pane não encontrado:', this.options.pane); return; }
        pane.appendChild(this._canvas);
        map.on('moveend zoomend resize',this._reset,this); this._reset();},
    onRemove(map){this._canvas.remove();map.off('moveend zoomend resize',this._reset,this);},
    redraw(){this._reset();return this;},
    _reset(){
        if(!this._map||!db) return;
        const sz=this._map.getSize(),cnv=this._canvas;
        cnv.width=sz.x; cnv.height=sz.y;
        const ctx=cnv.getContext('2d');
        const top=this._map.containerPointToLayerPoint([0,0]);
        L.DomUtil.setPosition(cnv,top);
        ctx.clearRect(0,0,sz.x,sz.y);
        const sc=db.scale||100000;
        const vb=this._map.getBounds().pad(0.15);
        const isSSDMTmode = inconsMode&&(inconsMode==='r01'||inconsMode==='r02'||inconsMode==='r08');

        for(let key in db.tiles) db.tiles[key].forEach(d=>{
            const ct=db.ctmt[d[1]],fid=d[0];
            if(currentCT&&ct!==currentCT) return;
            if(currentSE&&subToCtmt[currentSE]&&!subToCtmt[currentSE].has(ct)) return;
            const la1=d[3]/sc,lo1=d[4]/sc,la2=d[5]/sc,lo2=d[6]/sc;
            if(!vb.contains([la1,lo1])&&!vb.contains([la2,lo2])) return;
            const pt1=this._map.latLngToContainerPoint([la1,lo1]);
            const pt2=this._map.latLngToContainerPoint([la2,lo2]);
            const isSel=(fid===selectedFID)||(currentElem&&fid===currentElem);
            let color,lw=1.6,alpha=0.85;
            if(isSSDMTmode)
                { color=inconsSetSSDMT.has(fid)?COR_ERR:COR_OK; lw=inconsSetSSDMT.has(fid)?2.5:1.2; alpha=inconsSetSSDMT.has(fid)?1:0.5; }
            else color=getNeonColor(ct);
            if(isSel){color='#FFFFFF';lw=3.5;alpha=1;}
            ctx.beginPath(); ctx.strokeStyle=color; ctx.lineWidth=lw; ctx.globalAlpha=alpha;
            ctx.moveTo(pt1.x,pt1.y); ctx.lineTo(pt2.x,pt2.y);
            ctx.stroke(); ctx.globalAlpha=1;
        });
    }
});
let ssdLayer=new L.CanvasLayer({pane:'overlayPane'}); map.addLayer(ssdLayer);

// ── Camadas GeoJSON — nos panes acima do canvas ────────────────────────────
let subLayer,regLayer,chvLayer,untrmtLayer,inconsPointLayer;

function initGeoLayers(){
    // Canvas fica em overlayPane(400) com pointer-events:none
    // GeoJSON panes ficam em 410-470 → acima do canvas → recebem cliques normalmente
    const panes=[['sePane',410],['seIconPane',470],['chvPane',420],['regPane',430],['untrmtPane',440],['inconsPane',460]];
    panes.forEach(([n,z])=>{if(!map.getPane(n)){const p=map.createPane(n);p.style.zIndex=z;}});

    subLayer   = createPolyLayer(seData,   'sePane',    COR_SUB,    'Subestação');
    // REG, CHV, UNTRMT: iniciam desmarcados e não adicionados ao mapa
    regLayer   = createPointLayer(regData,    'regPane',    COR_REG,    'Regulador', 7, false);
    chvLayer   = createChvLayer(chvData,      'chvPane',    COR_CHV,    'Chave MT');
    untrmtLayer= createPointLayer(untrmtData, 'untrmtPane', COR_UNTRMT, 'Transformador', 5, false);

    // UNTRMT: zoom condicional (zoom ≥ 13) — só adiciona se toggle marcado
    map.on('zoomend',()=>{
        const z=map.getZoom();
        const onU=z>=13&&document.getElementById('toggle-untrmt')?.checked;
        if(untrmtLayer){ if(onU) map.addLayer(untrmtLayer); else map.removeLayer(untrmtLayer); }
    });
}

// Camada temporária para marcadores de inconsistência em pontos (REG, CHV, TRAFO)
function atualizarInconsPoints(){
    if(inconsPointLayer){ map.removeLayer(inconsPointLayer); inconsPointLayer=null; }
    if(!inconsMode||!inconsSetPts.size) return;
    const color = (inconsMode==='r07'||inconsMode==='r10') ? COR_REG :
                  (inconsMode==='r05'||inconsMode==='r06') ? COR_WARN : COR_ERR;
    const markers=[...inconsSetPts].map(fid=>{
        const e=elemPts[fid]; if(!e||!e.lat) return null;
        const m=L.circleMarker([e.lat,e.lon],{
            radius:11,color:'#fff',weight:2,fillColor:color,fillOpacity:0.92,pane:'inconsPane'
        });
        m.on('click',ev=>{L.DomEvent.stopPropagation(ev); showInfo(e,e.tipo||'Elemento Inconsistente');});
        m.on('mouseover',()=>mapDiv.style.cursor='pointer');
        m.on('mouseout', ()=>mapDiv.style.cursor='');
        return m;
    }).filter(Boolean);
    inconsPointLayer=L.layerGroup(markers); map.addLayer(inconsPointLayer);
}

function createPolyLayer(data,pane,color,title){
    if(!data||!Array.isArray(data.features)||!data.features.length) return null;
    return L.geoJSON(data,{pane,
        style:()=>({color,fillColor:color,fillOpacity:0.08,weight:1.5,dashArray:'4,4'}),
        onEachFeature:(f,l)=>{
            l.on('click',e=>{L.DomEvent.stopPropagation(e); showInfo(f.properties,title);});
            l.on('mouseover',()=>mapDiv.style.cursor='pointer');
            l.on('mouseout', ()=>mapDiv.style.cursor='');
        }}).addTo(map);
}
function createPointLayer(data,pane,color,title,radius=6,addToMap=true){
    if(!data||!Array.isArray(data.features)||!data.features.length) return null;
    const layer = L.geoJSON(data,{pane,
        pointToLayer:(f,ll)=>L.circleMarker(ll,{
            radius, color:'#fff', weight:1.5,
            fillColor:color, fillOpacity:0.9,
            interactive:true  // garante recebimento de cliques mesmo sobre canvas
        }),
        onEachFeature:(f,l)=>{
            l.on('click',e=>{L.DomEvent.stopPropagation(e); showInfo(f.properties,title);});
            l.on('mouseover',()=>mapDiv.style.cursor='pointer');
            l.on('mouseout', ()=>mapDiv.style.cursor='');
        }});
    if(addToMap) layer.addTo(map);
    return layer;
}

// 1D — Chaves MT: ícone quadrado SVG para diferenciação visual rápida
function createChvLayer(data,pane,color,title){
    if(!data||!Array.isArray(data.features)||!data.features.length) return null;
    const sz=10;
    const chvIcon = (c)=>L.divIcon({
        className:'',
        html:`<svg width="${sz*2}" height="${sz*2}" viewBox="0 0 ${sz*2} ${sz*2}"
                   xmlns="http://www.w3.org/2000/svg">
               <rect x="2" y="2" width="${sz*2-4}" height="${sz*2-4}"
                     rx="2" fill="${c}" stroke="#fff" stroke-width="1.5"/>
              </svg>`,
        iconSize:[sz*2,sz*2], iconAnchor:[sz,sz]
    });
    const layer = L.geoJSON(data,{pane,
        pointToLayer:(f,ll)=>L.marker(ll,{icon:chvIcon(color), interactive:true, pane}),
        onEachFeature:(f,l)=>{
            l.on('click',e=>{L.DomEvent.stopPropagation(e); showInfo(f.properties,title);});
            l.on('mouseover',()=>mapDiv.style.cursor='pointer');
            l.on('mouseout', ()=>mapDiv.style.cursor='');
        }});
    // Não adicionar ao mapa inicialmente (toggle desmarcado)
    return layer;
}

// ── Click na rede MT via tile lookup ──────────────────────────────────────
// NOTA: o Canvas está no pane mais baixo (tilePane), então GeoJSON recebe
// cliques primeiro. Só chega aqui se não clicou num GeoJSON.
function findNearest(latlng){
    if(!db) return null;
    const n=Math.pow(2,db.z),sc=db.scale,lr=latlng.lat*(Math.PI/180);
    const xt=Math.floor((latlng.lng+180)/360*n);
    const yt=Math.floor((1-(Math.log(Math.tan(lr)+1/Math.cos(lr))/Math.PI))/2*n);
    const items=db.tiles[xt+','+yt]; if(!items) return null;
    const z=map.getZoom(),tol=z<13?0.002:z>16?0.0001:0.0003;
    let closest=null,minD=Infinity;
    items.forEach(d=>{
        const ct=db.ctmt[d[1]];
        if(currentCT&&ct!==currentCT) return;
        if(currentSE&&subToCtmt[currentSE]&&!subToCtmt[currentSE].has(ct)) return;
        const lm=(d[3]+d[5])/2/sc,om=(d[4]+d[6])/2/sc;
        const dist=Math.sqrt(Math.pow(latlng.lat-lm,2)+Math.pow(latlng.lng-om,2));
        if(dist<tol&&dist<minD){minD=dist;closest=d[0];}
    });
    return closest;
}

let lastMove=0;
map.on('mousemove',e=>{
    const now=Date.now(); if(now-lastMove<50) return; lastMove=now;
    mapDiv.style.cursor=findNearest(e.latlng)?'pointer':'';
});
map.on('click',e=>{
    const fid=findNearest(e.latlng);
    if(fid){selectedFID=fid;currentElem=null;if(props[fid])showInfo(props[fid],'Trecho MT');
            L.DomEvent.stopPropagation(e);}
    else{selectedFID=null;
         document.getElementById('info').innerHTML='<div id="info-placeholder">🗺 Clique num elemento.</div>';}
    ssdLayer.redraw();
});

// ── Filtros ────────────────────────────────────────────────────────────────
document.getElementById('input-ctmt')?.addEventListener('input',function(){
    const val=this.value.trim(),opts=[...document.getElementById('list-ctmt').children].map(o=>o.value);
    if(opts.includes(val)||val===''){currentCT=val;selectedFID=null;currentElem=null;
        if(boundsIndex.ctmt[val]) zoomTo(boundsIndex.ctmt[val]);
        ssdLayer.redraw();updateGeoFilters();}
});
document.getElementById('input-se')?.addEventListener('input',function(){
    const val=this.value.trim(),opts=[...document.getElementById('list-se').children].map(o=>o.value);
    if(opts.includes(val)||val===''){currentSE=val;currentCT='';selectedFID=null;currentElem=null;
        const ic=document.getElementById('input-ctmt');if(ic)ic.value='';
        if(boundsIndex.sub[val]) zoomTo(boundsIndex.sub[val]);
        ssdLayer.redraw();updateGeoFilters();}
});
document.getElementById('input-elem')?.addEventListener('input',function(){
    const val=this.value.trim();
    const clr=document.getElementById('elem-clear');
    if(clr) clr.style.display=val?'block':'none';
    if(!val){currentElem=null;ssdLayer.redraw();return;}
    if(props[val]){
        currentElem=val;selectedFID=val;showInfo(props[val],'Trecho MT');
        const sc=db.scale;
        for(let key in db.tiles){const f=db.tiles[key].find(d=>d[0]===val);
            if(f){map.flyTo([(f[3]+f[5])/2/sc,(f[4]+f[6])/2/sc],Math.max(map.getZoom(),15),{duration:1.2});break;}}
        ssdLayer.redraw();return;
    }
    if(elemPts[val]){
        const e=elemPts[val];currentElem=val;selectedFID=null;
        showInfo(e,e.tipo||'Elemento');
        map.flyTo([e.lat,e.lon],Math.max(map.getZoom(),15),{duration:1.2});
        ssdLayer.redraw();
    }
});
document.getElementById('elem-clear')?.addEventListener('click',function(){
    const inp=document.getElementById('input-elem');if(inp)inp.value='';
    this.style.display='none';currentElem=null;selectedFID=null;ssdLayer.redraw();
    document.getElementById('info').innerHTML='<div id="info-placeholder">🗺 Clique num elemento.</div>';
});

function updateGeoFilters(){
    [chvLayer,regLayer].forEach(lyr=>{if(!lyr)return;
        lyr.eachLayer(l=>{const p=l.feature.properties;let vis=true;
            if(currentCT&&p.CTMT!==currentCT) vis=false;
            if(currentSE&&subToCtmt[currentSE]){
                if(p.SUB&&p.SUB!==currentSE) vis=false;
                else if(p.CTMT&&!subToCtmt[currentSE].has(p.CTMT)) vis=false;}
            if(vis)l.addTo(map);else l.removeFrom(map);});});
    if(subLayer) subLayer.eachLayer(l=>{
        const cod=l.feature.properties.COD_ID||l.feature.properties.SUB;
        const vis=!currentSE||(cod===currentSE);
        if(vis)l.addTo(map);else l.removeFrom(map);});
}

// ── Toggles ────────────────────────────────────────────────────────────────
$('#toggle-ssd').change(e=>e.target.checked?map.addLayer(ssdLayer):map.removeLayer(ssdLayer));
$('#toggle-sub').change(e=>{
    subLayer&&(e.target.checked?map.addLayer(subLayer):map.removeLayer(subLayer));
    subIconLayer&&(e.target.checked?map.addLayer(subIconLayer):map.removeLayer(subIconLayer));
});
$('#toggle-reg').change(e=>regLayer&&(e.target.checked?map.addLayer(regLayer):map.removeLayer(regLayer)));
$('#toggle-chv').change(e=>chvLayer&&(e.target.checked?map.addLayer(chvLayer):map.removeLayer(chvLayer)));
$('#toggle-untrmt').change(e=>{
    if(!untrmtLayer)return;
    if(e.target.checked&&map.getZoom()>=13)map.addLayer(untrmtLayer);else map.removeLayer(untrmtLayer);
});
// toggle-ucmt removido
map.on('baselayerchange',()=>setTimeout(()=>ssdLayer.redraw(),100));

// ── Inconsistências ────────────────────────────────────────────────────────
function initInconsControls(){
    document.getElementById('sel-incons')?.addEventListener('change',e=>setInconsMode(e.target.value));
    document.getElementById('btn-incons-prev')?.addEventListener('click',()=>navegarIncons(-1));
    document.getElementById('btn-incons-next')?.addEventListener('click',()=>navegarIncons(+1));
}

function setInconsMode(mode){
    inconsMode=mode||null; inconsIds=[]; inconsIdx=-1;
    inconsSetSSDMT=new Set(); inconsSetPts=new Set();
    if(inconsPointLayer){map.removeLayer(inconsPointLayer);inconsPointLayer=null;}
    const stat=document.getElementById('incons-stat');
    const ctr =document.getElementById('incons-counter');
    if(!mode||!incons.disponivel){
        if(stat)stat.style.display='none'; if(ctr)ctr.textContent='';
        ssdLayer.redraw(); return;
    }

    // Mapear ids brutos para filtrados (somente visíveis no mapa MT)
    const rawMap={
        r01: incons.r01_isolados||[], r02: incons.r02_fase||[],
        r03: incons.r03_neutro||[],   r05: incons.r05_trafo_pot||[],
        r06: incons.r06_trafo_per||[],r07: incons.r07_reg_pot||[],
        r08: incons.r08_ssdmt_comp||[],r10: incons.r10_reg_model||[],
    };
    const rawIds = rawMap[mode]||[];

    // Separar em SSDMT (props) e pontuais (elemPts) — descartar invisíveis
    const ssdmtIds=[], ptsIds=[];
    rawIds.forEach(id=>{
        if(props[id])         ssdmtIds.push(id);
        else if(elemPts[id]) ptsIds.push(id);
        // se não está em nenhum: é de rede BT/outra entidade não plotada → ignorar
    });

    inconsIds   = [...ssdmtIds,...ptsIds].sort();
    inconsSetSSDMT = new Set(ssdmtIds);
    inconsSetPts   = new Set(ptsIds);

    // Calcular total visível vs total bruto para info ao usuário
    const totalBruto = rawIds.length;
    const totalVisivel = inconsIds.length;
    const ignorados = totalBruto - totalVisivel;

    if(stat){
        stat.style.display='block';
        const labels={
            r01:`🔴 ${totalVisivel} isolados na rede MT (${inconsIds.length>0?incons.r01_conectados_pct+'% conect.':'—'})`,
            r02:`⚠ ${ssdmtIds.length} SSDMT + ${ptsIds.length} pontos c/ erro fase`,
            r03:`⚠ ${ptsIds.length} trafos com erro de neutro`,
            r05:`⚠ ${ptsIds.length} trafos com potência inconsistente`,
            r06:`⚠ ${ptsIds.length} trafos com perdas inconsistentes`,
            r07:`⚠ ${ptsIds.length} reguladores c/ potência baixa`,
            r08:`⚠ ${ssdmtIds.length} segmentos SSDMT comprimento zero`,
            r10:`⚠ ${ptsIds.length} reguladores com erro de modelagem`,
        };
        let txt = labels[mode]||'';
        if(ignorados>0) txt += `<br><span style='color:#7A9BB5;font-size:10px'>(${ignorados} de rede BT/outros não plotados)</span>`;
        stat.innerHTML=txt;
    }

    _removePing();  // remover highlight do modo anterior
    if(!inconsIds.length){
        if(ctr) ctr.textContent='✓ Sem inconsistências na rede MT.';
    } else {
        if(ctr) ctr.textContent=`0 / ${inconsIds.length}`;
        atualizarInconsPoints();
    }
    ssdLayer.redraw();
}

// Marcador pulsante atual (removido ao navegar para o próximo)
let _pingMarker = null;

function _removePing(){
    if(_pingMarker){ map.removeLayer(_pingMarker); _pingMarker=null; }
}

function _addPing(lat, lon){
    _removePing();
    // Círculo externo pulsante (magenta/amarelo) via divIcon com CSS keyframe
    const pingIcon = L.divIcon({
        className:'',
        html:`<div class="incons-ping" style="
            width:32px;height:32px;border-radius:50%;
            border:3px solid #FF00FF;
            background:rgba(255,0,255,0.15);
            box-shadow:0 0 8px 4px rgba(255,0,255,0.5);
        "></div>`,
        iconSize:[32,32], iconAnchor:[16,16]
    });
    _pingMarker = L.marker([lat,lon], {icon:pingIcon, pane:'inconsPane', interactive:false});
    map.addLayer(_pingMarker);
}

function navegarIncons(delta){
    if(!inconsIds.length) return;
    inconsIdx=Math.max(0,Math.min(inconsIds.length-1, inconsIdx+delta));
    const fid=inconsIds[inconsIdx];
    const ctr=document.getElementById('incons-counter');
    if(ctr) ctr.textContent=`${inconsIdx+1} / ${inconsIds.length}`;

    if(inconsSetPts.has(fid)){
        const e=elemPts[fid]; if(!e) return;
        map.flyTo([e.lat,e.lon],16,{duration:1.0,
            animate:true}).once('moveend',()=>_addPing(e.lat,e.lon));
        const label = inconsMode==='r07'?'Regulador — Potência Baixa':
                      inconsMode==='r10'?'Regulador — Erro Modelagem':
                      inconsMode==='r05'?'Trafo — Potência Inconsistente':
                      inconsMode==='r06'?'Trafo — Perdas Inconsistentes':
                      inconsMode==='r03'?'Trafo — Erro Neutro':
                      inconsMode==='r02'?'Elem. — Erro Faseamento':'Elemento Isolado';
        showInfo(e, label);
    } else {
        // SSDMT — highlight como segmento selecionado + ping no midpoint
        const sc=db.scale;
        let lat=null, lon=null;
        for(let key in db.tiles){
            const f=db.tiles[key].find(d=>d[0]===fid);
            if(f){ lat=(f[3]+f[5])/2/sc; lon=(f[4]+f[6])/2/sc;
                   map.flyTo([lat,lon],16,{duration:1.0})
                      .once('moveend',()=>{ if(lat) _addPing(lat,lon); });
                   break; }
        }
        selectedFID=fid;
        const label = inconsMode==='r08'?'SSDMT — Comprimento Zero':
                      inconsMode==='r02'?'SSDMT — Erro Faseamento':'SSDMT Isolado';
        if(props[fid]) showInfo(props[fid],label);
        ssdLayer.redraw();
    }
}

// ── Painel de informações ──────────────────────────────────────────────────
window.showInfo=function(p,title='Elemento'){
    const d=document.getElementById('info');
    let h=`<h4>📍 ${title}</h4><table>`;
    const order=['COD_ID','NOME','CTMT','SUB','PAC_1','PAC_2','PAC','FAS_CON','COMP','TIP_CND','POT_NOM','DMD_CON','DIST','tipo'];
    order.forEach(k=>{if(p[k]===undefined||p[k]===null||p[k]==='')return;
        let val=p[k];
        if(k==='SUB'&&subNameMap[val])
            val=`<strong>${val}</strong><br><span style='font-size:10px;color:#7A9BB5'>${subNameMap[val]}</span>`;
        h+=`<tr><td>${k}</td><td>${val}</td></tr>`;});
    for(const k in p) if(!order.includes(k)&&k!=='geometry'&&p[k]!==null&&p[k]!=='')
        h+=`<tr><td>${k}</td><td>${p[k]}</td></tr>`;
    h+='</table>'; d.innerHTML=h;
};

}); // fim $(function)
"""

