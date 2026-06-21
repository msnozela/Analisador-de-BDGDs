# -*- coding: utf-8 -*-
"""
ui/aba_home.py
Aba inicial (Home) do Analisador de BDGDs.

Exibe boas-vindas, cards de navegação para cada módulo e
informações rápidas sobre o projeto.
"""

import tkinter as tk
from tkinter import ttk

from ui.tema import CORES, FONTES


# ---------------------------------------------------------------------------
# Dados dos módulos
# ---------------------------------------------------------------------------

MODULOS = [
    {
        "idx":   1,
        "icon":  "⬇",
        "label": "Extração",
        "desc":  "Faça download de BDGDs diretamente via API ArcGIS da ANEEL.",
        "cor":   "#00C8FF",
    },
    {
        "idx":   2,
        "icon":  "🗄",
        "label": "Banco",
        "desc":  "Crie e atualize bancos DuckDB a partir dos arquivos GDB extraídos.",
        "cor":   "#00E676",
    },
    {
        "idx":   3,
        "icon":  "🔍",
        "label": "Consultas",
        "desc":  "Execute as 10 regras de inconsistência e exporte os resultados.",
        "cor":   "#FFD600",
    },
    {
        "idx":   4,
        "icon":  "🌐",
        "label": "Topologia",
        "desc":  "Analise a conectividade da rede com algoritmo BFS e detecte isolados.",
        "cor":   "#A78BFA",
    },
    {
        "idx":   5,
        "icon":  "⚙",
        "label": "Conversão",
        "desc":  "Converta alimentadores da BDGD para o formato OpenDSS.",
        "cor":   "#FF9800",
    },
    {
        "idx":   6,
        "icon":  "▶",
        "label": "Simulação",
        "desc":  "Simule o fluxo de carga em modo Daily no OpenDSS.",
        "cor":   "#FF5252",
    },
    {
        "idx":   7,
        "icon":  "📊",
        "label": "Dashboard",
        "desc":  "Visualize gráficos e KPIs das 10 regras por BDGD analisada.",
        "cor":   "#00C8FF",
    },
    {
        "idx":   8,
        "icon":  "🗺",
        "label": "Mapas",
        "desc":  "Gere mapas HTML interativos com inconsistências georreferenciadas.",
        "cor":   "#00E676",
    },
]

REGRAS = [
    ("R01", "Elementos Isolados"),
    ("R02", "Erros de Faseamento"),
    ("R03", "Erros de Neutro"),
    ("R04", "Resistência de Condutores"),
    ("R05", "Potência de Transformadores"),
    ("R06", "Perdas em Transformadores"),
    ("R07", "Potência de Reguladores"),
    ("R08", "Comprimento Zerado"),
    ("R09", "Curvas de Carga"),
    ("R10", "Modelagem de Reguladores"),
]


# ---------------------------------------------------------------------------
# Classe da aba
# ---------------------------------------------------------------------------

class AbaHome(ttk.Frame):
    """
    Tela inicial do Analisador de BDGDs.

    Parâmetros
    ----------
    parent : widget pai (área de conteúdo do app)
    navegar_fn : callable(idx: int) — função de navegação do app principal
    """

    def __init__(self, parent, navegar_fn, **kwargs):
        super().__init__(parent, **kwargs)
        self.configure(style="TFrame")
        self._nav = navegar_fn
        self._build()

    # ------------------------------------------------------------------
    def _build(self):
        C = CORES

        # Canvas com scrollbar para permitir rolagem vertical
        outer = tk.Frame(self, bg=C["bg_app"])
        outer.pack(fill="both", expand=True)

        canvas = tk.Canvas(outer, bg=C["bg_app"], highlightthickness=0,
                           bd=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical",
                                  command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # Frame interno (scrollável)
        self._inner = tk.Frame(canvas, bg=C["bg_app"])
        self._win_id = canvas.create_window((0, 0), window=self._inner,
                                            anchor="nw")

        self._inner.bind("<Configure>",
                         lambda e: canvas.configure(
                             scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(self._win_id,
                                                width=e.width))

        # Scroll com roda do mouse
        def _scroll(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _scroll)

        # Conteúdo
        self._build_hero()
        self._build_modulos()
        self._build_regras()
        self._build_footer()

    # ------------------------------------------------------------------
    def _build_hero(self):
        C = CORES
        hero = tk.Frame(self._inner, bg=C["bg_app"])
        hero.pack(fill="x", padx=40, pady=(36, 20))

        # Linha decorativa superior
        accent_line = tk.Frame(hero, bg=C["acento"], height=3, width=60)
        accent_line.pack(anchor="w", pady=(0, 16))

        # Título principal
        tk.Label(
            hero,
            text="Analisador de BDGDs",
            bg=C["bg_app"],
            fg=C["texto"],
            font=("Segoe UI", 28, "bold"),
            anchor="w",
        ).pack(anchor="w")

        # Subtítulo
        tk.Label(
            hero,
            text="Base de Dados Geográfica da Distribuidora  ·  ANEEL",
            bg=C["bg_app"],
            fg=C["texto_sec"],
            font=("Segoe UI", 11),
            anchor="w",
        ).pack(anchor="w", pady=(4, 0))

        # Descrição
        tk.Label(
            hero,
            text=(
                "Ferramenta integrada para extração, análise de inconsistências, "
                "conversão e simulação de redes elétricas de distribuição."
            ),
            bg=C["bg_app"],
            fg=C["texto_sec"],
            font=("Segoe UI", 9),
            anchor="w",
            wraplength=700,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

        # Badge TCC
        badge_frame = tk.Frame(hero, bg=C["bg_painel"], padx=10, pady=5)
        badge_frame.pack(anchor="w", pady=(14, 0))
        tk.Label(
            badge_frame,
            text="🎓  TCC · MBA em Análise de Dados — USP  ·  Marco A. S. Nozela",
            bg=C["bg_painel"],
            fg=C["acento"],
            font=("Segoe UI", 8, "bold"),
        ).pack()

        # Separador
        tk.Frame(self._inner, bg=C["borda"], height=1).pack(
            fill="x", padx=40, pady=(20, 0))

    # ------------------------------------------------------------------
    def _build_modulos(self):
        C = CORES

        # Título da seção
        sec = tk.Frame(self._inner, bg=C["bg_app"])
        sec.pack(fill="x", padx=40, pady=(24, 12))
        tk.Label(
            sec,
            text="MÓDULOS",
            bg=C["bg_app"],
            fg=C["acento"],
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            sec,
            text="Clique em um card para acessar o módulo",
            bg=C["bg_app"],
            fg=C["texto_sec"],
            font=("Segoe UI", 8),
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        # Grid de cards — 4 colunas
        grid = tk.Frame(self._inner, bg=C["bg_app"])
        grid.pack(fill="x", padx=40, pady=(0, 8))

        for col in range(4):
            grid.columnconfigure(col, weight=1, uniform="card")

        for i, mod in enumerate(MODULOS):
            row, col = divmod(i, 4)
            card = self._make_card(grid, mod)
            card.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")

        # Separador
        tk.Frame(self._inner, bg=C["borda"], height=1).pack(
            fill="x", padx=40, pady=(16, 0))

    # ------------------------------------------------------------------
    def _make_card(self, parent, mod: dict) -> tk.Frame:
        C = CORES
        cor = mod["cor"]

        card = tk.Frame(parent, bg=C["bg_card"], cursor="hand2",
                        relief="flat", bd=0)

        # Borda colorida superior
        borda_top = tk.Frame(card, bg=cor, height=3)
        borda_top.pack(fill="x")

        inner = tk.Frame(card, bg=C["bg_card"], padx=14, pady=12)
        inner.pack(fill="both", expand=True)

        # Ícone + label
        header = tk.Frame(inner, bg=C["bg_card"])
        header.pack(fill="x")

        tk.Label(
            header,
            text=mod["icon"],
            bg=C["bg_card"],
            fg=cor,
            font=("Segoe UI", 20),
        ).pack(side="left")

        tk.Label(
            header,
            text=mod["label"],
            bg=C["bg_card"],
            fg=C["texto"],
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        ).pack(side="left", padx=(8, 0))

        # Descrição
        tk.Label(
            inner,
            text=mod["desc"],
            bg=C["bg_card"],
            fg=C["texto_sec"],
            font=("Segoe UI", 8),
            wraplength=180,
            justify="left",
            anchor="w",
        ).pack(anchor="w", pady=(6, 0))

        # Link "Acessar →"
        link = tk.Label(
            inner,
            text="Acessar  →",
            bg=C["bg_card"],
            fg=cor,
            font=("Segoe UI", 8, "bold"),
            anchor="w",
            cursor="hand2",
        )
        link.pack(anchor="w", pady=(10, 0))

        # Navegação ao clicar
        idx = mod["idx"]
        for w in [card, inner, header, link]:
            w.bind("<Button-1>", lambda e, i=idx: self._nav(i))
        for child in inner.winfo_children():
            child.bind("<Button-1>", lambda e, i=idx: self._nav(i))

        # Hover visual
        def _enter(e, c=card, i=inner, cor=cor):
            c.config(bg=C["bg_hover"])
            i.config(bg=C["bg_hover"])
            for w in i.winfo_children():
                try:
                    w.config(bg=C["bg_hover"])
                except Exception:
                    pass
            for w in i.winfo_children():
                for ww in (w.winfo_children() if hasattr(w, 'winfo_children') else []):
                    try:
                        ww.config(bg=C["bg_hover"])
                    except Exception:
                        pass

        def _leave(e, c=card, i=inner):
            c.config(bg=C["bg_card"])
            i.config(bg=C["bg_card"])
            for w in i.winfo_children():
                try:
                    w.config(bg=C["bg_card"])
                except Exception:
                    pass
            for w in i.winfo_children():
                for ww in (w.winfo_children() if hasattr(w, 'winfo_children') else []):
                    try:
                        ww.config(bg=C["bg_card"])
                    except Exception:
                        pass

        for w in [card, inner]:
            w.bind("<Enter>", _enter)
            w.bind("<Leave>", _leave)
        for child in inner.winfo_children():
            child.bind("<Enter>", _enter)
            child.bind("<Leave>", _leave)

        return card

    # ------------------------------------------------------------------
    def _build_regras(self):
        C = CORES

        sec = tk.Frame(self._inner, bg=C["bg_app"])
        sec.pack(fill="x", padx=40, pady=(24, 12))
        tk.Label(
            sec,
            text="REGRAS DE INCONSISTÊNCIA",
            bg=C["bg_app"],
            fg=C["acento"],
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            sec,
            text="10 verificações automáticas aplicadas sobre a BDGD importada",
            bg=C["bg_app"],
            fg=C["texto_sec"],
            font=("Segoe UI", 8),
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        # Grid 2×5
        grid = tk.Frame(self._inner, bg=C["bg_app"])
        grid.pack(fill="x", padx=40, pady=(0, 8))
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        for i, (cod, nome) in enumerate(REGRAS):
            row, col = divmod(i, 2)
            item = tk.Frame(grid, bg=C["bg_painel"], padx=12, pady=8)
            item.grid(row=row, column=col, padx=5, pady=4, sticky="ew")

            badge = tk.Label(
                item,
                text=cod,
                bg=C["acento"],
                fg=C["bg_app"],
                font=("Segoe UI", 7, "bold"),
                padx=6,
                pady=2,
            )
            badge.pack(side="left")

            tk.Label(
                item,
                text=nome,
                bg=C["bg_painel"],
                fg=C["texto"],
                font=("Segoe UI", 9),
                anchor="w",
            ).pack(side="left", padx=(10, 0))

        # Separador
        tk.Frame(self._inner, bg=C["borda"], height=1).pack(
            fill="x", padx=40, pady=(16, 0))

    # ------------------------------------------------------------------
    def _build_footer(self):
        C = CORES

        footer = tk.Frame(self._inner, bg=C["bg_app"])
        footer.pack(fill="x", padx=40, pady=(20, 36))

        # Stack de tecnologias
        tk.Label(
            footer,
            text="Stack:",
            bg=C["bg_app"],
            fg=C["texto_sec"],
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left", padx=(0, 8))

        tecnologias = [
            "Python", "Tkinter", "DuckDB", "GeoPandas",
            "Folium", "Matplotlib", "OpenDSS",
        ]
        for tec in tecnologias:
            lbl = tk.Label(
                footer,
                text=tec,
                bg=C["bg_input"],
                fg=C["texto_sec"],
                font=("Segoe UI", 8),
                padx=8,
                pady=3,
            )
            lbl.pack(side="left", padx=3)
