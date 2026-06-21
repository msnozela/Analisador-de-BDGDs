# -*- coding: utf-8 -*-
"""
ui/aba_dashboard.py
Dashboard de Análise de Inconsistências — visualização gráfica via Matplotlib.

DECISÕES DE DESIGN
-------------------
1. Gráficos vazios: quando uma regra não encontra inconsistências, exibe um
   card verde "✓ Sem inconsistências" no lugar do gráfico — evita gráficos
   de pizza/barra com 0 valores, que confundem o usuário.
2. Tipo de gráfico adaptado ao dado:
   R01 Isolados       → Donut (conectados vs desconectados por tabela)
   R02 Faseamento     → Barras horizontais (erros por tabela)
   R03 Neutro         → Barras horizontais (erros por tabela)
   R04 Resistência    → KPI card (número absoluto)
   R05 Potência Trafos → Barras empilhadas (corretos vs inconsistentes por tipo)
   R06 Perdas Trafos  → Barras agrupadas (erro ferro vs erro total)
   R07 Reguladores Pot → KPI card
   R08 Comprimento    → Barras verticais (SSDMT / SSDBT / RAMLIG)
   R09 Curva Carga    → Pizza (distribuição por tabela)
   R10 Modelagem Reg  → Barras horizontais (por tipo de erro)
3. Modal de detalhe: Toplevel com Treeview + exportação CSV/XLSX.
"""

import os
import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import pandas as pd

try:
    import matplotlib
    matplotlib.use("TkAgg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    MPL_OK = True
except ImportError:
    MPL_OK = False

from core.consultas import (
    CONSULTAS_PREDEFINIDAS,
    listar_bdgds_no_banco_resultados,
    carregar_resultados_banco,
    NOME_BANCO_RESULTADOS,
)
from ui.tema import CORES, FONTES

# Cores do tema para matplotlib
_BG    = "#1E2D3D"
_FG    = "#E8F0F7"
_ACC   = "#00C8FF"
_ERR   = "#FF5252"
_OK    = "#00E676"
_WARN  = "#FFD600"
_GRID  = "#243447"
_BARS  = ["#00C8FF", "#00E676", "#FFD600", "#FF5252", "#B39DDB",
          "#80DEEA", "#A5D6A7", "#FFCC80", "#EF9A9A", "#CE93D8"]


def _safe_int(df, col: str, row: int = 0, default: int = 0) -> int:
    """Converte df[col].iloc[row] para int, retornando default para NaN/None/erro."""
    import pandas as _pd
    try:
        if df is None or df.empty or col not in df.columns:
            return default
        val = df[col].iloc[row]
        if _pd.isna(val):
            return default
        return int(val)
    except Exception:
        return default


def _cfg_ax(ax, title=""):
    """Aplica estilo escuro padrão a um eixo matplotlib."""
    ax.set_facecolor(_BG)
    ax.tick_params(colors=_FG, labelsize=7)
    for spine in ax.spines.values():
        spine.set_edgecolor(_GRID)
    ax.xaxis.label.set_color(_FG)
    ax.yaxis.label.set_color(_FG)
    if title:
        ax.set_title(title, color=_ACC, fontsize=8, pad=6, fontweight="bold")


class AbaDashboard(ttk.Frame):

    def __init__(self, parent, caminhos: dict, status_var: tk.StringVar):
        super().__init__(parent, style="TFrame")
        self._caminhos   = caminhos
        self._status_var = status_var
        self._resultados: dict[int, dict] = {}
        self._bdgd_atual: str = ""

        self._build()

        if not MPL_OK:
            self._log_aviso(
                "matplotlib não instalado. Instale com: pip install matplotlib"
            )

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self):
        C = CORES
        F = FONTES

        # Título
        tk.Label(self, text="Dashboard — Análise de Inconsistências",
                 bg=C["bg_app"], fg=C["texto"],
                 font=F["titulo_aba"], anchor="w").pack(
            fill="x", padx=24, pady=(20, 2))

        tk.Label(self,
                 text="Visualização gráfica das 10 regras de inconsistência da BDGD.",
                 bg=C["bg_app"], fg=C["texto_sec"],
                 font=F["pequeno"], anchor="w").pack(
            fill="x", padx=24, pady=(0, 12))

        # ── Barra de controles ────────────────────────────────────────
        ctrl = tk.Frame(self, bg=C["bg_card"])
        ctrl.pack(fill="x", padx=24, pady=(0, 10))

        tk.Label(ctrl, text="BDGD analisada:", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(
            side="left", padx=(14, 8), pady=10)

        self._var_bdgd = tk.StringVar()
        self._combo_bdgd = ttk.Combobox(
            ctrl, textvariable=self._var_bdgd, state="readonly", width=55)
        self._combo_bdgd.pack(side="left", padx=(0, 8), pady=10)
        self._combo_bdgd.bind("<<ComboboxSelected>>", self._on_bdgd_selecionada)

        tk.Button(
            ctrl, text="↺  Atualizar",
            command=self._atualizar_lista_bdgds,
            bg=C["bg_input"], fg=C["texto"],
            font=F["botao"], relief="flat", bd=0,
            padx=10, pady=4, cursor="hand2",
            activebackground=C["bg_hover"], activeforeground=C["acento"],
        ).pack(side="left", padx=(0, 6), pady=10)

        tk.Button(
            ctrl, text="↓  Exportar resumo (.xlsx)",
            command=self._exportar_resumo,
            bg=C["bg_input"], fg=C["texto"],
            font=F["botao"], relief="flat", bd=0,
            padx=10, pady=4, cursor="hand2",
            activebackground=C["bg_hover"], activeforeground=C["acento"],
        ).pack(side="left", pady=10)

        # Aviso quando sem dados
        self._var_aviso = tk.StringVar(value="")
        self._lbl_aviso = tk.Label(
            ctrl, textvariable=self._var_aviso,
            bg=C["bg_card"], fg=C["aviso"],
            font=F["pequeno"], wraplength=400, justify="left")
        self._lbl_aviso.pack(side="left", padx=14, pady=10)

        # ── Área de gráficos (canvas scrollável) ─────────────────────
        frame_scroll = tk.Frame(self, bg=C["bg_app"])
        frame_scroll.pack(fill="both", expand=True, padx=24, pady=(0, 8))

        sc_y = tk.Scrollbar(frame_scroll, orient="vertical",
                            bg=C["bg_painel"], troughcolor=C["bg_app"])
        sc_y.pack(side="right", fill="y")

        self._canvas_scroll = tk.Canvas(
            frame_scroll, bg=C["bg_app"],
            highlightthickness=0, bd=0,
            yscrollcommand=sc_y.set)
        self._canvas_scroll.pack(side="left", fill="both", expand=True)
        sc_y.config(command=self._canvas_scroll.yview)

        self._frame_graficos = tk.Frame(self._canvas_scroll, bg=C["bg_app"])
        self._canvas_win = self._canvas_scroll.create_window(
            (0, 0), window=self._frame_graficos, anchor="nw")

        self._frame_graficos.bind(
            "<Configure>",
            lambda e: self._canvas_scroll.configure(
                scrollregion=self._canvas_scroll.bbox("all")))
        self._canvas_scroll.bind(
            "<Configure>",
            lambda e: self._canvas_scroll.itemconfig(
                self._canvas_win, width=e.width))

        # Scroll com roda do mouse
        self._canvas_scroll.bind_all(
            "<MouseWheel>",
            lambda e: self._canvas_scroll.yview_scroll(
                int(-1 * (e.delta / 120)), "units"))

        # Placeholder inicial
        self._mostrar_placeholder()
        self._atualizar_lista_bdgds()

    # ------------------------------------------------------------------
    # Gerenciamento de BDGDs
    # ------------------------------------------------------------------

    def _atualizar_lista_bdgds(self):
        bdgds = listar_bdgds_no_banco_resultados(self._caminhos["duckdb"])
        self._combo_bdgd["values"] = bdgds

        if bdgds:
            self._combo_bdgd.config(state="readonly")
            self._combo_bdgd.set(bdgds[0])
            self._var_aviso.set("")
            self._on_bdgd_selecionada()
        else:
            self._combo_bdgd.config(state="disabled")
            self._var_aviso.set(
                "⚠  Execute as consultas pré-definidas na aba Consultas "
                "para habilitar este painel.")
            self._mostrar_placeholder()

    def _on_bdgd_selecionada(self, *_):
        bdgd = self._var_bdgd.get()
        if not bdgd:
            return
        self._bdgd_atual = bdgd
        self._resultados = carregar_resultados_banco(
            self._caminhos["duckdb"], bdgd)
        self._renderizar_todos()
        self._status_var.set(f"Dashboard: {bdgd}")

    # ------------------------------------------------------------------
    # Renderização dos 10 gráficos
    # ------------------------------------------------------------------

    def _limpar_graficos(self):
        for w in self._frame_graficos.winfo_children():
            w.destroy()
        plt.close("all")

    def _mostrar_placeholder(self):
        self._limpar_graficos()
        C = CORES
        F = FONTES
        tk.Label(
            self._frame_graficos,
            text="Nenhuma BDGD analisada.\n\nExecute as consultas pré-definidas "
                 "na aba Consultas e volte aqui.",
            bg=C["bg_app"], fg=C["texto_desab"],
            font=("Segoe UI", 12), justify="center",
        ).pack(expand=True, pady=80)

    def _renderizar_todos(self):
        if not MPL_OK:
            return
        self._limpar_graficos()

        C = CORES

        # Grade 2 colunas de cards
        self._frame_graficos.columnconfigure(0, weight=1)
        self._frame_graficos.columnconfigure(1, weight=1)

        renderers = [
            self._card_r01, self._card_r02, self._card_r03, self._card_r04,
            self._card_r05, self._card_r06, self._card_r07, self._card_r08,
            self._card_r09, self._card_r10,
        ]

        for i, renderer in enumerate(renderers):
            row, col = divmod(i, 2)
            card = tk.Frame(
                self._frame_graficos,
                bg=C["bg_card"], bd=0,
                highlightthickness=1,
                highlightbackground=C["borda"])
            card.grid(row=row, column=col, sticky="nsew",
                      padx=6, pady=6, ipadx=4, ipady=4)
            self._frame_graficos.rowconfigure(row, weight=1)

            q = CONSULTAS_PREDEFINIDAS[i]
            dados = self._resultados.get(q["id"], {})
            df_q  = dados.get("quant", pd.DataFrame())

            try:
                renderer(card, q, df_q)
            except Exception as _card_err:
                tk.Label(
                    card,
                    text=f"⚠ Erro ao renderizar este card:\n{_card_err}",
                    bg=CORES["bg_card"], fg=CORES["erro"],
                    font=FONTES["pequeno"], wraplength=320, justify="left",
                ).pack(padx=14, pady=20, anchor="w")

    # ------------------------------------------------------------------
    # Helpers de card
    # ------------------------------------------------------------------

    def _header_card(self, parent, q: dict) -> tk.Frame:
        """Cria cabeçalho do card com título, descrição e botão Ver Detalhes."""
        C = CORES; F = FONTES
        hdr = tk.Frame(parent, bg=C["bg_card"])
        hdr.pack(fill="x", padx=10, pady=(10, 4))

        left = tk.Frame(hdr, bg=C["bg_card"])
        left.pack(side="left", fill="x", expand=True)

        tk.Label(left,
                 text=f"R{q['id']:02d} — {q['nome']}",
                 bg=C["bg_card"], fg=C["acento"],
                 font=F["corpo_bold"], anchor="w").pack(fill="x")

        tk.Label(left, text=q["descricao"],
                 bg=C["bg_card"], fg=C["texto_desab"],
                 font=F["pequeno"], anchor="w",
                 wraplength=340, justify="left").pack(fill="x")

        tk.Button(
            hdr, text="Ver Detalhes",
            command=lambda: self._abrir_modal(q),
            bg=C["bg_input"], fg=C["texto"],
            font=F["pequeno"], relief="flat", bd=0,
            padx=8, pady=3, cursor="hand2",
            activebackground=C["bg_hover"], activeforeground=C["acento"],
        ).pack(side="right", padx=(8, 0))

        return hdr

    def _card_sem_inconsistencias(self, parent):
        """Exibe badge verde quando não há erros."""
        C = CORES; F = FONTES
        fr = tk.Frame(parent, bg=C["bg_card"])
        fr.pack(fill="both", expand=True, pady=20)
        tk.Label(fr, text="✓  Sem inconsistências encontradas",
                 bg=C["bg_card"], fg=C["sucesso"],
                 font=("Segoe UI", 10, "bold")).pack(expand=True)

    def _embed_fig(self, parent, fig):
        """Embute uma figura matplotlib em um frame Tkinter."""
        canvas = FigureCanvasTkAgg(fig, master=parent)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True,
                                    padx=6, pady=(0, 8))
        plt.close(fig)

    def _fig_base(self, w=5.5, h=2.8):
        """Cria figura com fundo escuro."""
        fig = plt.Figure(figsize=(w, h), facecolor=_BG, tight_layout=True)
        return fig

    # ------------------------------------------------------------------
    # R01 — Elementos Isolados → Donut por tabela
    # ------------------------------------------------------------------

    def _card_r01(self, parent, q, df):
        self._header_card(parent, q)

        df = df[df["DESCONECTADOS"] > 0] if not df.empty else df

        if df.empty:
            self._card_sem_inconsistencias(parent)
            return

        fig = self._fig_base(w=5.8, h=2.9)
        ax  = fig.add_subplot(111)

        labels  = df["TABELA"].tolist()
        valores = df["DESCONECTADOS"].tolist()
        total   = sum(valores)

        # Calcular percentuais para decidir o que exibir
        pcts = [v / total * 100 if total > 0 else 0 for v in valores]

        # Suprimir autopct em fatias pequenas (<3%) para evitar sobreposição
        def _autopct(pct):
            return f"{pct:.1f}%" if pct >= 3.0 else ""

        wedges, texts, autotexts = ax.pie(
            valores,
            labels=None,
            autopct=_autopct,
            pctdistance=0.80,       # empurrar % para dentro da rosca
            colors=_BARS[:len(valores)],
            wedgeprops=dict(width=0.55, edgecolor=_BG, linewidth=0.8),
            startangle=90,
            textprops=dict(color=_FG, fontsize=6.5),
        )

        # Esconder textos de % que ficaram em branco (fatias < 3%)
        for at in autotexts:
            if at.get_text() == "":
                at.set_visible(False)

        # Legenda externa com todos os itens — inclui as fatias pequenas
        leg_labels = [
            f"{l}  {v:,}  ({p:.1f}%)"
            for l, v, p in zip(labels, valores, pcts)
        ]
        ax.legend(
            wedges, leg_labels,
            loc="center left", bbox_to_anchor=(1.0, 0.5),
            fontsize=6.5, labelcolor=_FG,
            facecolor=_BG, edgecolor=_GRID,
            framealpha=0.9,
        )

        ax.set_title(f"Total isolados: {total:,}", color=_ACC,
                     fontsize=8, fontweight="bold", pad=8)
        ax.set_facecolor(_BG)
        fig.patch.set_facecolor(_BG)
        self._embed_fig(parent, fig)

    # ------------------------------------------------------------------
    # R02 — Erros de Faseamento → Barras horizontais
    # ------------------------------------------------------------------

    def _card_r02(self, parent, q, df):
        self._header_card(parent, q)
        if df.empty or df["TOTAL_PROBLEMAS_FASEAMENTO"].sum() == 0:
            self._card_sem_inconsistencias(parent)
            return

        fig = self._fig_base()
        ax  = fig.add_subplot(111)
        df_s = df.sort_values("TOTAL_PROBLEMAS_FASEAMENTO")
        bars = ax.barh(df_s["TABELA"], df_s["TOTAL_PROBLEMAS_FASEAMENTO"],
                       color=_ERR, height=0.5)
        ax.bar_label(bars, fmt="%d", color=_FG, fontsize=7, padding=3)
        _cfg_ax(ax, "Erros por tabela")
        ax.set_facecolor(_BG)
        fig.patch.set_facecolor(_BG)
        self._embed_fig(parent, fig)

    # ------------------------------------------------------------------
    # R03 — Erros de Neutro → Barras horizontais
    # ------------------------------------------------------------------

    def _card_r03(self, parent, q, df):
        self._header_card(parent, q)
        col = "TOTAL_ERROS_NEUTRO"
        if df.empty or col not in df.columns or df[col].fillna(0).sum() == 0:
            self._card_sem_inconsistencias(parent)
            return

        fig = self._fig_base()
        ax  = fig.add_subplot(111)
        df_s = df.sort_values(col)
        bars = ax.barh(df_s["TABELA"], df_s[col], color=_WARN, height=0.5)
        ax.bar_label(bars, fmt="%d", color=_FG, fontsize=7, padding=3)
        _cfg_ax(ax, "Violações de neutro por tabela")
        ax.set_facecolor(_BG)
        fig.patch.set_facecolor(_BG)
        self._embed_fig(parent, fig)

    # ------------------------------------------------------------------
    # R04 — Resistência de Condutores → KPI card
    # ------------------------------------------------------------------

    def _card_r04(self, parent, q, df):
        self._header_card(parent, q)
        C = CORES; F = FONTES

        col_principal = "TOTAL_CONDUTORES_INCONSISTENTES"
        if df.empty or col_principal not in df.columns:
            self._card_sem_inconsistencias(parent)
            return

        val = _safe_int(df, col_principal)

        fr = tk.Frame(parent, bg=C["bg_card"])
        fr.pack(fill="both", expand=True, pady=10)

        cor   = C["sucesso"] if val == 0 else C["erro"]
        emoji = "✓" if val == 0 else "⚠"

        tk.Label(fr, text=f"{emoji}  {val:,}",
                 bg=C["bg_card"], fg=cor,
                 font=("Segoe UI", 22, "bold")).pack(pady=(10, 4))
        tk.Label(fr, text="condutores com impedância inconsistente",
                 bg=C["bg_card"], fg=C["texto_sec"],
                 font=F["pequeno"]).pack()

        for lbl, c in [("SSDMT afetados",  "TOTAL_SSDMT_AFETADOS"),
                        ("SSDBT afetados",  "TOTAL_SSDBT_AFETADOS"),
                        ("RAMLIG afetados", "TOTAL_RAMLIG_AFETADOS")]:
            v = _safe_int(df, c)
            tk.Label(fr, text=f"{lbl}: {v:,}",
                     bg=C["bg_card"], fg=C["texto"],
                     font=F["pequeno"]).pack()

    # ------------------------------------------------------------------
    # R05 — Potência de Transformadores → Barras empilhadas
    # ------------------------------------------------------------------

    def _card_r05(self, parent, q, df):
        self._header_card(parent, q)
        if df.empty or "TOTAL_INCONSISTENCIAS" not in df.columns or                 df["TOTAL_INCONSISTENCIAS"].fillna(0).sum() == 0:
            self._card_sem_inconsistencias(parent)
            return

        fig = self._fig_base()
        ax  = fig.add_subplot(111)

        tipos   = df["DESCRICAO_TIPO"].tolist()
        total   = df["TOTAL_TRANSFORMADORES_TIPO"].tolist()
        incons  = df["TOTAL_INCONSISTENCIAS"].tolist()
        correto = [max(0, t - i) for t, i in zip(total, incons)]
        x = range(len(tipos))

        ax.bar(x, correto, label="Corretos", color=_OK,   width=0.5)
        ax.bar(x, incons,  label="Inconsist.", color=_ERR, width=0.5, bottom=correto)
        ax.set_xticks(list(x))
        ax.set_xticklabels(tipos, rotation=15, fontsize=7, color=_FG)
        ax.legend(fontsize=7, labelcolor=_FG,
                  facecolor=_BG, edgecolor=_GRID)
        _cfg_ax(ax, "Corretos vs Inconsistentes por tipo")
        ax.set_facecolor(_BG)
        fig.patch.set_facecolor(_BG)
        self._embed_fig(parent, fig)

    # ------------------------------------------------------------------
    # R06 — Perdas Ferro/Total → Barras agrupadas
    # ------------------------------------------------------------------

    def _card_r06(self, parent, q, df):
        self._header_card(parent, q)
        cols_needed = ["QTD_TRAFOS_ERRO_PERDA_FERRO", "QTD_TRAFOS_ERRO_PERDA_TOTAL"]
        if df.empty or not all(c in df.columns for c in cols_needed):
            self._card_sem_inconsistencias(parent)
            return

        v_ferro = _safe_int(df, "QTD_TRAFOS_ERRO_PERDA_FERRO")
        v_total = _safe_int(df, "QTD_TRAFOS_ERRO_PERDA_TOTAL")

        if v_ferro == 0 and v_total == 0:
            self._card_sem_inconsistencias(parent)
            return

        fig = self._fig_base(h=2.4)
        ax  = fig.add_subplot(111)
        cats = ["Erro Perda\nFerro (>5%)", "Erro Perda\nTotal (>10%)"]
        vals = [v_ferro, v_total]
        bars = ax.bar(cats, vals, color=[_WARN, _ERR], width=0.45)
        ax.bar_label(bars, fmt="%d", color=_FG, fontsize=8, padding=3)
        _cfg_ax(ax, "Trafos com erros de perda")
        ax.set_facecolor(_BG)
        fig.patch.set_facecolor(_BG)
        self._embed_fig(parent, fig)

    # ------------------------------------------------------------------
    # R07 — Potência de Reguladores → KPI card
    # ------------------------------------------------------------------

    def _card_r07(self, parent, q, df):
        self._header_card(parent, q)
        C = CORES; F = FONTES

        col_err = "TOTAL_REGULADORES_COM_ERRO"
        col_tot = "TOTAL_REGULADORES_BASE"
        val_err = _safe_int(df, col_err)
        val_tot = _safe_int(df, col_tot)

        fr = tk.Frame(parent, bg=C["bg_card"])
        fr.pack(fill="both", expand=True, pady=10)

        cor   = C["sucesso"] if val_err == 0 else C["erro"]
        emoji = "✓" if val_err == 0 else "⚠"

        tk.Label(fr, text=f"{emoji}  {val_err:,}",
                 bg=C["bg_card"], fg=cor,
                 font=("Segoe UI", 22, "bold")).pack(pady=(10, 4))
        tk.Label(fr, text="reguladores com potência abaixo do mínimo",
                 bg=C["bg_card"], fg=C["texto_sec"],
                 font=F["pequeno"]).pack()

        mono = _safe_int(df, "QTD_MONOFASICOS_ABAIXO_LIMITE")
        tri  = _safe_int(df, "QTD_TRIFASICOS_ABAIXO_LIMITE")

        tk.Label(fr, text=f"Monofásicos <1000 kVA: {mono:,}",
                 bg=C["bg_card"], fg=C["texto"], font=F["pequeno"]).pack()
        tk.Label(fr, text=f"Trifásicos <3000 kVA: {tri:,}",
                 bg=C["bg_card"], fg=C["texto"], font=F["pequeno"]).pack()
        tk.Label(fr, text=f"Total reguladores na base: {val_tot:,}",
                 bg=C["bg_card"], fg=C["texto_desab"], font=F["pequeno"]).pack(pady=(4, 0))

    # ------------------------------------------------------------------
    # R08 — Comprimento Zerado → Barras verticais
    # ------------------------------------------------------------------

    def _card_r08(self, parent, q, df):
        self._header_card(parent, q)
        col = "TOTAL_COMP_ZERADO_OU_NULO"
        if df.empty or col not in df.columns or df[col].fillna(0).sum() == 0:
            self._card_sem_inconsistencias(parent)
            return

        fig = self._fig_base(h=2.4)
        ax  = fig.add_subplot(111)
        bars = ax.bar(df["ORIGEM"], df[col],
                      color=_BARS[:len(df)], width=0.45)
        ax.bar_label(bars, fmt="%d", color=_FG, fontsize=8, padding=3)
        _cfg_ax(ax, "Segmentos com comp. zero ou nulo")
        ax.tick_params(axis="x", labelsize=8, colors=_FG)
        ax.set_facecolor(_BG)
        fig.patch.set_facecolor(_BG)
        self._embed_fig(parent, fig)

    # ------------------------------------------------------------------
    # R09 — Curva de Carga → Pizza
    # ------------------------------------------------------------------

    def _card_r09(self, parent, q, df):
        self._header_card(parent, q)
        col = "TOTAL_INCOMPATIBILIDADES"
        if df.empty or col not in df.columns or df[col].fillna(0).sum() == 0:
            self._card_sem_inconsistencias(parent)
            return

        fig = self._fig_base()
        ax  = fig.add_subplot(111)

        df_f = df[df[col] > 0]
        wedges, _, autotexts = ax.pie(
            df_f[col], labels=None, autopct="%1.1f%%",
            colors=_BARS[:len(df_f)],
            startangle=90,
            textprops=dict(color=_FG, fontsize=7))

        ax.legend(wedges,
                  [f"{r} ({v})" for r, v in zip(df_f["TABELA_ORIGEM"], df_f[col])],
                  loc="center left", bbox_to_anchor=(1, 0.5),
                  fontsize=7, labelcolor=_FG,
                  facecolor=_BG, edgecolor=_GRID)

        ax.set_title(f"Total: {df_f[col].sum():,}", color=_ACC,
                     fontsize=8, fontweight="bold")
        ax.set_facecolor(_BG)
        fig.patch.set_facecolor(_BG)
        self._embed_fig(parent, fig)

    # ------------------------------------------------------------------
    # R10 — Modelagem de Reguladores → Barras horizontais
    # ------------------------------------------------------------------

    def _card_r10(self, parent, q, df):
        self._header_card(parent, q)
        col = "QUANTIDADE_POSTOS"
        if df.empty or col not in df.columns or df[col].fillna(0).sum() == 0:
            self._card_sem_inconsistencias(parent)
            return

        fig = self._fig_base()
        ax  = fig.add_subplot(111)
        df_s = df.sort_values(col)
        # Encurtar labels para caber no gráfico
        labels = [s[:40] for s in df_s["STATUS_VALIDACAO"].tolist()]
        bars = ax.barh(labels, df_s[col],
                       color=_BARS[:len(df_s)], height=0.5)
        ax.bar_label(bars, fmt="%d", color=_FG, fontsize=7, padding=3)
        _cfg_ax(ax, "Postos inconsistentes por tipo de erro")
        ax.tick_params(axis="y", labelsize=6)
        ax.set_facecolor(_BG)
        fig.patch.set_facecolor(_BG)
        self._embed_fig(parent, fig)

    # ------------------------------------------------------------------
    # Modal de detalhes (abertura)
    # ------------------------------------------------------------------

    def _abrir_modal(self, q: dict):
        dados    = self._resultados.get(q["id"], {})
        df_abert = dados.get("abert", pd.DataFrame())
        erro     = dados.get("erro")

        top = tk.Toplevel(self)
        top.title(f"Detalhes — R{q['id']:02d} {q['nome']}")
        top.geometry("1000x600")
        top.configure(bg=CORES["bg_app"])

        # Header
        fr_hdr = tk.Frame(top, bg=CORES["bg_card"])
        fr_hdr.pack(fill="x", padx=16, pady=(16, 8))

        tk.Label(fr_hdr,
                 text=f"R{q['id']:02d} — {q['nome']}",
                 bg=CORES["bg_card"], fg=CORES["acento"],
                 font=FONTES["subtitulo"]).pack(side="left", padx=10, pady=8)

        if df_abert.empty:
            msg = erro if erro else "Sem registros de abertura."
            tk.Label(top, text=msg,
                     bg=CORES["bg_app"], fg=CORES["aviso"],
                     font=FONTES["corpo"]).pack(pady=40)
            return

        # Info + botão exportar
        tk.Label(fr_hdr,
                 text=f"{len(df_abert):,} registro(s)",
                 bg=CORES["bg_card"], fg=CORES["texto_sec"],
                 font=FONTES["pequeno"]).pack(side="left", padx=8)

        def _exportar():
            path = filedialog.asksaveasfilename(
                defaultextension=".xlsx",
                filetypes=[("Excel", "*.xlsx"), ("CSV", "*.csv")],
                initialfile=f"r{q['id']:02d}_{q['nome'][:20]}_abertura",
                title="Exportar abertura",
                parent=top,
            )
            if not path:
                return
            try:
                if path.endswith(".csv"):
                    df_abert.to_csv(path, index=False, encoding="utf-8-sig")
                else:
                    df_abert.to_excel(path, index=False)
                messagebox.showinfo("Exportado", path, parent=top)
            except Exception as e:
                messagebox.showerror("Erro", str(e), parent=top)

        tk.Button(
            fr_hdr, text="↓  Exportar CSV/Excel",
            command=_exportar,
            bg=CORES["acento"], fg=CORES["bg_app"],
            font=FONTES["botao"], relief="flat", bd=0,
            padx=10, pady=4, cursor="hand2",
        ).pack(side="right", padx=10)

        # Filtro rápido
        fr_filtro = tk.Frame(top, bg=CORES["bg_input"])
        fr_filtro.pack(fill="x", padx=16, pady=(0, 4))

        tk.Label(fr_filtro, text="🔍 Filtrar:",
                 bg=CORES["bg_input"], fg=CORES["texto_sec"],
                 font=FONTES["pequeno"]).pack(side="left", padx=(8, 4))

        var_filtro = tk.StringVar()
        entry_filtro = tk.Entry(
            fr_filtro, textvariable=var_filtro,
            bg=CORES["bg_input"], fg=CORES["texto"],
            insertbackground=CORES["acento"],
            relief="flat", bd=0, font=FONTES["corpo"])
        entry_filtro.pack(side="left", fill="x", expand=True, pady=4, padx=(0, 8))

        # Treeview
        fr_tree = tk.Frame(top, bg=CORES["bg_card"])
        fr_tree.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        cols = list(df_abert.columns)
        sc_y = tk.Scrollbar(fr_tree, orient="vertical")
        sc_y.pack(side="right", fill="y")
        sc_x = tk.Scrollbar(fr_tree, orient="horizontal")
        sc_x.pack(side="bottom", fill="x")

        tree = ttk.Treeview(fr_tree, columns=cols, show="headings",
                            yscrollcommand=sc_y.set, xscrollcommand=sc_x.set)
        tree.pack(side="left", fill="both", expand=True)
        sc_y.config(command=tree.yview)
        sc_x.config(command=tree.xview)

        for col in cols:
            larg = max(df_abert[col].astype(str).map(len).max(), len(col))
            tree.heading(col, text=col)
            tree.column(col, width=min(larg * 8 + 16, 280), minwidth=60)

        def _popular(df_src):
            tree.delete(*tree.get_children())
            for _, row in df_src.head(5000).iterrows():
                tree.insert("", "end", values=list(row))

        def _filtrar(*_):
            termo = var_filtro.get().strip().lower()
            if not termo:
                _popular(df_abert)
            else:
                mask = df_abert.apply(
                    lambda c: c.astype(str).str.lower().str.contains(termo, na=False)
                ).any(axis=1)
                _popular(df_abert[mask])

        var_filtro.trace_add("write", _filtrar)
        _popular(df_abert)

    # ------------------------------------------------------------------
    # Exportar resumo
    # ------------------------------------------------------------------

    def _exportar_resumo(self):
        if not self._resultados:
            messagebox.showwarning("Aviso", "Carregue uma BDGD primeiro.")
            return

        ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        nome = f"dashboard_inconsistencias_{ts}.xlsx"
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialfile=nome, title="Exportar resumo")
        if not path:
            return

        try:
            consultas_idx = {q["id"]: q for q in CONSULTAS_PREDEFINIDAS}
            with pd.ExcelWriter(path, engine="openpyxl") as writer:
                for qid, dados in self._resultados.items():
                    q    = consultas_idx.get(qid, {"nome": f"R{qid:02d}"})
                    df_q = dados.get("quant", pd.DataFrame())
                    if not df_q.empty:
                        sheet = f"R{qid:02d}_{q['nome']}"[:31]
                        df_q.to_excel(writer, sheet_name=sheet, index=False)
            messagebox.showinfo("Exportado", path)
        except Exception as e:
            messagebox.showerror("Erro", str(e))

    def _log_aviso(self, msg: str):
        C = CORES
        tk.Label(self._frame_graficos, text=f"⚠  {msg}",
                 bg=C["bg_app"], fg=C["aviso"],
                 font=FONTES["pequeno"]).pack(pady=20)

    # ------------------------------------------------------------------
    # Chamado pelo app.py ao navegar para a aba
    # ------------------------------------------------------------------

    def atualizar_dashboard(self):
        self._atualizar_lista_bdgds()
