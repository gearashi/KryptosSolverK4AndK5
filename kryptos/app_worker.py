"""Private, finite file-protocol worker for the local dashboard."""
import argparse
import json
from pathlib import Path

from .advanced_cli import json_safe_integers,run_advanced
from .__main__ import _target,run_recovery,run_layers,run_grid,run_residues
from .next_cli import run_next


def execute(job):
    if job["kind"]=="accelerated":
        from .accelerated import scan_batch
        return scan_batch(job["request"],backend=job["backend"],offset=int(job["offset"]),
                          batch_size=job["batch_size"],top=job["top"])
    command=job["command"]
    first={"recover":run_recovery,"layers":run_layers,"grid":run_grid,"residues":run_residues}
    if command in first:
        return first[command](job["request"])
    if command in {"joint","scheduled","mixed","alphabet-plus","optimize-plus"}:
        return run_next(command,job["request"],_target)
    return run_advanced(command,job["request"],_target)


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--job",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    args=p.parse_args()
    job=json.loads(args.job.read_text(encoding="utf-8"))
    result=execute(job)
    with args.output.open("x",encoding="utf-8") as stream:
        json.dump(json_safe_integers(result),stream,allow_nan=False)
