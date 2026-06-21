# -*- coding: utf-8 -*-
"""
ui/aba_extracao.py
Aba de extração / download de BDGDs da ANEEL.
"""

import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from core.extrator import carregar_lista_bdgds, baixar_bdgd, listar_bdgds_baixadas
from ui.tema import CORES, FONTES


class AbaExtracao(ttk.Frame):
    """
    Painel com:
      - Campo de pesquisa com filtragem em tempo real
      - Listbox rolável com todas as BDGDs disponíveis
      - Contador de resultados filtrados
      - Botão de download com barra de progresso
      - Lista de arquivos já baixados
    """

    def __init__(self, parent, caminhos: dict, status_var: tk.StringVar):
        super().__init__(parent, style="TFrame")
        self._caminhos = caminhos
        self._status_var = status_var
        self._bdgd_dict: dict[str, str] = {}
        self._titulos_filtrados: list[str] = []

        self._build()
        self._carregar_lista()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self):
        C = CORES
        F = FONTES

        # Título
        tk.Label(
            self, text="Extração de BDGDs — ANEEL",
            bg=C["bg_app"], fg=C["texto"],
            font=F["titulo_aba"], anchor="w",
        ).pack(fill="x", padx=24, pady=(20, 2))

        tk.Label(
            self, text="Conecta à API ArcGIS da ANEEL e realiza o download automatizado.",
            bg=C["bg_app"], fg=C["texto_sec"],
            font=F["pequeno"], anchor="w",
        ).pack(fill="x", padx=24, pady=(0, 16))

        # ── Layout de duas colunas ────────────────────────────────────
        cols = tk.Frame(self, bg=C["bg_app"])
        cols.pack(fill="both", expand=True, padx=24, pady=0)

        cols.columnconfigure(0, weight=3)
        cols.columnconfigure(1, weight=1, minsize=260)

        # ── Coluna esquerda: seleção ──────────────────────────────────
        esq = tk.Frame(cols, bg=C["bg_card"], bd=0)
        esq.grid(row=0, column=0, sticky="nsew", padx=(0, 12), pady=0)

        tk.Label(
            esq, text="BASES DISPONÍVEIS",
            bg=C["bg_card"], fg=C["acento"],
            font=F["badge"], anchor="w",
        ).pack(fill="x", padx=14, pady=(14, 4))

        # Busca
        frame_busca = tk.Frame(esq, bg=C["bg_input"], height=34)
        frame_busca.pack(fill="x", padx=14, pady=(0, 8))
        frame_busca.pack_propagate(False)

        tk.Label(
            frame_busca, text="🔍",
            bg=C["bg_input"], fg=C["texto_sec"],
            font=("Segoe UI", 10),
        ).pack(side="left", padx=(8, 4))

        self._var_busca = tk.StringVar()
        self._var_busca.trace_add("write", self._filtrar)

        entry = tk.Entry(
            frame_busca,
            textvariable=self._var_busca,
            bg=C["bg_input"], fg=C["texto"],
            insertbackground=C["acento"],
            relief="flat", bd=0,
            font=F["corpo"],
        )
        entry.pack(side="left", fill="both", expand=True, pady=4, padx=(0, 8))

        # Contador
        self._var_contador = tk.StringVar(value="0 bases")
        tk.Label(
            esq, textvariable=self._var_contador,
            bg=C["bg_card"], fg=C["texto_sec"],
            font=F["pequeno"], anchor="e",
        ).pack(fill="x", padx=14, pady=(0, 4))

        # Listbox + scroll
        frame_lista = tk.Frame(esq, bg=C["bg_card"])
        frame_lista.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        scroll = tk.Scrollbar(frame_lista, orient="vertical",
                              bg=C["bg_painel"], troughcolor=C["bg_app"])
        scroll.pack(side="right", fill="y")

        self._listbox = tk.Listbox(
            frame_lista,
            yscrollcommand=scroll.set,
            selectmode="single",
            activestyle="none",
            bg=C["bg_input"], fg=C["texto"],
            selectbackground=C["acento_escuro"],
            selectforeground=C["texto"],
            font=F["corpo"],
            relief="flat", bd=0,
            highlightthickness=0,
        )
        self._listbox.pack(side="left", fill="both", expand=True)
        scroll.config(command=self._listbox.yview)

        self._listbox.bind("<<ListboxSelect>>", self._on_selecionar)

        # ── Coluna direita: ações + baixadas ─────────────────────────
        dir_ = tk.Frame(cols, bg=C["bg_app"])
        dir_.grid(row=0, column=1, sticky="nsew")

        # Card: seleção atual
        card_sel = tk.Frame(dir_, bg=C["bg_card"], bd=0)
        card_sel.pack(fill="x", pady=(0, 12))

        tk.Label(
            card_sel, text="SELECIONADA",
            bg=C["bg_card"], fg=C["acento"],
            font=F["badge"], anchor="w",
        ).pack(fill="x", padx=14, pady=(14, 4))

        self._var_selecionada = tk.StringVar(value="—")
        tk.Label(
            card_sel, textvariable=self._var_selecionada,
            bg=C["bg_card"], fg=C["texto"],
            font=F["pequeno"], wraplength=220, justify="left", anchor="w",
        ).pack(fill="x", padx=14, pady=(0, 14))

        # Botão download
        self._btn_download = tk.Button(
            dir_,
            text="⬇  Baixar BDGD",
            command=self._iniciar_download,
            bg=C["acento"], fg=C["bg_app"],
            font=F["botao"], relief="flat", bd=0,
            cursor="hand2", padx=12, pady=8,
            activebackground=C["acento_hover"],
            activeforeground=C["bg_app"],
        )
        self._btn_download.pack(fill="x", pady=(0, 10))

        # Barra de progresso
        self._progress = ttk.Progressbar(
            dir_, mode="indeterminate", style="TProgressbar"
        )
        self._progress.pack(fill="x", pady=(0, 6))

        self._var_prog_msg = tk.StringVar(value="")
        tk.Label(
            dir_, textvariable=self._var_prog_msg,
            bg=C["bg_app"], fg=C["texto_sec"],
            font=F["status"], anchor="w",
        ).pack(fill="x", pady=(0, 16))

        # Card: arquivos já baixados
        card_baixadas = tk.Frame(dir_, bg=C["bg_card"])
        card_baixadas.pack(fill="both", expand=True)

        tk.Label(
            card_baixadas, text="JÁ BAIXADAS",
            bg=C["bg_card"], fg=C["acento"],
            font=F["badge"], anchor="w",
        ).pack(fill="x", padx=14, pady=(14, 4))

        frame_lb2 = tk.Frame(card_baixadas, bg=C["bg_card"])
        frame_lb2.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        sc2 = tk.Scrollbar(frame_lb2, orient="vertical",
                           bg=C["bg_painel"], troughcolor=C["bg_app"])
        sc2.pack(side="right", fill="y")

        self._lb_baixadas = tk.Listbox(
            frame_lb2,
            yscrollcommand=sc2.set,
            bg=C["bg_input"], fg=C["texto_sec"],
            font=F["pequeno"],
            relief="flat", bd=0,
            highlightthickness=0,
        )
        self._lb_baixadas.pack(side="left", fill="both", expand=True)
        sc2.config(command=self._lb_baixadas.yview)

        self._atualizar_baixadas()

    # ------------------------------------------------------------------
    # Lógica
    # ------------------------------------------------------------------

    def _carregar_lista(self):
        excel_path = self._caminhos["excel"]
        try:
            self._bdgd_dict = carregar_lista_bdgds(excel_path)
            self._titulos_filtrados = sorted(self._bdgd_dict.keys())
            self._popular_listbox(self._titulos_filtrados)
        except Exception as e:
            messagebox.showerror("Erro ao carregar lista", str(e))

    def _filtrar(self, *_):
        termo = self._var_busca.get().strip().lower()
        if termo:
            self._titulos_filtrados = [
                t for t in sorted(self._bdgd_dict.keys()) if termo in t.lower()
            ]
        else:
            self._titulos_filtrados = sorted(self._bdgd_dict.keys())
        self._popular_listbox(self._titulos_filtrados)

    def _popular_listbox(self, titulos: list[str]):
        self._listbox.delete(0, tk.END)
        for t in titulos:
            self._listbox.insert(tk.END, f"  {t}")
        self._var_contador.set(f"{len(titulos)} base(s)")

    def _on_selecionar(self, *_):
        sel = self._listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        titulo = self._titulos_filtrados[idx]
        self._var_selecionada.set(titulo)

    def _iniciar_download(self):
        titulo = self._var_selecionada.get()
        if titulo == "—" or not titulo:
            messagebox.showwarning("Aviso", "Selecione uma BDGD na lista.")
            return

        bdgd_id = self._bdgd_dict.get(titulo)
        if not bdgd_id:
            messagebox.showerror("Erro", "ID não encontrado para a BDGD selecionada.")
            return

        self._btn_download.config(state="disabled")
        self._progress.start(12)
        self._var_prog_msg.set("Iniciando...")
        self._status_var.set(f"Baixando: {titulo}...")

        def _worker():
            try:
                baixar_bdgd(
                    bdgd_id=bdgd_id,
                    titulo=titulo,
                    save_path=self._caminhos["bdgds"],
                    callback_progresso=lambda msg: self._var_prog_msg.set(msg),
                )
                self.after(0, self._download_ok, titulo)
            except Exception as e:
                self.after(0, self._download_erro, str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _download_ok(self, titulo: str):
        self._progress.stop()
        self._btn_download.config(state="normal")
        self._var_prog_msg.set("Download concluído ✓")
        self._status_var.set(f"Download concluído: {titulo}")
        self._atualizar_baixadas()
        messagebox.showinfo("Sucesso", f"BDGD baixada com sucesso:\n{titulo}.zip")

    def _download_erro(self, msg: str):
        self._progress.stop()
        self._btn_download.config(state="normal")
        self._var_prog_msg.set("Erro no download.")
        self._status_var.set("Erro no download.")
        messagebox.showerror("Erro no download", msg)

    def _atualizar_baixadas(self):
        self._lb_baixadas.delete(0, tk.END)
        baixadas = listar_bdgds_baixadas(self._caminhos["bdgds"])
        for b in baixadas:
            self._lb_baixadas.insert(tk.END, f"  {b}")
