# Local application

The browser workbench runs on your computer at `http://127.0.0.1:8767/`. Opening it leaves the solver idle. It has bounded CPU constraint jobs, CPU or NVIDIA CUDA family scans, saved runs, candidate explanations and JSON export. No answer is submitted to an outside service.

## Setup and launch

CPU use needs Python 3.10 or later and only its standard library. Setup creates `.venv` when absent and preserves an existing environment. It verifies imports and installs no network packages unless GPU setup is explicitly requested.

On Windows, double-click `Setup.cmd` once, then `OpenDashboard.cmd`, or run:

```powershell
.\Setup.cmd
.\OpenDashboard.cmd
```

For optional NVIDIA GPU dependencies:

```powershell
.\Setup.cmd -Gpu
.\OpenDashboard.cmd
```

The tested GPU environment is 64-bit Python 3.12.2, an NVIDIA RTX 2060, `cupy-cuda12x==14.2.0`, `nvidia-cuda-runtime-cu12==12.9.79` and `nvidia-cuda-nvrtc-cu12==12.9.86`. These are the pins in `requirements-gpu.txt`. A compatible NVIDIA driver is also required; setup does not install drivers. Windows setup prefers Python 3.12 when creating a new environment. `-Python C:\path\python.exe` selects another creation interpreter, without replacing an existing `.venv`.

On Linux or macOS, CPU launch is:

```sh
sh Setup.sh
sh OpenDashboard.sh
```

`sh Setup.sh --gpu` requests the optional CUDA packages. GPU use requires a platform supported by that CUDA stack and an NVIDIA device; macOS has no supported CUDA backend here. Unix launcher syntax is provided; the recorded hardware test was on Windows. To select an interpreter, use `--python /path/to/python`.

Launchers install nothing. They prefer `.venv` and otherwise use a compatible system Python. To bypass them:

```text
python -B -m kryptos.app
```

Useful options are `-Port 8768`, `-NoBrowser`, `-SkipGpuProbe` and `-StateDir path` for the PowerShell launcher, or `--port`, `--no-browser`, `--skip-gpu-probe` and `--state-dir` for the Unix launcher/Python module. Port 0 selects an available local port and prints its address. Each launcher has `-Help`/`--help`. `--skip-gpu-probe` avoids the small compiled CUDA readiness check, leaving CPU operation available.

## First experiment

1. Choose a control preset to check the workflow, or K4 to test a stated hypothesis. The public K4 letters and 24 known plaintext letters are preloaded.
2. Choose the displayed recipe, backend and finite bounds. CPU constraints and accelerated family scans are different job types; CUDA applies only to supported scans.
3. Select **Start experiment**. Inspect the recorded assumptions, progress and candidates. Use **Run details** or **Export run** to retain inputs, bounds, hashes and replay evidence.

Custom and exploratory K5 inputs require explicit ciphertext. The project has no authenticated public K5 ciphertext to preload. Changing the passage does not turn K4 clues into K5 evidence.

## Job controls and persistence

The default local state directory is `runtime/`, excluded from version control. Completed pages advance the durable scan position. Saved runs can be inspected and resumed when their request, source revision and scoring model still match.

- **Pause** finishes the current wave of family-scan pages, commits it, then pauses. It is not an immediate interruption. Exact constraint commands can be stopped/restarted; they do not expose page pause.
- **Stop** terminates current workers and discards the in-flight wave. Earlier committed pages and results remain. Resuming repeats work from the last committed position.
- The displayed run time limit is checked **between waves**. It is not a strict deadline for an already running wave. Each worker has a separate **60-second outer deadline**; reduce batch size or command bounds if a worker reaches it.
- CPU family scans can use up to four workers. CUDA uses one worker/context. More workers can increase resource use without improving useful throughput.
- Ctrl+C in the launcher terminal shuts down the service. Closing the browser alone does not stop the server or its work. An interrupted service is recovered from saved state on restart; a changed source/model identity prevents incompatible resume.

The service binds only to loopback and checks host, origin and a local session token for control requests. It is a local research tool, not a public multi-user web service or a BOINC server.

## What the scores mean

CPU pages use exact integer products for their frozen n-gram objective, with deterministic ties. CUDA evaluates letters with exact integer arithmetic but uses floating-point scores to select a shortlist. Retained candidates are rescored exactly and independently re-encrypted on CPU. **A CUDA shortlist is approximate unless every candidate in that page was exactly rescored.** CPU replay proves consistency of retained candidates; it does not prove that a GPU shortlist contains every best candidate.

Completion and ranking apply to the declared family, page range, bounds and model. A page reaching the family end does not prove that earlier pages were evaluated. Saved run records preserve actual committed coverage. Known plaintext positions and every n-gram touching them are excluded from ordinary ranking. A separate reporting-only sensitivity check can additionally mask letters fixed indirectly by the model; no surviving windows means unavailable, and this does not silently change ranking.

Neither K4 nor K5 has been deciphered by this project. Crib fits, fluent text, exact re-encryption and high scores are insufficient to authenticate a solution. The recorded historical controls and model exclusions are described in [checkpoint K](../research/IMPROVEMENTS_K.md); they do not establish the sculpture's actual method.

## Files and reproduction

The package retains normalized sculpture data and frozen language-count models. Ordinary geometry checks the pinned normalized dataset and does not require downloaded HTML. The explicit source-audit loader still requires the original source snapshots. The optional raw books, third-party page/code caches, runtime state and bulky historical results stay local; research scripts that need them explain their additional inputs. See [source distribution](SOURCE_DISTRIBUTION.md) and [third-party notices](../THIRD_PARTY_NOTICES.md).

The research CLI remains available; use [checkpoint K commands](CLI_CHECKPOINT_K.md) and [earlier examples](CLI_EXAMPLES.md). Run the CPU test suite from the repository root with:

```text
python -B -m unittest discover -s tests -v
```

GPU tests are opt-in with `KRYPTOS_TEST_CUDA=1` in the configured GPU environment. An optional raw-source audit skips when its excluded snapshots are absent; the packaged-data integrity checks still run. Test output, source versions and actual device evidence are more useful than treating a historical test count as a guarantee for another machine.
