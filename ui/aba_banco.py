# -*- coding: utf-8 -*-
"""
ui/aba_banco.py
Aba de criação e atualização do banco DuckDB.

LAYOUT (3 colunas)
------------------
[Entidades BDGD] | [Seleção rápida + ações] | [Importação DDA / Arquivo externo]

NOVIDADES
---------
- Seção "Importar Tabela de Arquivo": botão para selecionar .xlsx/.csv e criar
  tabela com o nome do arquivo (sem extensão) no banco atual.
- Seção "Tabelas DDA": mostra status da pasta DDA/, lista arquivos encontrados
  e importa automaticamente ao criar o banco. Exibe badge de aviso quando DDA
  está ausente.
- Após criação do banco, painel inferior exibe as tabelas existentes no banco.
"""

import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path

from core.banco import (
    listar_entidades_zip,
    criar_ou_atualizar_banco,
    listar_bancos,
    listar_tabelas_banco,
    importar_arquivo_para_banco,
    carregar_pasta_dda,
    verificar_dda,
    ENTIDADES_MINIMAS,
)
from core.extrator import listar_bdgds_baixadas
from ui.tema import CORES, FONTES


class AbaBanco(ttk.Frame):

    def __init__(self, parent, caminhos: dict, status_var: tk.StringVar):
        super().__init__(parent, style="TFrame")
        self._caminhos = caminhos
        self._status_var = status_var
        self._entidades_disponiveis: list[str] = []
        self._banco_atual_path: str | None = None  # path do banco recém-criado/selecionado

        self._build()
        self._atualizar_lista_zips()
        self._verificar_dda_status()

    # ------------------------------------------------------------------
    # Build principal
    # ------------------------------------------------------------------

    def _build(self):
        C = CORES
        F = FONTES

        # Título
        tk.Label(
            self, text="Banco de Dados DuckDB",
            bg=C["bg_app"], fg=C["texto"],
            font=F["titulo_aba"], anchor="w",
        ).pack(fill="x", padx=24, pady=(20, 2))

        tk.Label(
            self,
            text="Converte entidades da BDGD para DuckDB. Suporta importação de tabelas externas (.xlsx/.csv) e carga automática da pasta DDA.",
            bg=C["bg_app"], fg=C["texto_sec"],
            font=F["pequeno"], anchor="w", wraplength=1100,
        ).pack(fill="x", padx=24, pady=(0, 12))

        # ── Linha superior: seleção BDGD + nome do banco ─────────────
        self._build_topo()

        # ── Corpo 3 colunas ──────────────────────────────────────────
        corpo = tk.Frame(self, bg=C["bg_app"])
        corpo.pack(fill="both", expand=True, padx=24, pady=(0, 8))
        corpo.columnconfigure(0, weight=3)
        corpo.columnconfigure(1, weight=1)
        corpo.columnconfigure(2, weight=2)

        self._build_col_entidades(corpo)
        self._build_col_acoes(corpo)
        self._build_col_importacao(corpo)

        # ── Barra de progresso + botão criar ─────────────────────────
        self._build_rodape()

    def _build_topo(self):
        C = CORES
        F = FONTES

        topo = tk.Frame(self, bg=C["bg_card"])
        topo.pack(fill="x", padx=24, pady=(0, 10))

        # BDGD zip
        col1 = tk.Frame(topo, bg=C["bg_card"])
        col1.pack(side="left", fill="both", expand=True, padx=14, pady=12)

        tk.Label(col1, text="BDGD (arquivo .zip):", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(anchor="w", pady=(0, 4))

        self._var_zip = tk.StringVar()
        self._combo_zip = ttk.Combobox(
            col1, textvariable=self._var_zip, state="readonly", width=55
        )
        self._combo_zip.pack(fill="x")
        self._combo_zip.bind("<<ComboboxSelected>>", self._on_zip_selecionado)

        # Nome do banco
        col2 = tk.Frame(topo, bg=C["bg_card"])
        col2.pack(side="left", fill="both", padx=14, pady=12, ipadx=20)

        tk.Label(col2, text="Nome do banco (opcional):", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(anchor="w", pady=(0, 4))

        self._var_nome = tk.StringVar()
        tk.Entry(
            col2, textvariable=self._var_nome,
            bg=C["bg_input"], fg=C["texto"],
            insertbackground=C["acento"],
            relief="flat", bd=0, font=F["corpo"],
        ).pack(fill="x", ipady=5, padx=2)

        tk.Label(col2, text="Se vazio, usa o nome da BDGD",
                 bg=C["bg_card"], fg=C["texto_sec"], font=F["pequeno"]).pack(anchor="w")

    # ------------------------------------------------------------------
    # Coluna 1: entidades do GDB
    # ------------------------------------------------------------------

    def _build_col_entidades(self, parent):
        C = CORES
        F = FONTES

        card = tk.Frame(parent, bg=C["bg_card"])
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        hdr = tk.Frame(card, bg=C["bg_card"])
        hdr.pack(fill="x", padx=14, pady=(14, 6))

        tk.Label(hdr, text="ENTIDADES DO GDB", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(side="left")

        self._var_cont_ent = tk.StringVar(value="0 selecionadas")
        tk.Label(hdr, textvariable=self._var_cont_ent, bg=C["bg_card"],
                 fg=C["texto_sec"], font=F["pequeno"]).pack(side="right")

        frame_lb = tk.Frame(card, bg=C["bg_card"])
        frame_lb.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        sc = tk.Scrollbar(frame_lb, orient="vertical",
                          bg=C["bg_painel"], troughcolor=C["bg_app"])
        sc.pack(side="right", fill="y")

        self._lb_ent = tk.Listbox(
            frame_lb,
            selectmode="multiple", activestyle="none",
            yscrollcommand=sc.set,
            bg=C["bg_input"], fg=C["texto"],
            selectbackground=C["acento_escuro"],
            font=F["corpo"], relief="flat", bd=0, highlightthickness=0,
        )
        self._lb_ent.pack(side="left", fill="both", expand=True)
        sc.config(command=self._lb_ent.yview)
        self._lb_ent.bind("<<ListboxSelect>>", self._atualizar_contador)

    # ------------------------------------------------------------------
    # Coluna 2: ações de seleção + botão criar
    # ------------------------------------------------------------------

    def _build_col_acoes(self, parent):
        C = CORES
        F = FONTES

        card = tk.Frame(parent, bg=C["bg_card"])
        card.grid(row=0, column=1, sticky="nsew", padx=(0, 8))

        tk.Label(card, text="SELEÇÃO RÁPIDA", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(padx=14, pady=(14, 10), anchor="w")

        for texto, cmd in [
            ("✔  Selecionar todas",           self._sel_todas),
            ("⚡  Mínimas (dashboard)",        self._sel_minimas),
            ("✕  Desmarcar todas",             self._dessel_todas),
        ]:
            tk.Button(
                card, text=texto, command=cmd,
                bg=C["bg_input"], fg=C["texto"],
                font=F["botao"], relief="flat", bd=0,
                padx=10, pady=6, cursor="hand2", anchor="w",
                activebackground=C["bg_hover"],
                activeforeground=C["acento"],
            ).pack(fill="x", padx=14, pady=3)

        tk.Label(
            card,
            text="Mínimas:\n" + "\n".join(ENTIDADES_MINIMAS),
            bg=C["bg_card"], fg=C["texto_desab"],
            font=F["pequeno"], justify="left",
        ).pack(padx=14, pady=(8, 0), anchor="w")

    # ------------------------------------------------------------------
    # Coluna 3: DDA + importação de arquivo externo
    # ------------------------------------------------------------------

    def _build_col_importacao(self, parent):
        C = CORES
        F = FONTES

        col = tk.Frame(parent, bg=C["bg_app"])
        col.grid(row=0, column=2, sticky="nsew")

        # ── Card DDA ─────────────────────────────────────────────────
        card_dda = tk.Frame(col, bg=C["bg_card"])
        card_dda.pack(fill="x", pady=(0, 8))

        hdr_dda = tk.Frame(card_dda, bg=C["bg_card"])
        hdr_dda.pack(fill="x", padx=14, pady=(14, 6))

        tk.Label(hdr_dda, text="PASTA DDA", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(side="left")

        # Badge de status da DDA (verde/amarelo)
        self._var_badge_dda = tk.StringVar(value="...")
        self._lbl_badge_dda = tk.Label(
            hdr_dda, textvariable=self._var_badge_dda,
            bg=C["aviso"], fg=C["bg_app"],
            font=F["badge"], padx=6, pady=1,
        )
        self._lbl_badge_dda.pack(side="right")

        tk.Label(
            card_dda,
            text="Arquivos .xlsx/.csv em DDA/ são importados\nautomaticamente ao criar o banco.",
            bg=C["bg_card"], fg=C["texto_sec"],
            font=F["pequeno"], justify="left",
        ).pack(padx=14, anchor="w")

        # Listbox de arquivos DDA encontrados
        frame_dda = tk.Frame(card_dda, bg=C["bg_card"])
        frame_dda.pack(fill="x", padx=14, pady=(6, 0))

        sc_dda = tk.Scrollbar(frame_dda, orient="vertical",
                              bg=C["bg_painel"], troughcolor=C["bg_app"])
        sc_dda.pack(side="right", fill="y")

        self._lb_dda = tk.Listbox(
            frame_dda,
            yscrollcommand=sc_dda.set,
            selectmode="browse", activestyle="none",
            bg=C["bg_input"], fg=C["texto_sec"],
            font=F["pequeno"], relief="flat", bd=0,
            highlightthickness=0, height=5,
        )
        self._lb_dda.pack(side="left", fill="both", expand=True)
        sc_dda.config(command=self._lb_dda.yview)

        tk.Button(
            card_dda, text="↺  Verificar pasta DDA",
            command=self._verificar_dda_status,
            bg=C["bg_input"], fg=C["texto"],
            font=F["botao"], relief="flat", bd=0,
            padx=10, pady=5, cursor="hand2",
            activebackground=C["bg_hover"], activeforeground=C["acento"],
        ).pack(fill="x", padx=14, pady=(6, 14))

        # ── Card Importar arquivo externo ─────────────────────────────
        card_imp = tk.Frame(col, bg=C["bg_card"])
        card_imp.pack(fill="both", expand=True)

        tk.Label(card_imp, text="IMPORTAR TABELA DE ARQUIVO", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(padx=14, pady=(14, 6), anchor="w")

        tk.Label(
            card_imp,
            text="Selecione um .xlsx ou .csv para criar\numa tabela no banco. O nome da tabela\nserá o nome do arquivo (sem extensão).",
            bg=C["bg_card"], fg=C["texto_sec"],
            font=F["pequeno"], justify="left",
        ).pack(padx=14, anchor="w")

        # Banco de destino para importação avulsa
        tk.Label(card_imp, text="Banco de destino:", bg=C["bg_card"],
                 fg=C["texto_sec"], font=F["pequeno"]).pack(padx=14, pady=(10, 2), anchor="w")

        self._var_banco_imp = tk.StringVar()
        self._combo_banco_imp = ttk.Combobox(
            card_imp, textvariable=self._var_banco_imp,
            state="readonly", width=28,
        )
        self._combo_banco_imp.pack(fill="x", padx=14, pady=(0, 6))

        # Arquivo selecionado
        self._var_arquivo_imp = tk.StringVar(value="Nenhum arquivo selecionado")
        tk.Label(
            card_imp, textvariable=self._var_arquivo_imp,
            bg=C["bg_card"], fg=C["texto_desab"],
            font=F["pequeno"], wraplength=220, justify="left",
        ).pack(padx=14, pady=(0, 6), anchor="w")

        tk.Button(
            card_imp, text="📄  Selecionar arquivo (.xlsx / .csv)",
            command=self._selecionar_arquivo_imp,
            bg=C["bg_input"], fg=C["texto"],
            font=F["botao"], relief="flat", bd=0,
            padx=10, pady=5, cursor="hand2",
            activebackground=C["bg_hover"], activeforeground=C["acento"],
        ).pack(fill="x", padx=14, pady=(0, 4))

        self._btn_importar = tk.Button(
            card_imp, text="⬆  Importar como tabela",
            command=self._importar_arquivo,
            bg=C["acento"], fg=C["bg_app"],
            font=F["botao"], relief="flat", bd=0,
            padx=10, pady=7, cursor="hand2",
            state="disabled",
            activebackground=C["acento_hover"],
            activeforeground=C["bg_app"],
        )
        self._btn_importar.pack(fill="x", padx=14, pady=(0, 14))

        # Tabelas existentes no banco
        tk.Frame(col, bg=C["borda"], height=1).pack(fill="x", pady=4)

        card_tab = tk.Frame(col, bg=C["bg_card"])
        card_tab.pack(fill="both", expand=True)

        hdr_tab = tk.Frame(card_tab, bg=C["bg_card"])
        hdr_tab.pack(fill="x", padx=14, pady=(10, 4))

        tk.Label(hdr_tab, text="TABELAS NO BANCO", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(side="left")

        tk.Button(
            hdr_tab, text="↺",
            command=self._atualizar_tabelas_banco,
            bg=C["bg_input"], fg=C["texto"],
            font=F["pequeno"], relief="flat", bd=0,
            padx=6, pady=2, cursor="hand2",
        ).pack(side="right")

        frame_tab = tk.Frame(card_tab, bg=C["bg_card"])
        frame_tab.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        sc_tab = tk.Scrollbar(frame_tab, orient="vertical",
                              bg=C["bg_painel"], troughcolor=C["bg_app"])
        sc_tab.pack(side="right", fill="y")

        self._lb_tabelas = tk.Listbox(
            frame_tab,
            yscrollcommand=sc_tab.set,
            activestyle="none",
            bg=C["bg_input"], fg=C["texto_sec"],
            font=F["pequeno"], relief="flat", bd=0,
            highlightthickness=0,
        )
        self._lb_tabelas.pack(side="left", fill="both", expand=True)
        sc_tab.config(command=self._lb_tabelas.yview)

    # ------------------------------------------------------------------
    # Rodapé: progresso + botão criar banco
    # ------------------------------------------------------------------

    def _build_rodape(self):
        C = CORES
        F = FONTES

        frame_prog = tk.Frame(self, bg=C["bg_app"])
        frame_prog.pack(fill="x", padx=24, pady=(0, 4))

        self._var_prog_msg = tk.StringVar(value="")
        tk.Label(
            frame_prog, textvariable=self._var_prog_msg,
            bg=C["bg_app"], fg=C["texto_sec"], font=F["status"], anchor="w",
        ).pack(side="left")

        self._progress = ttk.Progressbar(
            self, mode="indeterminate", style="TProgressbar"
        )
        self._progress.pack(fill="x", padx=24, pady=(0, 4))

        self._btn_criar = tk.Button(
            self,
            text="⚙  Criar / Atualizar Banco DuckDB",
            command=self._iniciar_criacao,
            bg=C["acento"], fg=C["bg_app"],
            font=F["botao"], relief="flat", bd=0,
            padx=14, pady=9, cursor="hand2",
            activebackground=C["acento_hover"],
            activeforeground=C["bg_app"],
        )
        self._btn_criar.pack(padx=24, pady=(0, 12), anchor="e")

    # ------------------------------------------------------------------
    # Lógica: BDGD / entidades
    # ------------------------------------------------------------------

    def _atualizar_lista_zips(self):
        zips = listar_bdgds_baixadas(self._caminhos["bdgds"])
        self._combo_zip["values"] = zips
        if zips:
            self._combo_zip.set(zips[0])
            self._on_zip_selecionado()
        self._atualizar_combo_bancos()

    def _on_zip_selecionado(self, *_):
        zip_file = self._var_zip.get()
        if not zip_file:
            return

        zip_path = os.path.join(self._caminhos["bdgds"], zip_file)
        self._lb_ent.delete(0, tk.END)
        self._var_prog_msg.set("Lendo entidades do arquivo...")

        def _worker():
            try:
                entidades = listar_entidades_zip(zip_path)
                self._entidades_disponiveis = entidades
                self.after(0, self._popular_entidades, entidades)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Erro", str(e)))
                self.after(0, lambda: self._var_prog_msg.set(""))

        threading.Thread(target=_worker, daemon=True).start()

    def _popular_entidades(self, entidades: list[str]):
        self._lb_ent.delete(0, tk.END)
        for e in entidades:
            self._lb_ent.insert(tk.END, f"  {e}")
        self._var_prog_msg.set(f"{len(entidades)} entidades encontradas.")
        self._atualizar_contador()

    def _atualizar_contador(self, *_):
        n = len(self._lb_ent.curselection())
        self._var_cont_ent.set(f"{n} selecionada(s)")

    def _sel_todas(self):
        self._lb_ent.select_set(0, tk.END)
        self._atualizar_contador()

    def _sel_minimas(self):
        self._lb_ent.selection_clear(0, tk.END)
        for i in range(self._lb_ent.size()):
            if self._lb_ent.get(i).strip() in ENTIDADES_MINIMAS:
                self._lb_ent.selection_set(i)
        self._atualizar_contador()

    def _dessel_todas(self):
        self._lb_ent.selection_clear(0, tk.END)
        self._atualizar_contador()

    # ------------------------------------------------------------------
    # Lógica: criar banco (BDGD + DDA automático)
    # ------------------------------------------------------------------

    def _iniciar_criacao(self):
        zip_file = self._var_zip.get()
        if not zip_file:
            messagebox.showwarning("Aviso", "Selecione uma BDGD.")
            return

        selecionados_idx = self._lb_ent.curselection()
        if not selecionados_idx:
            messagebox.showwarning("Aviso", "Selecione ao menos uma entidade.")
            return

        entidades  = [self._lb_ent.get(i).strip() for i in selecionados_idx]
        zip_path   = os.path.join(self._caminhos["bdgds"], zip_file)

        nome_digitado = self._var_nome.get().strip()
        if nome_digitado:
            nome_banco = nome_digitado if nome_digitado.endswith(".duckdb") else nome_digitado + ".duckdb"
        else:
            nome_banco = zip_file.replace(".zip", ".duckdb")

        banco_path = os.path.join(self._caminhos["duckdb"], nome_banco)

        if os.path.exists(banco_path):
            resp = messagebox.askyesno(
                "Banco existente",
                f"O banco '{nome_banco}' já existe.\n"
                "As entidades selecionadas serão sobrescritas.\n"
                "As demais permanecerão inalteradas.\n\nContinuar?",
            )
            if not resp:
                return

        self._btn_criar.config(state="disabled")
        self._progress.start(10)
        self._var_prog_msg.set("Iniciando importação...")
        self._status_var.set(f"Criando banco: {nome_banco}...")

        def _worker():
            try:
                # 1. Importar entidades BDGD
                importadas = criar_ou_atualizar_banco(
                    zip_path=zip_path,
                    banco_path=banco_path,
                    entidades=entidades,
                    callback_progresso=lambda m: self.after(0,
                        lambda msg=m: self._var_prog_msg.set(msg)),
                )

                # 2. Carregar DDA automaticamente
                dda_result = carregar_pasta_dda(
                    base_path=self._caminhos["base"],
                    banco_path=banco_path,
                    callback_progresso=lambda m: self.after(0,
                        lambda msg=m: self._var_prog_msg.set(msg)),
                )

                self.after(0, self._criacao_ok, nome_banco, banco_path,
                           importadas, dda_result)

            except Exception as e:
                self.after(0, self._criacao_erro, str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _criacao_ok(self, nome: str, banco_path: str,
                    importadas: list[str], dda_result: dict):
        self._progress.stop()
        self._btn_criar.config(state="normal")
        self._banco_atual_path = banco_path
        self._var_prog_msg.set(f"{len(importadas)} entidade(s) BDGD + "
                               f"{len(dda_result['importadas'])} DDA importada(s) ✓")
        self._status_var.set(f"Banco criado: {nome}")

        # Atualizar listas
        self._atualizar_combo_bancos()
        self._atualizar_tabelas_banco_path(banco_path)

        # Montar mensagem final
        linhas = [
            f"Banco '{nome}' criado/atualizado.",
            f"  • {len(importadas)} entidade(s) BDGD importada(s).",
        ]

        dda_ok  = len(dda_result["importadas"])
        dda_err = len(dda_result["erros"])

        if dda_result["dda_existe"]:
            linhas.append(f"  • {dda_ok} tabela(s) DDA importada(s)" +
                          (f" ({dda_err} erro(s))." if dda_err else "."))
        else:
            # DDA ausente — aviso informativo (opção 2 do spec: modal sutil)
            linhas.append(
                "\n⚠  Pasta 'DDA' não localizada no diretório raiz.\n"
                "Algumas consultas analíticas pré-definidas podem não\n"
                "funcionar corretamente até que as tabelas sejam\n"
                "importadas manualmente."
            )

        messagebox.showinfo("Banco criado", "\n".join(linhas))

    def _criacao_erro(self, msg: str):
        self._progress.stop()
        self._btn_criar.config(state="normal")
        self._var_prog_msg.set("Erro na criação.")
        self._status_var.set("Erro ao criar banco.")
        messagebox.showerror("Erro", msg)

    # ------------------------------------------------------------------
    # Lógica: DDA
    # ------------------------------------------------------------------

    def _verificar_dda_status(self):
        info = verificar_dda(self._caminhos["base"])

        self._lb_dda.delete(0, tk.END)

        if info["existe"]:
            self._var_badge_dda.set(f"✔  {len(info['arquivos'])} arquivo(s)")
            self._lbl_badge_dda.config(bg=CORES["sucesso"])
            for arq in info["arquivos"]:
                self._lb_dda.insert(tk.END, f"  {arq}")
            if not info["arquivos"]:
                self._lb_dda.insert(tk.END, "  (pasta vazia)")
        else:
            self._var_badge_dda.set("⚠  Não encontrada")
            self._lbl_badge_dda.config(bg=CORES["aviso"])
            self._lb_dda.insert(
                tk.END, "  Crie a pasta DDA/ ao lado do app.py"
            )
            self._lb_dda.insert(
                tk.END, "  e adicione arquivos .xlsx/.csv."
            )

    # ------------------------------------------------------------------
    # Lógica: importação de arquivo externo
    # ------------------------------------------------------------------

    def _atualizar_combo_bancos(self):
        bancos = listar_bancos(self._caminhos["duckdb"])
        self._combo_banco_imp["values"] = bancos
        if bancos and not self._var_banco_imp.get():
            self._combo_banco_imp.set(bancos[0])

    def _selecionar_arquivo_imp(self):
        path = filedialog.askopenfilename(
            title="Selecionar arquivo para importar",
            filetypes=[
                ("Planilhas", "*.xlsx *.csv"),
                ("Excel", "*.xlsx"),
                ("CSV", "*.csv"),
                ("Todos", "*.*"),
            ],
        )
        if not path:
            return

        self._arquivo_imp_path = path
        nome = Path(path).name
        tabela = Path(path).stem
        self._var_arquivo_imp.set(f"{nome}  →  tabela: '{tabela}'")
        self._btn_importar.config(state="normal")

    def _importar_arquivo(self):
        banco = self._var_banco_imp.get()
        if not banco:
            messagebox.showwarning("Aviso", "Selecione o banco de destino.")
            return

        arq_path = getattr(self, "_arquivo_imp_path", None)
        if not arq_path or not os.path.exists(arq_path):
            messagebox.showwarning("Aviso", "Selecione um arquivo válido.")
            return

        banco_path = os.path.join(self._caminhos["duckdb"], banco)
        tabela     = Path(arq_path).stem

        self._btn_importar.config(state="disabled")
        self._progress.start(10)
        self._var_prog_msg.set(f"Importando '{tabela}'...")

        def _worker():
            try:
                nome = importar_arquivo_para_banco(
                    arquivo_path=arq_path,
                    banco_path=banco_path,
                    callback_progresso=lambda m: self.after(0,
                        lambda msg=m: self._var_prog_msg.set(msg)),
                )
                self.after(0, self._importacao_ok, nome, banco_path)
            except Exception as e:
                self.after(0, self._importacao_erro, str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _importacao_ok(self, nome_tabela: str, banco_path: str):
        self._progress.stop()
        self._btn_importar.config(state="normal")
        self._var_prog_msg.set(f"Tabela '{nome_tabela}' importada ✓")
        self._status_var.set(f"Tabela '{nome_tabela}' importada com sucesso.")
        self._atualizar_tabelas_banco_path(banco_path)
        messagebox.showinfo("Sucesso", f"Tabela '{nome_tabela}' criada no banco.")

    def _importacao_erro(self, msg: str):
        self._progress.stop()
        self._btn_importar.config(state="normal")
        self._var_prog_msg.set("Erro na importação.")
        messagebox.showerror("Erro na importação", msg)

    # ------------------------------------------------------------------
    # Lógica: painel de tabelas existentes no banco
    # ------------------------------------------------------------------

    def _atualizar_tabelas_banco(self):
        banco = self._var_banco_imp.get()
        if not banco:
            return
        banco_path = os.path.join(self._caminhos["duckdb"], banco)
        self._atualizar_tabelas_banco_path(banco_path)

    def _atualizar_tabelas_banco_path(self, banco_path: str):
        self._lb_tabelas.delete(0, tk.END)
        try:
            tabelas = listar_tabelas_banco(banco_path)
            for t in tabelas:
                self._lb_tabelas.insert(tk.END, f"  {t}")
            if not tabelas:
                self._lb_tabelas.insert(tk.END, "  (banco vazio)")
        except Exception:
            self._lb_tabelas.insert(tk.END, "  Erro ao ler tabelas")

    # ------------------------------------------------------------------
    # Chamado externamente (app.py)
    # ------------------------------------------------------------------

    def atualizar_zips(self):
        """Recarrega ZIPs disponíveis e verifica DDA ao navegar para a aba."""
        self._atualizar_lista_zips()
        self._verificar_dda_status()
