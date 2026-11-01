"""Repository paths, resolved from this file so the package works from any cwd."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
CACHE = DATA / "cache"
CONFIGS = ROOT / "configs"
OUTPUTS = ROOT / "outputs"
LABELS = ROOT / "labels"
ONTOLOGY_DIR = ROOT / "ontology"
SOURCES = ROOT / "sources.yaml"
DUCKDB = DATA / "firmable.duckdb"
