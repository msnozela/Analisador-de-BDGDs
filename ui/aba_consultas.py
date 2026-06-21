# -*- coding: utf-8 -*-
"""
ui/aba_consultas.py
Aba de execução de consultas SQL — manual e pré-definidas.
Inclui tabela com ordenação, filtragem e exportação.
"""

import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter.scrolledtext import ScrolledText as _ScrolledText

import pandas as pd

from core.consultas import (
    ConexaoBanco,
    CONSULTAS_PREDEFINIDAS,
    executar_e_salvar_consultas,
    exportar_resultados_excel,
    listar_tabelas_banco_resultados,
    NOME_BANCO_RESULTADOS,
)
from core.banco import listar_bancos
from ui.tema import CORES, FONTES


class AbaConsultas(ttk.Frame):

    def __init__(self, parent, caminhos: dict, status_var: tk.StringVar):
        super().__init__(parent, style="TFrame")
        self._caminhos = caminhos
        self._status_var = status_var
        self._conexao = ConexaoBanco()
        self._df_atual: pd.DataFrame | None = None
        self._df_filtrado: pd.DataFrame | None = None
        self._resultados_predefinidas: dict = {}
        self._col_sort: str | None = None
        self._sort_asc: bool = True
        # Larguras de coluna ajustadas pelo usuário (persistem entre rerenderizações)
        self._col_larguras_usuario: dict[str, int] = {}
        # Flag para detectar drag real no separador de coluna
        self._resize_em_andamento: bool = False
        # Log persistente das execuções pré-definidas
        self._log_execucao: list[str] = []

        self._build()
        self._atualizar_lista_bancos()

    # ------------------------------------------------------------------
    # Build principal
    # ------------------------------------------------------------------

    def _build(self):
        C = CORES
        F = FONTES

        tk.Label(
            self, text="Consultas SQL — DuckDB",
            bg=C["bg_app"], fg=C["texto"],
            font=F["titulo_aba"], anchor="w",
        ).pack(fill="x", padx=24, pady=(20, 2))
        tk.Label(
            self, text="Execute consultas manuais ou pré-definidas para análise de inconsistências.",
            bg=C["bg_app"], fg=C["texto_sec"],
            font=F["pequeno"], anchor="w",
        ).pack(fill="x", padx=24, pady=(0, 14))

        # ── Conexão ──────────────────────────────────────────────────
        card_con = tk.Frame(self, bg=C["bg_card"])
        card_con.pack(fill="x", padx=24, pady=(0, 10))

        frame_top = tk.Frame(card_con, bg=C["bg_card"])
        frame_top.pack(fill="x", padx=14, pady=12)

        tk.Label(frame_top, text="BANCO:", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(side="left", padx=(0, 8))

        self._var_banco = tk.StringVar()
        self._combo_banco = ttk.Combobox(
            frame_top, textvariable=self._var_banco, state="readonly", width=55
        )
        self._combo_banco.pack(side="left", padx=(0, 8))

        self._btn_conectar = tk.Button(
            frame_top, text="Conectar",
            command=self._conectar,
            bg=C["acento"], fg=C["bg_app"],
            font=F["botao"], relief="flat", bd=0,
            padx=12, pady=4, cursor="hand2",
            activebackground=C["acento_hover"],
            activeforeground=C["bg_app"],
        )
        self._btn_conectar.pack(side="left")

        self._var_status_con = tk.StringVar(value="● Desconectado")
        self._lbl_status_con = tk.Label(
            frame_top, textvariable=self._var_status_con,
            bg=C["bg_card"], fg=C["erro"], font=F["pequeno"],
        )
        self._lbl_status_con.pack(side="left", padx=10)

        # ── Corpo: PanedWindow arrastável ────────────────────────────
        # O usuário pode arrastar o divisor para redimensionar os paineis
        paned = tk.PanedWindow(
            self,
            orient=tk.HORIZONTAL,
            bg=C["bg_app"],
            sashwidth=6,
            sashrelief="flat",
            sashpad=0,
            showhandle=False,
            handlesize=0,
        )
        paned.pack(fill="both", expand=True, padx=24, pady=0)

        # ── Painel esquerdo: consultas ────────────────────────────────
        esq = tk.Frame(paned, bg=C["bg_card"])
        paned.add(esq, minsize=260, width=340, stretch="never")

        tk.Label(esq, text="CONSULTA SQL", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(padx=14, pady=(14, 6), anchor="w")

        self._text_sql = tk.Text(
            esq, height=7,
            bg=C["bg_input"], fg=C["texto"],
            insertbackground=C["acento"],
            font=F["mono"], relief="flat", bd=0,
            wrap="word", padx=8, pady=6,
            undo=True,          # habilita histórico de undo nativo
            maxundo=-1,         # histórico ilimitado
            autoseparators=True,# cada palavra vira um ponto de undo separado
        )
        self._text_sql.pack(fill="x", padx=14)

        # Ctrl+Z = desfazer / Ctrl+Y = refazer
        # O tk.Text não mapeia Ctrl+Y por padrão — bind explícito necessário
        self._text_sql.bind("<Control-z>", lambda e: self._text_sql.edit_undo() or "break")
        self._text_sql.bind("<Control-Z>", lambda e: self._text_sql.edit_undo() or "break")
        self._text_sql.bind("<Control-y>", lambda e: self._text_sql.edit_redo() or "break")
        self._text_sql.bind("<Control-Y>", lambda e: self._text_sql.edit_redo() or "break")

        frame_btns = tk.Frame(esq, bg=C["bg_card"])
        frame_btns.pack(fill="x", padx=14, pady=8)

        self._btn_exec = tk.Button(
            frame_btns, text="▶  Executar",
            command=self._executar_manual,
            bg=C["acento"], fg=C["bg_app"],
            font=F["botao"], relief="flat", bd=0,
            padx=10, pady=5, cursor="hand2",
            activebackground=C["acento_hover"],
            activeforeground=C["bg_app"],
        )
        self._btn_exec.pack(side="left", padx=(0, 6))

        tk.Button(
            frame_btns, text="Limpar",
            command=self._limpar,
            bg=C["bg_input"], fg=C["texto_sec"],
            font=F["botao"], relief="flat", bd=0,
            padx=10, pady=5, cursor="hand2",
            activebackground=C["bg_hover"],
        ).pack(side="left")

        tk.Frame(esq, bg=C["borda"], height=1).pack(fill="x", padx=14, pady=10)

        # Consultas pré-definidas
        tk.Label(esq, text="CONSULTAS PRÉ-DEFINIDAS", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(padx=14, pady=(0, 6), anchor="w")

        frame_pd = tk.Frame(esq, bg=C["bg_card"])
        frame_pd.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        sc_pd = tk.Scrollbar(frame_pd, orient="vertical",
                             bg=C["bg_painel"], troughcolor=C["bg_app"])
        sc_pd.pack(side="right", fill="y")

        self._lb_predefinidas = tk.Listbox(
            frame_pd,
            yscrollcommand=sc_pd.set,
            selectmode="single",
            activestyle="none",
            bg=C["bg_input"], fg=C["texto"],
            selectbackground=C["acento_escuro"],
            font=F["pequeno"], relief="flat", bd=0,
            highlightthickness=0,
        )
        self._lb_predefinidas.pack(side="left", fill="both", expand=True)
        sc_pd.config(command=self._lb_predefinidas.yview)

        for q in CONSULTAS_PREDEFINIDAS:
            self._lb_predefinidas.insert(tk.END, f"  {q['id']:02d}. {q['nome']}")

        self._lb_predefinidas.bind("<Double-Button-1>", self._exibir_consulta_predefinida)
        self._lb_predefinidas.bind("<<ListboxSelect>>", self._preview_consulta)

        # Descrição da query selecionada
        self._var_desc = tk.StringVar(value="")
        tk.Label(
            esq, textvariable=self._var_desc,
            bg=C["bg_card"], fg=C["texto_sec"],
            font=F["pequeno"], wraplength=230, justify="left",
        ).pack(padx=14, pady=(4, 2), anchor="w")

        # Visualização do SQL (quant + abert) ao clicar na listbox
        tk.Label(esq, text="SQL DA REGRA SELECIONADA", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(padx=14, pady=(6, 2), anchor="w")

        frame_sql_prev = tk.Frame(esq, bg=C["bg_card"])
        frame_sql_prev.pack(fill="x", padx=14, pady=(0, 4))

        self._text_sql_prev = _ScrolledText(
            frame_sql_prev,
            height=7,
            bg=C["bg_input"], fg=C["texto_sec"],
            font=("Consolas", 7),
            relief="flat", bd=0,
            state="disabled",
            padx=6, pady=4,
            wrap="word",
        )
        self._text_sql_prev.pack(fill="x")
        self._text_sql_prev.tag_config("header", foreground=CORES["acento"],
                                        font=("Consolas", 7, "bold"))
        self._text_sql_prev.tag_config("sql",    foreground=CORES["texto_sec"])

        tk.Button(
            esq, text="Copiar SQL",
            command=self._copiar_sql_preview,
            bg=C["bg_input"], fg=C["texto"],
            font=F["pequeno"], relief="flat", bd=0,
            padx=6, pady=3, cursor="hand2",
            activebackground=C["bg_hover"], activeforeground=C["acento"],
        ).pack(padx=14, anchor="e", pady=(0, 6))

        # Botões executar pré-definidas
        frame_pd_btns = tk.Frame(esq, bg=C["bg_card"])
        frame_pd_btns.pack(fill="x", padx=14, pady=(8, 14))

        tk.Button(
            frame_pd_btns, text="▶  Ver selecionada",
            command=self._exibir_consulta_predefinida,
            bg=C["bg_input"], fg=C["texto"],
            font=F["botao"], relief="flat", bd=0,
            padx=8, pady=5, cursor="hand2",
            activebackground=C["bg_hover"], activeforeground=C["acento"],
        ).pack(side="left", padx=(0, 6))

        self._btn_exec_todas = tk.Button(
            frame_pd_btns, text="⚡  Executar todas",
            command=self._executar_todas_predefinidas,
            bg=C["acento"], fg=C["bg_app"],
            font=F["botao"], relief="flat", bd=0,
            padx=8, pady=5, cursor="hand2",
            activebackground=C["acento_hover"], activeforeground=C["bg_app"],
        )
        self._btn_exec_todas.pack(side="left")

        tk.Frame(esq, bg=C["borda"], height=1).pack(fill="x", padx=14, pady=8)

        # ── Log de execução das pré-definidas ────────────────────────
        hdr_log_pd = tk.Frame(esq, bg=C["bg_card"])
        hdr_log_pd.pack(fill="x", padx=14, pady=(0, 4))

        tk.Label(hdr_log_pd, text="LOG DE EXECUÇÃO", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(side="left")

        tk.Button(
            hdr_log_pd, text="Limpar",
            command=self._limpar_log_execucao,
            bg=C["bg_input"], fg=C["texto_sec"],
            font=F["pequeno"], relief="flat", bd=0,
            padx=6, pady=2, cursor="hand2",
        ).pack(side="right")

        frame_log_exec = tk.Frame(esq, bg=C["bg_card"])
        frame_log_exec.pack(fill="x", padx=14, pady=(0, 8))

        sc_log_exec = tk.Scrollbar(frame_log_exec, orient="vertical",
                                   bg=C["bg_painel"], troughcolor=C["bg_app"])
        sc_log_exec.pack(side="right", fill="y")

        self._text_log_exec = tk.Text(
            frame_log_exec,
            yscrollcommand=sc_log_exec.set,
            height=9,
            bg=C["bg_input"], fg=C["texto"],
            font=("Consolas", 7),
            relief="flat", bd=0,
            state="disabled", padx=6, pady=4,
            wrap="word",
        )
        self._text_log_exec.pack(side="left", fill="x", expand=True)
        sc_log_exec.config(command=self._text_log_exec.yview)

        self._text_log_exec.tag_config("ok",    foreground=CORES["sucesso"])
        self._text_log_exec.tag_config("erro",  foreground=CORES["erro"])
        self._text_log_exec.tag_config("aviso", foreground=CORES["aviso"])
        self._text_log_exec.tag_config("info",  foreground=CORES["acento"])

        tk.Frame(esq, bg=C["borda"], height=1).pack(fill="x", padx=14, pady=8)

        # ── Consulta livre ao banco de resultados ─────────────────────
        tk.Label(esq, text="BANCO DE RESULTADOS", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(padx=14, pady=(0, 4), anchor="w")

        tk.Label(
            esq,
            text="Consulte o " + NOME_BANCO_RESULTADOS + " diretamente "
                 "com SQL para verificar os dados salvos.",
            bg=C["bg_card"], fg=C["texto_desab"],
            font=F["pequeno"], justify="left", wraplength=220,
        ).pack(padx=14, anchor="w")

        # Tabelas disponíveis
        self._var_tabelas_res = tk.StringVar(value="")
        self._lbl_tabelas_res = tk.Label(
            esq, textvariable=self._var_tabelas_res,
            bg=C["bg_card"], fg=C["texto_desab"],
            font=("Consolas", 7), justify="left", wraplength=220,
        )
        self._lbl_tabelas_res.pack(padx=14, pady=(2, 4), anchor="w")

        frame_res_btns = tk.Frame(esq, bg=C["bg_card"])
        frame_res_btns.pack(fill="x", padx=14, pady=(0, 14))

        tk.Button(
            frame_res_btns, text="🗄  Conectar banco resultados",
            command=self._conectar_banco_resultados,
            bg=C["bg_input"], fg=C["texto"],
            font=F["botao"], relief="flat", bd=0,
            padx=8, pady=5, cursor="hand2", anchor="w",
            activebackground=C["bg_hover"], activeforeground=C["acento"],
        ).pack(fill="x", pady=(0, 3))

        tk.Button(
            frame_res_btns, text="↺  Atualizar lista de tabelas",
            command=self._atualizar_tabelas_resultado,
            bg=C["bg_input"], fg=C["texto"],
            font=F["botao"], relief="flat", bd=0,
            padx=8, pady=5, cursor="hand2", anchor="w",
            activebackground=C["bg_hover"], activeforeground=C["acento"],
        ).pack(fill="x")

        # ── Painel direito: tabela de resultados ─────────────────────
        dir_ = tk.Frame(paned, bg=C["bg_card"])
        paned.add(dir_, minsize=400, stretch="always")

        # Header da tabela
        hdr_tab = tk.Frame(dir_, bg=C["bg_card"])
        hdr_tab.pack(fill="x", padx=14, pady=(14, 6))

        tk.Label(hdr_tab, text="RESULTADO", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(side="left")

        self._var_info = tk.StringVar(value="")
        tk.Label(hdr_tab, textvariable=self._var_info, bg=C["bg_card"],
                 fg=C["texto_sec"], font=F["pequeno"]).pack(side="left", padx=10)

        # Botão de autoajuste de largura de colunas
        self._btn_autoajuste = tk.Button(
            hdr_tab, text="⟺  Autoajustar colunas",
            command=self._autoajustar_colunas,
            bg=C["bg_input"], fg=C["texto"],
            font=F["botao"], relief="flat", bd=0,
            padx=8, pady=3, cursor="hand2",
            activebackground=C["bg_hover"], activeforeground=C["acento"],
        )
        self._btn_autoajuste.pack(side="right", padx=(6, 0))

        # Botões de exportação
        frame_exp = tk.Frame(dir_, bg=C["bg_card"])
        frame_exp.pack(fill="x", padx=14, pady=(0, 6))

        tk.Button(
            frame_exp, text="↓  Exportar atual (.xlsx)",
            command=self._exportar_atual,
            bg=C["bg_input"], fg=C["texto"],
            font=F["botao"], relief="flat", bd=0,
            padx=8, pady=4, cursor="hand2",
            activebackground=C["bg_hover"], activeforeground=C["acento"],
        ).pack(side="left", padx=(0, 6))

        tk.Button(
            frame_exp, text="↓  Exportar todas pré-definidas",
            command=self._exportar_todas,
            bg=C["bg_input"], fg=C["texto"],
            font=F["botao"], relief="flat", bd=0,
            padx=8, pady=4, cursor="hand2",
            activebackground=C["bg_hover"], activeforeground=C["acento"],
        ).pack(side="left")

        # Filtro rápido
        frame_filtro = tk.Frame(dir_, bg=C["bg_input"], height=30)
        frame_filtro.pack(fill="x", padx=14, pady=(0, 6))
        frame_filtro.pack_propagate(False)

        tk.Label(frame_filtro, text="🔍 Filtrar:",
                 bg=C["bg_input"], fg=C["texto_sec"], font=F["pequeno"]).pack(side="left", padx=(8, 4))

        self._var_filtro = tk.StringVar()
        self._var_filtro.trace_add("write", self._aplicar_filtro)
        tk.Entry(
            frame_filtro, textvariable=self._var_filtro,
            bg=C["bg_input"], fg=C["texto"],
            insertbackground=C["acento"],
            relief="flat", bd=0, font=F["corpo"],
        ).pack(side="left", fill="both", expand=True, pady=4, padx=(0, 8))

        # Treeview
        frame_tree = tk.Frame(dir_, bg=C["bg_card"])
        frame_tree.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        sc_y = tk.Scrollbar(frame_tree, orient="vertical",
                            bg=C["bg_painel"], troughcolor=C["bg_app"])
        sc_y.pack(side="right", fill="y")

        sc_x = tk.Scrollbar(frame_tree, orient="horizontal",
                            bg=C["bg_painel"], troughcolor=C["bg_app"])
        sc_x.pack(side="bottom", fill="x")

        self._tree = ttk.Treeview(
            frame_tree,
            show="headings",
            yscrollcommand=sc_y.set,
            xscrollcommand=sc_x.set,
            style="Treeview",
        )
        self._tree.pack(side="left", fill="both", expand=True)
        sc_y.config(command=self._tree.yview)
        sc_x.config(command=self._tree.xview)

        # Capturar ajuste manual de largura de coluna pelo usuário.
        # O Treeview não tem evento nativo de column-resize; usamos
        # ButtonRelease-1 no separador do heading (região "separator").
        # ── Detecção de resize de coluna ─────────────────────────────
        # Estratégia: Button-1 identifica se está no separador e ativa
        # a flag; B1-Motion confirma que houve drag; ButtonRelease-1
        # salva as larguras apenas se a flag estava ativa. Isso evita
        # que um simples clique no cabeçalho (ordenar) dispare o save.
        self._tree.bind("<Button-1>",       self._on_tree_btn_press)
        self._tree.bind("<B1-Motion>",      self._on_tree_drag)
        self._tree.bind("<ButtonRelease-1>", self._on_tree_btn_release)

        # Menu de contexto (botão direito) e Ctrl+C para copiar
        self._tree.bind("<Button-3>",   self._mostrar_menu_contexto)
        self._tree.bind("<Control-c>",  self._copiar_celula_selecionada)
        self._tree.bind("<Control-C>",  self._copiar_celula_selecionada)

        # Barra de progresso (compartilhada)
        self._progress = ttk.Progressbar(
            self, mode="indeterminate", style="TProgressbar"
        )
        self._progress.pack(fill="x", padx=24, pady=(0, 6))

        self._var_prog_msg = tk.StringVar(value="")
        tk.Label(
            self, textvariable=self._var_prog_msg,
            bg=C["bg_app"], fg=C["texto_sec"], font=F["status"], anchor="w",
        ).pack(fill="x", padx=24, pady=(0, 8))

    # ------------------------------------------------------------------
    # Conexão
    # ------------------------------------------------------------------

    def _atualizar_lista_bancos(self):
        bancos = listar_bancos(self._caminhos["duckdb"])
        self._combo_banco["values"] = bancos
        if bancos:
            self._combo_banco.set(bancos[0])

    def _conectar(self):
        banco = self._var_banco.get()
        if not banco:
            messagebox.showwarning("Aviso", "Selecione um banco.")
            return

        caminho = os.path.join(self._caminhos["duckdb"], banco)
        try:
            self._conexao.conectar(caminho)
            self._var_status_con.set("● Conectado")
            self._lbl_status_con.config(fg=CORES["sucesso"])
            self._status_var.set(f"Conectado: {banco}")
        except Exception as e:
            messagebox.showerror("Erro ao conectar", str(e))

    # ------------------------------------------------------------------
    # Execução SQL
    # ------------------------------------------------------------------

    def _executar_manual(self):
        sql = self._text_sql.get("1.0", tk.END).strip()
        if not sql:
            messagebox.showwarning("Aviso", "Digite uma consulta SQL.")
            return

        self._executar_sql(sql)

    def _executar_sql(self, sql: str):
        if not self._conexao.conectado:
            messagebox.showwarning("Aviso", "Conecte-se a um banco primeiro.")
            return

        self._btn_exec.config(state="disabled")
        self._progress.start(10)
        self._var_prog_msg.set("Executando consulta...")

        def _worker():
            try:
                df, elapsed = self._conexao.executar(sql)
                self.after(0, self._mostrar_resultado, df, elapsed)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Erro SQL", str(e)))
                self.after(0, self._parar_progresso)

        threading.Thread(target=_worker, daemon=True).start()

    def _mostrar_resultado(self, df: pd.DataFrame, elapsed: float):
        self._parar_progresso()
        self._df_atual = df
        self._df_filtrado = df.copy()
        self._var_filtro.set("")
        self._renderizar_tabela(df, elapsed)

    def _renderizar_tabela(self, df: pd.DataFrame, elapsed: float | None = None):
        self._tree.delete(*self._tree.get_children())
        self._tree["columns"] = []

        if df.empty:
            self._var_info.set("0 registros")
            return

        cols = list(df.columns)
        self._tree["columns"] = cols
        self._tree["show"] = "headings"

        for col in cols:
            self._tree.heading(
                col, text=col,
                command=lambda c=col: self._ordenar(c),
            )
            # Usar largura salva pelo usuário se existir; senão calcular automático
            if col in self._col_larguras_usuario:
                largura_px = self._col_larguras_usuario[col]
            else:
                largura_chars = max(
                    df[col].astype(str).map(len).max() if len(df) > 0 else 0,
                    len(col),
                )
                largura_px = min(largura_chars * 9 + 20, 280)
            self._tree.column(col, width=largura_px, minwidth=60)

        # Inserir linhas (max 2000 para performance)
        for _, row in df.head(2000).iterrows():
            self._tree.insert("", "end", values=list(row))

        info = f"{len(df)} registro(s)"
        if elapsed is not None:
            info += f"  |  {elapsed:.3f}s"
        if len(df) > 2000:
            info += "  |  (exibindo 2.000 de {len(df)})"
        self._var_info.set(info)

        self._status_var.set(f"Consulta retornou {len(df)} registro(s).")

    # ------------------------------------------------------------------
    # Filtro em tempo real
    # ------------------------------------------------------------------

    def _aplicar_filtro(self, *_):
        if self._df_atual is None:
            return

        termo = self._var_filtro.get().strip().lower()

        if not termo:
            self._df_filtrado = self._df_atual.copy()
        else:
            mask = self._df_atual.apply(
                lambda col: col.astype(str).str.lower().str.contains(termo, na=False)
            ).any(axis=1)
            self._df_filtrado = self._df_atual[mask].copy()

        self._renderizar_tabela(self._df_filtrado)

    # ------------------------------------------------------------------
    # Ordenação
    # ------------------------------------------------------------------

    def _ordenar(self, col: str):
        if self._df_filtrado is None:
            return

        if self._col_sort == col:
            self._sort_asc = not self._sort_asc
        else:
            self._col_sort = col
            self._sort_asc = True

        try:
            df_sorted = self._df_filtrado.sort_values(
                col, ascending=self._sort_asc, na_position="last"
            )
        except Exception:
            df_sorted = self._df_filtrado

        self._df_filtrado = df_sorted
        seta = "▲" if self._sort_asc else "▼"

        for c in self._tree["columns"]:
            texto = c + (" " + seta if c == col else "")
            self._tree.heading(c, text=texto, command=lambda cc=c: self._ordenar(cc))

        self._renderizar_tabela(df_sorted)

    # ------------------------------------------------------------------
    # Consultas pré-definidas
    # ------------------------------------------------------------------

    def _preview_consulta(self, *_):
        sel = self._lb_predefinidas.curselection()
        if not sel:
            return
        idx = sel[0]
        q = CONSULTAS_PREDEFINIDAS[idx]
        self._var_desc.set(q["descricao"])

        # Preencher ScrolledText com SQL quantitativo e abertura formatados
        t = self._text_sql_prev
        t.config(state="normal")
        t.delete("1.0", tk.END)

        t.insert("end", f"-- R{q['id']:02d} | {q['nome']}\n", "header")
        t.insert("end", f"-- {q['descricao']}\n\n", "sql")

        t.insert("end", "-- QUANTITATIVO:\n", "header")
        t.insert("end", q.get("sql_quant", "N/A") + "\n\n", "sql")

        t.insert("end", "-- ABERTURA (detalhe):\n", "header")
        t.insert("end", q.get("sql_abert", "N/A") + "\n", "sql")

        t.config(state="disabled")

    def _copiar_sql_preview(self):
        """Copia o SQL visível no preview para o clipboard."""
        t = self._text_sql_prev
        conteudo = t.get("1.0", tk.END).strip()
        if conteudo:
            self.clipboard_clear()
            self.clipboard_append(conteudo)
            self._status_var.set("SQL copiado para o clipboard.")

    def _exibir_consulta_predefinida(self, *_):
        sel = self._lb_predefinidas.curselection()
        if not sel:
            return
        idx = sel[0]
        q = CONSULTAS_PREDEFINIDAS[idx]

        # Verificar se já foi executada
        if q["id"] in self._resultados_predefinidas:
            df, elapsed = self._resultados_predefinidas[q["id"]]
            self._df_atual = df
            self._df_filtrado = df.copy()
            self._var_filtro.set("")
            self._renderizar_tabela(df, elapsed)
        else:
            # Executar direto
            self._text_sql.delete("1.0", tk.END)
            self._text_sql.insert("1.0", q["sql"])
            self._executar_sql(q["sql"])

    def _executar_todas_predefinidas(self):
        if not self._conexao.conectado:
            messagebox.showwarning("Aviso", "Conecte-se a um banco primeiro.")
            return

        self._btn_exec_todas.config(state="disabled")
        self._progress.start(10)

        banco_sel  = self._var_banco.get().replace(".duckdb", "")
        duckdb_dir = self._caminhos["duckdb"]

        self._limpar_log_execucao()
        self._append_log_exec(f"▶ Iniciando — BDGD: {banco_sel}", "info")

        def _cb(msg: str):
            # Classificar por marcadores explícitos — evita falso positivo
            # quando o NOME da regra contém "Erros" (ex: R02 Erros de Faseamento)
            msg_stripped = msg.strip()
            if (msg_stripped.startswith("⚠")
                    or msg_stripped.startswith("✗")
                    or msg_stripped.startswith("Erro ")
                    or ": Binder Error" in msg
                    or ": Catalog Error" in msg
                    or ": Parser Error" in msg
                    or "not found" in msg.lower()):
                tag = "erro"
            elif (msg_stripped.startswith("✔")
                    or "Concluído" in msg
                    or "OK" in msg):
                tag = "ok"
            else:
                tag = "info"
            self.after(0, lambda m=msg, t=tag: self._append_log_exec(m, t))
            self.after(0, lambda m=msg: self._var_prog_msg.set(m[:90]))

        def _worker():
            try:
                resultados = executar_e_salvar_consultas(
                    conexao=self._conexao,
                    duckdb_dir=duckdb_dir,
                    nome_bdgd=banco_sel,
                    callback_progresso=_cb,
                )
                self._resultados_predefinidas = {
                    qid: v["quant"] for qid, v in resultados.items()
                }
                n_erros = sum(1 for v in resultados.values() if v.get("erro"))
                for qid, v in resultados.items():
                    if v.get("erro"):
                        self.after(0, lambda e=v["erro"], q=qid:
                            self._append_log_exec(f"  ✗ R{q:02d}: {e}", "erro"))
                self.after(0, self._predefinidas_ok,
                           self._resultados_predefinidas, n_erros)
            except Exception as e:
                self.after(0, lambda err=str(e):
                    self._append_log_exec(f"✗ Erro fatal: {err}", "erro"))
                self.after(0, lambda: messagebox.showerror("Erro", str(e)))
                self.after(0, self._parar_progresso)

        threading.Thread(target=_worker, daemon=True).start()

    def _predefinidas_ok(self, resultados: dict, n_erros: int = 0):
        self._parar_progresso()
        self._btn_exec_todas.config(state="normal")

        n_ok = len(resultados) - n_erros
        self._status_var.set(
            f"{n_ok}/{len(resultados)} regras OK"
            + (f" | {n_erros} com erro" if n_erros else "")
            + " — Resultados em bdgd_inconsistencias.duckdb."
        )
        self._append_log_exec(
            f"{'─'*38}\n"
            f"Finalizado: {n_ok}/{len(resultados)} OK"
            + (f" | {n_erros} erro(s) — veja detalhes acima." if n_erros else "."),
            "ok" if n_erros == 0 else "aviso",
        )

        if n_erros > 0:
            messagebox.showwarning(
                "Consultas concluídas com erros",
                f"{n_ok}/{len(resultados)} regra(s) executadas com sucesso.\n"
                f"{n_erros} regra(s) com erro — verifique o LOG DE EXECUÇÃO\n"
                "no painel esquerdo para entender o motivo.\n\n"
                "As regras com erro não terão gráfico no Dashboard.",
            )
        else:
            messagebox.showinfo(
                "Consultas concluídas",
                f"Todas as {len(resultados)} regras executadas com sucesso.\n"
                "Acesse o Dashboard para visualizar os gráficos.",
            )

    # ------------------------------------------------------------------
    # Exportar
    # ------------------------------------------------------------------

    def _exportar_atual(self):
        if self._df_filtrado is None or self._df_filtrado.empty:
            messagebox.showwarning("Aviso", "Nenhum resultado para exportar.")
            return

        caminho = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx"), ("CSV", "*.csv")],
            title="Exportar resultado",
        )
        if not caminho:
            return

        try:
            if caminho.endswith(".csv"):
                self._df_filtrado.to_csv(caminho, index=False, encoding="utf-8-sig")
            else:
                self._df_filtrado.to_excel(caminho, index=False)
            messagebox.showinfo("Sucesso", f"Exportado para:\n{caminho}")
        except Exception as e:
            messagebox.showerror("Erro", str(e))

    def _exportar_todas(self):
        if not self._resultados_predefinidas:
            messagebox.showwarning("Aviso", "Execute as consultas pré-definidas primeiro.")
            return

        banco = self._var_banco.get().replace(".duckdb", "")
        caminho = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialfile=f"{banco}_inconsistencias.xlsx",
            title="Exportar todas consultas",
        )
        if not caminho:
            return

        try:
            exportar_resultados_excel(self._resultados_predefinidas, caminho)
            messagebox.showinfo("Sucesso", f"Exportado para:\n{caminho}")
        except Exception as e:
            messagebox.showerror("Erro", str(e))

    # ------------------------------------------------------------------
    # Utilitários
    # ------------------------------------------------------------------

    def _limpar(self):
        self._text_sql.delete("1.0", tk.END)
        self._tree.delete(*self._tree.get_children())
        self._df_atual = None
        self._df_filtrado = None
        self._var_info.set("")
        self._var_filtro.set("")
        self._col_larguras_usuario.clear()  # reset larguras ao limpar

    def _append_log_exec(self, msg: str, tag: str = ""):
        """Adiciona linha ao log persistente de execução das pré-definidas."""
        import datetime
        ts  = datetime.datetime.now().strftime("%H:%M:%S")
        txt = f"[{ts}] {msg}\n"
        self._text_log_exec.config(state="normal")
        self._text_log_exec.insert("end", txt, tag or "")
        self._text_log_exec.see("end")
        self._text_log_exec.config(state="disabled")
        self._log_execucao.append(txt)

    def _limpar_log_execucao(self):
        self._text_log_exec.config(state="normal")
        self._text_log_exec.delete("1.0", "end")
        self._text_log_exec.config(state="disabled")
        self._log_execucao.clear()

    def _on_tree_btn_press(self, event):
        """
        Registra se o botão 1 foi pressionado sobre um separador de coluna.
        Apenas nesse caso um drag posterior deve ser interpretado como resize.
        """
        region = self._tree.identify_region(event.x, event.y)
        self._resize_em_andamento = (region == "separator")

    def _on_tree_drag(self, event):
        """
        Durante o drag com B1, se a flag de resize estiver ativa, salva
        continuamente as larguras — garante que o estado final seja capturado
        mesmo que o usuário solte o botão fora da região "separator".
        """
        if self._resize_em_andamento:
            for col in self._tree["columns"]:
                try:
                    self._col_larguras_usuario[col] = self._tree.column(col, "width")
                except Exception:
                    pass

    def _on_tree_btn_release(self, event):
        """
        Ao soltar o botão, se estava em resize, faz uma última leitura
        das larguras (estado final) e desativa a flag.
        """
        if self._resize_em_andamento:
            for col in self._tree["columns"]:
                try:
                    self._col_larguras_usuario[col] = self._tree.column(col, "width")
                except Exception:
                    pass
            self._resize_em_andamento = False

    def _autoajustar_colunas(self):
        """
        Calcula a largura ideal de cada coluna com base no conteúdo real
        (cabeçalho + valores visíveis na tabela) e aplica.
        Também salva as larguras calculadas para que persistam em filtros
        e ordenações subsequentes.
        Útil quando as colunas estão muito apertadas (muitas colunas).
        """
        if self._df_filtrado is None or self._df_filtrado.empty:
            return

        df = self._df_filtrado
        cols = list(df.columns)

        for col in cols:
            if col not in self._tree["columns"]:
                continue

            # Calcular largura pelo conteúdo (amostra de até 500 linhas para performance)
            max_conteudo = (
                df[col].head(500).astype(str).map(len).max()
                if len(df) > 0 else 0
            )
            # Comparar com o cabeçalho atual (pode ter ▲/▼ da ordenação)
            texto_cabecalho = self._tree.heading(col, "text")
            max_chars = max(max_conteudo, len(texto_cabecalho))

            # ~7px por caractere + 24px de padding, limitado entre 60 e 500px
            largura_px = max(60, min(max_chars * 7 + 24, 500))

            self._tree.column(col, width=largura_px)
            self._col_larguras_usuario[col] = largura_px

        self._status_var.set(
            f"Colunas autoajustadas ({len(cols)} colunas)."
        )

    def _parar_progresso(self):
        self._progress.stop()
        self._btn_exec.config(state="normal")
        self._var_prog_msg.set("")

    # ------------------------------------------------------------------
    # Copiar conteúdo da tabela
    # ------------------------------------------------------------------

    def _celula_selecionada(self, event=None) -> tuple[str | None, int | None]:
        """
        Retorna (valor_da_célula, indice_coluna) da célula onde o cursor está.
        Usa a posição do mouse quando chamado via menu de contexto,
        ou a primeira coluna da linha selecionada via Ctrl+C.
        """
        if event and event.x and event.y:
            col_id = self._tree.identify_column(event.x)
            item   = self._tree.identify_row(event.y)
        else:
            sel = self._tree.selection()
            item   = sel[0] if sel else None
            col_id = "#1"

        if not item or not col_id:
            return None, None

        # col_id vem como "#1", "#2", ... — converter para índice 0-based
        try:
            col_idx = int(col_id.replace("#", "")) - 1
        except ValueError:
            return None, None

        valores = self._tree.item(item, "values")
        if not valores or col_idx >= len(valores):
            return None, None

        return str(valores[col_idx]), col_idx

    def _copiar_celula_selecionada(self, event=None):
        """Copia o valor da célula sob o cursor (ou selecionada) para o clipboard."""
        valor, _ = self._celula_selecionada(event)
        if valor is None:
            return "break"
        self.clipboard_clear()
        self.clipboard_append(valor)
        self._status_var.set(f"Copiado: {valor[:80]}")
        return "break"  # impede propagação do evento

    def _copiar_linha_selecionada(self, event=None):
        """Copia todos os valores da linha selecionada separados por tabulação."""
        sel = self._tree.selection()
        if not sel:
            return
        valores = self._tree.item(sel[0], "values")
        linha = "	".join(str(v) for v in valores)
        self.clipboard_clear()
        self.clipboard_append(linha)
        self._status_var.set(f"Linha copiada ({len(valores)} campos).")

    def _copiar_tabela_inteira(self):
        """
        Copia toda a tabela visível (cabeçalho + linhas filtradas) para o
        clipboard no formato TSV (Tab Separated Values) — compatível com
        colar diretamente no Excel ou Google Sheets.
        """
        if self._df_filtrado is None or self._df_filtrado.empty:
            return

        # Cabeçalho
        cols = list(self._df_filtrado.columns)
        linhas = ["\t".join(cols)]

        # Linhas (limitar a 10.000 para não travar o clipboard)
        for _, row in self._df_filtrado.head(10_000).iterrows():
            linhas.append("\t".join(str(v) for v in row))

        tsv = "\n".join(linhas)
        self.clipboard_clear()
        self.clipboard_append(tsv)
        n = len(self._df_filtrado)
        self._status_var.set(
            f"Tabela copiada: {n} linha(s) × {len(cols)} coluna(s). "
            "Cole no Excel com Ctrl+V."
        )

    def _mostrar_menu_contexto(self, event):
        """Exibe menu de contexto com opções de cópia ao clicar com botão direito."""
        # Selecionar o item sob o cursor antes de mostrar o menu
        item = self._tree.identify_row(event.y)
        if item:
            self._tree.selection_set(item)

        # Guardar event para passar à função de cópia de célula
        self._ultimo_event_ctx = event

        menu = tk.Menu(self, tearoff=0,
                       bg=CORES["bg_painel"], fg=CORES["texto"],
                       activebackground=CORES["acento_escuro"],
                       activeforeground=CORES["texto"],
                       relief="flat", bd=0,
                       font=FONTES["pequeno"])

        menu.add_command(
            label="📋  Copiar célula          Ctrl+C",
            command=lambda: self._copiar_celula_selecionada(self._ultimo_event_ctx),
        )
        menu.add_command(
            label="📋  Copiar linha inteira",
            command=self._copiar_linha_selecionada,
        )
        menu.add_separator()
        menu.add_command(
            label="📊  Copiar tabela (para Excel)",
            command=self._copiar_tabela_inteira,
        )

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _conectar_banco_resultados(self):
        """
        Conecta ao banco bdgd_inconsistencias.duckdb para consulta SQL livre.
        Permite ao usuário verificar diretamente a estrutura e os dados salvos.
        """
        import os
        res_path = os.path.join(self._caminhos["duckdb"], NOME_BANCO_RESULTADOS)
        if not os.path.exists(res_path):
            messagebox.showwarning(
                "Banco não encontrado",
                f"O banco '{NOME_BANCO_RESULTADOS}' ainda não existe.\n"
                "Execute as consultas pré-definidas primeiro."
            )
            return
        try:
            self._conexao.conectar(res_path)
            self._var_status_con.set("● Conectado (banco resultados)")
            self._lbl_status_con.config(fg=CORES["acento"])
            self._status_var.set(f"Conectado ao banco de resultados: {NOME_BANCO_RESULTADOS}")
            self._atualizar_tabelas_resultado()
            # Sugerir um exemplo de SQL útil
            exemplo = (
                "-- Exemplo: ver histórico de execuções\n"
                "SELECT * FROM tb_historico_execucao\n"
                "ORDER BY data_execucao DESC"
            )
            self._text_sql.delete("1.0", tk.END)
            self._text_sql.insert("1.0", exemplo)
        except Exception as e:
            messagebox.showerror("Erro ao conectar", str(e))

    def _atualizar_tabelas_resultado(self):
        """Atualiza a lista de tabelas do banco de resultados exibida na interface."""
        tabelas = listar_tabelas_banco_resultados(self._caminhos["duckdb"])
        if tabelas:
            self._var_tabelas_res.set("\n".join(tabelas))
        else:
            self._var_tabelas_res.set("(banco ainda não criado)")

    def atualizar_bancos(self):
        """Chamado externamente quando novos bancos são criados."""
        self._atualizar_lista_bancos()
        self._atualizar_tabelas_resultado()
