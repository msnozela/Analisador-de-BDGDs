# -*- coding: utf-8 -*-
"""
core/simulacao.py
Lógica de simulação elétrica no OpenDSS via biblioteca opendssdirect.
Sem dependência de GUI.

ESTRUTURA DE PASTAS ESPERADA
-----------------------------
Alimentadores Convertidos/
    └── <nome_bdgd>/
            └── dss_models_output/
                    └── sub__<sub>/
                            └── <alimentador>/
                                    ├── Master_DO01_...dss
                                    ├── Master_DU01_...dss
                                    ├── Master_SA01_...dss
                                    └── ...outros .dss

MODOS DE ARQUIVO MASTER
------------------------
_DO  = Dia Útil Ordinário
_DU  = Dia Útil
_SA  = Sábado / Domingos e Feriados

Cada modo possui 12 arquivos (um por mês).
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Callable

try:
    import opendssdirect as dss
    DSS_DISPONIVEL = True
except ImportError:
    DSS_DISPONIVEL = False


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

PASTA_CONVERTIDOS = "Alimentadores Convertidos"

# Prefixos de modo dos arquivos Master
MODOS_MASTER = {
    "DO": "Dia Útil Ordinário (DO)",
    "DU": "Dia Útil (DU)",
    "SA": "Sábado/Domingo/Feriado (SA)",
}


# ---------------------------------------------------------------------------
# Navegação de pastas
# ---------------------------------------------------------------------------

def pasta_convertidos(base_path: str) -> str:
    """Retorna o path da pasta raiz de alimentadores convertidos."""
    return os.path.join(base_path, PASTA_CONVERTIDOS)


def listar_bdgds_convertidas(base_path: str) -> list[str]:
    """Lista as BDGDs que já possuem alimentadores convertidos."""
    raiz = pasta_convertidos(base_path)
    if not os.path.exists(raiz):
        return []
    return sorted(
        d for d in os.listdir(raiz)
        if os.path.isdir(os.path.join(raiz, d))
    )


def listar_alimentadores_convertidos(base_path: str, nome_bdgd: str) -> list[dict]:
    """
    Percorre a estrutura de pastas e lista todos os alimentadores convertidos
    de uma BDGD, junto com o path da pasta do alimentador.

    Estrutura suportada:
        <raiz>/<nome_bdgd>/dss_models_output/sub__<X>/<alimentador>/
        <raiz>/<nome_bdgd>/<alimentador>/          (estrutura plana)

    Retorna lista de dicts: {"nome": str, "pasta": str}
    """
    raiz_bdgd = os.path.join(pasta_convertidos(base_path), nome_bdgd)
    resultado: list[dict] = []

    if not os.path.exists(raiz_bdgd):
        return resultado

    # Tentar estrutura com dss_models_output
    dss_out = os.path.join(raiz_bdgd, "dss_models_output")

    if os.path.exists(dss_out):
        # sub__AGR/AGR11/, sub__AVA/AVA01/, ...
        for sub in sorted(os.listdir(dss_out)):
            sub_path = os.path.join(dss_out, sub)
            if not os.path.isdir(sub_path):
                continue
            for alim in sorted(os.listdir(sub_path)):
                alim_path = os.path.join(sub_path, alim)
                if os.path.isdir(alim_path) and _tem_master(alim_path):
                    resultado.append({"nome": alim, "pasta": alim_path})
    else:
        # Estrutura plana: <raiz_bdgd>/<alimentador>/
        for alim in sorted(os.listdir(raiz_bdgd)):
            alim_path = os.path.join(raiz_bdgd, alim)
            if os.path.isdir(alim_path) and _tem_master(alim_path):
                resultado.append({"nome": alim, "pasta": alim_path})

    return resultado


def _tem_master(pasta: str) -> bool:
    """Verifica se a pasta contém ao menos um arquivo Master*.dss."""
    return any(
        f.lower().startswith("master") and f.lower().endswith(".dss")
        for f in os.listdir(pasta)
    )


def listar_masters(pasta_alim: str) -> dict[str, list[str]]:
    """
    Lista os arquivos Master*.dss encontrados na pasta do alimentador,
    agrupados por modo (DO, DU, SA) e ordenados por nome.

    Retorna dict: {"DO": [arquivo1, arquivo2, ...], "DU": [...], "SA": [...]}
    """
    resultado: dict[str, list[str]] = {"DO": [], "DU": [], "SA": [], "OUTROS": []}

    if not os.path.exists(pasta_alim):
        return resultado

    for arq in sorted(os.listdir(pasta_alim)):
        if not (arq.lower().startswith("master") and arq.lower().endswith(".dss")):
            continue

        # Identificar modo pelo padrão Master_DO, Master_DU, Master_SA
        match = re.search(r'Master_([A-Z]{2})', arq, re.IGNORECASE)
        if match:
            modo = match.group(1).upper()
            if modo in resultado:
                resultado[modo].append(arq)
            else:
                resultado["OUTROS"].append(arq)
        else:
            resultado["OUTROS"].append(arq)

    return resultado


# ---------------------------------------------------------------------------
# Informações do circuito
# ---------------------------------------------------------------------------

def info_circuito(pasta: str, master: str) -> dict:
    """
    Compila o circuito e retorna dicionário com contadores dos elementos.
    Baseado em SimuladorDSS.info_circuito() do curva_carga.py.

    Returns dict com chaves:
        carga_bt, carga_mt, carga_pip, trafos, barras,
        linhas, ramais, reguladores, reatores, curvas
    """
    if not DSS_DISPONIVEL:
        raise ImportError("opendssdirect não está instalado.")

    # Normalizar path para evitar falhas do OpenDSS com espaços/barras
    pasta_abs  = os.path.abspath(pasta)
    master_abs = os.path.join(pasta_abs, master)

    cwd_orig = os.getcwd()
    try:
        os.chdir(pasta_abs)
        dss.Command("Clear")
        dss.Command(f'Compile "{master_abs}"')
        dss.Command("Set MaxIter=100")
        dss.Command("Set Tolerance=0.0001")

        n_bt = n_mt = n_pip = 0
        dss.Loads.First()
        while True:
            nome = dss.Loads.Name().lower()
            if   nome.startswith("bt_"):  n_bt  += 1
            elif nome.startswith("mt_"):  n_mt  += 1
            elif nome.startswith("pip_"): n_pip += 1
            if not dss.Loads.Next():
                break

        todos = dss.Circuit.AllElementNames()
        curvas_em_uso: set[str] = set()
        dss.Loads.First()
        while True:
            curvas_em_uso.add(dss.Loads.Daily())
            if not dss.Loads.Next():
                break

        return {
            "carga_bt":    n_bt,
            "carga_mt":    n_mt,
            "carga_pip":   n_pip,
            "trafos":      dss.Transformers.Count(),
            "barras":      dss.Circuit.NumBuses(),
            "linhas":      dss.Lines.Count(),
            "ramais":      sum(1 for e in todos if re.match(r'line\.rbt_', e, re.I)),
            "reguladores": sum(1 for e in todos if e.lower().startswith("regcontrol.")),
            "reatores":    sum(1 for e in todos if e.lower().startswith("reactor.")),
            "curvas":      len(curvas_em_uso),
        }
    finally:
        os.chdir(cwd_orig)


# ---------------------------------------------------------------------------
# Simulação Daily
# ---------------------------------------------------------------------------

def simular_daily(
    pasta: str,
    master: str,
    callback_hora: Callable[[dict], None] | None = None,
    callback_log:  Callable[[str], None] | None  = None,
    cancelar_flag: threading.Event | None = None,
) -> list[dict]:
    """
    Executa simulação em modo Daily (24 patamares horários).
    Baseado em SimuladorDSS.simula_daily_iter() do curva_carga.py.

    Args:
        pasta:          Pasta do alimentador (com os .dss).
        master:         Nome do arquivo Master*.dss (só o nome, não o path).
        callback_hora:  Chamado após cada hora com o dict do resultado.
        callback_log:   Chamado com mensagens de log em texto.
        cancelar_flag:  threading.Event — quando set(), interrompe o loop.

    Returns:
        Lista de dicts (24 itens, um por hora):
            {hora, kw, perdas_kw, pct_perdas, convergiu, iteracoes}
    """
    if not DSS_DISPONIVEL:
        raise ImportError("opendssdirect não está instalado.")

    pasta_abs  = os.path.abspath(pasta)
    master_abs = os.path.join(pasta_abs, master)

    cwd_orig = os.getcwd()
    rows: list[dict] = []

    try:
        os.chdir(pasta_abs)

        if callback_log:
            callback_log(f"Compilando circuito: {master}")
            callback_log(f"  Path: {master_abs}")

        dss.Command("Clear")
        dss.Command(f'Compile "{master_abs}"')
        dss.Command("Set MaxIter=100")
        dss.Command("Set maxcontroliter=100")
        dss.Command("Set Tolerance=0.0001")
        dss.Command("Set Mode=Daily StepSize=1h Number=1")

        if callback_log:
            callback_log("Circuito compilado. Iniciando simulação Daily (24h)...")

        for h in range(24):
            if cancelar_flag is not None and cancelar_flag.is_set():
                if callback_log:
                    callback_log("⚠ Simulação cancelada pelo usuário.")
                break

            if callback_log:
                callback_log(f"  Executando patamar {h+1:02d}h...")

            dss.Command("Solve")

            conv    = dss.Solution.Converged()
            total   = abs(dss.Circuit.TotalPower()[0])
            perdas  = dss.Circuit.Losses()[0] / 1000   # W → kW
            iters   = dss.Solution.Iterations()

            pct = (perdas / total * 100) if (conv and total > 0) else 0.0

            row = {
                "hora":      h + 1,
                "kw":        round(total,  2) if conv else 0.0,
                "perdas_kw": round(perdas, 2) if conv else 0.0,
                "pct_perdas": round(pct,   3) if conv else 0.0,
                "convergiu": conv,
                "iteracoes": iters,
            }
            rows.append(row)

            status = "✓ OK" if conv else "✗ NÃO CONVERGIU"
            if callback_log:
                callback_log(
                    f"    {h+1:02d}h → {status} | "
                    f"Pot: {row['kw']:.1f} kW | "
                    f"Perd: {row['perdas_kw']:.2f} kW | "
                    f"Iter: {iters}"
                )

            if callback_hora:
                callback_hora(row)

    finally:
        os.chdir(cwd_orig)

    if callback_log and rows:
        n_ok   = sum(1 for r in rows if r["convergiu"])
        en_tot = sum(r["kw"]        for r in rows if r["convergiu"])
        pd_tot = sum(r["perdas_kw"] for r in rows if r["convergiu"])
        pct_t  = (pd_tot / en_tot * 100) if en_tot > 0 else 0
        callback_log(
            f"\n── Resumo ──────────────────────────────────────────"
        )
        callback_log(f"  Convergência : {n_ok}/24 patamares")
        callback_log(f"  Potência tot : {en_tot:,.2f} kW·h")
        callback_log(f"  Perdas total : {pd_tot:,.2f} kW·h")
        callback_log(f"  % Perdas     : {pct_t:.3f} %")
        callback_log(f"────────────────────────────────────────────────────")

    return rows


# ---------------------------------------------------------------------------
# Exportação
# ---------------------------------------------------------------------------

def exportar_resultados_xlsx(
    rows: list[dict],
    caminho: str,
    meta: dict | None = None,
) -> None:
    """
    Exporta os resultados da simulação Daily para Excel.

    Args:
        rows:    Lista de dicts retornada por simular_daily().
        caminho: Caminho completo do arquivo .xlsx de saída.
        meta:    Dicionário opcional com metadados (alimentador, master, etc.)
                 gravados em uma aba separada "Info".
    """
    import pandas as pd

    registros = []
    for r in rows:
        registros.append({
            "Hora":          f"{r['hora']:02d}h",
            "Potência (kW)": r["kw"]        if r["convergiu"] else None,
            "Perdas (kW)":   r["perdas_kw"] if r["convergiu"] else None,
            "% Perdas":      r["pct_perdas"] if r["convergiu"] else None,
            "Convergiu":     "Sim" if r["convergiu"] else "Não",
            "Iterações":     r["iteracoes"],
        })

    df = pd.DataFrame(registros)

    # Linha de total
    en_ok   = [r for r in rows if r["convergiu"]]
    en_tot  = sum(r["kw"]        for r in en_ok)
    pd_tot  = sum(r["perdas_kw"] for r in en_ok)
    pct_tot = (pd_tot / en_tot * 100) if en_tot > 0 else None
    total_row = pd.DataFrame([{
        "Hora":          "TOTAL",
        "Potência (kW)": round(en_tot, 2),
        "Perdas (kW)":   round(pd_tot, 2),
        "% Perdas":      round(pct_tot, 3) if pct_tot else None,
        "Convergiu":     f"{len(en_ok)}/24",
        "Iterações":     "",
    }])

    df_final = pd.concat([df, total_row], ignore_index=True)

    with pd.ExcelWriter(caminho, engine="openpyxl") as writer:
        df_final.to_excel(writer, sheet_name="Resultados", index=False)

        if meta:
            df_meta = pd.DataFrame(
                list(meta.items()), columns=["Campo", "Valor"]
            )
            df_meta.to_excel(writer, sheet_name="Info", index=False)
