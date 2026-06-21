# -*- coding: utf-8 -*-
"""
core/conversao.py
Lógica de conversão de BDGDs para arquivos OpenDSS via biblioteca bdgd2opendss.
Sem dependência de GUI.

FLUXO DE TRABALHO
-----------------
1. Usuário seleciona um arquivo .zip (baixado pelo módulo Extração)
2. extrair_gdb_permanente() extrai o ZIP para BDGDs Extraídas/<nome>/
   - Se já estiver extraído, reutiliza sem reextrair
3. listar_alimentadores_gdb() lê a pasta .gdb e retorna os COD_IDs da CTMT
4. converter_alimentadores() chama bdgd.run() com os parâmetros configurados

SOBRE O bdgd_file_path
-----------------------
A biblioteca bdgd2opendss espera o caminho de uma pasta com extensão .gdb,
por exemplo:
    C:/dados/CPFL_Santa_Cruz.gdb

Os ZIPs baixados da ANEEL contêm internamente essa pasta .gdb. Por isso,
extraímos o ZIP para um diretório permanente e localizamos o .gdb dentro dele.
"""

from __future__ import annotations

import os
import zipfile
import shutil
import warnings
import threading
from pathlib import Path
from typing import Callable

import fiona


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Pasta onde os GDBs são extraídos permanentemente (uma vez por BDGD)
PASTA_EXTRAIDAS = "BDGDs Extraídas"

# Todos os settings disponíveis no bdgd2opendss e seus valores padrão
SETTINGS_DISPONIVEIS: dict[str, dict] = {
    "TabelaPT": {
        "label":   "Gerar tabelas de Perdas Técnicas",
        "desc":    "Gera AuxBTNT, AuxMTNT e CircMT para cálculo de perdas.",
        "tipo":    "bool",
        "padrao":  True,
    },
    "intAdequarTensaoCargasMT": {
        "label":   "Adequar tensão mínima cargas MT",
        "desc":    "Limita tensão mínima das cargas MT a 0,93 pu.",
        "tipo":    "bool",
        "padrao":  False,
    },
    "intAdequarTensaoCargasBT": {
        "label":   "Adequar tensão mínima cargas BT",
        "desc":    "Limita tensão mínima das cargas BT a 0,92 pu.",
        "tipo":    "bool",
        "padrao":  False,
    },
    "intAdequarModeloCarga": {
        "label":   "Modelo de carga",
        "desc":    "1 = models 2 e 3 | 2 = models 1 e 1 | 3 = models 3 e 3",
        "tipo":    "int",
        "padrao":  1,
        "opcoes":  [1, 2, 3],
    },
    "dblVPUMin": {
        "label":   "Tensão mínima (pu)",
        "desc":    "Tensão mínima aceitável das cargas em pu.",
        "tipo":    "float",
        "padrao":  0.6,
    },
    "cbMeterComplete": {
        "label":   "Medidores completos",
        "desc":    "True = medidores em trafos e barramentos | False = só barramentos.",
        "tipo":    "bool",
        "padrao":  False,
    },
    "intUsaTrafoABNT": {
        "label":   "Usar perdas transformadores ABNT 5440",
        "desc":    "Utiliza as perdas dos transformadores da norma ABNT 5440.",
        "tipo":    "bool",
        "padrao":  False,
    },
    "intAdequarTensaoSuperior": {
        "label":   "Limitar tensão máxima de barras",
        "desc":    "Ativa limitação de tensão máxima nas barras.",
        "tipo":    "bool",
        "padrao":  False,
    },
    "intAdequarRamal": {
        "label":   "Limitar ramal em 30 m",
        "desc":    "Limita comprimento de ramal a 30 metros.",
        "tipo":    "bool",
        "padrao":  False,
    },
    "intAdequarTapTrafo": {
        "label":   "Usar taps dos transformadores",
        "desc":    "Utiliza os valores de tap dos transformadores.",
        "tipo":    "bool",
        "padrao":  False,
    },
    "intAdequarPotenciaCarga": {
        "label":   "Adequar potência à carga do trafo",
        "desc":    "Adequa potência das cargas BT à carga do transformador conectado.",
        "tipo":    "bool",
        "padrao":  False,
    },
    "intAdequarTrafoVazio": {
        "label":   "Comentar trafos a vazio",
        "desc":    "Desativa (comenta) transformadores sem carga.",
        "tipo":    "bool",
        "padrao":  False,
    },
    "intNeutralizarTrafoTerceiros": {
        "label":   "Neutralizar trafos de terceiros",
        "desc":    "Ignora transformadores pertencentes a terceiros.",
        "tipo":    "bool",
        "padrao":  False,
    },
    "intNeutralizarRedeTerceiros": {
        "label":   "Neutralizar redes de terceiros",
        "desc":    "Ignora redes elétricas pertencentes a terceiros.",
        "tipo":    "bool",
        "padrao":  False,
    },
    "CRVCRG96pts": {
        "label":   "Curva de carga com 96 pontos",
        "desc":    "Gera o arquivo de curva de carga com 96 pontos (vs. padrão GeoPerdas).",
        "tipo":    "bool",
        "padrao":  False,
    },
}


# ---------------------------------------------------------------------------
# Extração permanente do GDB
# ---------------------------------------------------------------------------

def pasta_extraidas(base_path: str) -> str:
    """Retorna (e cria se necessário) o diretório de GDBs extraídos."""
    p = os.path.join(base_path, PASTA_EXTRAIDAS)
    os.makedirs(p, exist_ok=True)
    return p


def extrair_gdb_permanente(
    zip_path: str,
    base_path: str,
    callback: Callable[[str], None] | None = None,
) -> str:
    """
    Extrai o ZIP da BDGD para uma pasta permanente e retorna o caminho do .gdb.

    Regra:
    - Destino: <base_path>/BDGDs Extraídas/<nome_zip_sem_extensão>/
    - Se o .gdb já existir lá, não extrai novamente.

    Args:
        zip_path:  Caminho completo do arquivo .zip.
        base_path: Pasta raiz da aplicação.
        callback:  Função opcional(str) para feedback de progresso.

    Returns:
        Caminho absoluto da pasta .gdb extraída.
    """
    nome_zip  = Path(zip_path).stem          # nome sem .zip
    dest_dir  = os.path.join(pasta_extraidas(base_path), nome_zip)
    os.makedirs(dest_dir, exist_ok=True)

    # Verificar se já existe um .gdb extraído
    gdb_path = _localizar_gdb(dest_dir)

    if gdb_path:
        if callback:
            callback(f"GDB já extraído: {os.path.basename(gdb_path)}")
        return gdb_path

    # Extrair ZIP
    if callback:
        callback(f"Extraindo {os.path.basename(zip_path)}...")

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)

    if callback:
        callback("Extração concluída. Localizando pasta .gdb...")

    gdb_path = _localizar_gdb(dest_dir)

    if not gdb_path:
        raise RuntimeError(
            f"Pasta .gdb não encontrada após extrair {zip_path}.\n"
            f"Conteúdo em: {dest_dir}"
        )

    if callback:
        callback(f"GDB localizado: {os.path.basename(gdb_path)}")

    return gdb_path


def _localizar_gdb(root_dir: str) -> str | None:
    """Busca recursivamente a primeira pasta .gdb dentro de root_dir."""
    for dirpath, dirnames, _ in os.walk(root_dir):
        for d in dirnames:
            if d.lower().endswith(".gdb"):
                return os.path.join(dirpath, d)
    return None


def gdb_ja_extraido(zip_path: str, base_path: str) -> bool:
    """Retorna True se o ZIP já foi extraído e o .gdb está disponível."""
    nome_zip = Path(zip_path).stem
    dest_dir = os.path.join(pasta_extraidas(base_path), nome_zip)
    return _localizar_gdb(dest_dir) is not None


# ---------------------------------------------------------------------------
# Leitura de alimentadores do GDB
# ---------------------------------------------------------------------------

def listar_alimentadores_gdb(gdb_path: str) -> list[str]:
    """
    Lê a camada CTMT do GDB e retorna a lista de alimentadores (COD_ID).
    Usa fiona para leitura sem precisar de DuckDB.
    """
    try:
        layers = fiona.listlayers(gdb_path)
    except Exception as e:
        raise RuntimeError(f"Não foi possível ler o GDB: {e}") from e

    if "CTMT" not in layers:
        raise RuntimeError(
            "Camada CTMT não encontrada no GDB. "
            "Verifique se o arquivo é uma BDGD válida."
        )

    alimentadores = []
    with fiona.open(gdb_path, layer="CTMT") as src:
        for feat in src:
            cod = feat["properties"].get("COD_ID")
            if cod:
                alimentadores.append(str(cod))

    return sorted(set(alimentadores))


# ---------------------------------------------------------------------------
# Conversão via bdgd2opendss
# ---------------------------------------------------------------------------

def aplicar_settings(cfg: dict) -> None:
    """
    Aplica as configurações do dicionário cfg ao módulo settings do bdgd2opendss.
    Somente aplica valores que diferem do padrão para evitar efeitos colaterais.
    """
    try:
        import bdgd2opendss as bdgd  # noqa: F401
        from bdgd2opendss import settings
    except ImportError as e:
        raise ImportError(
            "Biblioteca bdgd2opendss não encontrada.\n"
            "Instale com: pip install bdgd2opendss"
        ) from e

    for chave, valor in cfg.items():
        if hasattr(settings, chave):
            setattr(settings, chave, valor)


def converter_alimentadores(
    gdb_path: str,
    alimentadores: list[str] | None,
    cfg_settings: dict,
    pasta_saida: str,
    callback: Callable[[str], None] | None = None,
    cancelar_flag: threading.Event | None = None,
) -> list[str]:
    """
    Executa a conversão BDGD → OpenDSS para os alimentadores informados.

    Args:
        gdb_path:       Caminho da pasta .gdb.
        alimentadores:  Lista de COD_IDs a converter. None = todos.
        cfg_settings:   Dicionário {nome_setting: valor} a aplicar.
        pasta_saida:    Pasta base onde os arquivos DSS serão gravados.
        callback:       Função opcional(str) para log em tempo real.
        cancelar_flag:  threading.Event — quando set(), interrompe antes de iniciar.

    Returns:
        Lista de alimentadores convertidos com sucesso.
    """
    try:
        import bdgd2opendss as bdgd
    except ImportError as e:
        raise ImportError(
            "Biblioteca bdgd2opendss não encontrada.\n"
            "Instale com: pip install bdgd2opendss"
        ) from e

    warnings.filterwarnings("ignore", category=RuntimeWarning)
    warnings.filterwarnings("ignore", category=FutureWarning)

    aplicar_settings(cfg_settings)

    os.makedirs(pasta_saida, exist_ok=True)

    todos_feeders   = alimentadores is None
    feeders_lista   = None if todos_feeders else list(alimentadores)
    convertidos: list[str] = []

    if callback:
        n = "todos" if todos_feeders else str(len(feeders_lista))
        callback(f"Iniciando conversão de {n} alimentador(es)...")
        callback(f"GDB: {gdb_path}")
        callback(f"Saída: {pasta_saida}")

    # Verificar cancelamento antes de começar
    if cancelar_flag is not None and cancelar_flag.is_set():
        if callback:
            callback("⚠ Cancelado antes de iniciar.")
        return convertidos

    # A biblioteca bdgd2opendss grava os arquivos no diretório de trabalho atual.
    # Mudamos o cwd para pasta_saida para que os arquivos fiquem organizados lá.
    cwd_original = os.getcwd()

    try:
        os.chdir(pasta_saida)

        if callback:
            callback("Chamando bdgd2opendss...")

        # Capturar prints da biblioteca redirecionando stdout
        import io
        import sys

        class _LogCapture(io.StringIO):
            def __init__(self, cb):
                super().__init__()
                self._cb = cb
                self._original = sys.__stdout__

            def write(self, s):
                self._original.write(s)
                stripped = s.strip()
                if stripped and self._cb:
                    self._cb(stripped)

            def flush(self):
                self._original.flush()

        if callback:
            log_capture = _LogCapture(callback)
            sys.stdout = log_capture
        
        try:
            bdgd.run(
                bdgd_file_path=gdb_path,
                all_feeders=todos_feeders,
                lst_feeders=feeders_lista,
            )
        finally:
            sys.stdout = sys.__stdout__

        if callback:
            callback("Conversão finalizada pela biblioteca.")

        # Descobrir quais alimentadores foram gerados (subpastas criadas)
        for item in os.listdir(pasta_saida):
            if os.path.isdir(os.path.join(pasta_saida, item)):
                convertidos.append(item)

    except Exception as e:
        if callback:
            callback(f"Erro durante conversão: {e}")
        raise

    finally:
        os.chdir(cwd_original)

    if callback:
        callback(
            f"✔ Concluído. {len(convertidos)} alimentador(es) na pasta de saída."
        )

    return convertidos


# ---------------------------------------------------------------------------
# Listagem de ZIPs e GDBs disponíveis
# ---------------------------------------------------------------------------

def listar_zips(bdgds_path: str) -> list[str]:
    """Retorna ZIPs disponíveis na pasta de BDGDs."""
    if not os.path.exists(bdgds_path):
        return []
    return sorted(f for f in os.listdir(bdgds_path) if f.endswith(".zip"))


def listar_gdbs_extraidos(base_path: str) -> list[dict]:
    """
    Retorna lista de GDBs já extraídos em BDGDs Extraídas/.
    Cada item: {"nome": str, "gdb_path": str}
    """
    ext_dir = pasta_extraidas(base_path)
    resultado = []

    for subdir in sorted(os.listdir(ext_dir)):
        full = os.path.join(ext_dir, subdir)
        if not os.path.isdir(full):
            continue
        gdb = _localizar_gdb(full)
        if gdb:
            resultado.append({"nome": subdir, "gdb_path": gdb})

    return resultado


def pasta_saida_conversao(base_path: str, nome_bdgd: str) -> str:
    """
    Retorna (e cria) a pasta de saída para os arquivos DSS de uma BDGD.
    Estrutura: <base_path>/Alimentadores Convertidos/<nome_bdgd>/
    """
    p = os.path.join(base_path, "Alimentadores Convertidos", nome_bdgd)
    os.makedirs(p, exist_ok=True)
    return p
