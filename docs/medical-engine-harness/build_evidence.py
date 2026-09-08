"""Reproduce this review's local evidence, without model or network calls.

This is a snapshot audit, not the proposed production feedback/adjudication system.
Each toolkit runs in its own process and virtual environment. Output must be new.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path


TOPICS = [
    ("C01", "公共流程：回应当前问题", "public_procedure_candidate", "S10-Q004 S04-Q005 S07-Q001", "W09 W12"),
    ("C02", "公共流程：必要且非引导的追问", "public_procedure_candidate", "S12-Q005 S16-Q002 S17-Q003 S13-Q002", "W09 W12"),
    ("C03", "公共流程：使用已知事实", "public_procedure_candidate", "S18-Q001 S03-Q001", "W02 W09"),
    ("C04", "公共流程：尊重本人目标", "public_procedure_candidate", "S09-Q012 S01-Q006 S05-Q006", "W04 W09"),
    ("C05", "专科共享候选：信息采集顺序", "domain_procedure_candidate", "S04-Q001 S02-Q002 S02-Q003", "W10 W11"),
    ("D01", "医生方法候选：抱姿介绍优先序", "doctor_method_candidate", "S03-Q005", "W10"),
    ("D02", "医生方法候选：支持与进一步评估的分支", "doctor_method_candidate", "S09-Q001 S12-Q005 S09-Q008", "W10 W11"),
    ("D03", "医生方法候选：面对家人评论的框架", "doctor_method_candidate", "S09-Q005", "W10"),
    ("K01", "待核知识：冷链器具", "knowledge_claim_pending", "S07-Q001 S07-Q004", "W11"),
    ("K02", "待核知识：储奶与配件处理", "knowledge_claim_pending", "S07-Q002 S06-Q004", "W11"),
    ("K03", "待裁决：分类与临床含义", "adjudication_pending", "S15-Q001 S15-Q002 S15-Q005 S12-Q002", "W04 W06"),
    ("X01", "待澄清：源输入与解释", "source_clarification_candidate", "S13-Q003 S04-Q006 S05-Q006", "W01 W04"),
]
COMMENT_FIELDS = ("confirmed_consultation_response", "confirmed_follow_ups", "medical_rationale")


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def execute(args: list[str], cwd: Path, stdin: str | None = None) -> str:
    return subprocess.run(args, cwd=cwd, input=stdin, text=True, capture_output=True, check=True).stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New local directory; never overwrite")
    parser.add_argument("--cozy", type=Path, default=Path("/Users/lute/lute_work/cozy_agent"))
    parser.add_argument("--deer", type=Path, default=Path("/Users/lute/recent_projects/deer-flow"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if output.exists():
        raise ValueError(f"Output already exists: {output}")
    reviewed = root / "annotation-toolkit/workbench/output/medical-case-review-50-20260907_submitted_20260908_142539.csv"
    source = root / "annotation-toolkit/workbench/input/cases-2026-09-07T01-19-57-173Z.csv"
    engine = root / "annotation-toolkit/workbench/output/cases-2026-09-07T01-19-57-173Z_engine.csv"
    run_path = engine.with_suffix(".run.json")
    prompt = root / "prompt-agent/prompt.md"
    rows, raw_rows, engine_rows = read_csv(reviewed), read_csv(source), read_csv(engine)
    raw = {r["case_id"]: r for r in raw_rows}
    predictions = {r["case_id"]: r for r in engine_rows}
    assert len(rows) == len({r["case_id"] for r in rows}) == 50
    assert len(raw) == len(raw_rows) == len(predictions) == len(engine_rows) == 100
    run = json.loads(run_path.read_text())
    assert run["source_sha256"] == sha_bytes(source.read_bytes())
    assert run["output_sha256"] == sha_bytes(engine.read_bytes())
    assert run["prompt_sha256"] == sha_bytes(prompt.read_bytes())

    # Use the actual current renderer in its own environment, not a copied renderer.
    annotation = root / "annotation-toolkit"
    rendering_code = (
        "import json,sys\n"
        "from app.profiles.cozie_medical_review import _profile_materials\n"
        "profiles=json.load(sys.stdin)\n"
        "print(json.dumps({k:_profile_materials(v) for k,v in profiles.items()},ensure_ascii=False))"
    )
    rendered = json.loads(execute(
        [str(annotation / ".venv/bin/python"), "-c", rendering_code], annotation,
        json.dumps({r["case_id"]: raw[r["case_id"]]["user_profile"] for r in rows}),
    ))
    for row in rows:
        cid = row["case_id"]
        assert row["user_input"] == raw[cid]["user_input"], cid
        assert row["user_profile"] == rendered[cid], cid
        for field in ("predicted_safety_class", "candidate_safety_class"):
            assert row[field] == predictions[cid][field], (cid, field)
        assert row["engine_status"] == "SUCCESS" and not predictions[cid]["error"], cid
        assert row["candidate_safety_class"] == raw[cid]["candidate_safety_class"], cid
        assert json.loads(raw[cid]["user_profile"]) == json.loads(predictions[cid]["user_profile"]), cid

    # Refresh stats through the shipped CLI; never import another tool's app package.
    query = root / "review-query-toolkit"
    metrics = json.loads(execute([
        str(query / ".venv/bin/python"), "run.py", "evaluate", "--input", str(reviewed), "--format", "json",
    ], query))
    assert metrics["population"]["analysis_rows"] == 50
    prompt_tool = root / "prompt-agent"
    replay_code = (
        "import json,sys\nfrom pathlib import Path\n"
        "from app.safety_classifier import load_safety_cases\n"
        "try:\n load_safety_cases(Path(sys.argv[1]))\n"
        "except ValueError as exc:\n print(json.dumps({'error_type':'ValueError','message':str(exc)}))\n"
        "else:\n print(json.dumps({'error_type':None}))"
    )
    replay = json.loads(execute([str(prompt_tool / ".venv/bin/python"), "-c", replay_code, str(reviewed)], prompt_tool))
    assert replay["error_type"] == "ValueError" and "invalid context JSON" in replay["message"]

    artifact = {"path": str(reviewed), "sha256": sha_bytes(reviewed.read_bytes())}
    lookup = {r["case_id"]: (i, r) for i, r in enumerate(rows, 1)}
    topics = []
    for tid, title, scope, case_ids, tasks in TOPICS:
        anchors = []
        for cid in case_ids.split():
            ordinal, row = lookup[cid]
            comments = [{"field": f, "verbatim": row[f]} for f in COMMENT_FIELDS if row[f].strip()]
            assert comments, (tid, cid)
            anchors.append({"case_id": cid, "record_id": row["record_id"], "data_row_ordinal": ordinal, "comments": comments})
        topics.append({
            "topic_id": tid, "title": title, "scope_candidate": scope,
            "status": "proposed", "proposed_by": "analysis", "runtime_enabled": False,
            "approved_revision": None, "doctor_exclusivity": "not_established",
            "work_item_ids": tasks.split(), "review_artifact": artifact, "evidence": anchors,
            "conditions_and_counterexamples_ref": "docs/medical-engine-harness/doctor-components.md",
        })

    ledger = []
    for ordinal, row in enumerate(rows, 1):
        cid = row["case_id"]
        issues = [i for i in metrics["issues"] if i["case_id"] == cid]
        linked = [t for t in topics if any(e["case_id"] == cid for e in t["evidence"])]
        tasks = {"W01", "W02", "W03", "W06"}
        gaps = []
        if row["predicted_safety_class"] != row["expected_safety_class"]:
            gaps.append("safety_classification_disagreement")
            tasks.update(("W04", "W05", "W12"))
        if any(row[f].strip() for f in COMMENT_FIELDS[:2]):
            gaps.append("material_comment_present_not_a_final_answer")
            tasks.update(("W08", "W12"))
        if issues:
            gaps.append("annotation_structure_or_context_issue")
            tasks.add("W04")
        for topic in linked:
            tasks.update(topic["work_item_ids"])
        input_snapshot = {"query": raw[cid]["user_input"], "user_profile": json.loads(raw[cid]["user_profile"])}
        ledger.append({
            "case_id": cid, "response_key": f"{row['record_id']}:{row['annotator_username']}",
            "review_artifact": artifact, "data_row_ordinal": ordinal,
            "source_case_id": cid, "source_artifact": str(source),
            "source_data_row_ordinal": next(i for i, r in enumerate(raw_rows, 1) if r["case_id"] == cid),
            "input_projection": input_snapshot, "input_projection_sha256": sha_bytes(canonical(input_snapshot)),
            "projection_schema": "snapshot-query-profile/v1",
            "raw_review": {f: row[f] for f in ("expected_safety_class", "boundary_status", "reason_codes", "material_review", "needs_expert_adjudication", *COMMENT_FIELDS)},
            "candidate_class": row["candidate_safety_class"], "engine_class": row["predicted_safety_class"],
            "observed_gaps": gaps, "structure_issues": issues,
            "proposed_topic_ids": [t["topic_id"] for t in linked],
            "proposed_work_item_ids": sorted(tasks), "task_state": "open",
            "adjudication": None, "note": "分析路由；没有改变医生判断或批准运行规则。",
        })

    # Narrow inventory: no env files, account lists, or unrelated user documents.
    paths = [reviewed, source, engine, run_path, prompt, Path(__file__).resolve()]
    paths += [root / p for p in (
        "langfuse-toolkit/prompts/questions.system.txt", "langfuse-toolkit/prompts/questions.user.txt",
        "langfuse-toolkit/prompts/review.system.txt", "langfuse-toolkit/prompts/review.user.txt",
        "langfuse-toolkit/app/projects/prompts.py", "langfuse-toolkit/app/projects/playground.py",
        "output-collector-toolkit/index.html", "annotation-toolkit/app/profiles/cozie_medical_review.py",
        "annotation-toolkit/docs/medical_case_review_guidelines.md", "prompt-agent/app/safety_classifier.py",
        "prompt-agent/classify.py", "review-query-toolkit/app/evaluation.py",
    )]
    paths += [args.cozy / p for p in (
        "AGENTS.md", "README.md", "backend/app/agents/factory.py",
        "backend/app/agents/shared/safety_classifier.py", "backend/app/agents/lactation/agent.py",
        "backend/app/agents/lactation/models.py", "backend/app/agents/lactation/prompts/builder.py",
        "backend/app/agents/lactation/prompts/system.md", "backend/app/agents/lactation/tools/knowledge.py",
        "backend/app/agents/lactation/rag/models.py",
    )]
    harness = args.deer / "backend/packages/harness/deerflow"
    paths += [harness / p for p in (
        "agents/features.py", "agents/lead_agent/agent.py", "skills/types.py", "skills/catalog.py",
        "skills/describe.py", "agents/middlewares/skill_tool_policy_middleware.py",
        "agents/middlewares/durable_context_middleware.py", "agents/thread_state.py",
        "subagents/report_contract.py", "subagents/status_contract.py",
        "agents/middlewares/tool_receipt_middleware.py", "agents/middlewares/receipt_verification.py",
        "agents/memory/manager.py", "runtime/checkpoint_state.py", "client.py",
    )]
    paths += [args.deer / p for p in (
        "backend/tests/test_harness_boundary.py", "backend/scripts/benchmark/deermem_eviction/config.py",
        "backend/scripts/benchmark/deermem_eviction/manifest.py",
    )]
    inventory = [{"path": str(p), "sha256": sha_bytes(p.read_bytes()), "bytes": p.stat().st_size} for p in paths]
    repositories = [{"path": str(p), "head": execute(["git", "rev-parse", "HEAD"], p).strip(),
                     "working_tree_status": execute(["git", "status", "--short"], p).splitlines()}
                    for p in (root, args.cozy, args.deer)]
    summary = {
        "status": "analysis_evidence_not_production_assets", "network_or_model_calls": 0,
        "review_rows": len(rows), "source_rows": len(raw_rows),
        "exact_query_and_rendered_profile_matches": len(rows), "missing_or_mismatched_cases": 0,
        "source_prompt_output_hashes_match_engine_manifest": True,
        "engine_run_model": run["model"], "engine_run_completed": run["completed"], "engine_run_total": run["total"],
        "historical_question_generation_prompt_version": None,
        "historical_material_generation_prompt_version": None,
        "missing_reason": "No GenerationRun snapshot links those actual resolved Langfuse versions to this source batch.",
        "direct_review_csv_replay": replay, "topic_candidates": len(topics),
        "feedback_ledger_rows": len(ledger), "structure_issue_rows": len(metrics["issues"]),
        "work_item_case_counts": dict(sorted(Counter(t for r in ledger for t in r["proposed_work_item_ids"]).items())),
        "files": inventory, "repositories": repositories,
        "row_number_convention": "1-based data record ordinal, excludes header; not physical CSV line number",
    }
    output.mkdir(parents=True)
    for name, value in (("source-evidence.json", summary), ("feedback-ledger.json", ledger),
                        ("concept-candidates.json", topics), ("metrics.json", metrics)):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "README.md").write_text(
        "# 本地审核闭环证据\n\n"
        "50条来源全部匹配。此包为分析证据，方法候选均未批准执行，工作项均待实施。\n\n"
        "- [来源、源码摘要与回放失败复现](source-evidence.json)\n"
        "- [50条审核及建议任务路由](feedback-ledger.json)\n"
        "- [12个主题候选与原文锚点](concept-candidates.json)\n"
        "- [重新计算的多维统计](metrics.json)\n\n"
        "CSV行号为去掉表头后的逻辑记录序号；不是多行文本中的物理行号。\n"
        "原始数据未修改。未知历史生成Prompt版本保持空值。\n", encoding="utf-8",
    )
    print(json.dumps({k: summary[k] for k in ("review_rows", "exact_query_and_rendered_profile_matches", "topic_candidates", "feedback_ledger_rows", "structure_issue_rows")}, ensure_ascii=False))
    print(output)


if __name__ == "__main__":
    main()
