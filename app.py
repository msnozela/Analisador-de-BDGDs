# -*- coding: utf-8 -*-
"""
app.py — Analisador de BDGDs  |  Ponto de entrada da aplicação.

Módulos (menu lateral):
    0 - Home        : tela inicial com navegação por cards
    1 - Extração    : download de BDGDs via ArcGIS
    2 - Banco       : criação de banco DuckDB + importação DDA
    3 - Consultas   : 10 regras SQL + persistência de resultados
    4 - Topologia   : algoritmo BFS
    5 - Conversão   : BDGD → OpenDSS
    6 - Simulação   : simulação Daily OpenDSS
    7 - Dashboard   : gráficos das 10 regras de inconsistência
    8 - Mapas       : mapas HTML interativos
"""

import os, sys, tkinter as tk
from tkinter import ttk

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ui.tema          import aplicar_tema, make_status_bar, CORES, FONTES
from ui.aba_home      import AbaHome
from ui.aba_extracao  import AbaExtracao
from ui.aba_banco     import AbaBanco
from ui.aba_consultas import AbaConsultas
from ui.aba_topologia import AbaTopologia
from ui.aba_conversao import AbaConversao
from ui.aba_simulacao import AbaSimulacao
from ui.aba_dashboard import AbaDashboard
from ui.aba_mapas     import AbaMapas

CAMINHOS = {
    "base":   ROOT,
    "excel":  os.path.join(ROOT, "Lista codigos BDGDs",
                           "Agência Nacional de Energia Elétrica.xlsx"),
    "bdgds":  os.path.join(ROOT, "BDGDs"),
    "duckdb": os.path.join(ROOT, "Bancos Duckdb"),
    "saida":  os.path.join(ROOT, "Resultado Consultas"),
}
for pasta in ("bdgds", "duckdb", "saida"):
    os.makedirs(CAMINHOS[pasta], exist_ok=True)


class BDGDApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Analisador de BDGDs  —  Análise de Inconsistências")
        self.geometry("1280x780")
        self.minsize(960, 620)
        try:
            self.iconbitmap(os.path.join(ROOT, "icon.ico"))
        except Exception:
            pass
        aplicar_tema(self)
        self._status_var = make_status_bar(self)
        self._build_layout()
        self._navegar(0)

    def _build_layout(self):
        C = CORES; F = FONTES
        main = tk.Frame(self, bg=C["bg_app"])
        main.pack(fill="both", expand=True)

        # Sidebar
        self._sidebar = tk.Frame(main, bg=C["menu_bg"], width=220)
        self._sidebar.pack(side="left", fill="y")
        self._sidebar.pack_propagate(False)

        tk.Label(self._sidebar, text="Analisador", bg=C["menu_bg"], fg=C["acento"],
                 font=("Segoe UI", 14, "bold")).pack(pady=(24, 0))
        tk.Label(self._sidebar, text="de BDGDs", bg=C["menu_bg"], fg=C["acento"],
                 font=("Segoe UI", 14, "bold")).pack(pady=(0, 4))
        tk.Label(self._sidebar, text="Análise de Inconsistências",
                 bg=C["menu_bg"], fg=C["texto_desab"],
                 font=F["pequeno"]).pack(pady=(0, 20))
        tk.Frame(self._sidebar, bg=C["borda"], height=1).pack(
            fill="x", padx=16, pady=(0, 16))

        self._menu_itens: list[dict] = [
            {"icon": "🏠", "label": "Home",       "desc": "Início"},
            {"icon": "⬇",  "label": "Extração",   "desc": "Download de BDGDs"},
            {"icon": "🗄",  "label": "Banco",       "desc": "Criar banco DuckDB"},
            {"icon": "🔍", "label": "Consultas",   "desc": "10 regras SQL"},
            {"icon": "🌐", "label": "Topologia",   "desc": "Algoritmo BFS"},
            {"icon": "⚙",  "label": "Conversão",   "desc": "BDGD → OpenDSS"},
            {"icon": "▶",  "label": "Simulação",   "desc": "Simulação Daily"},
            {"icon": "📊", "label": "Dashboard",   "desc": "Análise de Inconsistências"},
            {"icon": "🗺",  "label": "Mapas",       "desc": "Mapas HTML da rede"},
        ]

        self._btns_menu: list[tk.Frame] = []
        self._aba_ativa = tk.IntVar(value=-1)
        for i, item in enumerate(self._menu_itens):
            self._btns_menu.append(self._criar_btn_menu(i, item))

        tk.Frame(self._sidebar, bg=C["borda"], height=1).pack(
            fill="x", padx=16, pady=(16, 12), side="bottom")
        tk.Label(self._sidebar,
                 text="Marco A. S. Nozela\nMBA Análise de Dados — USP",
                 bg=C["menu_bg"], fg=C["texto_desab"],
                 font=F["pequeno"], justify="center").pack(side="bottom", pady=(0, 12))

        # Área de conteúdo
        self._area = tk.Frame(main, bg=C["bg_app"])
        self._area.pack(side="left", fill="both", expand=True)

        # A aba Home recebe a função de navegação como parâmetro
        self._abas: list[ttk.Frame] = [
            AbaHome(self._area,      self._navegar),
            AbaExtracao(self._area,  CAMINHOS, self._status_var),
            AbaBanco(self._area,     CAMINHOS, self._status_var),
            AbaConsultas(self._area, CAMINHOS, self._status_var),
            AbaTopologia(self._area, CAMINHOS, self._status_var),
            AbaConversao(self._area, CAMINHOS, self._status_var),
            AbaSimulacao(self._area, CAMINHOS, self._status_var),
            AbaDashboard(self._area, CAMINHOS, self._status_var),
            AbaMapas(self._area,     CAMINHOS, self._status_var),
        ]
        for aba in self._abas:
            aba.place(relx=0, rely=0, relwidth=1, relheight=1)

    def _criar_btn_menu(self, idx: int, item: dict) -> tk.Frame:
        C = CORES; F = FONTES
        frame = tk.Frame(self._sidebar, bg=C["menu_bg"], cursor="hand2")
        frame.pack(fill="x", padx=0, pady=1)
        inner = tk.Frame(frame, bg=C["menu_bg"])
        inner.pack(fill="x", padx=12, pady=6)
        lbl_icon = tk.Label(inner, text=item["icon"],
                            bg=C["menu_bg"], fg=C["texto_sec"],
                            font=F["menu_icon"])
        lbl_icon.pack(side="left", padx=(4, 8))
        txt = tk.Frame(inner, bg=C["menu_bg"])
        txt.pack(side="left", fill="x", expand=True)
        lbl_nome = tk.Label(txt, text=item["label"],
                            bg=C["menu_bg"], fg=C["texto"],
                            font=F["menu"], anchor="w")
        lbl_nome.pack(fill="x")
        lbl_desc = tk.Label(txt, text=item["desc"],
                            bg=C["menu_bg"], fg=C["texto_desab"],
                            font=F["pequeno"], anchor="w")
        lbl_desc.pack(fill="x")
        indicador = tk.Frame(frame, bg=C["menu_bg"], width=4)
        indicador.pack(side="left", fill="y")
        for w in [frame, inner, lbl_icon, txt, lbl_nome, lbl_desc]:
            w.bind("<Button-1>", lambda e, i=idx: self._navegar(i))
            w.bind("<Enter>",
                   lambda e, f=frame, n=lbl_nome, d=lbl_desc, ic=indicador:
                   self._hover_menu(f, n, d, ic, True))
            w.bind("<Leave>",
                   lambda e, i2=idx, f=frame, n=lbl_nome, d=lbl_desc, ic=indicador:
                   self._hover_menu(f, n, d, ic, False, i2))
        frame._indicador = indicador
        frame._lbl_nome  = lbl_nome
        frame._lbl_desc  = lbl_desc
        frame._lbl_icon  = lbl_icon
        frame._inner     = inner
        return frame

    def _hover_menu(self, frame, lbl_nome, lbl_desc, indicador,
                    entrou: bool, idx: int = -1):
        C = CORES
        ativo = (idx == self._aba_ativa.get())
        if entrou and not ativo:
            for w in [frame, frame._inner]:
                w.config(bg=C["menu_hover"])
            lbl_nome.config(bg=C["menu_hover"], fg=C["texto"])
            lbl_desc.config(bg=C["menu_hover"])
            frame._lbl_icon.config(bg=C["menu_hover"])
        elif not entrou and not ativo:
            self._reset_btn_menu(frame)

    def _navegar(self, idx: int):
        C = CORES; F = FONTES
        for btn in self._btns_menu:
            self._reset_btn_menu(btn)
        btn = self._btns_menu[idx]
        btn.config(bg=C["menu_sel"])
        btn._inner.config(bg=C["menu_sel"])
        btn._lbl_nome.config(bg=C["menu_sel"], fg=C["acento"], font=F["menu"])
        btn._lbl_desc.config(bg=C["menu_sel"], fg=C["texto_sec"])
        btn._lbl_icon.config(bg=C["menu_sel"], fg=C["acento"])
        btn._indicador.config(bg=C["acento"])
        self._aba_ativa.set(idx)
        self._abas[idx].lift()

        # Índices deslocaram +1 por causa da aba Home (idx 0)
        sincronizar = {
            2: "atualizar_zips",
            3: "atualizar_bancos",
            4: "atualizar_bancos",
            5: "atualizar_zips",
            6: "atualizar_alimentadores",
            7: "atualizar_dashboard",
            8: "atualizar_mapas",
        }
        if idx in sincronizar:
            getattr(self._abas[idx], sincronizar[idx], lambda: None)()
        self._status_var.set(
            f"Módulo: {self._menu_itens[idx]['label']} "
            f"— {self._menu_itens[idx]['desc']}")

    def _reset_btn_menu(self, btn: tk.Frame):
        C = CORES; F = FONTES
        btn.config(bg=C["menu_bg"])
        btn._inner.config(bg=C["menu_bg"])
        btn._lbl_nome.config(bg=C["menu_bg"], fg=C["texto"], font=F["menu"])
        btn._lbl_desc.config(bg=C["menu_bg"], fg=C["texto_desab"])
        btn._lbl_icon.config(bg=C["menu_bg"], fg=C["texto_sec"])
        btn._indicador.config(bg=C["menu_bg"])


if __name__ == "__main__":
    BDGDApp().mainloop()
