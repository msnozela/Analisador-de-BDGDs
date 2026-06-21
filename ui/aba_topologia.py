# -*- coding: utf-8 -*-
"""
ui/aba_topologia.py
Aba de reconstrução topológica da rede elétrica (algoritmo BFS).

GERENCIAMENTO DE CONEXÃO
------------------------
Esta aba possui um GerenciadorConexao próprio que mantém UMA ÚNICA
conexão read/write com o banco selecionado. Todas as operações
(listar alimentadores, verificar entidades, executar BFS, salvar resultado)
utilizam essa mesma conexão — eliminando o erro:
    "Can't open a connection to same database file with a different configuration"
"""

import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from core.topologia import (
    GerenciadorConexao,
    listar_alimentadores,
    verificar_entidades,
    rodar_bfs_lista,
    TABELA_TOPOLOGIA,
)
from core.banco import listar_bancos
from ui.tema import CORES, FONTES


class AbaTopologia(ttk.Frame):

    def __init__(self, parent, caminhos: dict, status_var: tk.StringVar):
        super().__init__(parent, style="TFrame")
        self._caminhos   = caminhos
        self._status_var = status_var

        # Gerenciador de conexão exclusivo desta aba
        self._gc = GerenciadorConexao()

        # Flag de cancelamento (threading.Event)
        self._cancelar = threading.Event()

        # Dados em memória
        self._alimentadores: list[str] = []
        self._df_resultado = None

        self._build()
        self._atualizar_lista_bancos()

    # ------------------------------------------------------------------
    # Destruição — garantir fechamento da conexão
    # ------------------------------------------------------------------

    def destroy(self):
        self._gc.fechar()
        super().destroy()

    # ------------------------------------------------------------------
    # Build da interface
    # ------------------------------------------------------------------

    def _build(self):
        C = CORES
        F = FONTES

        # Título
        tk.Label(
            self, text="Topologia da Rede Elétrica",
            bg=C["bg_app"], fg=C["texto"],
            font=F["titulo_aba"], anchor="w",
        ).pack(fill="x", padx=24, pady=(20, 2))

        tk.Label(
            self,
            text=(
                "Reconstrói a estrutura elétrica pai-filho via BFS (Busca em Largura) "
                "e persiste o resultado na tabela TOPOLOGIA do banco DuckDB."
            ),
            bg=C["bg_app"], fg=C["texto_sec"],
            font=F["pequeno"], anchor="w", wraplength=900,
        ).pack(fill="x", padx=24, pady=(0, 16))

        # ── Layout 2 colunas ─────────────────────────────────────────
        corpo = tk.Frame(self, bg=C["bg_app"])
        corpo.pack(fill="both", expand=True, padx=24)
        corpo.columnconfigure(0, weight=1)
        corpo.columnconfigure(1, weight=2)

        # ── Coluna esquerda: painel de configuração ───────────────────
        esq = tk.Frame(corpo, bg=C["bg_card"])
        esq.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        tk.Label(esq, text="CONFIGURAÇÃO", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(padx=14, pady=(14, 8), anchor="w")

        # Seleção de banco
        tk.Label(esq, text="Banco DuckDB:", bg=C["bg_card"],
                 fg=C["texto_sec"], font=F["pequeno"]).pack(padx=14, anchor="w")

        self._var_banco = tk.StringVar()
        self._combo_banco = ttk.Combobox(
            esq, textvariable=self._var_banco, state="readonly", width=40
        )
        self._combo_banco.pack(fill="x", padx=14, pady=(2, 8))
        self._combo_banco.bind("<<ComboboxSelected>>", self._on_banco_selecionado)

        # Botão carregar (também funciona sem evento de combo)
        self._btn_carregar = tk.Button(
            esq, text="↺  Carregar alimentadores",
            command=self._on_banco_selecionado,
            bg=C["bg_input"], fg=C["texto"],
            font=F["botao"], relief="flat", bd=0,
            padx=10, pady=5, cursor="hand2",
            activebackground=C["bg_hover"], activeforeground=C["acento"],
        )
        self._btn_carregar.pack(fill="x", padx=14, pady=(0, 8))

        # Status de conexão
        self._var_status_con = tk.StringVar(value="● Desconectado")
        self._lbl_con = tk.Label(
            esq, textvariable=self._var_status_con,
            bg=C["bg_card"], fg=C["erro"], font=F["pequeno"],
        )
        self._lbl_con.pack(padx=14, anchor="w", pady=(0, 4))

        # Entidades disponíveis
        self._var_entidades_ok = tk.StringVar(value="")
        tk.Label(
            esq, textvariable=self._var_entidades_ok,
            bg=C["bg_card"], fg=C["texto_sec"],
            font=F["pequeno"], wraplength=220, justify="left",
        ).pack(padx=14, anchor="w", pady=(0, 8))

        tk.Frame(esq, bg=C["borda"], height=1).pack(fill="x", padx=14, pady=6)

        # Modo de execução
        tk.Label(esq, text="MODO DE EXECUÇÃO", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(padx=14, pady=(6, 8), anchor="w")

        self._var_modo = tk.StringVar(value="todos")

        frame_modo = tk.Frame(esq, bg=C["bg_card"])
        frame_modo.pack(fill="x", padx=14, pady=(0, 8))

        for texto, valor in [
            ("Todos os alimentadores", "todos"),
            ("Alimentador específico", "um"),
        ]:
            tk.Radiobutton(
                frame_modo, text=texto,
                variable=self._var_modo, value=valor,
                command=self._on_modo_changed,
                bg=C["bg_card"], fg=C["texto"],
                selectcolor=C["bg_input"],
                activebackground=C["bg_card"],
                activeforeground=C["acento"],
                font=F["corpo"],
            ).pack(anchor="w", pady=2)

        # Combobox de alimentador específico
        tk.Label(esq, text="Alimentador (CTMT):", bg=C["bg_card"],
                 fg=C["texto_sec"], font=F["pequeno"]).pack(padx=14, anchor="w")

        self._var_alim = tk.StringVar()
        self._combo_alim = ttk.Combobox(
            esq, textvariable=self._var_alim,
            state="disabled", width=40,
        )
        self._combo_alim.pack(fill="x", padx=14, pady=(2, 14))

        tk.Frame(esq, bg=C["borda"], height=1).pack(fill="x", padx=14, pady=6)

        # Botão executar BFS
        self._btn_exec = tk.Button(
            esq,
            text="▶  Executar BFS",
            command=self._executar,
            bg=C["acento"], fg=C["bg_app"],
            font=F["botao"], relief="flat", bd=0,
            padx=14, pady=9, cursor="hand2",
            state="disabled",
            activebackground=C["acento_hover"],
            activeforeground=C["bg_app"],
        )
        self._btn_exec.pack(fill="x", padx=14, pady=(8, 6))

        # Botão cancelar
        self._btn_cancelar = tk.Button(
            esq,
            text="⏹  Cancelar execução",
            command=self._cancelar_execucao,
            bg=C["erro"], fg=C["texto"],
            font=F["botao"], relief="flat", bd=0,
            padx=14, pady=7, cursor="hand2",
            state="disabled",
            activebackground="#FF7070",
        )
        self._btn_cancelar.pack(fill="x", padx=14, pady=(0, 6))

        # Botão exportar
        self._btn_exportar = tk.Button(
            esq, text="↓  Exportar resultado (.xlsx / .csv)",
            command=self._exportar,
            bg=C["bg_input"], fg=C["texto"],
            font=F["botao"], relief="flat", bd=0,
            padx=10, pady=6, cursor="hand2",
            state="disabled",
            activebackground=C["bg_hover"], activeforeground=C["acento"],
        )
        self._btn_exportar.pack(fill="x", padx=14, pady=(0, 14))

        # ── Coluna direita: log + stats ───────────────────────────────
        dir_ = tk.Frame(corpo, bg=C["bg_card"])
        dir_.grid(row=0, column=1, sticky="nsew")

        # Header do log
        hdr_log = tk.Frame(dir_, bg=C["bg_card"])
        hdr_log.pack(fill="x", padx=14, pady=(14, 4))

        tk.Label(hdr_log, text="LOG DE EXECUÇÃO", bg=C["bg_card"],
                 fg=C["acento"], font=F["badge"]).pack(side="left")

        tk.Button(
            hdr_log, text="Limpar log",
            command=self._limpar_log,
            bg=C["bg_input"], fg=C["texto_sec"],
            font=F["pequeno"], relief="flat", bd=0,
            padx=6, pady=2, cursor="hand2",
        ).pack(side="right")

        # Área de log
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

        # Cards de estatísticas
        card_stats = tk.Frame(dir_, bg=C["bg_painel"])
        card_stats.pack(fill="x", padx=14, pady=(0, 10))

        for var_attr, label in [
            ("_var_stat_alim",   "Alimentadores"),
            ("_var_stat_elem",   "Elementos"),
            ("_var_stat_status", "Status"),
        ]:
            frame_s = tk.Frame(card_stats, bg=C["bg_painel"])
            frame_s.pack(side="left", expand=True, padx=10, pady=10)
            var = tk.StringVar(value="—")
            setattr(self, var_attr, var)
            tk.Label(frame_s, textvariable=var,
                     bg=C["bg_painel"], fg=C["texto"],
                     font=("Segoe UI", 14, "bold")).pack()
            tk.Label(frame_s, text=label,
                     bg=C["bg_painel"], fg=C["texto_sec"],
                     font=F["badge"]).pack()

        # Barra de progresso
        self._progress = ttk.Progressbar(
            self, mode="indeterminate", style="TProgressbar"
        )
        self._progress.pack(fill="x", padx=24, pady=(0, 4))

        self._var_prog_msg = tk.StringVar(value="")
        tk.Label(
            self, textvariable=self._var_prog_msg,
            bg=C["bg_app"], fg=C["texto_sec"], font=F["status"], anchor="w",
        ).pack(fill="x", padx=24, pady=(0, 8))

    # ------------------------------------------------------------------
    # Gerenciamento de banco
    # ------------------------------------------------------------------

    def _atualizar_lista_bancos(self):
        bancos = listar_bancos(self._caminhos["duckdb"])
        self._combo_banco["values"] = bancos
        if bancos:
            self._combo_banco.set(bancos[0])

    def _on_banco_selecionado(self, *_):
        banco = self._var_banco.get()
        if not banco:
            messagebox.showwarning("Aviso", "Selecione um banco DuckDB.")
            return

        banco_path = os.path.join(self._caminhos["duckdb"], banco)

        self._log("Conectando ao banco...", "info")
        self._btn_carregar.config(state="disabled")
        self._btn_exec.config(state="disabled")

        def _worker():
            try:
                # Abre (ou reutiliza) conexão centralizada
                self._gc.abrir(banco_path)
                con = self._gc.conexao

                self.after(0, self._log, "Carregando alimentadores...", "info")

                alimentadores = listar_alimentadores(con)
                existentes, faltantes = verificar_entidades(con)

                self.after(
                    0, self._banco_carregado,
                    alimentadores, existentes, faltantes
                )

            except Exception as e:
                self.after(0, self._log, f"Erro: {e}", "erro")
                self.after(0, lambda: self._btn_carregar.config(state="normal"))

        threading.Thread(target=_worker, daemon=True).start()

    def _banco_carregado(
        self,
        alimentadores: list[str],
        existentes: list[str],
        faltantes: list[str],
    ):
        self._alimentadores = alimentadores
        self._combo_alim["values"] = alimentadores
        if alimentadores:
            self._combo_alim.set(alimentadores[0])

        self._var_stat_alim.set(str(len(alimentadores)))

        # Status de conexão
        self._var_status_con.set("● Conectado")
        self._lbl_con.config(fg=CORES["sucesso"])

        # Entidades
        if faltantes:
            msg = f"⚠ Faltando: {', '.join(faltantes)}"
            self._var_entidades_ok.set(msg)
            self._log(msg, "aviso")
        else:
            self._var_entidades_ok.set(f"✔ {len(existentes)} entidades disponíveis")

        self._log(
            f"Banco carregado: {len(alimentadores)} alimentadores.",
            "ok" if not faltantes else "aviso",
        )

        # Habilitar execução apenas se há alimentadores
        if alimentadores:
            self._btn_exec.config(state="normal")

        self._btn_carregar.config(state="normal")

    # ------------------------------------------------------------------
    # Modo de execução
    # ------------------------------------------------------------------

    def _on_modo_changed(self):
        if self._var_modo.get() == "um":
            self._combo_alim.config(state="readonly")
        else:
            self._combo_alim.config(state="disabled")

    # ------------------------------------------------------------------
    # Execução BFS
    # ------------------------------------------------------------------

    def _executar(self):
        if not self._gc.conectado:
            messagebox.showwarning("Aviso", "Carregue um banco primeiro.")
            return

        modo = self._var_modo.get()

        if modo == "um":
            alim = self._var_alim.get()
            if not alim:
                messagebox.showwarning("Aviso", "Selecione um alimentador.")
                return
            alimentadores_exec = [alim]
        else:
            alimentadores_exec = list(self._alimentadores)

        if not alimentadores_exec:
            messagebox.showwarning("Aviso", "Nenhum alimentador disponível.")
            return

        # Resetar flag de cancelamento
        self._cancelar.clear()

        self._btn_exec.config(state="disabled")
        self._btn_cancelar.config(state="normal")
        self._btn_exportar.config(state="disabled")
        self._btn_carregar.config(state="disabled")
        self._progress.start(10)
        self._var_stat_status.set("Em execução")
        self._var_stat_elem.set("...")
        self._log(
            f"Iniciando BFS — {len(alimentadores_exec)} alimentador(es)...",
            "info",
        )

        def _worker():
            try:
                con = self._gc.conexao
                df, n_ok, n_erro = rodar_bfs_lista(
                    con=con,
                    alimentadores=alimentadores_exec,
                    callback_progresso=lambda m: self.after(0, self._log, m),
                    cancelar_flag=self._cancelar,
                )
                self.after(0, self._bfs_ok, df, n_ok, n_erro)

            except Exception as e:
                self.after(0, self._bfs_erro, str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _cancelar_execucao(self):
        self._cancelar.set()
        self._log("Solicitação de cancelamento enviada...", "aviso")
        self._btn_cancelar.config(state="disabled")

    def _bfs_ok(self, df, n_ok: int, n_erro: int):
        self._progress.stop()
        self._btn_exec.config(state="normal")
        self._btn_cancelar.config(state="disabled")
        self._btn_carregar.config(state="normal")
        self._var_prog_msg.set("")
        self._df_resultado = df

        cancelado = self._cancelar.is_set()
        n_elem = len(df) if df is not None and not df.empty else 0

        self._var_stat_elem.set(str(n_elem))
        self._var_stat_status.set("Cancelado" if cancelado else "Concluído ✓")

        msg = (
            f"{'Cancelado pelo usuário.' if cancelado else 'BFS concluído.'} "
            f"{n_ok} OK | {n_erro} erro(s) | "
            f"{n_elem} elemento(s) | "
            f"Tabela {TABELA_TOPOLOGIA} atualizada no banco."
        )
        self._log(msg, "aviso" if cancelado else "ok")
        self._status_var.set(f"Topologia: {n_elem} elemento(s).")

        if n_elem > 0:
            self._btn_exportar.config(state="normal")

    def _bfs_erro(self, msg: str):
        self._progress.stop()
        self._btn_exec.config(state="normal")
        self._btn_cancelar.config(state="disabled")
        self._btn_carregar.config(state="normal")
        self._var_prog_msg.set("")
        self._var_stat_status.set("Erro")
        self._log(f"Erro fatal: {msg}", "erro")
        messagebox.showerror("Erro BFS", msg)

    # ------------------------------------------------------------------
    # Exportação
    # ------------------------------------------------------------------

    def _exportar(self):
        if self._df_resultado is None or self._df_resultado.empty:
            messagebox.showwarning("Aviso", "Execute o BFS primeiro.")
            return

        caminho = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx"), ("CSV", "*.csv")],
            initialfile="TOPOLOGIA.xlsx",
            title="Exportar topologia",
        )
        if not caminho:
            return

        try:
            if caminho.endswith(".csv"):
                self._df_resultado.to_csv(caminho, index=False, encoding="utf-8-sig")
            else:
                self._df_resultado.to_excel(caminho, index=False)
            messagebox.showinfo("Sucesso", f"Exportado:\n{caminho}")
        except Exception as e:
            messagebox.showerror("Erro", str(e))

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
        self._var_prog_msg.set(msg[:80])

    def _limpar_log(self):
        self._text_log.config(state="normal")
        self._text_log.delete("1.0", "end")
        self._text_log.config(state="disabled")

    # ------------------------------------------------------------------
    # Chamado externamente (app.py) ao navegar para esta aba
    # ------------------------------------------------------------------

    def atualizar_bancos(self):
        """Atualiza a lista de bancos disponíveis."""
        self._atualizar_lista_bancos()
