# -*- coding: utf-8 -*-
"""
ui/aba_simulacao.py
Aba de simulação elétrica OpenDSS — modo Daily (24 patamares horários).

FLUXO DA INTERFACE
------------------
1. Usuário seleciona BDGD convertida → lista alimentadores disponíveis
2. Usuário seleciona alimentador → lista arquivos Master por modo (DO/DU/SA)
3. Usuário seleciona Master e clica "Compilar circuito"
   → painel lateral exibe info do circuito (cargas, trafos, barras, ...)
4. Usuário clica "Executar simulação Daily"
   → thread separada roda 24 patamares, linha por linha na tabela
5. Linha TOTAL calculada ao final; botão Exportar XLSX ativado
"""

import os
import datetime
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from core.simulacao import (
    DSS_DISPONIVEL,
    listar_bdgds_convertidas,
    listar_alimentadores_convertidos,
    listar_masters,
    info_circuito,
    simular_daily,
    exportar_resultados_xlsx,
    MODOS_MASTER,
)
from ui.tema import CORES, FONTES


# ---------------------------------------------------------------------------
# Formatação numérica brasileira
# ---------------------------------------------------------------------------

def _fmt(valor, dec=2) -> str:
    if valor is None:
        return "—"
    s = f"{valor:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


# ---------------------------------------------------------------------------
# Aba principal
# ---------------------------------------------------------------------------

class AbaSimulacao(ttk.Frame):

    def __init__(self, parent, caminhos: dict, status_var: tk.StringVar):
        super().__init__(parent, style="TFrame")
        self._caminhos   = caminhos
        self._status_var = status_var

        # Estado interno
        self._pasta_alim:     str | None = None
        self._master_sel:     str | None = None
        self._nome_alim_ativo: str       = "—"  # nome exibido no painel de info
        self._rows:  list[dict]      = []
        self._info_circuito: dict    = {}
        self._cancelar = threading.Event()

        self._build()

        if not DSS_DISPONIVEL:
            self._log(
                "⚠ opendssdirect não está instalado.\n"
                "  Instale com: pip install opendssdirect\n",
                "aviso",
            )

        self._atualizar_bdgds()

    # ------------------------------------------------------------------
    # Build principal — 3 paineis verticais
    # ------------------------------------------------------------------

    def _build(self):
        C = CORES
        F = FONTES

        # Título
        tk.Label(
            self, text="Simulação OpenDSS",
            bg=C["bg_app"], fg=C["texto"],
            font=F["titulo_aba"], anchor="w",
        ).pack(fill="x", padx=24, pady=(20, 2))

        tk.Label(
            self,
            text="Executa simulação Daily (24 patamares) nos arquivos DSS gerados pelo módulo Conversão.",
            bg=C["bg_app"], fg=C["texto_sec"],
            font=F["pequeno"], anchor="w",
        ).pack(fill="x", padx=24, pady=(0, 12))

        # ── Corpo: 3 colunas ─────────────────────────────────────────
        corpo = tk.Frame(self, bg=C["bg_app"])
        corpo.pack(fill="both", expand=True, padx=24, pady=(0, 4))
        corpo.columnconfigure(0, weight=1)   # Seleção
        corpo.columnconfigure(1, weight=1)   # Info circuito
        corpo.columnconfigure(2, weight=3)   # Tabela + log

        self._build_col_selecao(corpo)
        self._build_col_info(corpo)
        self._build_col_resultados(corpo)

        # Barra de progresso global
        self._progress = ttk.Progressbar(
            self, mode="determinate", style="TProgressbar", maximum=24
        )
        self._progress.pack(fill="x", padx=24, pady=(0, 3))

        self._var_prog_msg = tk.StringVar(value="")
        tk.Label(
            self, textvariable=self._var_prog_msg,
            bg=C["bg_app"], fg=C["texto_sec"],
            font=F["status"], anchor="w",
        ).pack(fill="x", padx=24, pady=(0, 6))

    # ------------------------------------------------------------------
    # Coluna 1: Seleção de alimentador e master
    # ------------------------------------------------------------------

    def _build_col_selecao(self, parent):
        C = CORES
        F = FONTES

        col = tk.Frame(parent, bg=C["bg_card"])
        col.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        tk.Label(col, text="SELEÇÃO", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(padx=14, pady=(14, 8), anchor="w")

        # BDGD convertida
        tk.Label(col, text="BDGD convertida:", bg=C["bg_card"],
                 fg=C["texto_sec"], font=F["pequeno"]).pack(padx=14, anchor="w")

        self._var_bdgd = tk.StringVar()
        self._combo_bdgd = ttk.Combobox(
            col, textvariable=self._var_bdgd, state="readonly", width=32
        )
        self._combo_bdgd.pack(fill="x", padx=14, pady=(2, 8))
        self._combo_bdgd.bind("<<ComboboxSelected>>", self._on_bdgd_selecionada)

        # Alimentador
        tk.Label(col, text="Alimentador:", bg=C["bg_card"],
                 fg=C["texto_sec"], font=F["pequeno"]).pack(padx=14, anchor="w")

        self._var_alim = tk.StringVar()
        self._combo_alim = ttk.Combobox(
            col, textvariable=self._var_alim, state="readonly", width=32
        )
        self._combo_alim.pack(fill="x", padx=14, pady=(2, 8))
        self._combo_alim.bind("<<ComboboxSelected>>", self._on_alim_selecionado)

        tk.Frame(col, bg=C["borda"], height=1).pack(fill="x", padx=14, pady=6)

        # Modo (DO / DU / SA)
        tk.Label(col, text="ARQUIVO MASTER", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(padx=14, pady=(0, 6), anchor="w")

        tk.Label(col, text="Modo:", bg=C["bg_card"],
                 fg=C["texto_sec"], font=F["pequeno"]).pack(padx=14, anchor="w")

        self._var_modo = tk.StringVar(value="DO")
        frame_modo = tk.Frame(col, bg=C["bg_card"])
        frame_modo.pack(fill="x", padx=14, pady=(2, 8))

        for modo, desc in MODOS_MASTER.items():
            tk.Radiobutton(
                frame_modo, text=modo,
                variable=self._var_modo, value=modo,
                command=self._on_modo_changed,
                bg=C["bg_card"], fg=C["texto"],
                selectcolor=C["bg_input"],
                activebackground=C["bg_card"],
                activeforeground=C["acento"],
                font=F["pequeno"],
            ).pack(side="left", padx=(0, 8))

        # Descrição do modo
        self._var_desc_modo = tk.StringVar(value=MODOS_MASTER["DO"])
        tk.Label(
            col, textvariable=self._var_desc_modo,
            bg=C["bg_card"], fg=C["texto_desab"],
            font=F["pequeno"], anchor="w",
        ).pack(padx=14, pady=(0, 6), anchor="w")

        # Master disponíveis (listbox)
        tk.Label(col, text="Arquivos disponíveis:", bg=C["bg_card"],
                 fg=C["texto_sec"], font=F["pequeno"]).pack(padx=14, anchor="w")

        frame_lb = tk.Frame(col, bg=C["bg_card"])
        frame_lb.pack(fill="both", expand=True, padx=14, pady=(2, 8))

        sc_m = tk.Scrollbar(frame_lb, orient="vertical",
                            bg=C["bg_painel"], troughcolor=C["bg_app"])
        sc_m.pack(side="right", fill="y")

        self._lb_masters = tk.Listbox(
            frame_lb,
            selectmode="single", activestyle="none",
            yscrollcommand=sc_m.set,
            bg=C["bg_input"], fg=C["texto"],
            selectbackground=C["acento_escuro"],
            font=F["pequeno"],
            relief="flat", bd=0, highlightthickness=0,
        )
        self._lb_masters.pack(side="left", fill="both", expand=True)
        sc_m.config(command=self._lb_masters.yview)
        self._lb_masters.bind("<<ListboxSelect>>", self._on_master_selecionado)

        # Master manual
        tk.Button(
            col, text="📁  Selecionar Master manualmente",
            command=self._master_manual,
            bg=C["bg_input"], fg=C["texto"],
            font=F["botao"], relief="flat", bd=0,
            padx=10, pady=5, cursor="hand2",
            activebackground=C["bg_hover"], activeforeground=C["acento"],
        ).pack(fill="x", padx=14, pady=(0, 6))

        # Master selecionado
        self._var_master_atual = tk.StringVar(value="Nenhum Master selecionado")
        tk.Label(
            col, textvariable=self._var_master_atual,
            bg=C["bg_card"], fg=C["texto_desab"],
            font=F["pequeno"], wraplength=200, justify="left",
        ).pack(padx=14, pady=(0, 8), anchor="w")

        # Botão compilar
        self._btn_compilar = tk.Button(
            col, text="⚙  Compilar circuito",
            command=self._compilar_circuito,
            bg=C["bg_input"], fg=C["texto"],
            font=F["botao"], relief="flat", bd=0,
            padx=12, pady=6, cursor="hand2",
            state="disabled",
            activebackground=C["bg_hover"], activeforeground=C["acento"],
        )
        self._btn_compilar.pack(fill="x", padx=14, pady=(0, 6))

        tk.Frame(col, bg=C["borda"], height=1).pack(fill="x", padx=14, pady=6)

        # Botões de simulação
        self._btn_simular = tk.Button(
            col,
            text="▶  Executar simulação Daily",
            command=self._iniciar_simulacao,
            bg=C["acento"], fg=C["bg_app"],
            font=F["botao"], relief="flat", bd=0,
            padx=14, pady=9, cursor="hand2",
            state="disabled",
            activebackground=C["acento_hover"],
            activeforeground=C["bg_app"],
        )
        self._btn_simular.pack(fill="x", padx=14, pady=(0, 6))

        self._btn_parar = tk.Button(
            col,
            text="⏹  Parar simulação",
            command=self._parar_simulacao,
            bg=C["erro"], fg=C["texto"],
            font=F["botao"], relief="flat", bd=0,
            padx=14, pady=7, cursor="hand2",
            state="disabled",
            activebackground="#FF7070",
        )
        self._btn_parar.pack(fill="x", padx=14, pady=(0, 6))

        self._btn_exportar = tk.Button(
            col, text="↓  Exportar XLSX",
            command=self._exportar,
            bg=C["bg_input"], fg=C["texto"],
            font=F["botao"], relief="flat", bd=0,
            padx=10, pady=6, cursor="hand2",
            state="disabled",
            activebackground=C["bg_hover"], activeforeground=C["acento"],
        )
        self._btn_exportar.pack(fill="x", padx=14, pady=(0, 14))

    # ------------------------------------------------------------------
    # Coluna 2: Painel de informações do circuito
    # ------------------------------------------------------------------

    def _build_col_info(self, parent):
        C = CORES
        F = FONTES

        col = tk.Frame(parent, bg=C["bg_card"])
        col.grid(row=0, column=1, sticky="nsew", padx=(0, 8))

        tk.Label(col, text="INFORMAÇÕES DO CIRCUITO", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(padx=14, pady=(14, 6), anchor="w")

        # Alimentador ativo em destaque
        frame_alim_ativo = tk.Frame(col, bg=C["bg_painel"])
        frame_alim_ativo.pack(fill="x", padx=14, pady=(0, 10))

        tk.Label(
            frame_alim_ativo, text="Alimentador:",
            bg=C["bg_painel"], fg=C["texto_sec"],
            font=F["pequeno"],
        ).pack(side="left", padx=(8, 4), pady=6)

        self._var_alim_ativo = tk.StringVar(value="—")
        tk.Label(
            frame_alim_ativo, textvariable=self._var_alim_ativo,
            bg=C["bg_painel"], fg=C["acento"],
            font=F["corpo_bold"],
        ).pack(side="left", pady=6)

        # Itens de info — mesma estrutura do curva_carga.py
        CAMPOS_INFO = [
            ("carga_bt",    "Cargas BT"),
            ("carga_mt",    "Cargas MT"),
            ("carga_pip",   "Cargas PIP"),
            ("trafos",      "Transformadores"),
            ("barras",      "Barras"),
            ("linhas",      "Linhas"),
            ("ramais",      "Ramais BT"),
            ("reguladores", "Reguladores"),
            ("reatores",    "Reatores"),
            ("curvas",      "Tipos de curva"),
        ]

        self._info_labels: dict[str, tk.Label] = {}

        frame_info = tk.Frame(col, bg=C["bg_card"])
        frame_info.pack(fill="x", padx=14, pady=(0, 14))

        for chave, rotulo in CAMPOS_INFO:
            row_fr = tk.Frame(frame_info, bg=C["bg_card"])
            row_fr.pack(fill="x", pady=3)

            tk.Label(
                row_fr, text=rotulo + ":",
                bg=C["bg_card"], fg=C["texto_sec"],
                font=F["corpo"], anchor="w", width=16,
            ).pack(side="left")

            lbl_val = tk.Label(
                row_fr, text="—",
                bg=C["bg_card"], fg=C["texto"],
                font=F["corpo_bold"], anchor="w",
            )
            lbl_val.pack(side="left")
            self._info_labels[chave] = lbl_val

        tk.Frame(col, bg=C["borda"], height=1).pack(fill="x", padx=14, pady=6)

        # Stats de convergência (atualizados durante simulação)
        tk.Label(col, text="RESULTADO PARCIAL", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(padx=14, pady=(0, 8), anchor="w")

        stats = [
            ("_var_stat_conv",    "Convergência"),
            ("_var_stat_pot",     "Potência total"),
            ("_var_stat_perdas",  "Perdas totais"),
            ("_var_stat_pct",     "% Perdas"),
        ]

        for var_attr, label in stats:
            fr = tk.Frame(col, bg=C["bg_card"])
            fr.pack(fill="x", padx=14, pady=3)
            tk.Label(fr, text=label + ":", bg=C["bg_card"],
                     fg=C["texto_sec"], font=F["pequeno"],
                     anchor="w", width=16).pack(side="left")
            var = tk.StringVar(value="—")
            setattr(self, var_attr, var)
            tk.Label(fr, textvariable=var,
                     bg=C["bg_card"], fg=C["acento"],
                     font=F["corpo_bold"], anchor="w").pack(side="left")

    # ------------------------------------------------------------------
    # Coluna 3: Tabela de resultados + log
    # ------------------------------------------------------------------

    def _build_col_resultados(self, parent):
        C = CORES
        F = FONTES

        col = tk.Frame(parent, bg=C["bg_card"])
        col.grid(row=0, column=2, sticky="nsew")

        # Header
        hdr = tk.Frame(col, bg=C["bg_card"])
        hdr.pack(fill="x", padx=14, pady=(14, 4))

        tk.Label(hdr, text="RESULTADOS — SIMULAÇÃO DAILY", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(side="left")

        tk.Button(
            hdr, text="Limpar",
            command=self._limpar_tudo,
            bg=C["bg_input"], fg=C["texto_sec"],
            font=F["pequeno"], relief="flat", bd=0,
            padx=6, pady=2, cursor="hand2",
        ).pack(side="right")

        # Tabela de resultados
        frame_tree = tk.Frame(col, bg=C["bg_card"])
        frame_tree.pack(fill="both", expand=True, padx=14, pady=(0, 6))

        colunas = [
            ("Hora",           60),
            ("Potência (kW)", 130),
            ("Perdas (kW)",   120),
            ("% Perdas",       90),
            ("Convergiu",     100),
            ("Iterações",      70),
        ]

        sc_y = tk.Scrollbar(frame_tree, orient="vertical",
                            bg=C["bg_painel"], troughcolor=C["bg_app"])
        sc_y.pack(side="right", fill="y")

        self._tree = ttk.Treeview(
            frame_tree,
            columns=[c[0] for c in colunas],
            show="headings",
            yscrollcommand=sc_y.set,
            height=14,
        )
        self._tree.pack(side="left", fill="both", expand=True)
        sc_y.config(command=self._tree.yview)

        for nome, largura in colunas:
            self._tree.heading(nome, text=nome)
            self._tree.column(nome, width=largura, minwidth=50, anchor="center")

        # Tags de cor nas linhas
        self._tree.tag_configure("ok",    background=C["bg_card"],    foreground=C["sucesso"])
        self._tree.tag_configure("fail",  background=C["bg_card"],    foreground=C["erro"])
        self._tree.tag_configure("total", background=C["bg_painel"],  foreground=C["texto"],
                                  font=("Segoe UI", 9, "bold"))

        # Separador
        tk.Frame(col, bg=C["borda"], height=1).pack(fill="x", padx=14, pady=4)

        # Log
        hdr_log = tk.Frame(col, bg=C["bg_card"])
        hdr_log.pack(fill="x", padx=14, pady=(0, 4))

        tk.Label(hdr_log, text="LOG", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(side="left")

        tk.Button(
            hdr_log, text="Limpar log",
            command=self._limpar_log,
            bg=C["bg_input"], fg=C["texto_sec"],
            font=F["pequeno"], relief="flat", bd=0,
            padx=6, pady=2, cursor="hand2",
        ).pack(side="right")

        frame_log = tk.Frame(col, bg=C["bg_card"])
        frame_log.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        sc_log = tk.Scrollbar(frame_log, orient="vertical",
                              bg=C["bg_painel"], troughcolor=C["bg_app"])
        sc_log.pack(side="right", fill="y")

        self._text_log = tk.Text(
            frame_log,
            yscrollcommand=sc_log.set,
            bg=C["bg_input"], fg=C["texto"],
            font=F["mono"], relief="flat", bd=0,
            state="disabled", padx=8, pady=6,
            wrap="word", height=8,
        )
        self._text_log.pack(side="left", fill="both", expand=True)
        sc_log.config(command=self._text_log.yview)

        # Tags de cor no log
        self._text_log.tag_config("ok",      foreground=CORES["sucesso"])
        self._text_log.tag_config("aviso",   foreground=CORES["aviso"])
        self._text_log.tag_config("erro",    foreground=CORES["erro"])
        self._text_log.tag_config("info",    foreground=CORES["acento"])
        self._text_log.tag_config("section", foreground=CORES["texto_sec"])

    # ------------------------------------------------------------------
    # Lógica: seleção de BDGD → alimentador → master
    # ------------------------------------------------------------------

    def _atualizar_bdgds(self):
        bdgds = listar_bdgds_convertidas(self._caminhos["base"])
        self._combo_bdgd["values"] = bdgds
        if bdgds:
            self._combo_bdgd.set(bdgds[0])
            self._on_bdgd_selecionada()

    def _on_bdgd_selecionada(self, *_):
        bdgd = self._var_bdgd.get()
        if not bdgd:
            return

        alims = listar_alimentadores_convertidos(self._caminhos["base"], bdgd)
        nomes = [a["nome"] for a in alims]
        self._combo_alim["values"] = nomes

        # Guardar mapa nome → pasta
        self._alim_map = {a["nome"]: a["pasta"] for a in alims}

        if nomes:
            self._combo_alim.set(nomes[0])
            self._on_alim_selecionado()
        else:
            self._lb_masters.delete(0, tk.END)
            self._var_master_atual.set("Nenhum alimentador encontrado")

    def _on_alim_selecionado(self, *_):
        nome = self._var_alim.get()
        if not nome:
            return

        self._pasta_alim = self._alim_map.get(nome)
        if not self._pasta_alim:
            return

        self._nome_alim_ativo = nome
        self._popular_masters()

    def _on_modo_changed(self):
        modo = self._var_modo.get()
        self._var_desc_modo.set(MODOS_MASTER.get(modo, ""))
        self._popular_masters()

    def _popular_masters(self):
        if not self._pasta_alim:
            return

        modo   = self._var_modo.get()
        masters = listar_masters(self._pasta_alim)
        lista   = masters.get(modo, []) + masters.get("OUTROS", [])

        self._lb_masters.delete(0, tk.END)
        for m in lista:
            self._lb_masters.insert(tk.END, f"  {m}")

        if lista:
            self._lb_masters.selection_set(0)
            self._master_sel = lista[0]
            self._var_master_atual.set(lista[0])
            self._btn_compilar.config(state="normal")
        else:
            self._master_sel = None
            self._var_master_atual.set("Nenhum Master encontrado para este modo")
            self._btn_compilar.config(state="disabled")

    def _on_master_selecionado(self, *_):
        sel = self._lb_masters.curselection()
        if not sel:
            return
        nome = self._lb_masters.get(sel[0]).strip()
        self._master_sel = nome
        self._var_master_atual.set(nome)
        self._btn_compilar.config(state="normal")

    def _master_manual(self):
        path = filedialog.askopenfilename(
            title="Selecionar arquivo Master*.dss",
            filetypes=[("Arquivos DSS", "*.dss"), ("Todos", "*.*")],
        )
        if not path:
            return

        self._pasta_alim = os.path.dirname(path)
        self._master_sel = os.path.basename(path)
        self._nome_alim_ativo = f"{os.path.basename(self._pasta_alim)} (manual)"
        self._var_master_atual.set(self._master_sel)
        self._btn_compilar.config(state="normal")
        self._log(f"Master manual: {path}", "info")

    # ------------------------------------------------------------------
    # Compilação do circuito
    # ------------------------------------------------------------------

    def _compilar_circuito(self):
        if not self._pasta_alim or not self._master_sel:
            messagebox.showwarning("Aviso", "Selecione um Master antes de compilar.")
            return

        if not DSS_DISPONIVEL:
            messagebox.showerror(
                "OpenDSS não disponível",
                "A biblioteca opendssdirect não está instalada.\n"
                "Execute: pip install opendssdirect",
            )
            return

        self._btn_compilar.config(state="disabled")
        self._btn_simular.config(state="disabled")
        self._log(f"Compilando: {self._master_sel}", "info")

        def _worker():
            try:
                info = info_circuito(self._pasta_alim, self._master_sel)
                self.after(0, self._compilacao_ok, info)
            except Exception as e:
                self.after(0, self._compilacao_erro, str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _compilacao_ok(self, info: dict):
        self._info_circuito = info
        self._btn_compilar.config(state="normal")
        self._btn_simular.config(state="normal")

        for chave, lbl in self._info_labels.items():
            val = info.get(chave, "—")
            lbl.config(text=str(val))

        # Atualizar label do alimentador ativo
        self._var_alim_ativo.set(self._nome_alim_ativo)

        self._log(
            f"✔ Circuito compilado: {info.get('barras',0)} barras, "
            f"{info.get('linhas',0)} linhas, "
            f"{info.get('trafos',0)} trafos.",
            "ok",
        )
        self._status_var.set(
            f"Compilado: {self._master_sel} | "
            f"{info.get('barras',0)} barras | "
            f"{info.get('trafos',0)} trafos"
        )

    def _compilacao_erro(self, msg: str):
        self._btn_compilar.config(state="normal")
        self._log(f"Erro ao compilar: {msg}", "erro")
        messagebox.showerror("Erro de compilação", msg)

    # ------------------------------------------------------------------
    # Simulação Daily
    # ------------------------------------------------------------------

    def _iniciar_simulacao(self):
        if not self._pasta_alim or not self._master_sel:
            messagebox.showwarning("Aviso", "Selecione e compile um circuito primeiro.")
            return

        if not DSS_DISPONIVEL:
            messagebox.showerror(
                "OpenDSS não disponível",
                "Instale com: pip install opendssdirect",
            )
            return

        # Limpar tabela e estado
        self._rows = []
        self._tree.delete(*self._tree.get_children())
        self._cancelar.clear()
        self._progress["value"] = 0

        self._btn_simular.config(state="disabled")
        self._btn_parar.config(state="normal")
        self._btn_exportar.config(state="disabled")
        self._var_stat_conv.set("—")
        self._var_stat_pot.set("—")
        self._var_stat_perdas.set("—")
        self._var_stat_pct.set("—")

        self._log(
            f"\n{'─'*50}\n"
            f"Simulação: {self._master_sel}\n"
            f"{'─'*50}",
            "section",
        )
        self._status_var.set(f"Simulando: {self._master_sel}...")

        def _worker():
            try:
                rows = simular_daily(
                    pasta=self._pasta_alim,
                    master=self._master_sel,
                    callback_hora=lambda r: self.after(0, self._on_hora_concluida, r),
                    callback_log=lambda m: self.after(0, self._log, m),
                    cancelar_flag=self._cancelar,
                )
                self.after(0, self._simulacao_ok, rows)
            except Exception as e:
                self.after(0, self._simulacao_erro, str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_hora_concluida(self, row: dict):
        """Chamado após cada patamar horário — atualiza tabela e stats."""
        self._rows.append(row)

        conv = row["convergiu"]
        kw   = row["kw"]
        perd = row["perdas_kw"]
        pct  = row["pct_perdas"]

        tag = "ok" if conv else "fail"

        self._tree.insert("", "end", values=(
            f"{row['hora']:02d}h",
            _fmt(kw)   if conv else "—",
            _fmt(perd) if conv else "—",
            (f"{_fmt(pct, 3)} %") if conv else "—",
            "✓  OK" if conv else "✗  FALHA",
            str(row["iteracoes"]),
        ), tags=(tag,))
        self._tree.yview_moveto(1)

        # Atualizar barra de progresso
        self._progress["value"] = row["hora"]
        self._var_prog_msg.set(
            f"Patamar {row['hora']:02d}/24  |  "
            f"{'✓ Convergiu' if conv else '✗ Não convergiu'}"
        )

        # Atualizar stats acumulados
        n_ok   = sum(1 for r in self._rows if r["convergiu"])
        en_acc = sum(r["kw"]        for r in self._rows if r["convergiu"])
        pd_acc = sum(r["perdas_kw"] for r in self._rows if r["convergiu"])
        pct_ac = (pd_acc / en_acc * 100) if en_acc > 0 else 0

        self._var_stat_conv.set(f"{n_ok}/{len(self._rows)}")
        self._var_stat_pot.set(f"{_fmt(en_acc)} kW·h")
        self._var_stat_perdas.set(f"{_fmt(pd_acc)} kW·h")
        self._var_stat_pct.set(f"{_fmt(pct_ac, 3)} %")

    def _simulacao_ok(self, rows: list[dict]):
        self._btn_simular.config(state="normal")
        self._btn_parar.config(state="disabled")
        self._progress["value"] = 24
        self._var_prog_msg.set("")

        cancelado = self._cancelar.is_set()
        self._rows = rows

        if rows:
            self._inserir_linha_total(rows)
            self._btn_exportar.config(state="normal")

        n_ok   = sum(1 for r in rows if r["convergiu"])
        en_tot = sum(r["kw"]        for r in rows if r["convergiu"])
        pd_tot = sum(r["perdas_kw"] for r in rows if r["convergiu"])
        pct_t  = (pd_tot / en_tot * 100) if en_tot > 0 else 0

        self._var_stat_conv.set(f"{n_ok}/24")
        self._var_stat_pot.set(f"{_fmt(en_tot)} kW·h")
        self._var_stat_perdas.set(f"{_fmt(pd_tot)} kW·h")
        self._var_stat_pct.set(f"{_fmt(pct_t, 3)} %")

        status = "Cancelada" if cancelado else "Concluída ✓"
        self._log(
            f"{'Cancelada.' if cancelado else 'Simulação concluída.'} "
            f"{n_ok}/24 OK | Perdas: {_fmt(pd_tot)} kW·h ({_fmt(pct_t, 3)} %)",
            "aviso" if cancelado else "ok",
        )
        self._status_var.set(
            f"{status}: {n_ok}/24 | Perdas: {_fmt(pct_t, 3)} %"
        )

    def _simulacao_erro(self, msg: str):
        self._btn_simular.config(state="normal")
        self._btn_parar.config(state="disabled")
        self._var_prog_msg.set("")
        self._log(f"Erro fatal: {msg}", "erro")
        messagebox.showerror("Erro na simulação", msg)

    def _parar_simulacao(self):
        self._cancelar.set()
        self._log("⚠ Solicitação de parada enviada...", "aviso")
        self._btn_parar.config(state="disabled")

    # ------------------------------------------------------------------
    # Tabela: linha TOTAL
    # ------------------------------------------------------------------

    def _inserir_linha_total(self, rows: list[dict]):
        en_ok  = [r for r in rows if r["convergiu"]]
        en_tot = sum(r["kw"]        for r in en_ok)
        pd_tot = sum(r["perdas_kw"] for r in en_ok)
        pct_t  = (pd_tot / en_tot * 100) if en_tot > 0 else 0
        n_ok   = len(en_ok)

        self._tree.insert("", "end", values=(
            "TOTAL",
            _fmt(en_tot, 0),
            _fmt(pd_tot, 0),
            f"{_fmt(pct_t, 3)} %" if en_tot > 0 else "—",
            f"{n_ok}/24",
            "",
        ), tags=("total",))

    # ------------------------------------------------------------------
    # Exportação XLSX
    # ------------------------------------------------------------------

    def _exportar(self):
        if not self._rows:
            messagebox.showwarning("Aviso", "Nenhum resultado para exportar.")
            return

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        alim = self._var_alim.get() or "simulacao"
        nome_sugerido = f"{alim}_daily_{ts}.xlsx"

        caminho = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialfile=nome_sugerido,
            title="Exportar resultados",
        )
        if not caminho:
            return

        meta = {
            "BDGD":        self._var_bdgd.get(),
            "Alimentador": self._var_alim.get(),
            "Master":      self._master_sel or "",
            "Modo":        self._var_modo.get(),
            "Data/Hora":   datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        }

        try:
            exportar_resultados_xlsx(self._rows, caminho, meta)
            messagebox.showinfo("Sucesso", f"Exportado:\n{caminho}")
            self._log(f"✔ Exportado: {caminho}", "ok")
        except Exception as e:
            messagebox.showerror("Erro ao exportar", str(e))

    # ------------------------------------------------------------------
    # Log
    # ------------------------------------------------------------------

    def _log(self, msg: str, tag: str = ""):
        ts  = datetime.datetime.now().strftime("%H:%M:%S")
        txt = f"[{ts}] {msg}\n"
        self._text_log.config(state="normal")
        self._text_log.insert("end", txt, tag or "")
        self._text_log.see("end")
        self._text_log.config(state="disabled")

    def _limpar_log(self):
        self._text_log.config(state="normal")
        self._text_log.delete("1.0", "end")
        self._text_log.config(state="disabled")

    def _limpar_tudo(self):
        self._limpar_log()
        self._tree.delete(*self._tree.get_children())
        self._rows = []
        self._progress["value"] = 0
        self._var_prog_msg.set("")
        self._btn_exportar.config(state="disabled")
        for var in [self._var_stat_conv, self._var_stat_pot,
                    self._var_stat_perdas, self._var_stat_pct]:
            var.set("—")

    # ------------------------------------------------------------------
    # Chamado externamente (app.py) ao navegar para esta aba
    # ------------------------------------------------------------------

    def atualizar_alimentadores(self):
        """Recarrega a lista de BDGDs/alimentadores convertidos."""
        self._atualizar_bdgds()
