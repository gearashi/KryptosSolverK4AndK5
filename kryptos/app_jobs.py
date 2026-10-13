"""Durable local jobs. Only completed pages advance the saved scan frontier."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

from .advanced_cli import json_safe_integers
from .parallel_search import _decode
from .__main__ import _target

ROOT=Path(__file__).resolve().parents[1]
EXACT_COMMANDS={"joint","scheduled","mixed","alphabet-plus","optimize-plus","general","columns","alphabet","optimize","recover","layers","grid","residues","layout"}
MODELS=[{"id":name,"label":name.title()+" · two authors","path":f"research/runs/evaluation-J-001/artifacts/{name}-two-author-trigram.json"}
        for name in ("english","spanish","french","italian","latin")]
MODELS.append({"id":"english-pilot","label":"English · pilot control","path":"research/models/multilingual-001/artifacts/pg1342-english-trigram.json"})
MODEL_PATHS={m["path"] for m in MODELS}
ACTIVE={"running","pausing","stopping"}


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path,value):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
    try:
        with temporary.open("x",encoding="utf-8") as stream:
            json.dump(json_safe_integers(value),stream,allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if temporary.exists():
            temporary.unlink()


def integer(value,name,lo,hi):
    if type(value) is not int or not lo<=value<=hi:
        raise ValueError(f"{name} must be an integer in {lo}..{hi}")
    return value


def validate_start(body):
    allowed={"kind","command","request","backend","workers","batch_size","max_batches","time_limit_seconds","note"}
    if not isinstance(body,dict) or set(body)-allowed:
        raise ValueError("Unknown run setting")
    kind=body.get("kind","exact")
    command=body.get("command","joint")
    backend=body.get("backend","cpu")
    if kind not in ("exact","accelerated") or command not in EXACT_COMMANDS or backend not in ("cpu","cuda","auto"):
        raise ValueError("Unsupported run kind, command or backend")
    if kind=="exact" and backend=="cuda":
        raise ValueError("This constraint command runs on CPU; choose a family scan for CUDA")
    request=copy.deepcopy(body.get("request",{}))
    if not isinstance(request,dict):
        raise ValueError("Recipe request must be an object")
    if {"checkpoint_path","resume_path"}&set(request):
        raise ValueError("The dashboard manages its own saved run paths")
    if "model_path" in request and request["model_path"] not in MODEL_PATHS:
        raise ValueError("Select a bundled scoring model")
    target,text,cribs,known=_target(request)
    if len(text)>512:
        raise ValueError("Dashboard messages are limited to 512 letters")
    request.update(target=target,ciphertext=text,cribs=cribs)
    caps={"max_nodes":100000,"max_states":200000,"max_segmentations":4096,"max_candidates":1000,
          "top":100,"max_key_slots":256,"max_matrix_cells":2000000,"max_operations":20000000,
          "max_relation_checks":2000000,"max_distinct_plaintexts":10000,"max_constraints":4096,
          "max_frontier":20000,"max_cache_entries":100000,"local_exact_limit":4096}
    for name,cap in caps.items():
        if name in request:
            integer(request[name],name,0,cap)
    if "time_limit_seconds" in request:
        value=request["time_limit_seconds"]
        if type(value) not in (int,float) or not math.isfinite(value) or not 0<value<=10:
            raise ValueError("Per-command time_limit_seconds must be in (0,10]")
    if "stages" in request and (not isinstance(request["stages"],list) or not 1<=len(request["stages"])<=16):
        raise ValueError("Supply 1..16 stages")
    settings={"backend":backend,"workers":integer(body.get("workers",1),"workers",1,4),
        "batch_size":integer(body.get("batch_size",512),"batch_size",1,8192),
        "max_batches":integer(body.get("max_batches",100),"max_batches",1,1000000),
        "time_limit_seconds":integer(body.get("time_limit_seconds",60),"time_limit_seconds",1,86400)}
    if kind=="accelerated":
        if command!="optimize-plus":
            raise ValueError("Family scans use an optimize-plus general/scheduled recipe")
        if "model_path" not in request:
            raise ValueError("Select a frozen model for a family scan")
        if backend in ("cuda","auto"):
            settings["workers"]=1  # One CUDA context; do not multiply GPU memory by worker count.
    note=body.get("note","")
    if not isinstance(note,str) or len(note)>1000:
        raise ValueError("Source/assumptions note must be at most 1000 characters")
    if kind=="exact":
        settings["workers"]=1
    return {"kind":kind,"command":command,"request":request,"settings":settings,"note":note}


def source_identity(request):
    files=sorted((ROOT/"kryptos").glob("*.py"))
    if "model_path" in request:
        files.append(ROOT/request["model_path"])
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def scan_sort(candidate):
    value=candidate.get("score_exact",0)
    exact=int(value,16) if isinstance(value,str) else value
    return (-exact,candidate.get("plaintext",""),int(candidate.get("assignment_index_decimal","0")))


class _DirectoryOwnership:
    """OS lock, released on handle/process exit; the stable lock file is kept."""
    def __init__(self,path):
        handle=Path(path).open("a+b")
        try:
            if os.name=="nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as error:
            handle.close()
            raise RuntimeError("This state directory is already owned by another app manager, or its OS lock is unavailable. Close the other app or select a different state directory.") from error
        self.handle=handle

    def close(self):
        if self.handle is not None:
            self.handle.close()  # Closing releases the OS lock, including after process death.
            self.handle=None


class RunManager:
    def __init__(self,state_dir,python=None):
        self.directory=Path(state_dir).resolve()
        self.directory.mkdir(parents=True,exist_ok=True)
        self.python=str(python or sys.executable)
        self.worker_env=os.environ.copy()
        for name,part in (("TEMP","tmp"),("TMP","tmp"),("CUPY_CACHE_DIR","cupy")):
            destination=self.directory.parent/"cache"/part
            destination.mkdir(parents=True,exist_ok=True)
            self.worker_env[name]=str(destination)
        self.lock=threading.RLock()
        self.records={}
        self.current=None
        self.thread=None
        self.desired=None
        self._closed=False
        self._ownership=_DirectoryOwnership(self.directory/".owner.lock")
        try:
            self._load_records()
        except BaseException:
            self._ownership.close()
            self._closed=True
            raise

    def _load_records(self):
        for path in sorted(self.directory.glob("*/run.json")):
            try:
                value=_decode(json.loads(path.read_text(encoding="utf-8")))
                if value.get("schema")!="kryptos.local-run.v1" or path.parent.name!=value["id"]:
                    continue
                if value["state"] in ACTIVE:
                    value.update(state="interrupted",error="The local server ended before this run finished. Resume repeats only uncommitted work.",updated_at=now())
                    atomic_json(path,value)
                self.records[value["id"]]=value
                value.setdefault("ranking_exact_over_committed_pages",False if value.get("kind")=="accelerated" and value.get("progress",{}).get("completed",0) else None)
                value.setdefault("backends_used",[])
                value.setdefault("fallback_reasons",[])
            except (ValueError,KeyError,OSError):
                continue
        if self.records:
            self.current=max(self.records,key=lambda key:self.records[key]["updated_at"])

    def _save(self,record):
        record["updated_at"]=now()
        atomic_json(self.directory/record["id"]/"run.json",record)

    def view(self,run_id=None):
        with self.lock:
            key=run_id or self.current
            if key is None:
                return None
            if key not in self.records:
                raise KeyError("Run not found")
            value=copy.deepcopy(self.records[key])
            value["can_pause"]=value["state"]=="running" and value["kind"]=="accelerated"
            value["can_resume"]=value["state"] in {"paused","stopped","limited","interrupted","failed"}
            value["progress"]["completed_decimal"]=str(value["progress"]["completed"])
            total=value["progress"]["total"]
            value["progress"]["total_decimal"]=str(total) if total is not None else None
            return value

    def list_runs(self):
        with self.lock:
            return [{k:v for k,v in self.view(key).items() if k not in {"candidates","result","source_identity"}}
                    for key in sorted(self.records,key=lambda k:self.records[k]["created_at"],reverse=True)]

    def _idle(self):
        if self._closed:
            raise ValueError("This app manager is closed")
        if self.thread is not None and self.thread.is_alive():
            raise ValueError("Wait for the current run to pause or stop first")

    def start(self,body):
        config=validate_start(body)
        with self.lock:
            self._idle()
            key=uuid.uuid4().hex
            record={"schema":"kryptos.local-run.v1","id":key,"state":"running",**config,
                "created_at":now(),"updated_at":now(),"progress":{"completed":0,"total":None if config["kind"]=="accelerated" else 1,
                 "unit":"candidates" if config["kind"]=="accelerated" else "jobs"},
                "elapsed_seconds":0.0,"rate":0.0,"candidates":[],"result":None,"error":None,
                "backend_requested":config["settings"]["backend"],"backend_actual":None,"batches_committed":0,
                "ranking_exact_over_committed_pages":None,"backends_used":[],"fallback_reasons":[],
                "source_identity":source_identity(config["request"]),"authenticated_solution":False}
            self._save(record)
            self.records[key]=record
            self.current=key
            self._begin(key)
            return self.view(key)

    def _begin(self,key):
        self.desired=None
        self.thread=threading.Thread(target=self._run,args=(key,),daemon=True,name="kryptos-job")
        self.thread.start()

    def control(self,action,key):
        with self.lock:
            if self._closed:
                raise ValueError("This app manager is closed")
            if key not in self.records:
                raise KeyError("Run not found")
            record=self.records[key]
            if action=="resume":
                self._idle()
                if record["state"] not in {"paused","stopped","limited","interrupted","failed"}:
                    raise ValueError("This run cannot be resumed")
                if source_identity(record["request"])!=record["source_identity"]:
                    raise ValueError("Solver or model files changed. Start a new run to preserve provenance.")
                staged=dict(record,state="running",error=None)
                self._save(staged)
                record.update(staged)
                self.current=key
                self._begin(key)
            else:
                if key!=self.current or record["state"] not in ACTIVE:
                    raise ValueError("This run is not active")
                if action=="pause" and record["kind"]!="accelerated":
                    raise ValueError("This exact command can be stopped and restarted; page pause applies to family scans")
                staged=dict(record,state="pausing" if action=="pause" else "stopping")
                self._save(staged)
                record.update(staged)
                self.desired=action
            return self.view(key)

    def _launch(self,key,job):
        self._require_identity(self.records[key])
        folder=self.directory/key/"work"
        folder.mkdir(exist_ok=True)
        token=uuid.uuid4().hex
        input_path=folder/(token+"-job.json")
        output_path=folder/(token+"-result.json")
        error_path=folder/(token+"-stderr.txt")
        atomic_json(input_path,job)
        flags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0
        try:
            with error_path.open("w",encoding="utf-8") as errors:
                process=subprocess.Popen([self.python,"-B","-m","kryptos.app_worker","--job",str(input_path),"--output",str(output_path)],
                    cwd=ROOT,stdout=subprocess.DEVNULL,stderr=errors,creationflags=flags,env=self.worker_env)
                started=time.monotonic()
                try:
                    while process.poll() is None:
                        if self.desired=="stop":
                            raise InterruptedError("Stopped before this page committed")
                        if time.monotonic()-started>60:
                            raise TimeoutError("Worker exceeded its 60-second outer limit; reduce the batch or command bounds")
                        time.sleep(0.05)
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=3)
            if process.returncode:
                raise RuntimeError(error_path.read_text(encoding="utf-8",errors="replace")[-3000:])
            if not output_path.exists() or output_path.stat().st_size>32*1024*1024:
                raise RuntimeError("Worker produced no usable bounded result")
            return _decode(json.loads(output_path.read_text(encoding="utf-8")))
        finally:
            # Worker inputs/results are transient; the atomically saved run owns
            # every committed result. Only private named files are removed.
            for path in (input_path,output_path,error_path):
                if path.exists():
                    path.unlink()

    def _require_identity(self,record,results=()):
        if source_identity(record["request"])!=record["source_identity"]:
            raise ValueError("Solver or model files changed during this run; no new page was committed. Start a new run to preserve provenance.")
        for result in results:
            if "source_sha256" in result:
                expected={key.removeprefix("kryptos/"):value for key,value in record["source_identity"].items() if key.startswith("kryptos/")}
                if result["source_sha256"]!=expected:
                    raise ValueError("Worker solver identity differs from this run; no new page was committed")
            model=record["request"].get("model_path")
            if model and "model_file_sha256" in result and result["model_file_sha256"]!=record["source_identity"][model]:
                raise ValueError("Worker scoring model differs from this run; no new page was committed")

    def _run(self,key):
        record=self.records[key]
        started=time.monotonic()
        prior_elapsed=record["elapsed_seconds"]
        initial_batches=record["batches_committed"]
        settings=record["settings"]
        try:
            if record["kind"]=="exact":
                self._require_identity(record)
                result=self._launch(key,{"kind":"exact","command":record["command"],"request":record["request"]})
                with self.lock:
                    self._require_identity(record,[result])
                    record["result"]=result
                    record["candidates"]=result.get("candidates",[])
                    if "optimization" in result:
                        record["candidates"]=[result["optimization"]["candidate"]]
                    record["progress"].update(completed=1,total=1)
                    record["batches_committed"]+=1
                    record.update(state="completed",backend_actual="cpu",backends_used=["cpu"])
            else:
                while True:
                    with self.lock:
                        if self.desired:
                            record["state"]="paused" if self.desired=="pause" else "stopped"
                            break
                        if time.monotonic()-started>=settings["time_limit_seconds"] or record["batches_committed"]-initial_batches>=settings["max_batches"]:
                            record["state"]="limited"
                            break
                        self._require_identity(record)
                        offset=record["progress"]["completed"]
                        total=record["progress"]["total"]
                        workers=min(settings["workers"],settings["max_batches"]-(record["batches_committed"]-initial_batches))
                        if total is None:
                            workers=1  # First page establishes exact family size.
                        jobs=[]
                        for i in range(workers):
                            page=offset+i*settings["batch_size"]
                            if total is not None and page>=total:
                                break
                            jobs.append({"kind":"accelerated","request":record["request"],"backend":settings["backend"],
                                         "offset":page,"batch_size":settings["batch_size"],"top":20})
                    if not jobs:
                        with self.lock:
                            record["state"]="completed"
                        break
                    with ThreadPoolExecutor(max_workers=len(jobs)) as executor:
                        results=list(executor.map(lambda job:self._launch(key,job),jobs))
                    with self.lock:
                        self._require_identity(record,results)
                        unresolved=next((result for result in results if result.get("feasible","unspecified") is None
                                         or result.get("stop_reason")=="algebra_budget"),None)
                        if unresolved is not None:
                            record["result"]={k:v for k,v in unresolved.items() if k!="candidates"}
                            record.update(state="limited",error="The algebra resource bound was reached; feasibility is unresolved and no new page was committed. Resuming unchanged bounds will repeat this result; start a new request with suitable bounds or a smaller model.")
                            self._save(record)
                            break
                        merged=record["candidates"][:]
                        for result in results:
                            total=int(result.get("total_decimal",result.get("total",0)))
                            next_offset=int(result.get("next_offset_decimal",result.get("next_offset",0)))
                            merged.extend(result.get("candidates",[]))
                            record["progress"].update(completed=next_offset,total=total)
                            record["backend_actual"]=result.get("backend_used",settings["backend"])
                            backend=result.get("backend_used")
                            if backend is not None and backend not in record["backends_used"]:
                                record["backends_used"].append(backend)
                                record["backends_used"].sort()
                            if result.get("evaluated",0):
                                exact=result.get("ranking_exact_within_page") is True
                                previous=record["ranking_exact_over_committed_pages"]
                                record["ranking_exact_over_committed_pages"]=exact if previous is None else previous and exact
                            reason=result.get("fallback_reason")
                            if reason and reason not in record["fallback_reasons"]:
                                record["fallback_reasons"].append(reason)
                            record["result"]={k:v for k,v in result.items() if k!="candidates"}
                            record["batches_committed"]+=1
                        unique={}
                        for candidate in sorted(merged,key=scan_sort):
                            unique.setdefault(candidate["plaintext"],candidate)
                        record["candidates"]=list(unique.values())[:20]
                        record["elapsed_seconds"]=prior_elapsed+time.monotonic()-started
                        record["rate"]=record["progress"]["completed"]/max(record["elapsed_seconds"],0.001)
                        if record["progress"]["completed"]>=total:
                            record["state"]="completed"
                        self._save(record)
                        if record["state"]=="completed":
                            break
        except InterruptedError:
            with self.lock:
                record["state"]="stopped"
        except Exception as error:
            with self.lock:
                record.update(state="failed",error=str(error))
        finally:
            with self.lock:
                record["elapsed_seconds"]=prior_elapsed+time.monotonic()-started
                record["rate"]=record["progress"]["completed"]/max(record["elapsed_seconds"],0.001)
                self._save(record)

    def close(self):
        with self.lock:
            self._closed=True
            self.desired="stop"
        if self.thread is not None:
            self.thread.join(timeout=10)
            if self.thread.is_alive():
                # Do not allow a replacement manager while this writer is alive.
                raise RuntimeError("Worker shutdown is still pending; state-directory ownership was retained")
        with self.lock:
            self._ownership.close()
