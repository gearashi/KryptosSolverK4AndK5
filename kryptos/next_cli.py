"""Checkpoint-K interfaces for linked cipher constraints and resumable search."""
import hashlib
import json
from pathlib import Path
import time

from .advanced_cli import _integer,_candidate
from .explanations import replay_recipe
from .replay_expanded import replay_expanded

ROOT=Path(__file__).resolve().parents[1]
BASE={"target","ciphertext","cribs"}
LINEAR_LIMITS={"max_key_slots","max_matrix_cells","max_operations"}
SEARCH_LIMITS={"max_nodes","time_limit_seconds","max_frontier","max_cache_entries","local_exact_limit","ordering","resume_path","checkpoint_path"}


def _algebra_budget_result(error,request,stages,phase_provenance):
    return {"feasible":None,"complete":False,"truncated":True,"stop_reason":"algebra_budget",
            "detail":str(error),"candidates":[],
            "bounds":{key:request.get(key,default) for key,default in
                      (("max_key_slots",256),("max_matrix_cells",2000000),("max_operations",20000000))},
            "model_assumptions":{"stages":stages,"alphabet":request.get("alphabet","kryptos")},
            "phase_provenance":phase_provenance,
            "interpretation":"The algebra calculation exceeded a declared resource bound; feasibility is unresolved."}


def _check(request,allowed):
    if not isinstance(request,dict) or set(request)-allowed:
        raise ValueError("unknown checkpoint-K request field")


def _explain(command,request,result,text=None,cribs=None):
    result["authenticated_solution"]=False
    result["explanation"]={"command":command,"supplied_request":request,
        "request_sha256":hashlib.sha256(json.dumps(request,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest(),
        "source_sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/"kryptos").glob("*.py"))},
        "interpretation":"Exact results concern supplied model assumptions and bounds. Re-encryption and language scores do not authenticate a solution.",
        "external_verification_performed":False}
    if text is not None:
        result["explanation"]["input"]={"ciphertext":text,"sha256":hashlib.sha256(text.encode()).hexdigest(),"cribs":cribs,
            "crib_convention":"one-based original plaintext positions"}
    return result


def _verify(candidate,text,known):
    if candidate.get("plaintext") is None:
        return candidate
    candidate=dict(candidate)
    recipe=candidate.get("encryption_recipe")
    if not isinstance(recipe,dict):
        raise AssertionError("complete candidate lacks a recipe")
    replay=(replay_expanded if recipe["schema"]=="kryptos.expanded-recipe.v1" else replay_recipe)(candidate["plaintext"],recipe)
    if replay["ciphertext"]!=text or any(candidate["plaintext"][i]!=c for i,c in known.items()):
        raise AssertionError("candidate failed independent recipe/crib verification")
    candidate["evidence"]={"literal_reencryption_matches":True,"crib_matches":len(known),"stage_outputs":replay["stages"],"authenticated_solution":False}
    return candidate


def _cells(request,target,text):
    if "cells" in request:
        return request["cells"]
    from .data import K4_CIPHERTEXT
    if target!="k4" or text!=K4_CIPHERTEXT:
        raise ValueError("custom/K5 coordinate models require explicit cells")
    from .sculpture import section_cells
    return [[c.row,c.column] for c in section_cells("K4")]


def _stages(request,target,text):
    from .scheduled_layers import make_phase_map,stage_position_map
    stages=request.get("stages")
    if not isinstance(stages,list) or not 1<=len(stages)<=16:
        raise ValueError("supply1..16 encryption-order stages")
    resolved=[]
    provenance=[]
    for number,stage in enumerate(stages):
        if not isinstance(stage,dict):
            raise ValueError("stage must be an object")
        stage=dict(stage)
        if "schedule" in stage:
            schedule=stage.pop("schedule")
            if stage.get("operation")!="substitution" or "phase_map" in stage:
                raise ValueError("a schedule requires a substitution without an explicit phase_map")
            _check(schedule,{"kind","frame"})
            frame=schedule.get("frame","current")
            cells=_cells(request,target,text)
            position_map=stage_position_map(len(text),resolved) if frame=="source" else None
            phases=make_phase_map(cells,schedule.get("kind"),stage.get("key_length"),frame=frame,stage_to_source=position_map)
            stage["phase_map"]=phases
            provenance.append({"stage_zero_based":number,"cells":cells,"rule":schedule,"phase_map":phases,
                               "stage_to_source":position_map,"offset_applied_later":stage.get("offset",0)})
        resolved.append(stage)
    return resolved,provenance


def _optimization_job(request,parse_target):
    from .general_layers import solve_layers,LayerBudgetExceeded
    from .scheduled_layers import solve_scheduled
    from .language import CharacterNgramModel
    from .search_runtime import lazy_ngram_problem
    _check(request,BASE|LINEAR_LIMITS|SEARCH_LIMITS|{"stages","alphabet","cells","layer_model","model_path"})
    target,text,cribs,known=parse_target(request)
    layer_model=request.get("layer_model","general")
    if layer_model not in ("general","scheduled"):
        raise ValueError("layer_model must be general or scheduled")
    if layer_model=="scheduled":
        stages,phase_provenance=_stages(request,target,text)
    else:
        stages=request.get("stages")
        phase_provenance=[]
        if "cells" in request:
            raise ValueError("coordinate cells require layer_model scheduled")
    path=request.get("model_path")
    if not isinstance(path,str):
        raise ValueError("an explicit frozen model_path is required")
    path=Path(path)
    if path.stat().st_size>32*1024*1024:
        raise ValueError("model exceeds32MiB")
    raw=path.read_bytes()
    model=CharacterNgramModel.from_json(raw.decode("utf-8-sig"))
    job={"target":target,"text":text,"cribs":cribs,"known":known,"model":model,
         "model_sha256":hashlib.sha256(raw).hexdigest(),"stages":stages,"phase_provenance":phase_provenance,
         "layer_model":layer_model,"solution":None,"problem":None,"algebra_budget":None}
    solver=solve_scheduled if layer_model=="scheduled" else solve_layers
    try:
        solution=solver(text,known,stages,request.get("alphabet","kryptos"),**{k:request[k] for k in LINEAR_LIMITS if k in request})
    except LayerBudgetExceeded as exc:
        job["algebra_budget"]=_algebra_budget_result(exc,request,stages,phase_provenance)
    else:
        job["solution"]=solution
        job["problem"]=lazy_ngram_problem(solution,model,known) if solution.feasible else None
    return job


def _optimization_result(job,search):
    solution=job["solution"]
    point=search["assignment"]
    candidate=solution.candidate(point[:solution.dimensions_mod2],point[solution.dimensions_mod2:])
    if job["layer_model"]=="general":
        candidate=_candidate(candidate,job["stages"],solution.alphabet,job["text"],job["known"])
    candidate=_verify(candidate,job["text"],job["known"])
    return {"search":search,"candidate":candidate,"scoring":job["problem"]["metadata"],
            "model_file_sha256":job["model_sha256"],"display_model_score":job["model"].score(candidate["plaintext"],job["known"]).to_dict()}


def run_next(command,request,parse_target):
    if command=="joint":
        from .joint_columnar import recover_joint_columnar
        fields={"period","order","cipher","alphabet","width","cells","column_direction","max_segmentations","max_states","max_candidates","time_limit_seconds"}
        _check(request,BASE|fields)
        target,text,cribs,known=parse_target(request)
        options={k:request[k] for k in fields if k in request}
        if "period" not in options:
            raise ValueError("joint recovery requires an explicit period")
        if "width" not in options and "cells" not in options:
            options["cells"]=_cells(request,target,text)
        result=recover_joint_columnar(text,cribs,**options)
        result["candidates"]=[_verify(c,text,known) for c in result["candidates"]]
        return _explain(command,request,{"target":target,**result},text,cribs)
    if command=="alphabet-plus":
        from .alphabet_propagation import recover_cyclic_alphabet
        fields={"period","cipher","fixed_indices","max_states","max_candidates","time_limit_seconds"}
        _check(request,BASE|fields)
        target,text,cribs,known=parse_target(request)
        if "period" not in request:
            raise ValueError("an explicit period is required")
        result=recover_cyclic_alphabet(text,cribs,**{k:request[k] for k in fields if k in request})
        result["candidates"]=[_verify(c,text,known) for c in result["candidates"]]
        return _explain(command,request,{"target":target,**result},text,cribs)
    if command in ("scheduled","mixed"):
        from .general_layers import LayerBudgetExceeded
        from .scheduled_layers import solve_scheduled
        from .mixed_stages import solve_mixed_stages
        fields={"stages","cells","max_candidates","time_limit_seconds","max_key_slots"}
        fields|={"alphabet","max_matrix_cells","max_operations","top"} if command=="scheduled" else {"max_nodes","max_relation_checks","max_distinct_plaintexts","max_constraints","dispatch_equal_alphabets"}
        _check(request,BASE|fields)
        target,text,cribs,known=parse_target(request)
        stages,phase_provenance=_stages(request,target,text)
        if command=="mixed":
            result=solve_mixed_stages(text,known,stages,**{k:request[k] for k in fields-{"stages","cells"} if k in request})
        else:
            limit=_integer(request.get("max_candidates",676),"max_candidates",1,100000)
            keep=_integer(request.get("top",10),"top",1,1000)
            seconds=_integer(request.get("time_limit_seconds",10),"time_limit_seconds",1,600)
            try:
                solution=solve_scheduled(text,known,stages,request.get("alphabet","kryptos"),**{k:request[k] for k in LINEAR_LIMITS if k in request})
            except LayerBudgetExceeded as exc:
                result={"target":target,**_algebra_budget_result(exc,request,stages,phase_provenance),
                        "enumeration_complete":False,
                        "enumeration_bounds":{"max_candidates":limit,"top_stored":keep,"time_limit_seconds":seconds}}
                return _explain(command,request,result,text,cribs)
            result={**solution.summary(),"candidates":[],"evaluated":0,"enumeration_complete":False,
                    "enumeration_bounds":{"max_candidates":limit,"top_stored":keep,"time_limit_seconds":seconds}}
            if not solution.feasible:
                result.update(enumeration_complete=True,stop_reason="exact_contradiction")
            elif solution.distinct_plaintext_count>limit:
                result["stop_reason"]="candidate_limit; no arbitrary subset enumerated"
            else:
                started=time.monotonic()
                for a,b,_ in solution.enumerate_plaintexts(limit):
                    if time.monotonic()-started>=seconds:
                        result["stop_reason"]="time_limit"
                        break
                    candidate=solution.candidate(a,b)
                    result["evaluated"]+=1
                    if len(result["candidates"])<keep:
                        result["candidates"].append(candidate)
                else:
                    result.update(enumeration_complete=True,stop_reason="exhausted_declared_family")
        result["candidates"]=[_verify(c,text,known) for c in result["candidates"]]
        result["phase_provenance"]=phase_provenance
        return _explain(command,request,{"target":target,**result},text,cribs)
    if command=="optimize-plus":
        from .search_runtime import optimize_lazy
        job=_optimization_job(request,parse_target)
        if job["algebra_budget"] is not None:
            result={"target":job["target"],**job["algebra_budget"],"model_file_sha256":job["model_sha256"],
                    "scoring_model_id":job["model"].model_id}
            return _explain(command,request,result,job["text"],job["cribs"])
        result={"target":job["target"],**job["solution"].summary(),"phase_provenance":job["phase_provenance"]}
        if job["solution"].feasible:
            result["optimization"]=_optimization_result(job,optimize_lazy(job["problem"],**{k:request[k] for k in SEARCH_LIMITS if k in request}))
        return _explain(command,request,result,job["text"],job["cribs"])
    if command=="batch":
        from .parallel_search import optimize_batch
        _check(request,{"jobs","workers"})
        jobs=request.get("jobs")
        if not isinstance(jobs,list) or not 1<=len(jobs)<=32:
            raise ValueError("batch needs1..32 optimization requests")
        workers=_integer(request.get("workers",2),"workers",1,4)
        names=set()
        for raw in jobs:
            _check(raw,{"id","request"})
            name=raw.get("id")
            if not isinstance(name,str) or not 1<=len(name)<=128 or name in names:
                raise ValueError("batch IDs must be unique nonempty strings up to128characters")
            names.add(name)
        pending=[]
        built={}
        records=[]
        for raw in jobs:
            name=raw["id"]
            job=_optimization_job(raw.get("request"),parse_target)
            built[name]=job
            if job["algebra_budget"] is not None:
                records.append({"id":name,"feasible":None,"complete":False,"stop_reason":"algebra_budget",
                                "model":job["algebra_budget"],"model_file_sha256":job["model_sha256"],
                                "scoring_model_id":job["model"].model_id})
            elif job["solution"].feasible:
                pending.append({"id":name,"problem":job["problem"],"options":{k:raw["request"][k] for k in SEARCH_LIMITS if k in raw["request"]}})
            else:
                records.append({"id":name,"feasible":False,"complete":True,"model":job["solution"].summary(),
                                "model_file_sha256":job["model_sha256"],"scoring_model_id":job["model"].model_id})
        result=optimize_batch(pending,workers=workers) if pending else {"jobs":[],"workers_requested":workers}
        for record in result["jobs"]:
            job=built[record["id"]]
            records.append({"id":record["id"],"feasible":True,"worker_pid":record["worker_pid"],
                            "model":job["solution"].summary(),"optimization":_optimization_result(job,record["result"])})
        result["jobs"]=sorted(records,key=lambda r:r["id"])
        result["requested_jobs"]=len(jobs)
        result["optimization_job_count"]=len(pending)
        result["job_count"]=len(records)
        result["inconclusive_algebra_jobs"]=sum(row["feasible"] is None for row in records)
        result["all_searches_complete"]=all(row["feasible"] is False or
            (row["feasible"] is True and row["optimization"]["search"]["complete"]) for row in records)
        result["all_objectives_proved_optimal"]=all(row["feasible"] is False or
            (row["feasible"] is True and row["optimization"]["search"]["optimal"]) for row in records)
        return _explain(command,request,result)
    raise ValueError("unknown checkpoint-K command")
