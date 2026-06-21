# -*- coding: utf-8 -*-
"""
ui/aba_mapas.py
Aba de geração e gestão de mapas georreferenciados da rede BDGD.

FLUXO
-----
1. Combobox lista os GDBs disponíveis em "BDGDs Extraídas/"
2. Painel de status mostra se o mapa já existe (data, tamanho)
3. "Gerar Mapa" roda o pipeline em thread separada com log em tempo real
4. "Abrir no Navegador" abre o HTML com webbrowser.open()

NOTA SOBRE RENDERIZAÇÃO
------------------------
O mapa NÃO é embutido no Tkinter — abre no browser padrão do sistema.
Isso garante aceleração de hardware (WebGL/Canvas) e todos os recursos
interativos do Leaflet.js sem limitações de memória ou compatibilidade.
"""

import os
import threading
import webbrowser
import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from core.mapas import (
    listar_gdbs_disponiveis,
    mapa_existe,
    gerar_mapa,
    PASTA_MAPAS,
)
from ui.tema import CORES, FONTES


class AbaMapas(ttk.Frame):

    def __init__(self, parent, caminhos: dict, status_var: tk.StringVar):
        super().__init__(parent, style="TFrame")
        self._caminhos   = caminhos
        self._status_var = status_var

        # Estado
        self._gdb_map: dict[str, str] = {}   # nome → gdb_path
        self._gdb_sel: str | None     = None
        self._html_path: str | None   = None
        self._cancelar = threading.Event()

        self._build()
        self._atualizar_lista()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self):
        C = CORES
        F = FONTES

        # Título
        tk.Label(
            self, text="Mapas — Rede Georreferenciada",
            bg=C["bg_app"], fg=C["texto"],
            font=F["titulo_aba"], anchor="w",
        ).pack(fill="x", padx=24, pady=(20, 2))

        tk.Label(
            self,
            text=(
                "Gera mapas interativos HTML da rede MT a partir das BDGDs extraídas. "
                "O mapa é aberto no navegador padrão do sistema."
            ),
            bg=C["bg_app"], fg=C["texto_sec"],
            font=F["pequeno"], anchor="w", wraplength=1000,
        ).pack(fill="x", padx=24, pady=(0, 14))

        # ── Corpo 2 colunas ──────────────────────────────────────────
        corpo = tk.Frame(self, bg=C["bg_app"])
        corpo.pack(fill="both", expand=True, padx=24, pady=(0, 8))
        corpo.columnconfigure(0, weight=1)
        corpo.columnconfigure(1, weight=2)

        self._build_col_esq(corpo)
        self._build_col_dir(corpo)

        # Barra de progresso global
        self._progress = ttk.Progressbar(
            self, mode="indeterminate", style="TProgressbar"
        )
        self._progress.pack(fill="x", padx=24, pady=(0, 3))

        self._var_prog_msg = tk.StringVar(value="")
        tk.Label(
            self, textvariable=self._var_prog_msg,
            bg=C["bg_app"], fg=C["texto_sec"],
            font=F["status"], anchor="w",
        ).pack(fill="x", padx=24, pady=(0, 8))

    # ------------------------------------------------------------------
    # Coluna esquerda: seleção + ações
    # ------------------------------------------------------------------

    def _build_col_esq(self, parent):
        C = CORES
        F = FONTES

        esq = tk.Frame(parent, bg=C["bg_card"])
        esq.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        tk.Label(esq, text="BDGD DISPONÍVEL", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(padx=14, pady=(14, 6), anchor="w")

        # Combobox de GDBs
        self._var_gdb = tk.StringVar()
        self._combo_gdb = ttk.Combobox(
            esq, textvariable=self._var_gdb, state="readonly", width=38
        )
        self._combo_gdb.pack(fill="x", padx=14, pady=(0, 6))
        self._combo_gdb.bind("<<ComboboxSelected>>", self._on_gdb_selecionado)

        # Botão selecionar GDB manualmente
        tk.Button(
            esq, text="📁  Selecionar .gdb manualmente",
            command=self._selecionar_gdb_manual,
            bg=C["bg_input"], fg=C["texto"],
            font=F["botao"], relief="flat", bd=0,
            padx=10, pady=5, cursor="hand2",
            activebackground=C["bg_hover"], activeforeground=C["acento"],
        ).pack(fill="x", padx=14, pady=(0, 8))

        tk.Button(
            esq, text="↺  Atualizar lista",
            command=self._atualizar_lista,
            bg=C["bg_input"], fg=C["texto"],
            font=F["botao"], relief="flat", bd=0,
            padx=10, pady=5, cursor="hand2",
            activebackground=C["bg_hover"], activeforeground=C["acento"],
        ).pack(fill="x", padx=14, pady=(0, 8))

        tk.Frame(esq, bg=C["borda"], height=1).pack(fill="x", padx=14, pady=8)

        # Card de status do mapa
        tk.Label(esq, text="STATUS DO MAPA", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(padx=14, pady=(0, 6), anchor="w")

        card_status = tk.Frame(esq, bg=C["bg_painel"])
        card_status.pack(fill="x", padx=14, pady=(0, 10))

        for var_attr, label in [
            ("_var_stat_existe", "Gerado"),
            ("_var_stat_data",   "Data"),
            ("_var_stat_tam",    "Tamanho"),
        ]:
            fr = tk.Frame(card_status, bg=C["bg_painel"])
            fr.pack(fill="x", padx=10, pady=3)
            tk.Label(fr, text=label + ":",
                     bg=C["bg_painel"], fg=C["texto_sec"],
                     font=F["pequeno"], width=10, anchor="w").pack(side="left")
            var = tk.StringVar(value="—")
            setattr(self, var_attr, var)
            tk.Label(fr, textvariable=var,
                     bg=C["bg_painel"], fg=C["texto"],
                     font=F["corpo_bold"], anchor="w").pack(side="left")

        tk.Frame(esq, bg=C["borda"], height=1).pack(fill="x", padx=14, pady=8)

        # Botões de ação
        self._btn_gerar = tk.Button(
            esq,
            text="🗺  Gerar Mapa",
            command=self._iniciar_geracao,
            bg=C["acento"], fg=C["bg_app"],
            font=F["botao"], relief="flat", bd=0,
            padx=14, pady=9, cursor="hand2",
            state="disabled",
            activebackground=C["acento_hover"],
            activeforeground=C["bg_app"],
        )
        self._btn_gerar.pack(fill="x", padx=14, pady=(0, 6))

        self._btn_cancelar = tk.Button(
            esq,
            text="⏹  Cancelar",
            command=self._cancelar_geracao,
            bg=C["erro"], fg=C["texto"],
            font=F["botao"], relief="flat", bd=0,
            padx=14, pady=7, cursor="hand2",
            state="disabled",
            activebackground="#FF7070",
        )
        self._btn_cancelar.pack(fill="x", padx=14, pady=(0, 6))

        self._btn_abrir = tk.Button(
            esq,
            text="🌐  Abrir no Navegador",
            command=self._abrir_no_navegador,
            bg=C["bg_input"], fg=C["texto"],
            font=F["botao"], relief="flat", bd=0,
            padx=10, pady=7, cursor="hand2",
            state="disabled",
            activebackground=C["bg_hover"], activeforeground=C["acento"],
        )
        self._btn_abrir.pack(fill="x", padx=14, pady=(0, 14))

        # Mapas já gerados
        tk.Frame(esq, bg=C["borda"], height=1).pack(fill="x", padx=14, pady=(0, 8))

        tk.Label(esq, text="MAPAS GERADOS", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(padx=14, pady=(0, 4), anchor="w")

        frame_lb = tk.Frame(esq, bg=C["bg_card"])
        frame_lb.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        sc = tk.Scrollbar(frame_lb, orient="vertical",
                          bg=C["bg_painel"], troughcolor=C["bg_app"])
        sc.pack(side="right", fill="y")

        self._lb_gerados = tk.Listbox(
            frame_lb,
            yscrollcommand=sc.set, activestyle="none",
            bg=C["bg_input"], fg=C["texto_sec"],
            font=F["pequeno"], relief="flat", bd=0,
            highlightthickness=0,
        )
        self._lb_gerados.pack(side="left", fill="both", expand=True)
        sc.config(command=self._lb_gerados.yview)
        self._lb_gerados.bind("<Double-Button-1>", self._abrir_selecionado_da_lista)

    # ------------------------------------------------------------------
    # Coluna direita: log
    # ------------------------------------------------------------------

    def _build_col_dir(self, parent):
        C = CORES
        F = FONTES

        dir_ = tk.Frame(parent, bg=C["bg_card"])
        dir_.grid(row=0, column=1, sticky="nsew")

        hdr = tk.Frame(dir_, bg=C["bg_card"])
        hdr.pack(fill="x", padx=14, pady=(14, 4))

        tk.Label(hdr, text="LOG DE GERAÇÃO", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(side="left")

        tk.Button(
            hdr, text="Limpar",
            command=self._limpar_log,
            bg=C["bg_input"], fg=C["texto_sec"],
            font=F["pequeno"], relief="flat", bd=0,
            padx=6, pady=2, cursor="hand2",
        ).pack(side="right")

        frame_log = tk.Frame(dir_, bg=C["bg_card"])
        frame_log.pack(fill="both", expand=True, padx=14, pady=(0, 10))

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

        # Card de instruções
        card_info = tk.Frame(dir_, bg=C["bg_painel"])
        card_info.pack(fill="x", padx=14, pady=(0, 14))

        tk.Label(card_info,
                 text=(
                     "ℹ  O mapa é gerado como arquivo HTML e aberto no navegador.\n"
                     "   Requis.: folium, geopandas, shapely, branca\n"
                     "   Camada UNTRMT aparece somente em zoom ≥ 15."
                 ),
                 bg=C["bg_painel"], fg=C["texto_desab"],
                 font=F["pequeno"], justify="left", wraplength=480,
                 ).pack(padx=12, pady=8, anchor="w")

    # ------------------------------------------------------------------
    # Lógica
    # ------------------------------------------------------------------

    def _atualizar_lista(self):
        gdbs = listar_gdbs_disponiveis(self._caminhos["base"])
        self._gdb_map = {g["nome"]: g["gdb_path"] for g in gdbs}
        nomes = list(self._gdb_map.keys())
        self._combo_gdb["values"] = nomes

        if nomes:
            self._combo_gdb.set(nomes[0])
            self._on_gdb_selecionado()

        self._atualizar_lista_gerados()

    def _on_gdb_selecionado(self, *_):
        nome = self._var_gdb.get()
        if not nome:
            return
        self._gdb_sel = nome
        self._btn_gerar.config(state="normal")
        self._atualizar_status(nome)

    def _atualizar_status(self, nome_bdgd: str):
        info = mapa_existe(self._caminhos["base"], nome_bdgd)
        if info["existe"]:
            self._var_stat_existe.set("✔ Sim")
            self._var_stat_data.set(info["data"])
            self._var_stat_tam.set(f"{info['tamanho_mb']} MB")
            self._html_path = info["html"]
            self._btn_abrir.config(state="normal")
        else:
            self._var_stat_existe.set("✗ Não gerado")
            self._var_stat_data.set("—")
            self._var_stat_tam.set("—")
            self._html_path = None
            self._btn_abrir.config(state="disabled")

    def _atualizar_lista_gerados(self):
        self._lb_gerados.delete(0, tk.END)
        pasta_base = os.path.join(self._caminhos["base"], PASTA_MAPAS)
        if not os.path.exists(pasta_base):
            return
        for subdir in sorted(os.listdir(pasta_base)):
            html = os.path.join(pasta_base, subdir, "mapa_rede.html")
            if os.path.exists(html):
                tam = round(os.path.getsize(html) / 1_048_576, 1)
                self._lb_gerados.insert(tk.END, f"  {subdir}  ({tam} MB)")

    def _selecionar_gdb_manual(self):
        path = filedialog.askdirectory(title="Selecionar pasta .gdb")
        if not path:
            return
        if not path.lower().endswith(".gdb"):
            messagebox.showwarning("Aviso", "A pasta selecionada não tem extensão .gdb.")
            return
        nome = os.path.splitext(os.path.basename(path))[0]
        self._gdb_map[nome] = path
        valores = list(self._combo_gdb["values"]) + [nome]
        self._combo_gdb["values"] = valores
        self._combo_gdb.set(nome)
        self._gdb_sel = nome
        self._btn_gerar.config(state="normal")
        self._atualizar_status(nome)

    # ------------------------------------------------------------------
    # Geração
    # ------------------------------------------------------------------

    def _iniciar_geracao(self):
        nome = self._gdb_sel
        if not nome:
            messagebox.showwarning("Aviso", "Selecione uma BDGD.")
            return

        gdb_path = self._gdb_map.get(nome)
        if not gdb_path or not os.path.isdir(gdb_path):
            messagebox.showerror("Erro", f"Pasta .gdb não encontrada:\n{gdb_path}")
            return

        # Checar se já existe e perguntar se quer regerar
        info = mapa_existe(self._caminhos["base"], nome)
        if info["existe"]:
            resp = messagebox.askyesno(
                "Mapa já existe",
                f"O mapa de '{nome}' já foi gerado ({info['data']}).\n"
                "Deseja regenerar? O arquivo anterior será substituído.",
            )
            if not resp:
                return

        self._cancelar.clear()
        self._btn_gerar.config(state="disabled")
        self._btn_cancelar.config(state="normal")
        self._btn_abrir.config(state="disabled")
        self._progress.start(10)

        self._log(f"▶ Iniciando geração do mapa: {nome}", "info")
        self._log(f"  GDB: {gdb_path}", "info")

        def _worker():
            try:
                html = gerar_mapa(
                    gdb_path=gdb_path,
                    base_path=self._caminhos["base"],
                    nome_bdgd=nome,
                    cancelar_flag=self._cancelar,
                    callback=lambda m: self.after(0, lambda msg=m: self._log(msg)),
                )
                self.after(0, self._geracao_ok, html, nome)
            except InterruptedError:
                self.after(0, self._geracao_cancelada)
            except Exception as e:
                self.after(0, self._geracao_erro, str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _cancelar_geracao(self):
        self._cancelar.set()
        self._log("⚠ Cancelamento solicitado...", "aviso")
        self._btn_cancelar.config(state="disabled")

    def _geracao_ok(self, html: str, nome: str):
        self._progress.stop()
        self._btn_gerar.config(state="normal")
        self._btn_cancelar.config(state="disabled")
        self._html_path = html
        self._btn_abrir.config(state="normal")
        self._var_prog_msg.set("")
        self._atualizar_status(nome)
        self._atualizar_lista_gerados()
        self._log(f"✔ Mapa gerado com sucesso!", "ok")
        self._status_var.set(f"Mapa gerado: {nome}")

        resp = messagebox.askyesno(
            "Mapa gerado",
            f"Mapa '{nome}' gerado com sucesso.\n\nAbrir no navegador agora?",
        )
        if resp:
            self._abrir_no_navegador()

    def _geracao_cancelada(self):
        self._progress.stop()
        self._btn_gerar.config(state="normal")
        self._btn_cancelar.config(state="disabled")
        self._var_prog_msg.set("")
        self._log("Geração cancelada pelo usuário.", "aviso")

    def _geracao_erro(self, msg: str):
        self._progress.stop()
        self._btn_gerar.config(state="normal")
        self._btn_cancelar.config(state="disabled")
        self._var_prog_msg.set("")
        self._log(f"✗ Erro: {msg}", "erro")
        messagebox.showerror("Erro na geração", msg)

    def _abrir_no_navegador(self):
        if not self._html_path or not os.path.exists(self._html_path):
            messagebox.showwarning("Aviso", "Mapa não encontrado. Gere o mapa primeiro.")
            return
        webbrowser.open(f"file:///{self._html_path.replace(os.sep, '/')}")
        self._log(f"🌐 Abrindo no navegador: {self._html_path}", "info")

    def _abrir_selecionado_da_lista(self, *_):
        sel = self._lb_gerados.curselection()
        if not sel:
            return
        texto = self._lb_gerados.get(sel[0]).strip()
        nome  = texto.split("(")[0].strip()
        html  = os.path.join(self._caminhos["base"], PASTA_MAPAS, nome, "mapa_rede.html")
        if os.path.exists(html):
            webbrowser.open(f"file:///{html.replace(os.sep, '/')}")
        else:
            messagebox.showwarning("Aviso", f"Arquivo não encontrado:\n{html}")

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

    # ------------------------------------------------------------------
    # Chamado externamente (app.py)
    # ------------------------------------------------------------------

    def atualizar_mapas(self):
        """Recarrega a lista de GDBs e mapas gerados ao navegar para a aba."""
        self._atualizar_lista()
