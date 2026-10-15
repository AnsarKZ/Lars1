"""python -m perfdash  ->  site/index.html (+ model tables in out/model/)"""
from pathlib import Path
import argparse

from .build import main

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Build the performance dashboard.")
    p.add_argument("--out", default="site/index.html")
    p.add_argument("--model-dir", default="out/model", help="where to write the model tables as CSV")
    a = p.parse_args()
    path = main(Path(a.out), Path(a.model_dir))
    print(f"Dashboard written to {path}")
