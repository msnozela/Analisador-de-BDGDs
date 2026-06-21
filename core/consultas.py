# -*- coding: utf-8 -*-
"""
core/consultas.py
Execução das 10 regras de inconsistência e persistência multi-BDGD.

ARQUITETURA DO BANCO DE RESULTADOS (bdgd_inconsistencias.duckdb)
-----------------------------------------------------------------
Cada tabela de resultado inclui a coluna NOME_BDGD como primeira coluna,
permitindo armazenar resultados de múltiplas BDGDs no mesmo banco sem
sobrescrever dados anteriores.

Estratégia de upsert:
  1. DELETE FROM tabela WHERE NOME_BDGD = ?
  2. INSERT INTO tabela SELECT nome_bdgd, * FROM resultado

Assim reexecutar uma BDGD já existente atualiza apenas os registros dela,
preservando completamente os dados das demais BDGDs.
"""

import time
import os
import datetime

import duckdb
import pandas as pd


# ---------------------------------------------------------------------------
# Catálogo das 10 regras de inconsistência
# ---------------------------------------------------------------------------

CONSULTAS_PREDEFINIDAS: list[dict] = [
    {
        "id":       1,
        "nome":     "Elementos Isolados",
        "descricao": "Elementos da TOPOLOGIA sem conexão elétrica via PAC até o início do alimentador.",
        "tabela_quant": "r01_isolados_quant",
        "tabela_abert": "r01_isolados_abert",
        "sql_quant": (
            "SELECT TABELA, "
            "SUM(CASE WHEN ORDEM IS NOT NULL THEN 1 ELSE 0 END) AS CONECTADOS, "
            "SUM(CASE WHEN ORDEM IS NULL THEN 1 ELSE 0 END) AS DESCONECTADOS, "
            "ROUND(SUM(CASE WHEN ORDEM IS NULL THEN 1 ELSE 0 END)::DOUBLE / COUNT(*)::DOUBLE * 100, 3) AS PERCENT_DESCON "
            "FROM TOPOLOGIA GROUP BY TABELA ORDER BY DESCONECTADOS DESC"
        ),
        "sql_abert": (
            "SELECT * FROM TOPOLOGIA WHERE ORDEM IS NULL ORDER BY TABELA, COD_ID"
        ),
    },
    {
        "id":       2,
        "nome":     "Erros de Faseamento",
        "descricao": "Incompatibilidade de faseamento entre elemento pai e filho na TOPOLOGIA.",
        "tabela_quant": "r02_faseamento_quant",
        "tabela_abert": "r02_faseamento_abert",
        "sql_quant": (
            "SELECT TABELA, "
            "COUNT(CASE WHEN (PAI_FASE NOT LIKE '%A%' AND FASE LIKE '%A%') OR "
            "(PAI_FASE NOT LIKE '%B%' AND FASE LIKE '%B%') OR "
            "(PAI_FASE NOT LIKE '%C%' AND FASE LIKE '%C%') THEN 1 END) AS TOTAL_PROBLEMAS_FASEAMENTO, "
            "COUNT(*) AS TOTAL_REGISTROS_TABELA, "
            "ROUND((COUNT(CASE WHEN (PAI_FASE NOT LIKE '%A%' AND FASE LIKE '%A%') OR "
            "(PAI_FASE NOT LIKE '%B%' AND FASE LIKE '%B%') OR "
            "(PAI_FASE NOT LIKE '%C%' AND FASE LIKE '%C%') THEN 1 END)::DOUBLE / COUNT(*)::DOUBLE) * 100, 2) "
            "|| '%' AS PERCENTUAL_REPRESENTACAO "
            "FROM TOPOLOGIA GROUP BY TABELA "
            "HAVING TOTAL_PROBLEMAS_FASEAMENTO > 0 ORDER BY TOTAL_PROBLEMAS_FASEAMENTO DESC"
        ),
        "sql_abert": (
            "SELECT * FROM TOPOLOGIA WHERE "
            "(PAI_FASE NOT LIKE '%A%' AND FASE LIKE '%A%') OR "
            "(PAI_FASE NOT LIKE '%B%' AND FASE LIKE '%B%') OR "
            "(PAI_FASE NOT LIKE '%C%' AND FASE LIKE '%C%') ORDER BY TABELA"
        ),
    },
    {
        "id":       3,
        "nome":     "Erros envolvendo o Neutro",
        "descricao": "Pai sem neutro e filho com neutro, excluindo transformadores (pai e filho) e chaves BT.",
        "tabela_quant": "r03_neutro_quant",
        "tabela_abert": "r03_neutro_abert",
        "sql_quant": (
            "SELECT TABELA, COUNT(*) AS TOTAL_ERROS_NEUTRO "
            "FROM TOPOLOGIA WHERE "
            "PAI_FASE NOT LIKE '%N%' AND FASE LIKE '%N%' "
            "AND PAI_TABELA NOT LIKE '%UNTRMT%' "
            "AND TABELA NOT LIKE '%UNTRMT%' "
            "AND TABELA NOT LIKE '%UCMT%' "
            "AND PAI_TABELA NOT LIKE '%UNSEBT%' "
            "GROUP BY TABELA ORDER BY TOTAL_ERROS_NEUTRO DESC"
        ),
        "sql_abert": (
            "SELECT * FROM TOPOLOGIA WHERE "
            "PAI_FASE NOT LIKE '%N%' AND FASE LIKE '%N%' "
            "AND PAI_TABELA NOT LIKE '%UNTRMT%' "
            "AND TABELA NOT LIKE '%UNTRMT%' "
            "AND TABELA NOT LIKE '%UCMT%' "
            "AND PAI_TABELA NOT LIKE '%UNSEBT%' "
            "ORDER BY TABELA"
        ),
    },
    {
        "id":       4,
        "nome":     "Resistência de Condutores (SEGCON)",
        "descricao": "Condutores com resistência zerada, nula ou >10 Ohm/km (exceto AZN).",
        "tabela_quant": "r04_resistencia_quant",
        "tabela_abert": "r04_resistencia_abert",
        "sql_quant": (
            "SELECT COUNT(*) AS TOTAL_CONDUTORES_INCONSISTENTES, "
            "SUM(COALESCE(B.QTDE_SSDMT,0)) AS TOTAL_SSDMT_AFETADOS, "
            "SUM(COALESCE(C.QTDE_SSDBT,0)) AS TOTAL_SSDBT_AFETADOS, "
            "SUM(COALESCE(D.QTDE_RAMLIG,0)) AS TOTAL_RAMLIG_AFETADOS "
            "FROM SEGCON S "
            "LEFT JOIN (SELECT COUNT(COD_ID) AS QTDE_SSDMT, TIP_CND FROM SSDMT GROUP BY TIP_CND) B ON S.COD_ID = B.TIP_CND "
            "LEFT JOIN (SELECT COUNT(COD_ID) AS QTDE_SSDBT, TIP_CND FROM SSDBT GROUP BY TIP_CND) C ON S.COD_ID = C.TIP_CND "
            "LEFT JOIN (SELECT COUNT(COD_ID) AS QTDE_RAMLIG, TIP_CND FROM RAMLIG GROUP BY TIP_CND) D ON S.COD_ID = D.TIP_CND "
            "WHERE (S.R_REGUL NOT LIKE '%AZN%' OR S.R_REGUL IS NULL) "
            "AND (S.R1 > 10 OR S.R1 IS NULL OR S.R1 = 0 OR S.X1 IS NULL OR S.X1 = 0) "
            "AND (COALESCE(B.QTDE_SSDMT,0) > 0 OR COALESCE(C.QTDE_SSDBT,0) > 0 OR COALESCE(D.QTDE_RAMLIG,0) > 0)"
        ),
        "sql_abert": (
            "SELECT S.COD_ID, S.R1, S.X1, "
            "CASE WHEN B.QTDE_SSDMT IS NULL THEN '' ELSE B.QTDE_SSDMT::VARCHAR END AS QTDE_SSDMT, "
            "CASE WHEN C.QTDE_SSDBT IS NULL THEN '' ELSE C.QTDE_SSDBT::VARCHAR END AS QTDE_SSDBT, "
            "CASE WHEN D.QTDE_RAMLIG IS NULL THEN '' ELSE D.QTDE_RAMLIG::VARCHAR END AS QTDE_RAMLIG "
            "FROM SEGCON S "
            "LEFT JOIN (SELECT COUNT(COD_ID) AS QTDE_SSDMT, TIP_CND FROM SSDMT GROUP BY TIP_CND) B ON S.COD_ID = B.TIP_CND "
            "LEFT JOIN (SELECT COUNT(COD_ID) AS QTDE_SSDBT, TIP_CND FROM SSDBT GROUP BY TIP_CND) C ON S.COD_ID = C.TIP_CND "
            "LEFT JOIN (SELECT COUNT(COD_ID) AS QTDE_RAMLIG, TIP_CND FROM RAMLIG GROUP BY TIP_CND) D ON S.COD_ID = D.TIP_CND "
            "WHERE (S.R_REGUL NOT LIKE '%AZN%' OR S.R_REGUL IS NULL) "
            "AND (S.R1 > 10 OR S.R1 IS NULL OR S.R1 = 0 OR S.X1 IS NULL OR S.X1 = 0) "
            "AND (COALESCE(B.QTDE_SSDMT,0) > 0 OR COALESCE(C.QTDE_SSDBT,0) > 0 OR COALESCE(D.QTDE_RAMLIG,0) > 0)"
        ),
    },
    {
        "id":       5,
        "nome":     "Potência Nominal de Transformadores",
        "descricao": "Transformadores PD com potência acima dos limites técnicos por tipo.",
        "tabela_quant": "r05_potencia_trafos_quant",
        "tabela_abert": "r05_potencia_trafos_abert",
        "sql_quant": (
            "WITH total_por_tipo AS ("
            "SELECT U.TIP_TRAFO, E.COD_ID AS EQ_ID, "
            "CASE WHEN (U.TIP_TRAFO IN ('M','MT','B') AND P.POT >= 100) THEN 1 "
            "WHEN (U.TIP_TRAFO = 'T' AND P.POT >= 300) THEN 1 ELSE 0 END AS INCONSISTENTE "
            "FROM EQTRMT E INNER JOIN UNTRMT U ON E.UNI_TR_MT = U.COD_ID "
            "INNER JOIN TPOTAPRT P ON E.POT_NOM = P.COD_ID) "
            "SELECT TIP_TRAFO, "
            "CASE TIP_TRAFO WHEN 'M' THEN 'Monofásico' WHEN 'MT' THEN 'Mono três fios' "
            "WHEN 'B' THEN 'Bifásico' WHEN 'T' THEN 'Trifásico' ELSE 'Não Identificado' END AS DESCRICAO_TIPO, "
            "SUM(INCONSISTENTE) AS TOTAL_INCONSISTENCIAS, "
            "COUNT(EQ_ID) AS TOTAL_TRANSFORMADORES_TIPO, "
            "ROUND((SUM(INCONSISTENTE)::DOUBLE / COUNT(EQ_ID)::DOUBLE) * 100, 2) || '%' AS PERCENTUAL_INCONSISTENCIA "
            "FROM total_por_tipo GROUP BY TIP_TRAFO ORDER BY TOTAL_INCONSISTENCIAS DESC"
        ),
        "sql_abert": (
            "SELECT E.COD_ID AS COD_ID_EQTRMT, U.COD_ID AS COD_ID_UNTRMT, U.TIP_TRAFO, "
            "CASE U.TIP_TRAFO WHEN 'M' THEN 'Monofásico' WHEN 'MT' THEN 'Mono três fios' "
            "WHEN 'B' THEN 'Bifásico' WHEN 'T' THEN 'Trifásico' ELSE 'Não Identificado' END AS DESCRICAO_TIPO, "
            "U.POS AS POS_UNTRMT, E.POT_NOM AS COD_POT_NOM_EQTRMT, P.POT AS POTENCIA_KVA, "
            "E.TEN_SEC AS COD_TEN_SEC_EQTRMT, T.TEN AS TENSAO_V "
            "FROM EQTRMT E INNER JOIN UNTRMT U ON E.UNI_TR_MT = U.COD_ID "
            "INNER JOIN TPOTAPRT P ON E.POT_NOM = P.COD_ID INNER JOIN TTEN T ON E.TEN_SEC = T.COD_ID "
            "WHERE U.POS = 'PD' AND T.TEN < 2300 "
            "AND ((U.TIP_TRAFO IN ('M','MT','B') AND P.POT > 100) OR (U.TIP_TRAFO = 'T' AND P.POT > 300)) "
            "ORDER BY P.POT DESC, E.COD_ID"
        ),
    },
    {
        "id":       6,
        "nome":     "Perdas Ferro e Total (Transformadores)",
        "descricao": "Transformadores com perdas em vazio >5% ou perdas totais >10% da potência nominal.",
        "tabela_quant": "r06_perdas_trafos_quant",
        "tabela_abert": "r06_perdas_trafos_abert",
        "sql_quant": (
            "SELECT COUNT(*) AS TOTAL_TRAFOS_BASE, "
            "SUM(CASE WHEN (PER_TOT/(POT_NOM*1000.0))*100.0 > 10.0 THEN 1 ELSE 0 END) AS QTD_TRAFOS_ERRO_PERDA_TOTAL, "
            "SUM(CASE WHEN (PER_FER/(POT_NOM*1000.0))*100.0 > 5.0 THEN 1 ELSE 0 END) AS QTD_TRAFOS_ERRO_PERDA_FERRO, "
            "SUM(CASE WHEN (PER_TOT/(POT_NOM*1000.0))*100.0 > 10 OR (PER_FER/(POT_NOM*1000.0))*100.0 > 5 THEN 1 ELSE 0 END) AS TOTAL_TRAFOS_COM_QUALQUER_ERRO "
            "FROM UNTRMT WHERE POT_NOM > 0"
        ),
        "sql_abert": (
            "SELECT COD_ID, POT_NOM, PER_FER, PER_TOT, "
            "ROUND((PER_FER/(POT_NOM*1000.0))*100.0,4) AS PERC_PER_FER, "
            "ROUND((PER_TOT/(POT_NOM*1000.0))*100.0,4) AS PERC_PER_TOT, "
            "CASE WHEN (PER_TOT/(POT_NOM*1000.0))*100.0 > 5.0 AND (PER_FER/(POT_NOM*1000.0))*100.0 > 1.0 THEN 'Erro em Ambos' "
            "WHEN (PER_TOT/(POT_NOM*1000.0))*100.0 > 10.0 THEN 'Erro na Perda Total (>10%)' "
            "ELSE 'Erro na Perda Ferro (>5%)' END AS MOTIVO_INCONSISTENCIA "
            "FROM UNTRMT WHERE POT_NOM > 0 "
            "AND ((PER_TOT/(POT_NOM*1000.0))*100.0 > 10.0 OR (PER_FER/(POT_NOM*1000.0))*100.0 > 5.0) "
            "ORDER BY POT_NOM DESC, COD_ID"
        ),
    },
    {
        "id":       7,
        "nome":     "Potência de Reguladores de Tensão",
        "descricao": "Reguladores com potência abaixo do mínimo (<1000 kVA mono, <3000 kVA tri).",
        "tabela_quant": "r07_reguladores_pot_quant",
        "tabela_abert": "r07_reguladores_pot_abert",
        "sql_quant": (
            "SELECT COUNT(DISTINCT E.COD_ID) AS TOTAL_REGULADORES_BASE, "
            "SUM(CASE WHEN E.LIG_FAS_P IN ('AB','BC','CA','AN','BN','CN') AND P.POT < 1000 THEN 1 ELSE 0 END) AS QTD_MONOFASICOS_ABAIXO_LIMITE, "
            "SUM(CASE WHEN E.LIG_FAS_P = 'ABC' AND P.POT < 3000 THEN 1 ELSE 0 END) AS QTD_TRIFASICOS_ABAIXO_LIMITE, "
            "SUM(CASE WHEN (E.LIG_FAS_P IN ('AB','BC','CA','AN','BN','CN') AND P.POT < 1000) "
            "OR (E.LIG_FAS_P = 'ABC' AND P.POT < 3000) THEN 1 ELSE 0 END) AS TOTAL_REGULADORES_COM_ERRO "
            "FROM EQRE E INNER JOIN TPOTAPRT P ON P.COD_ID = E.POT_NOM"
        ),
        "sql_abert": (
            "SELECT E.COD_ID AS COD_EQUIPAMENTO, E.UN_RE AS COD_UNIDADE, E.LIG_FAS_P AS FASES_LIGACAO, "
            "E.POT_NOM AS COD_POT_NOMINAL, P.POT AS POTENCIA_KVA, "
            "CASE WHEN E.LIG_FAS_P IN ('AB','BC','CA','AN','BN','CN') THEN 'Mono/Bifásica (<1000 kVA)' "
            "WHEN E.LIG_FAS_P = 'ABC' THEN 'Trifásica (<3000 kVA)' ELSE 'Arranjo não padrão' END AS MOTIVO_ALERTA "
            "FROM EQRE E INNER JOIN TPOTAPRT P ON P.COD_ID = E.POT_NOM "
            "WHERE (E.LIG_FAS_P IN ('AB','BC','CA','AN','BN','CN') AND P.POT < 1000) "
            "OR (E.LIG_FAS_P = 'ABC' AND P.POT < 3000) ORDER BY E.LIG_FAS_P, P.POT, E.COD_ID"
        ),
    },
    {
        "id":       8,
        "nome":     "Comprimento de Segmentos Zerados",
        "descricao": "Segmentos MT (SSDMT), BT (SSDBT) e ramais (RAMLIG) com comprimento nulo ou zero.",
        "tabela_quant": "r08_comprimento_quant",
        "tabela_abert": "r08_comprimento_abert",
        "sql_quant": (
            "SELECT 'SSDMT' AS ORIGEM, COUNT(*) AS TOTAL_COMP_ZERADO_OU_NULO FROM SSDMT WHERE comp IS NULL OR comp = 0 "
            "UNION ALL SELECT 'SSDBT', COUNT(*) FROM SSDBT WHERE comp IS NULL OR comp = 0 "
            "UNION ALL SELECT 'RAMLIG', COUNT(*) FROM RAMLIG WHERE comp IS NULL OR comp = 0"
        ),
        "sql_abert": (
            "SELECT cod_id, comp, 'SSDMT' AS ORIGEM FROM SSDMT WHERE comp IS NULL OR comp = 0 "
            "UNION ALL SELECT cod_id, comp, 'SSDBT' FROM SSDBT WHERE comp IS NULL OR comp = 0 "
            "UNION ALL SELECT cod_id, comp, 'RAMLIG' FROM RAMLIG WHERE comp IS NULL OR comp = 0"
        ),
    },
    {
        "id":       9,
        "nome":     "Curvas de Carga Inválidas",
        "descricao": "Cargas (UCMT, UCBT, PIP) com TIP_CC sem correspondência na tabela CRVCRG.",
        "tabela_quant": "r09_curva_carga_quant",
        "tabela_abert": "r09_curva_carga_abert",
        "sql_quant": (
            "SELECT 'UCMT_tab' AS TABELA_ORIGEM, COUNT(*) AS TOTAL_INCOMPATIBILIDADES "
            "FROM UCMT_tab T LEFT JOIN CRVCRG C ON T.TIP_CC = C.COD_ID WHERE C.COD_ID IS NULL AND T.TIP_CC IS NOT NULL "
            "UNION ALL SELECT 'UCBT_tab', COUNT(*) FROM UCBT_tab T LEFT JOIN CRVCRG C ON T.TIP_CC = C.COD_ID WHERE C.COD_ID IS NULL AND T.TIP_CC IS NOT NULL "
            "UNION ALL SELECT 'PIP', COUNT(*) FROM PIP T LEFT JOIN CRVCRG C ON T.TIP_CC = C.COD_ID WHERE C.COD_ID IS NULL AND T.TIP_CC IS NOT NULL"
        ),
        "sql_abert": (
            "SELECT 'UCMT_tab' AS TABELA_ORIGEM, T.COD_ID AS COD_ID_REGISTRO, T.TIP_CC AS TIP_CC_INVALIDO "
            "FROM UCMT_tab T LEFT JOIN CRVCRG C ON T.TIP_CC = C.COD_ID WHERE C.COD_ID IS NULL AND T.TIP_CC IS NOT NULL "
            "UNION ALL SELECT 'UCBT_tab', T.COD_ID, T.TIP_CC FROM UCBT_tab T LEFT JOIN CRVCRG C ON T.TIP_CC = C.COD_ID WHERE C.COD_ID IS NULL AND T.TIP_CC IS NOT NULL "
            "UNION ALL SELECT 'PIP', T.COD_ID, T.TIP_CC FROM PIP T LEFT JOIN CRVCRG C ON T.TIP_CC = C.COD_ID WHERE C.COD_ID IS NULL AND T.TIP_CC IS NOT NULL "
            "ORDER BY TABELA_ORIGEM, COD_ID_REGISTRO"
        ),
    },
    {
        "id":       10,
        "nome":     "Modelagem de Reguladores de Tensão",
        "descricao": "Erros de arranjo em reguladores (UNREMT/EQRE): tipo, fases e quantidade.",
        "tabela_quant": "r10_modelagem_reg_quant",
        "tabela_abert": "r10_modelagem_reg_abert",
        "sql_quant": (
            "WITH eq_agrupados AS (SELECT UN_RE, COUNT(COD_ID) AS QTD_EQUIPAMENTOS, "
            "LIST(LIG_FAS_P) AS LISTA_FAS_P, LIST(LIG_FAS_S) AS LISTA_FAS_S, "
            "COUNT(DISTINCT LIG_FAS_P) < COUNT(COD_ID) AS TEM_DUPLICADO_P, "
            "COUNT(DISTINCT LIG_FAS_S) < COUNT(COD_ID) AS TEM_DUPLICADO_S FROM EQRE GROUP BY UN_RE), "
            "validacao_postos AS (SELECT U.COD_ID, U.TIP_REGU, E.QTD_EQUIPAMENTOS, "
            "CASE WHEN E.QTD_EQUIPAMENTOS = 1 AND NOT ("
            "(U.TIP_REGU = 'M' AND E.LISTA_FAS_P[1] IN ('AN','BN','CN') AND E.LISTA_FAS_S[1] IN ('AN','BN','CN')) OR "
            "(U.TIP_REGU = 'T' AND E.LISTA_FAS_P[1] = 'ABC' AND E.LISTA_FAS_S[1] = 'ABC')) "
            "THEN 'Erro Regra 1: Incompatibilidade para 1 equipamento' "
            "WHEN E.QTD_EQUIPAMENTOS = 2 AND (U.TIP_REGU != 'DA' OR E.TEM_DUPLICADO_P OR E.TEM_DUPLICADO_S "
            "OR NOT (E.LISTA_FAS_P[1] IN ('AB','BC','CA') AND E.LISTA_FAS_P[2] IN ('AB','BC','CA')) "
            "OR NOT (E.LISTA_FAS_S[1] IN ('AB','BC','CA') AND E.LISTA_FAS_S[2] IN ('AB','BC','CA'))) "
            "THEN 'Erro Regra 2: Incompatibilidade para 2 equipamentos' "
            "WHEN E.QTD_EQUIPAMENTOS = 3 AND (U.TIP_REGU NOT IN ('DF','T') OR E.TEM_DUPLICADO_P OR E.TEM_DUPLICADO_S) "
            "THEN 'Erro Regra 3: Incompatibilidade para 3 equipamentos' "
            "WHEN E.QTD_EQUIPAMENTOS IS NULL OR E.QTD_EQUIPAMENTOS = 0 OR E.QTD_EQUIPAMENTOS > 3 "
            "THEN 'Erro Crítico: Quantidade fora do padrão' ELSE 'OK' END AS STATUS_VALIDACAO "
            "FROM UNREMT U LEFT JOIN eq_agrupados E ON U.COD_ID = E.UN_RE) "
            "SELECT STATUS_VALIDACAO, COUNT(*) AS QUANTIDADE_POSTOS FROM validacao_postos "
            "WHERE STATUS_VALIDACAO != 'OK' GROUP BY STATUS_VALIDACAO"
        ),
        "sql_abert": (
            "WITH eq_agrupados AS (SELECT UN_RE, COUNT(COD_ID) AS QTD_EQUIPAMENTOS, "
            "LIST(LIG_FAS_P) AS LISTA_FAS_P, LIST(LIG_FAS_S) AS LISTA_FAS_S, "
            "COUNT(DISTINCT LIG_FAS_P) < COUNT(COD_ID) AS TEM_DUPLICADO_P, "
            "COUNT(DISTINCT LIG_FAS_S) < COUNT(COD_ID) AS TEM_DUPLICADO_S FROM EQRE GROUP BY UN_RE), "
            "postos_com_erro AS (SELECT U.COD_ID AS UNREMT_ID, U.TIP_REGU, COALESCE(E.QTD_EQUIPAMENTOS,0) AS QTD_EQUIPAMENTOS, "
            "CASE WHEN E.QTD_EQUIPAMENTOS = 1 AND NOT ("
            "(U.TIP_REGU = 'M' AND E.LISTA_FAS_P[1] IN ('AN','BN','CN') AND E.LISTA_FAS_S[1] IN ('AN','BN','CN')) OR "
            "(U.TIP_REGU = 'T' AND E.LISTA_FAS_P[1] = 'ABC' AND E.LISTA_FAS_S[1] = 'ABC')) "
            "THEN 'Erro Regra 1: Tipo ou Fases incorretas para 1 equipamento' "
            "WHEN E.QTD_EQUIPAMENTOS = 2 AND (U.TIP_REGU != 'DA' OR E.TEM_DUPLICADO_P OR E.TEM_DUPLICADO_S "
            "OR NOT (E.LISTA_FAS_P[1] IN ('AB','BC','CA') AND E.LISTA_FAS_P[2] IN ('AB','BC','CA')) "
            "OR NOT (E.LISTA_FAS_S[1] IN ('AB','BC','CA') AND E.LISTA_FAS_S[2] IN ('AB','BC','CA'))) "
            "THEN 'Erro Regra 2: Requisitos DA violados ou fases duplicadas' "
            "WHEN E.QTD_EQUIPAMENTOS = 3 AND (U.TIP_REGU NOT IN ('DF','T') OR E.TEM_DUPLICADO_P OR E.TEM_DUPLICADO_S) "
            "THEN 'Erro Regra 3: Requisitos DF/T violados ou fases duplicadas' "
            "WHEN E.QTD_EQUIPAMENTOS IS NULL OR E.QTD_EQUIPAMENTOS = 0 OR E.QTD_EQUIPAMENTOS > 3 "
            "THEN 'Erro Crítico: Posto sem equipamentos ou mais de 3' ELSE 'OK' END AS MOTIVO_ERRO "
            "FROM UNREMT U LEFT JOIN eq_agrupados E ON U.COD_ID = E.UN_RE) "
            "SELECT P.UNREMT_ID, P.TIP_REGU AS TIP_REGU_POSTO, P.QTD_EQUIPAMENTOS AS TOTAL_EQUIP_NO_POSTO, "
            "P.MOTIVO_ERRO, E.COD_ID AS COD_ID_EQUIPAMENTO, E.LIG_FAS_P, E.LIG_FAS_S "
            "FROM postos_com_erro P LEFT JOIN EQRE E ON P.UNREMT_ID = E.UN_RE "
            "WHERE P.MOTIVO_ERRO != 'OK' ORDER BY P.MOTIVO_ERRO, P.UNREMT_ID, E.COD_ID"
        ),
    },
]


# ---------------------------------------------------------------------------
# Classe de conexão com o banco BDGD
# ---------------------------------------------------------------------------

class ConexaoBanco:
    def __init__(self):
        self._con: duckdb.DuckDBPyConnection | None = None
        self._banco_path: str | None = None

    @property
    def conectado(self) -> bool:
        return self._con is not None

    @property
    def banco_path(self) -> str | None:
        return self._banco_path

    def conectar(self, banco_path: str) -> None:
        self.fechar()
        self._con = duckdb.connect(banco_path)
        self._banco_path = banco_path

    def fechar(self) -> None:
        if self._con:
            try:
                self._con.close()
            except Exception:
                pass
        self._con = None
        self._banco_path = None

    def executar(self, sql: str) -> tuple[pd.DataFrame, float]:
        if not self._con:
            raise RuntimeError("Banco não conectado.")
        inicio = time.perf_counter()
        df = self._con.execute(sql).fetchdf()
        return df, time.perf_counter() - inicio

    def listar_tabelas(self) -> list[str]:
        if not self._con:
            return []
        rows = self._con.execute(
            "SELECT table_name FROM information_schema.tables ORDER BY table_name"
        ).fetchall()
        return [r[0] for r in rows]

    def listar_alimentadores(self) -> list[str]:
        if not self._con:
            return []
        try:
            rows = self._con.execute("SELECT COD_ID FROM CTMT ORDER BY COD_ID").fetchall()
            return [r[0] for r in rows]
        except Exception:
            return []


# ---------------------------------------------------------------------------
# Banco de resultados — multi-BDGD com coluna NOME_BDGD
# ---------------------------------------------------------------------------

NOME_BANCO_RESULTADOS = "bdgd_inconsistencias.duckdb"


def _banco_resultados_path(duckdb_dir: str) -> str:
    return os.path.join(duckdb_dir, NOME_BANCO_RESULTADOS)


def _garantir_estrutura_banco_resultados(res_con: duckdb.DuckDBPyConnection) -> None:
    """
    Garante a existência da tabela de histórico.
    As tabelas de resultado são criadas dinamicamente na primeira inserção.
    """
    res_con.execute("""
        CREATE TABLE IF NOT EXISTS tb_historico_execucao (
            nome_bdgd_origem  VARCHAR,
            data_execucao     TIMESTAMP,
            status_sucesso    BOOLEAN,
            total_regras      INTEGER,
            regras_com_erro   INTEGER
        )
    """)


def _upsert_resultado(
    res_con: duckdb.DuckDBPyConnection,
    nome_tabela: str,
    nome_bdgd: str,
    df: pd.DataFrame,
) -> None:
    """
    Insere ou atualiza os resultados de uma BDGD em uma tabela do banco de resultados.

    Estratégia:
      1. Adiciona coluna NOME_BDGD ao DataFrame
      2. Cria a tabela se não existir (schema inferido do DataFrame)
      3. Detecta incompatibilidade de schema (ex: tabela legada com 1 coluna)
         → Se incompatível, recria a tabela preservando dados das outras BDGDs
      4. Deleta registros anteriores desta BDGD
      5. Insere os novos registros
    """
    # Adicionar identificador da BDGD
    df_com_bdgd = df.copy()
    df_com_bdgd.insert(0, "NOME_BDGD", nome_bdgd)

    res_con.register("_upsert_tmp", df_com_bdgd)

    # Verificar se a tabela já existe e tem schema compatível
    tabelas_existentes = {
        r[0] for r in res_con.execute(
            "SELECT table_name FROM information_schema.tables"
        ).fetchall()
    }

    if nome_tabela in tabelas_existentes:
        # Contar colunas da tabela existente
        n_cols_existente = res_con.execute(
            "SELECT COUNT(*) FROM information_schema.columns "
            f"WHERE table_name = '{nome_tabela}'"
        ).fetchone()[0]
        n_cols_novo = len(df_com_bdgd.columns)

        if n_cols_existente != n_cols_novo:
            # Schema incompatível — migrar: salvar dados das outras BDGDs e recriar
            try:
                df_outras = res_con.execute(
                    f'SELECT * FROM "{nome_tabela}" WHERE NOME_BDGD != ?',
                    [nome_bdgd],
                ).fetchdf()
            except Exception:
                df_outras = pd.DataFrame()

            # Recriar tabela com schema correto
            res_con.execute(f'DROP TABLE IF EXISTS "{nome_tabela}"')
            res_con.execute(f"""
                CREATE TABLE "{nome_tabela}" AS
                SELECT * FROM _upsert_tmp WHERE 1=0
            """)

            # Reinserir dados das outras BDGDs se existirem e forem compatíveis
            if not df_outras.empty and len(df_outras.columns) == n_cols_novo:
                res_con.register("_outras_tmp", df_outras)
                res_con.execute(
                    f'INSERT INTO "{nome_tabela}" SELECT * FROM _outras_tmp'
                )
                res_con.unregister("_outras_tmp")
    else:
        # Criar tabela nova com schema correto
        res_con.execute(f"""
            CREATE TABLE "{nome_tabela}" AS
            SELECT * FROM _upsert_tmp WHERE 1=0
        """)

    # Deletar registros anteriores desta BDGD (upsert seguro)
    res_con.execute(
        f'DELETE FROM "{nome_tabela}" WHERE NOME_BDGD = ?',
        [nome_bdgd],
    )

    # Inserir novos registros
    res_con.execute(f'INSERT INTO "{nome_tabela}" SELECT * FROM _upsert_tmp')
    res_con.unregister("_upsert_tmp")


def executar_e_salvar_consultas(
    conexao: ConexaoBanco,
    duckdb_dir: str,
    nome_bdgd: str,
    callback_progresso=None,
) -> dict[int, dict]:
    """
    Executa as 10 regras no banco BDGD conectado e persiste em bdgd_inconsistencias.duckdb.
    Resultados de BDGDs anteriores são preservados — apenas os dados desta BDGD são atualizados.

    Returns: dict {id: {"quant": df, "abert": df, "erro": str|None}}
    """
    res_path = _banco_resultados_path(duckdb_dir)
    res_con  = duckdb.connect(res_path)
    _garantir_estrutura_banco_resultados(res_con)

    resultados: dict[int, dict] = {}
    n_erro = 0

    for q in CONSULTAS_PREDEFINIDAS:
        if callback_progresso:
            callback_progresso(f"[{q['id']:02d}/10] {q['nome']}...")

        entrada: dict = {"quant": pd.DataFrame(), "abert": pd.DataFrame(), "erro": None}

        # Quantitativo
        try:
            df_q, _ = conexao.executar(q["sql_quant"])
            entrada["quant"] = df_q
            if not df_q.empty:
                _upsert_resultado(res_con, q["tabela_quant"], nome_bdgd, df_q)
            else:
                # Garantir que a tabela existe e os registros antigos são limpos
                res_con.execute(
                    f'CREATE TABLE IF NOT EXISTS "{q["tabela_quant"]}" '
                    f'(NOME_BDGD VARCHAR)'
                )
                res_con.execute(
                    f'DELETE FROM "{q["tabela_quant"]}" WHERE NOME_BDGD = ?',
                    [nome_bdgd],
                )
        except Exception as e:
            entrada["erro"] = str(e)
            n_erro += 1
            if callback_progresso:
                callback_progresso(f"  ⚠ Erro quant R{q['id']:02d}: {e}")

        # Abertura
        try:
            df_a, _ = conexao.executar(q["sql_abert"])
            entrada["abert"] = df_a
            if not df_a.empty:
                _upsert_resultado(res_con, q["tabela_abert"], nome_bdgd, df_a)
            else:
                res_con.execute(
                    f'CREATE TABLE IF NOT EXISTS "{q["tabela_abert"]}" '
                    f'(NOME_BDGD VARCHAR)'
                )
                res_con.execute(
                    f'DELETE FROM "{q["tabela_abert"]}" WHERE NOME_BDGD = ?',
                    [nome_bdgd],
                )
        except Exception as e:
            if entrada["erro"] is None:
                entrada["erro"] = str(e)
            n_erro += 1
            if callback_progresso:
                callback_progresso(f"  ⚠ Erro abert R{q['id']:02d}: {e}")

        resultados[q["id"]] = entrada

    # Registrar no histórico (upsert: atualiza se já existe esta BDGD)
    res_con.execute(
        "DELETE FROM tb_historico_execucao WHERE nome_bdgd_origem = ?",
        [nome_bdgd],
    )
    res_con.execute(
        "INSERT INTO tb_historico_execucao VALUES (?, ?, ?, ?, ?)",
        [nome_bdgd, datetime.datetime.now(), n_erro == 0,
         len(CONSULTAS_PREDEFINIDAS), n_erro],
    )

    res_con.close()

    if callback_progresso:
        callback_progresso(
            f"✔ Concluído — {len(CONSULTAS_PREDEFINIDAS) - n_erro}/10 regras OK. "
            f"BDGD '{nome_bdgd}' salva em {NOME_BANCO_RESULTADOS}."
        )

    return resultados


def _tem_coluna_nome_bdgd(con: duckdb.DuckDBPyConnection, tabela: str) -> bool:
    """Verifica se uma tabela possui a coluna NOME_BDGD (banco versão nova)."""
    try:
        cols = {
            r[0].upper()
            for r in con.execute(
                f"SELECT column_name FROM information_schema.columns "
                f"WHERE table_name = '{tabela}'"
            ).fetchall()
        }
        return "NOME_BDGD" in cols
    except Exception:
        return False


def carregar_resultados_banco(duckdb_dir: str, nome_bdgd: str) -> dict[int, dict]:
    """
    Lê os resultados de uma BDGD específica do banco bdgd_inconsistencias.duckdb.

    COMPATIBILIDADE COM BANCO LEGADO
    ---------------------------------
    Bancos gerados pela versão antiga (sem coluna NOME_BDGD) são detectados
    automaticamente. Nesses casos, a leitura ignora o filtro por NOME_BDGD
    e retorna os dados existentes na tabela sem modificação — o Dashboard
    exibirá os dados disponíveis com um aviso de migração pendente.

    Returns: dict {id: {"quant": df, "abert": df, "erro": str|None}}
    """
    res_path = _banco_resultados_path(duckdb_dir)
    if not os.path.exists(res_path):
        return {}

    con = duckdb.connect(res_path, read_only=True)
    resultados: dict[int, dict] = {}

    # Tabelas disponíveis no banco
    tabelas_existentes = {
        r[0]
        for r in con.execute(
            "SELECT table_name FROM information_schema.tables"
        ).fetchall()
    }

    for q in CONSULTAS_PREDEFINIDAS:
        entrada = {"quant": pd.DataFrame(), "abert": pd.DataFrame(), "erro": None}

        for tipo in ("quant", "abert"):
            tabela = q[f"tabela_{tipo}"]
            if tabela not in tabelas_existentes:
                continue
            try:
                if _tem_coluna_nome_bdgd(con, tabela):
                    # Banco versão nova — filtrar por BDGD e excluir coluna de controle
                    df = con.execute(
                        f'SELECT * EXCLUDE (NOME_BDGD) FROM "{tabela}" '
                        f'WHERE NOME_BDGD = ?',
                        [nome_bdgd],
                    ).fetchdf()
                else:
                    # Banco legado (sem NOME_BDGD) — ler tudo sem filtro
                    # Neste caso todos os dados são de uma única BDGD implícita
                    df = con.execute(f'SELECT * FROM "{tabela}"').fetchdf()
                    entrada["erro"] = (
                        "⚠ Banco legado: coluna NOME_BDGD ausente. "
                        "Reexecute as consultas para migrar."
                    )
                entrada[tipo] = df
            except Exception as e:
                entrada["erro"] = str(e)

        resultados[q["id"]] = entrada

    con.close()
    return resultados


def listar_bdgds_no_banco_resultados(duckdb_dir: str) -> list[str]:
    """Retorna as BDGDs disponíveis no banco de resultados, ordenadas pela mais recente."""
    res_path = _banco_resultados_path(duckdb_dir)
    if not os.path.exists(res_path):
        return []
    try:
        con = duckdb.connect(res_path, read_only=True)
        rows = con.execute(
            "SELECT DISTINCT nome_bdgd_origem FROM tb_historico_execucao "
            "ORDER BY data_execucao DESC"
        ).fetchall()
        con.close()
        return [r[0] for r in rows]
    except Exception:
        return []


def listar_tabelas_banco_resultados(duckdb_dir: str) -> list[str]:
    """Retorna todas as tabelas do banco de resultados (para consulta SQL livre)."""
    res_path = _banco_resultados_path(duckdb_dir)
    if not os.path.exists(res_path):
        return []
    try:
        con = duckdb.connect(res_path, read_only=True)
        rows = con.execute(
            "SELECT table_name FROM information_schema.tables ORDER BY table_name"
        ).fetchall()
        con.close()
        return [r[0] for r in rows]
    except Exception:
        return []


def exportar_resultados_excel(resultados: dict, caminho: str) -> None:
    consultas_idx = {q["id"]: q for q in CONSULTAS_PREDEFINIDAS}
    with pd.ExcelWriter(caminho, engine="openpyxl") as writer:
        for qid, entrada in resultados.items():
            nome  = consultas_idx.get(qid, {}).get("nome", f"Regra_{qid}")
            sheet = f"R{qid:02d}_{nome}"[:31]
            df    = entrada.get("quant", pd.DataFrame())
            if not df.empty:
                df.to_excel(writer, sheet_name=sheet, index=False)
