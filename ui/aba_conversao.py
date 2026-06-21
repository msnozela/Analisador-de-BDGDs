# -*- coding: utf-8 -*-
"""
ui/aba_conversao.py
Aba de conversão de BDGDs para arquivos OpenDSS.

FLUXO DA INTERFACE
------------------
1. Usuário seleciona um ZIP (da pasta BDGDs) ou um GDB já extraído
2. Sistema extrai o ZIP uma única vez → pasta "BDGDs Extraídas"
3. Sistema lê os alimentadores do GDB via CTMT
4. Usuário seleciona alimentadores e configura os settings
5. Conversão roda em thread separada com log em tempo real
6. Arquivos DSS gravados em "Alimentadores Convertidos/<nome_bdgd>/"
"""

import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path

from core.conversao import (
    extrair_gdb_permanente,
    gdb_ja_extraido,
    listar_alimentadores_gdb,
    listar_zips,
    listar_gdbs_extraidos,
    converter_alimentadores,
    pasta_saida_conversao,
    SETTINGS_DISPONIVEIS,
)
from ui.tema import CORES, FONTES


class AbaConversao(ttk.Frame):
    """
    Aba completa de conversão BDGD → OpenDSS.
    """

    def __init__(self, parent, caminhos: dict, status_var: tk.StringVar):
        super().__init__(parent, style="TFrame")
        self._caminhos   = caminhos
        self._status_var = status_var

        # Estado interno
        self._gdb_path:    str | None = None
        self._nome_bdgd:   str        = ""
        self._alimentadores: list[str] = []
        self._cancelar   = threading.Event()
        self._convertidos: list[str] = []

        # Widgets de settings (preenchidos dinamicamente)
        self._settings_vars: dict[str, tk.Variable] = {}

        self._build()
        self._atualizar_lista_zips()

    # ------------------------------------------------------------------
    # Build principal
    # ------------------------------------------------------------------

    def _build(self):
        C = CORES
        F = FONTES

        # Título
        tk.Label(
            self, text="Conversão para OpenDSS",
            bg=C["bg_app"], fg=C["texto"],
            font=F["titulo_aba"], anchor="w",
        ).pack(fill="x", padx=24, pady=(20, 2))

        tk.Label(
            self,
            text=(
                "Converte BDGDs para arquivos DSS compatíveis com OpenDSS "
                "utilizando a biblioteca bdgd2opendss."
            ),
            bg=C["bg_app"], fg=C["texto_sec"],
            font=F["pequeno"], anchor="w",
        ).pack(fill="x", padx=24, pady=(0, 14))

        # ── Layout 3 colunas: [Seleção+Alimentadores] [Settings] [Log] ─
        corpo = tk.Frame(self, bg=C["bg_app"])
        corpo.pack(fill="both", expand=True, padx=24, pady=(0, 4))
        corpo.columnconfigure(0, weight=2)
        corpo.columnconfigure(1, weight=2)
        corpo.columnconfigure(2, weight=3)

        self._build_col_esq(corpo)
        self._build_col_mid(corpo)
        self._build_col_dir(corpo)

        # Barra de progresso + mensagem
        self._progress = ttk.Progressbar(
            self, mode="indeterminate", style="TProgressbar"
        )
        self._progress.pack(fill="x", padx=24, pady=(0, 3))

        self._var_prog_msg = tk.StringVar(value="")
        tk.Label(
            self, textvariable=self._var_prog_msg,
            bg=C["bg_app"], fg=C["texto_sec"],
            font=F["status"], anchor="w",
        ).pack(fill="x", padx=24, pady=(0, 6))

    # ------------------------------------------------------------------
    # Coluna esquerda: seleção de BDGD + alimentadores
    # ------------------------------------------------------------------

    def _build_col_esq(self, parent):
        C = CORES
        F = FONTES

        esq = tk.Frame(parent, bg=C["bg_card"])
        esq.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        # ── Seleção de BDGD ────────────────────────────────────────
        tk.Label(esq, text="BDGD ORIGEM", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(padx=14, pady=(14, 6), anchor="w")

        # Abas ZIP / GDB extraído
        frame_tabs = tk.Frame(esq, bg=C["bg_card"])
        frame_tabs.pack(fill="x", padx=14, pady=(0, 6))

        self._var_origem = tk.StringVar(value="zip")

        for texto, val in [("  ZIP  ", "zip"), ("  GDB  ", "gdb")]:
            rb = tk.Radiobutton(
                frame_tabs, text=texto,
                variable=self._var_origem, value=val,
                command=self._on_origem_changed,
                bg=C["bg_input"], fg=C["texto"],
                selectcolor=C["acento_escuro"],
                activebackground=C["bg_hover"],
                activeforeground=C["acento"],
                font=F["pequeno"], relief="flat",
                indicatoron=False, padx=8, pady=3,
            )
            rb.pack(side="left", padx=(0, 4))

        # Combobox ZIP
        self._frame_zip = tk.Frame(esq, bg=C["bg_card"])
        self._frame_zip.pack(fill="x", padx=14, pady=(0, 4))

        tk.Label(self._frame_zip, text="Arquivo ZIP:", bg=C["bg_card"],
                 fg=C["texto_sec"], font=F["pequeno"]).pack(anchor="w")

        self._var_zip = tk.StringVar()
        self._combo_zip = ttk.Combobox(
            self._frame_zip, textvariable=self._var_zip,
            state="readonly", width=36,
        )
        self._combo_zip.pack(fill="x", pady=(2, 4))
        self._combo_zip.bind("<<ComboboxSelected>>", self._on_zip_selecionado)

        # Indicador de extração
        self._var_extracao = tk.StringVar(value="")
        tk.Label(
            self._frame_zip, textvariable=self._var_extracao,
            bg=C["bg_card"], fg=C["texto_sec"],
            font=F["pequeno"], anchor="w",
        ).pack(fill="x")

        self._btn_extrair = tk.Button(
            self._frame_zip, text="📂  Extrair ZIP e carregar alimentadores",
            command=self._extrair_e_carregar,
            bg=C["acento"], fg=C["bg_app"],
            font=F["botao"], relief="flat", bd=0,
            padx=10, pady=6, cursor="hand2",
            activebackground=C["acento_hover"],
            activeforeground=C["bg_app"],
        )
        self._btn_extrair.pack(fill="x", pady=(4, 0))

        # Frame GDB direto (oculto inicialmente)
        self._frame_gdb = tk.Frame(esq, bg=C["bg_card"])

        tk.Label(self._frame_gdb, text="GDB extraído:", bg=C["bg_card"],
                 fg=C["texto_sec"], font=F["pequeno"]).pack(anchor="w")

        self._var_gdb_sel = tk.StringVar()
        self._combo_gdb = ttk.Combobox(
            self._frame_gdb, textvariable=self._var_gdb_sel,
            state="readonly", width=36,
        )
        self._combo_gdb.pack(fill="x", pady=(2, 4))
        self._combo_gdb.bind("<<ComboboxSelected>>", self._on_gdb_selecionado)

        tk.Button(
            self._frame_gdb, text="📁  Selecionar pasta .gdb manualmente",
            command=self._selecionar_gdb_manual,
            bg=C["bg_input"], fg=C["texto"],
            font=F["botao"], relief="flat", bd=0,
            padx=10, pady=5, cursor="hand2",
            activebackground=C["bg_hover"], activeforeground=C["acento"],
        ).pack(fill="x", pady=(0, 4))

        tk.Button(
            self._frame_gdb, text="↺  Carregar alimentadores",
            command=self._carregar_alimentadores_gdb,
            bg=C["bg_input"], fg=C["texto"],
            font=F["botao"], relief="flat", bd=0,
            padx=10, pady=5, cursor="hand2",
            activebackground=C["bg_hover"], activeforeground=C["acento"],
        ).pack(fill="x")

        # GDB atual selecionado
        tk.Frame(esq, bg=C["borda"], height=1).pack(fill="x", padx=14, pady=8)

        self._var_gdb_atual = tk.StringVar(value="Nenhum GDB selecionado")
        tk.Label(
            esq, textvariable=self._var_gdb_atual,
            bg=C["bg_card"], fg=C["texto_desab"],
            font=F["pequeno"], wraplength=230, justify="left",
        ).pack(padx=14, pady=(0, 8), anchor="w")

        # ── Seleção de alimentadores ───────────────────────────────
        tk.Frame(esq, bg=C["borda"], height=1).pack(fill="x", padx=14, pady=(0, 8))

        tk.Label(esq, text="ALIMENTADORES", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(padx=14, pady=(0, 4), anchor="w")

        # Modo de seleção
        frame_modo = tk.Frame(esq, bg=C["bg_card"])
        frame_modo.pack(fill="x", padx=14, pady=(0, 6))

        self._var_modo = tk.StringVar(value="todos")
        for texto, val in [("Todos", "todos"), ("Selecionados", "sel")]:
            tk.Radiobutton(
                frame_modo, text=texto,
                variable=self._var_modo, value=val,
                command=self._on_modo_alim_changed,
                bg=C["bg_card"], fg=C["texto"],
                selectcolor=C["bg_input"],
                activebackground=C["bg_card"],
                activeforeground=C["acento"],
                font=F["corpo"],
            ).pack(side="left", padx=(0, 10))

        # Listbox de alimentadores
        frame_lb = tk.Frame(esq, bg=C["bg_card"])
        frame_lb.pack(fill="both", expand=True, padx=14, pady=(0, 4))

        sc_alim = tk.Scrollbar(frame_lb, orient="vertical",
                               bg=C["bg_painel"], troughcolor=C["bg_app"])
        sc_alim.pack(side="right", fill="y")

        self._lb_alim = tk.Listbox(
            frame_lb,
            selectmode="multiple",
            activestyle="none",
            yscrollcommand=sc_alim.set,
            bg=C["bg_input"], fg=C["texto"],
            selectbackground=C["acento_escuro"],
            font=F["pequeno"],
            relief="flat", bd=0, highlightthickness=0,
            state="disabled",
        )
        self._lb_alim.pack(side="left", fill="both", expand=True)
        sc_alim.config(command=self._lb_alim.yview)

        # Contador
        self._var_cont_alim = tk.StringVar(value="0 alimentadores")
        tk.Label(
            esq, textvariable=self._var_cont_alim,
            bg=C["bg_card"], fg=C["texto_sec"],
            font=F["pequeno"],
        ).pack(padx=14, pady=(0, 14), anchor="e")

    # ------------------------------------------------------------------
    # Coluna central: settings
    # ------------------------------------------------------------------

    def _build_col_mid(self, parent):
        C = CORES
        F = FONTES

        mid = tk.Frame(parent, bg=C["bg_card"])
        mid.grid(row=0, column=1, sticky="nsew", padx=(0, 8))

        tk.Label(mid, text="CONFIGURAÇÕES bdgd2opendss", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(padx=14, pady=(14, 6), anchor="w")

        tk.Label(
            mid, text="Parâmetros aplicados antes de cada conversão:",
            bg=C["bg_card"], fg=C["texto_sec"],
            font=F["pequeno"],
        ).pack(padx=14, pady=(0, 8), anchor="w")

        # Frame rolável para os settings
        frame_sc = tk.Frame(mid, bg=C["bg_card"])
        frame_sc.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        canvas = tk.Canvas(frame_sc, bg=C["bg_card"],
                           highlightthickness=0, bd=0)
        sc_cfg = tk.Scrollbar(frame_sc, orient="vertical",
                              bg=C["bg_painel"], troughcolor=C["bg_app"])
        sc_cfg.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=sc_cfg.set)
        sc_cfg.configure(command=canvas.yview)

        inner = tk.Frame(canvas, bg=C["bg_card"])
        canvas_win = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(canvas_win, width=canvas.winfo_width())

        inner.bind("<Configure>", _on_configure)
        canvas.bind("<Configure>", _on_configure)

        # Gerar um widget por setting
        for chave, meta in SETTINGS_DISPONIVEIS.items():
            self._build_setting_widget(inner, chave, meta, C, F)

        # Botão reset
        tk.Button(
            mid, text="↺  Restaurar padrões",
            command=self._reset_settings,
            bg=C["bg_input"], fg=C["texto_sec"],
            font=F["pequeno"], relief="flat", bd=0,
            padx=8, pady=4, cursor="hand2",
            activebackground=C["bg_hover"],
        ).pack(padx=14, pady=(0, 14), anchor="e")

    def _build_setting_widget(self, parent, chave: str, meta: dict, C, F):
        """Cria o widget adequado para cada tipo de setting."""
        frame = tk.Frame(parent, bg=C["bg_card"])
        frame.pack(fill="x", pady=4)

        tipo   = meta["tipo"]
        padrao = meta["padrao"]

        # Label + descrição
        tk.Label(
            frame, text=meta["label"],
            bg=C["bg_card"], fg=C["texto"],
            font=F["corpo_bold"], anchor="w",
        ).pack(anchor="w")

        tk.Label(
            frame, text=meta["desc"],
            bg=C["bg_card"], fg=C["texto_desab"],
            font=F["pequeno"], anchor="w", wraplength=220, justify="left",
        ).pack(anchor="w")

        if tipo == "bool":
            var = tk.BooleanVar(value=padrao)
            tk.Checkbutton(
                frame, variable=var, text="Ativado",
                bg=C["bg_card"], fg=C["texto"],
                selectcolor=C["bg_input"],
                activebackground=C["bg_card"],
                activeforeground=C["acento"],
                font=F["pequeno"],
            ).pack(anchor="w")

        elif tipo == "int" and "opcoes" in meta:
            var = tk.IntVar(value=padrao)
            fr_ops = tk.Frame(frame, bg=C["bg_card"])
            fr_ops.pack(anchor="w")
            for op in meta["opcoes"]:
                tk.Radiobutton(
                    fr_ops, text=str(op), variable=var, value=op,
                    bg=C["bg_card"], fg=C["texto"],
                    selectcolor=C["bg_input"],
                    activebackground=C["bg_card"],
                    font=F["pequeno"],
                ).pack(side="left", padx=(0, 6))

        elif tipo == "float":
            var = tk.DoubleVar(value=padrao)
            tk.Entry(
                frame, textvariable=var, width=8,
                bg=C["bg_input"], fg=C["texto"],
                insertbackground=C["acento"],
                relief="flat", bd=0, font=F["corpo"],
            ).pack(anchor="w", ipady=3, padx=2)

        else:
            var = tk.StringVar(value=str(padrao))
            tk.Entry(
                frame, textvariable=var, width=20,
                bg=C["bg_input"], fg=C["texto"],
                insertbackground=C["acento"],
                relief="flat", bd=0, font=F["corpo"],
            ).pack(anchor="w", ipady=3, padx=2)

        # Separador
        tk.Frame(frame, bg=C["borda"], height=1).pack(fill="x", pady=(6, 0))

        self._settings_vars[chave] = var

    # ------------------------------------------------------------------
    # Coluna direita: log + botões de execução
    # ------------------------------------------------------------------

    def _build_col_dir(self, parent):
        C = CORES
        F = FONTES

        dir_ = tk.Frame(parent, bg=C["bg_card"])
        dir_.grid(row=0, column=2, sticky="nsew")

        # Cabeçalho
        hdr = tk.Frame(dir_, bg=C["bg_card"])
        hdr.pack(fill="x", padx=14, pady=(14, 4))

        tk.Label(hdr, text="LOG DE CONVERSÃO", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(side="left")

        tk.Button(
            hdr, text="Limpar",
            command=self._limpar_log,
            bg=C["bg_input"], fg=C["texto_sec"],
            font=F["pequeno"], relief="flat", bd=0,
            padx=6, pady=2, cursor="hand2",
        ).pack(side="right")

        # Área de log
        frame_log = tk.Frame(dir_, bg=C["bg_card"])
        frame_log.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        sc_log = tk.Scrollbar(frame_log, orient="vertical",
                              bg=C["bg_painel"], troughcolor=C["bg_app"])
        sc_log.pack(side="right", fill="y")

        self._text_log = tk.Text(
            frame_log,
            yscrollcommand=sc_log.set,
            bg=C["bg_input"], fg=C["texto"],
            font=F["mono"], relief="flat", bd=0,
            state="disabled", padx=8, pady=6,
            wrap="word",
        )
        self._text_log.pack(side="left", fill="both", expand=True)
        sc_log.config(command=self._text_log.yview)

        self._text_log.tag_config("ok",    foreground=CORES["sucesso"])
        self._text_log.tag_config("aviso", foreground=CORES["aviso"])
        self._text_log.tag_config("erro",  foreground=CORES["erro"])
        self._text_log.tag_config("info",  foreground=CORES["acento"])

        # Cards de estatísticas
        card_stats = tk.Frame(dir_, bg=C["bg_painel"])
        card_stats.pack(fill="x", padx=14, pady=(0, 8))

        for var_attr, label in [
            ("_var_stat_alim",   "Alimentadores"),
            ("_var_stat_conv",   "Convertidos"),
            ("_var_stat_status", "Status"),
        ]:
            fr = tk.Frame(card_stats, bg=C["bg_painel"])
            fr.pack(side="left", expand=True, padx=10, pady=10)
            var = tk.StringVar(value="—")
            setattr(self, var_attr, var)
            tk.Label(fr, textvariable=var,
                     bg=C["bg_painel"], fg=C["texto"],
                     font=("Segoe UI", 14, "bold")).pack()
            tk.Label(fr, text=label,
                     bg=C["bg_painel"], fg=C["texto_sec"],
                     font=F["badge"]).pack()

        # Pasta de saída
        fr_saida = tk.Frame(dir_, bg=C["bg_card"])
        fr_saida.pack(fill="x", padx=14, pady=(0, 8))

        tk.Label(fr_saida, text="Pasta de saída:", bg=C["bg_card"],
                 fg=C["texto_sec"], font=F["pequeno"]).pack(anchor="w")

        fr_saida2 = tk.Frame(fr_saida, bg=C["bg_card"])
        fr_saida2.pack(fill="x")

        self._var_pasta_saida = tk.StringVar()
        tk.Entry(
            fr_saida2, textvariable=self._var_pasta_saida,
            bg=C["bg_input"], fg=C["texto"],
            insertbackground=C["acento"],
            relief="flat", bd=0, font=F["pequeno"],
        ).pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 4))

        tk.Button(
            fr_saida2, text="…",
            command=self._selecionar_pasta_saida,
            bg=C["bg_input"], fg=C["texto"],
            font=F["botao"], relief="flat", bd=0,
            padx=6, pady=4, cursor="hand2",
        ).pack(side="left")

        # Botões de ação
        fr_btns = tk.Frame(dir_, bg=C["bg_card"])
        fr_btns.pack(fill="x", padx=14, pady=(0, 14))

        self._btn_converter = tk.Button(
            fr_btns,
            text="▶  Converter para OpenDSS",
            command=self._iniciar_conversao,
            bg=C["acento"], fg=C["bg_app"],
            font=F["botao"], relief="flat", bd=0,
            padx=14, pady=9, cursor="hand2",
            state="disabled",
            activebackground=C["acento_hover"],
            activeforeground=C["bg_app"],
        )
        self._btn_converter.pack(fill="x", pady=(0, 6))

        self._btn_cancelar = tk.Button(
            fr_btns,
            text="⏹  Cancelar",
            command=self._cancelar_conversao,
            bg=C["erro"], fg=C["texto"],
            font=F["botao"], relief="flat", bd=0,
            padx=14, pady=7, cursor="hand2",
            state="disabled",
            activebackground="#FF7070",
        )
        self._btn_cancelar.pack(fill="x", pady=(0, 6))

        tk.Button(
            fr_btns, text="📂  Abrir pasta de saída",
            command=self._abrir_pasta_saida,
            bg=C["bg_input"], fg=C["texto"],
            font=F["botao"], relief="flat", bd=0,
            padx=10, pady=6, cursor="hand2",
            activebackground=C["bg_hover"], activeforeground=C["acento"],
        ).pack(fill="x")

    # ------------------------------------------------------------------
    # Lógica: seleção de origem
    # ------------------------------------------------------------------

    def _on_origem_changed(self):
        if self._var_origem.get() == "zip":
            self._frame_gdb.pack_forget()
            self._frame_zip.pack(fill="x", padx=14, pady=(0, 4))
        else:
            self._frame_zip.pack_forget()
            self._frame_gdb.pack(fill="x", padx=14, pady=(0, 4))
            self._atualizar_gdbs_extraidos()

    def _atualizar_lista_zips(self):
        zips = listar_zips(self._caminhos["bdgds"])
        self._combo_zip["values"] = zips
        if zips:
            self._combo_zip.set(zips[0])
            self._on_zip_selecionado()

    def _atualizar_gdbs_extraidos(self):
        gdbs = listar_gdbs_extraidos(self._caminhos["base"])
        nomes = [g["nome"] for g in gdbs]
        self._combo_gdb["values"] = nomes
        if nomes:
            self._combo_gdb.set(nomes[0])

    def _on_zip_selecionado(self, *_):
        zip_file = self._var_zip.get()
        if not zip_file:
            return

        zip_path = os.path.join(self._caminhos["bdgds"], zip_file)
        nome     = Path(zip_path).stem

        # Verificar se já extraído
        if gdb_ja_extraido(zip_path, self._caminhos["base"]):
            self._var_extracao.set("✔ Já extraído — pronto para carregar")
            self._btn_extrair.config(text="↺  Recarregar alimentadores")
        else:
            self._var_extracao.set("ZIP não extraído — clique para extrair")
            self._btn_extrair.config(text="📂  Extrair ZIP e carregar alimentadores")

        self._nome_bdgd = nome
        self._atualizar_pasta_saida_padrao(nome)

    def _on_gdb_selecionado(self, *_):
        nome = self._var_gdb_sel.get()
        if not nome:
            return
        gdbs = listar_gdbs_extraidos(self._caminhos["base"])
        for g in gdbs:
            if g["nome"] == nome:
                self._gdb_path = g["gdb_path"]
                self._nome_bdgd = nome
                self._var_gdb_atual.set(f"GDB: {os.path.basename(self._gdb_path)}")
                self._atualizar_pasta_saida_padrao(nome)
                break

    def _selecionar_gdb_manual(self):
        path = filedialog.askdirectory(title="Selecionar pasta .gdb")
        if not path:
            return
        if not path.lower().endswith(".gdb"):
            messagebox.showwarning("Aviso", "A pasta selecionada não tem extensão .gdb.")
            return
        self._gdb_path  = path
        self._nome_bdgd = Path(path).stem
        self._var_gdb_atual.set(f"GDB: {os.path.basename(path)}")
        self._atualizar_pasta_saida_padrao(self._nome_bdgd)
        self._carregar_alimentadores_gdb()

    def _atualizar_pasta_saida_padrao(self, nome_bdgd: str):
        padrao = os.path.join(
            self._caminhos["base"], "Alimentadores Convertidos", nome_bdgd
        )
        self._var_pasta_saida.set(padrao)

    # ------------------------------------------------------------------
    # Extração e carregamento de alimentadores
    # ------------------------------------------------------------------

    def _extrair_e_carregar(self):
        zip_file = self._var_zip.get()
        if not zip_file:
            messagebox.showwarning("Aviso", "Selecione um arquivo ZIP.")
            return

        zip_path = os.path.join(self._caminhos["bdgds"], zip_file)

        self._btn_extrair.config(state="disabled")
        self._progress.start(10)
        self._var_prog_msg.set("Extraindo ZIP...")
        self._log("Iniciando extração do ZIP...", "info")

        def _worker():
            try:
                gdb = extrair_gdb_permanente(
                    zip_path=zip_path,
                    base_path=self._caminhos["base"],
                    callback=lambda m: self.after(0, self._log, m),
                )
                self._gdb_path = gdb
                alims = listar_alimentadores_gdb(gdb)
                self.after(0, self._extracao_ok, alims, gdb)

            except Exception as e:
                self.after(0, self._extracao_erro, str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _carregar_alimentadores_gdb(self, *_):
        if not self._gdb_path:
            messagebox.showwarning("Aviso", "Nenhum GDB selecionado.")
            return

        self._progress.start(10)
        self._var_prog_msg.set("Lendo alimentadores...")
        self._log(f"Carregando alimentadores de: {os.path.basename(self._gdb_path)}", "info")

        def _worker():
            try:
                alims = listar_alimentadores_gdb(self._gdb_path)
                self.after(0, self._extracao_ok, alims, self._gdb_path)
            except Exception as e:
                self.after(0, self._extracao_erro, str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _extracao_ok(self, alimentadores: list[str], gdb_path: str):
        self._progress.stop()
        self._var_prog_msg.set("")
        self._btn_extrair.config(state="normal")

        self._gdb_path      = gdb_path
        self._alimentadores = alimentadores

        self._var_gdb_atual.set(f"GDB: {os.path.basename(gdb_path)}")
        self._var_extracao.set(f"✔ Já extraído — {len(alimentadores)} alimentadores")
        self._btn_extrair.config(text="↺  Recarregar alimentadores")

        # Popular listbox
        self._lb_alim.config(state="normal")
        self._lb_alim.delete(0, tk.END)
        for a in alimentadores:
            self._lb_alim.insert(tk.END, f"  {a}")
        self._lb_alim.bind("<<ListboxSelect>>", self._atualizar_contador_alim)

        self._var_cont_alim.set(f"{len(alimentadores)} alimentadores")
        self._var_stat_alim.set(str(len(alimentadores)))

        self._btn_converter.config(state="normal")

        self._log(
            f"✔ {len(alimentadores)} alimentadores carregados.",
            "ok",
        )
        self._status_var.set(f"BDGD carregada: {len(alimentadores)} alimentadores.")

    def _extracao_erro(self, msg: str):
        self._progress.stop()
        self._var_prog_msg.set("Erro na extração.")
        self._btn_extrair.config(state="normal")
        self._log(f"Erro: {msg}", "erro")
        messagebox.showerror("Erro na extração", msg)

    def _atualizar_contador_alim(self, *_):
        n = len(self._lb_alim.curselection())
        modo = self._var_modo.get()
        if modo == "todos":
            self._var_cont_alim.set(f"{len(self._alimentadores)} alimentadores (todos)")
        else:
            self._var_cont_alim.set(f"{n} selecionado(s)")

    def _on_modo_alim_changed(self):
        if self._var_modo.get() == "todos":
            self._lb_alim.selection_clear(0, tk.END)
        self._atualizar_contador_alim()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _coletar_settings(self) -> dict:
        cfg = {}
        for chave, var in self._settings_vars.items():
            try:
                cfg[chave] = var.get()
            except Exception:
                cfg[chave] = SETTINGS_DISPONIVEIS[chave]["padrao"]
        return cfg

    def _reset_settings(self):
        for chave, var in self._settings_vars.items():
            var.set(SETTINGS_DISPONIVEIS[chave]["padrao"])
        self._log("Settings restaurados aos valores padrão.", "info")

    # ------------------------------------------------------------------
    # Pasta de saída
    # ------------------------------------------------------------------

    def _selecionar_pasta_saida(self):
        path = filedialog.askdirectory(title="Selecionar pasta de saída dos arquivos DSS")
        if path:
            self._var_pasta_saida.set(path)

    def _abrir_pasta_saida(self):
        pasta = self._var_pasta_saida.get()
        if not pasta or not os.path.exists(pasta):
            messagebox.showwarning("Aviso", "Pasta de saída não existe ainda.")
            return
        import subprocess, sys
        if sys.platform == "win32":
            os.startfile(pasta)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", pasta])
        else:
            subprocess.Popen(["xdg-open", pasta])

    # ------------------------------------------------------------------
    # Conversão
    # ------------------------------------------------------------------

    def _iniciar_conversao(self):
        if not self._gdb_path:
            messagebox.showwarning("Aviso", "Carregue uma BDGD primeiro.")
            return

        pasta_saida = self._var_pasta_saida.get().strip()
        if not pasta_saida:
            messagebox.showwarning("Aviso", "Defina a pasta de saída.")
            return

        modo = self._var_modo.get()

        if modo == "sel":
            selecionados_idx = self._lb_alim.curselection()
            if not selecionados_idx:
                messagebox.showwarning("Aviso", "Selecione ao menos um alimentador.")
                return
            alimentadores_exec = [
                self._lb_alim.get(i).strip() for i in selecionados_idx
            ]
        else:
            alimentadores_exec = None  # todos

        # Verificar sobrescrita
        if os.path.exists(pasta_saida) and os.listdir(pasta_saida):
            resp = messagebox.askyesno(
                "Pasta não vazia",
                f"A pasta de saída já contém arquivos:\n{pasta_saida}\n\n"
                "Os arquivos existentes podem ser sobrescritos. Continuar?",
            )
            if not resp:
                return

        cfg = self._coletar_settings()

        self._cancelar.clear()
        self._btn_converter.config(state="disabled")
        self._btn_cancelar.config(state="normal")
        self._progress.start(10)
        self._var_stat_status.set("Convertendo")
        self._var_stat_conv.set("...")

        n_alim = "todos" if alimentadores_exec is None else str(len(alimentadores_exec))
        self._log(f"Iniciando conversão — {n_alim} alimentador(es)...", "info")
        self._log(f"GDB: {self._gdb_path}", "info")
        self._log(f"Saída: {pasta_saida}", "info")
        self._status_var.set("Convertendo para OpenDSS...")

        def _worker():
            try:
                convertidos = converter_alimentadores(
                    gdb_path=self._gdb_path,
                    alimentadores=alimentadores_exec,
                    cfg_settings=cfg,
                    pasta_saida=pasta_saida,
                    callback=lambda m: self.after(0, self._log, m),
                    cancelar_flag=self._cancelar,
                )
                self.after(0, self._conversao_ok, convertidos)
            except Exception as e:
                self.after(0, self._conversao_erro, str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _cancelar_conversao(self):
        self._cancelar.set()
        self._log("⚠ Solicitação de cancelamento enviada...", "aviso")
        self._btn_cancelar.config(state="disabled")

    def _conversao_ok(self, convertidos: list[str]):
        self._progress.stop()
        self._btn_converter.config(state="normal")
        self._btn_cancelar.config(state="disabled")
        self._var_prog_msg.set("")
        self._convertidos = convertidos

        cancelado = self._cancelar.is_set()
        n = len(convertidos)

        self._var_stat_conv.set(str(n))
        self._var_stat_status.set("Cancelado" if cancelado else "Concluído ✓")

        tag = "aviso" if cancelado else "ok"
        self._log(
            f"{'Cancelado.' if cancelado else 'Conversão concluída.'} "
            f"{n} pasta(s) gerada(s) em: {self._var_pasta_saida.get()}",
            tag,
        )
        self._status_var.set(f"Conversão: {n} alimentador(es) gerados.")

        if not cancelado and n > 0:
            messagebox.showinfo(
                "Conversão concluída",
                f"{n} alimentador(es) convertidos.\n\nPasta: {self._var_pasta_saida.get()}",
            )

    def _conversao_erro(self, msg: str):
        self._progress.stop()
        self._btn_converter.config(state="normal")
        self._btn_cancelar.config(state="disabled")
        self._var_prog_msg.set("")
        self._var_stat_status.set("Erro")
        self._log(f"Erro fatal: {msg}", "erro")
        messagebox.showerror("Erro na conversão", msg)

    # ------------------------------------------------------------------
    # Log
    # ------------------------------------------------------------------

    def _log(self, msg: str, tag: str = ""):
        import datetime
        ts  = datetime.datetime.now().strftime("%H:%M:%S")
        txt = f"[{ts}] {msg}\n"
        self._text_log.config(state="normal")
        self._text_log.insert("end", txt, tag or "")
        self._text_log.see("end")
        self._text_log.config(state="disabled")
        self._var_prog_msg.set(msg[:90])

    def _limpar_log(self):
        self._text_log.config(state="normal")
        self._text_log.delete("1.0", "end")
        self._text_log.config(state="disabled")

    # ------------------------------------------------------------------
    # Chamado externamente (app.py)
    # ------------------------------------------------------------------

    def atualizar_zips(self):
        """Atualiza a lista de ZIPs ao navegar para esta aba."""
        self._atualizar_lista_zips()
        if self._var_origem.get() == "gdb":
            self._atualizar_gdbs_extraidos()
