# -*- coding: utf-8 -*-
"""
ui/tema.py
Definição centralizada de cores, fontes e estilos da interface.
Altere aqui para modificar o visual de toda a aplicação.
"""

import tkinter as tk
from tkinter import ttk


# ---------------------------------------------------------------------------
# Paleta de cores
# ---------------------------------------------------------------------------

CORES = {
    # Fundo principal e paineis
    "bg_app":        "#0F1923",   # azul-marinho escuro
    "bg_painel":     "#162130",   # azul-marinho médio
    "bg_card":       "#1E2D3D",   # azul-marinho claro (cards)
    "bg_input":      "#243447",   # fundo de campos de entrada
    "bg_hover":      "#2A3F55",   # hover sobre itens

    # Acentos
    "acento":        "#00C8FF",   # ciano elétrico
    "acento_hover":  "#33D4FF",
    "acento_escuro": "#0099CC",

    # Sucesso / aviso / erro
    "sucesso":       "#00E676",
    "aviso":         "#FFD600",
    "erro":          "#FF5252",

    # Texto
    "texto":         "#E8F0F7",   # texto principal
    "texto_sec":     "#7A9BB5",   # texto secundário
    "texto_desab":   "#3A5068",   # texto desabilitado

    # Separadores / bordas
    "borda":         "#243447",
    "separador":     "#1E2D3D",

    # Menu lateral
    "menu_bg":       "#0A1520",
    "menu_sel":      "#162130",
    "menu_hover":    "#162130",
}

# ---------------------------------------------------------------------------
# Fontes (usa tk.font para garantir disponibilidade)
# ---------------------------------------------------------------------------

FONTES = {
    "titulo_app":  ("Segoe UI", 15, "bold"),
    "titulo_aba":  ("Segoe UI", 13, "bold"),
    "subtitulo":   ("Segoe UI", 10, "bold"),
    "corpo":       ("Segoe UI", 9),
    "corpo_bold":  ("Segoe UI", 9, "bold"),
    "pequeno":     ("Segoe UI", 8),
    "mono":        ("Consolas", 9),
    "menu":        ("Segoe UI", 10),
    "menu_icon":   ("Segoe UI", 14),
    "badge":       ("Segoe UI", 8, "bold"),
    "botao":       ("Segoe UI", 9, "bold"),
    "status":      ("Segoe UI", 8),
}


# ---------------------------------------------------------------------------
# Estilos ttk
# ---------------------------------------------------------------------------

def aplicar_tema(root: tk.Tk) -> None:
    """
    Configura o tema global ttk para toda a aplicação.
    Chamar uma única vez após criar a janela principal.
    """
    root.configure(bg=CORES["bg_app"])

    style = ttk.Style(root)
    style.theme_use("clam")

    C = CORES
    F = FONTES

    # --- Frame / LabelFrame ---
    style.configure("TFrame", background=C["bg_app"])
    style.configure("Card.TFrame", background=C["bg_card"])
    style.configure("Painel.TFrame", background=C["bg_painel"])
    style.configure("Menu.TFrame", background=C["menu_bg"])

    style.configure(
        "TLabelframe",
        background=C["bg_card"],
        foreground=C["texto"],
        bordercolor=C["borda"],
        relief="flat",
        padding=10,
    )
    style.configure(
        "TLabelframe.Label",
        background=C["bg_card"],
        foreground=C["acento"],
        font=F["subtitulo"],
    )

    # --- Label ---
    style.configure(
        "TLabel",
        background=C["bg_app"],
        foreground=C["texto"],
        font=F["corpo"],
    )
    style.configure(
        "Titulo.TLabel",
        background=C["bg_app"],
        foreground=C["texto"],
        font=F["titulo_aba"],
    )
    style.configure(
        "Sec.TLabel",
        background=C["bg_app"],
        foreground=C["texto_sec"],
        font=F["pequeno"],
    )
    style.configure(
        "Card.TLabel",
        background=C["bg_card"],
        foreground=C["texto"],
        font=F["corpo"],
    )
    style.configure(
        "Acento.TLabel",
        background=C["bg_app"],
        foreground=C["acento"],
        font=F["corpo_bold"],
    )
    style.configure(
        "Sucesso.TLabel",
        background=C["bg_app"],
        foreground=C["sucesso"],
        font=F["corpo"],
    )
    style.configure(
        "Erro.TLabel",
        background=C["bg_app"],
        foreground=C["erro"],
        font=F["corpo"],
    )
    style.configure(
        "Aviso.TLabel",
        background=C["bg_app"],
        foreground=C["aviso"],
        font=F["corpo"],
    )

    # --- Button ---
    style.configure(
        "TButton",
        background=C["bg_input"],
        foreground=C["texto"],
        font=F["botao"],
        relief="flat",
        borderwidth=0,
        padding=(12, 6),
        focusthickness=0,
    )
    style.map(
        "TButton",
        background=[("active", C["bg_hover"]), ("pressed", C["borda"])],
        foreground=[("active", C["acento"])],
    )

    style.configure(
        "Primario.TButton",
        background=C["acento"],
        foreground=C["bg_app"],
        font=F["botao"],
        relief="flat",
        borderwidth=0,
        padding=(14, 7),
    )
    style.map(
        "Primario.TButton",
        background=[("active", C["acento_hover"]), ("pressed", C["acento_escuro"])],
        foreground=[("active", C["bg_app"])],
    )

    style.configure(
        "Perigo.TButton",
        background=C["erro"],
        foreground=C["texto"],
        font=F["botao"],
        relief="flat",
        borderwidth=0,
        padding=(12, 6),
    )
    style.map(
        "Perigo.TButton",
        background=[("active", "#FF7070"), ("pressed", "#CC3333")],
    )

    style.configure(
        "Ghost.TButton",
        background=C["bg_painel"],
        foreground=C["texto_sec"],
        font=F["botao"],
        relief="flat",
        borderwidth=0,
        padding=(10, 5),
    )
    style.map(
        "Ghost.TButton",
        background=[("active", C["bg_hover"])],
        foreground=[("active", C["texto"])],
    )

    # --- Entry ---
    style.configure(
        "TEntry",
        fieldbackground=C["bg_input"],
        foreground=C["texto"],
        insertcolor=C["acento"],
        borderwidth=0,
        relief="flat",
        font=F["corpo"],
        padding=(8, 5),
    )
    style.map(
        "TEntry",
        fieldbackground=[("focus", C["bg_hover"])],
    )

    # --- Combobox ---
    style.configure(
        "TCombobox",
        fieldbackground=C["bg_input"],
        background=C["bg_input"],
        foreground=C["texto"],
        selectbackground=C["acento"],
        selectforeground=C["bg_app"],
        arrowcolor=C["acento"],
        borderwidth=0,
        relief="flat",
        font=F["corpo"],
        padding=(8, 5),
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", C["bg_input"]), ("focus", C["bg_hover"])],
        foreground=[("readonly", C["texto"])],
    )

    # --- Scrollbar ---
    style.configure(
        "TScrollbar",
        background=C["bg_painel"],
        troughcolor=C["bg_app"],
        arrowcolor=C["texto_sec"],
        borderwidth=0,
        relief="flat",
    )
    style.map(
        "TScrollbar",
        background=[("active", C["bg_hover"])],
    )

    # --- Treeview ---
    style.configure(
        "Treeview",
        background=C["bg_card"],
        foreground=C["texto"],
        fieldbackground=C["bg_card"],
        borderwidth=0,
        rowheight=26,
        font=F["corpo"],
    )
    style.configure(
        "Treeview.Heading",
        background=C["bg_painel"],
        foreground=C["acento"],
        font=F["corpo_bold"],
        relief="flat",
        borderwidth=0,
        padding=(6, 4),
    )
    style.map(
        "Treeview",
        background=[("selected", C["acento_escuro"])],
        foreground=[("selected", C["texto"])],
    )
    style.map(
        "Treeview.Heading",
        background=[("active", C["bg_hover"])],
    )

    # --- Progressbar ---
    style.configure(
        "TProgressbar",
        background=C["acento"],
        troughcolor=C["bg_input"],
        borderwidth=0,
        thickness=6,
    )

    # --- Separator ---
    style.configure(
        "TSeparator",
        background=C["borda"],
    )

    # --- Notebook (não usado, mas configurado por precaução) ---
    style.configure(
        "TNotebook",
        background=C["bg_app"],
        borderwidth=0,
    )
    style.configure(
        "TNotebook.Tab",
        background=C["bg_painel"],
        foreground=C["texto_sec"],
        font=F["menu"],
        padding=(12, 6),
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", C["bg_card"])],
        foreground=[("selected", C["acento"])],
    )

    # Configurar opção de listbox globalmente
    root.option_add("*Listbox.background", C["bg_input"])
    root.option_add("*Listbox.foreground", C["texto"])
    root.option_add("*Listbox.selectBackground", C["acento_escuro"])
    root.option_add("*Listbox.selectForeground", C["texto"])
    root.option_add("*Listbox.font", "TkFixedFont")
    root.option_add("*Listbox.relief", "flat")
    root.option_add("*Listbox.borderWidth", 0)

    # Text widget
    root.option_add("*Text.background", C["bg_input"])
    root.option_add("*Text.foreground", C["texto"])
    root.option_add("*Text.insertBackground", C["acento"])
    root.option_add("*Text.selectBackground", C["acento_escuro"])
    root.option_add("*Text.font", "TkFixedFont")
    root.option_add("*Text.relief", "flat")
    root.option_add("*Text.borderWidth", 0)


# ---------------------------------------------------------------------------
# Widgets customizados reutilizáveis
# ---------------------------------------------------------------------------

def make_separador(parent, pady=8):
    """Linha separadora horizontal."""
    sep = ttk.Separator(parent, orient="horizontal")
    sep.pack(fill="x", pady=pady)
    return sep


def make_label_secao(parent, texto: str, **pack_opts):
    """Label de título de seção com cor de acento."""
    lbl = ttk.Label(parent, text=texto, style="Acento.TLabel")
    lbl.pack(anchor="w", **pack_opts)
    return lbl


def make_status_bar(parent) -> tk.StringVar:
    """
    Cria uma barra de status na parte inferior do parent.
    Retorna a StringVar associada para atualização.
    """
    var = tk.StringVar(value="Pronto.")
    frame = tk.Frame(parent, bg=CORES["menu_bg"], height=22)
    frame.pack(side="bottom", fill="x")
    frame.pack_propagate(False)

    lbl = tk.Label(
        frame,
        textvariable=var,
        bg=CORES["menu_bg"],
        fg=CORES["texto_sec"],
        font=FONTES["status"],
        anchor="w",
        padx=10,
    )
    lbl.pack(side="left", fill="y")

    return var
