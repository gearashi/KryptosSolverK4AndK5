# Kryptos K4 and K5 research workbench

A local browser application for bounded CPU and optional NVIDIA GPU experiments on Kryptos. It includes exact cipher constraints, explicit sculpture-grid hypotheses, language comparisons, candidate explanations, replay checks and resumable family scans.

**This project has not deciphered K4 or K5.** Public K4 ciphertext and 24 known plaintext letters are included. There is no authenticated public K5 ciphertext in the reviewed sources; K5 experiments require your own explicit input.

## Start the application

CPU use requires Python 3.10 or newer and only the standard library. On Windows, double-click `Setup.cmd` once, then `OpenDashboard.cmd`, or run:

```powershell
.\Setup.cmd
.\OpenDashboard.cmd
```

The dashboard opens at `http://127.0.0.1:8767/` and remains idle until **Start experiment**. Setup creates a project `.venv` if needed and preserves an existing one. It downloads no packages for CPU use.

Optional NVIDIA GPU setup is explicit:

```powershell
.\Setup.cmd -Gpu
.\OpenDashboard.cmd
```

The tested CUDA environment uses an RTX 2060 and 64-bit Python 3.12.2. Exact package versions are pinned in [requirements-gpu.txt](requirements-gpu.txt); a compatible NVIDIA driver is required. Setup does not install drivers.

On Linux or macOS, use `sh Setup.sh` and `sh OpenDashboard.sh` for CPU operation. Optional CUDA setup is `sh Setup.sh --gpu` on a supported NVIDIA platform. The hardware validation was performed on Windows. Direct launch from any compatible environment is `python -B -m kryptos.app`.

See [the local application guide](docs/LOCAL_APP.md) for interpreter selection, ports, setup options, presets and exports.

## Controls and interpretation

- CPU scans use exact integer scoring. CUDA computes an approximate floating-point shortlist, then rescoring and full encryption replay occur on CPU. A shortlist is only exhaustive when every candidate in its page was exactly rescored.
- **Pause** completes and commits the current scan wave. **Stop** discards its in-flight work and preserves earlier committed results. Resume uses the saved position and checks source/model identity.
- The run time budget is checked between waves; every worker has a separate 60-second outer deadline. CPU family scans support up to four workers; CUDA uses one worker/context.
- Known clue letters and every n-gram touching them are masked from ordinary language scoring. A reporting-only sensitivity diagnostic can also mask letters fixed indirectly by the model.
- Re-encryption, crib consistency and a high language score do not authenticate a solution. Results describe their assumptions and actual bounded coverage. Nothing is submitted to an external service.

The server binds to loopback. Closing a browser tab does not stop it; use Ctrl+C in the launcher terminal to close the service. Saved state is local to `runtime/`. This is a local workbench, not a BOINC server.

## Research tools

The CLI remains available alongside the dashboard:

```text
python -m kryptos doctor
python -m kryptos layout
python -m kryptos layers --request examples/layers-small.json
python -m kryptos joint --request examples/joint-ragged.json
python -m kryptos scheduled --request examples/scheduled-shared.json
python -m kryptos mixed --request examples/mixed-shared.json
python -m kryptos optimize-plus --request examples/optimize-lazy.json
python -m kryptos batch --request examples/batch-lazy.json
```

See [checkpoint K commands](docs/CLI_CHECKPOINT_K.md), [earlier command examples](docs/CLI_EXAMPLES.md), [bounded results and limits](research/IMPROVEMENTS_K.md), and [the research history](research/STATUS.md). These document joint column/key recovery, shared keys and offsets, multiple known alphabets, coordinate-driven schedules, fractionation, arbitrary substitution feasibility, semantic hypotheses and exact constraint witnesses. The normalized sculpture dataset represents ordinal textual coordinates, not measured three-dimensional geometry.

Historical controls include independently published PK fixtures and 175,760 crib-compatible language completions. Their supplied methods, artificial clues, model choices and ambiguity limits are recorded in [PK benchmark notes](research/pk_benchmark_notes.md) and [checkpoint K](research/IMPROVEMENTS_K.md). They test the tools within declared assumptions; they do not establish Kryptos's actual method.

## Validation and packaged data

The curated publication checkout ran **256 tests: 255 passed and one optional raw-source audit skipped** because the original third-party pages are not distributed. Actual NVIDIA GPU tests passed. Browser checks exercised CPU workers, pause/resume/stop, history, export, candidate explanations and an actual CUDA page at desktop and mobile sizes. Small reproducible CPU/GPU and pruning audits are retained in `research/runs/release-L-002/`; their manifests also validate against the packaged checkout. See [release validation](research/release-validation.json) and [the research history](research/STATUS.md) for scope and limitations.

Run the CPU suite with:

```text
python -B -m unittest discover -s tests -v
```

GPU tests require `KRYPTOS_TEST_CUDA=1` in the configured GPU environment. An optional raw-source audit skips when its excluded snapshots are absent; packaged dataset integrity tests still run.

Frozen language-count models, normalized fixtures and the authored code snapshots needed by the release audits are included. Downloaded full books, third-party page/code caches, runtime state and bulky historical outputs remain local. Some historical research scripts therefore require separately obtaining the cited inputs. See [source distribution](docs/SOURCE_DISTRIBUTION.md) and [third-party notices](THIRD_PARTY_NOTICES.md). No license for the project code is implied by these notices.
