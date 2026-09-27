"""Send a tiny JSON request to each configured provider, without document content."""
import providers
import sys


def main():
    providers.load_env()
    if "--writing-intent" in sys.argv:
        return check_writing_intent()
    failed = False
    for provider in providers.status():
        name = provider["id"]
        if not provider["configured"]:
            print(f"{name}: missing or placeholder key")
            continue
        try:
            if "--models" in sys.argv:
                url = providers.PROVIDERS[name]["url"].replace("/chat/completions", "/models")
                req = providers.request.Request(url, headers={"Authorization": "Bearer " + providers.api_key(name), "User-Agent": "DPR-Workspace/0.2"})
                with providers.request.urlopen(req, timeout=30) as response:
                    models = providers.json.load(response)["data"]
                wanted = set(providers.GROQ_MODELS.values()) if name == "groq" else set(providers.OPENROUTER_MODELS.values())
                available = [model["id"] for model in models if name == "groq" or model["id"] in wanted]
                print(f"{name} available models: " + ", ".join(available))
                continue
            result = providers.complete(name, "planner", 'Reply with {"ok":true}.', {"check": "connection"}, max_tokens=1024)
            if result.get("ok") is not True:
                raise ValueError("Unexpected test response")
            print(f"{name}: authenticated JSON completion succeeded ({providers.model_for(name, 'planner')})")
        except (providers.ProviderError, ValueError, providers.error.URLError) as exc:
            print(providers.redact(str(exc)))
            failed = True
    if "--workflow" in sys.argv:
        import tempfile
        import core
        original = core.DB
        try:
            with tempfile.TemporaryDirectory() as directory:
                core.DB = core.Path(directory) / "check.sqlite3"
                job = {"id": core.uid(), "prompt": "Create a section called Writing workflow with two imperative steps: collect notes, revise draft. This is a proposed writing outline, not a claim about conducted research.",
                       "tasks": [], "status": "queued"}
                core.put("job", job)
                core.run_job(job["id"])
                result = core.get("job", job["id"])
                print("Temporary writing workflow: " + result["status"])
                for task in result["tasks"]:
                    print("Task: " + task["status"] + (" — " + task["reason"] if task.get("reason") else ""))
                if result.get("error"):
                    print(providers.redact(result["error"]))
                failed = failed or result["status"] != "complete" or not any(t["status"] == "committed" for t in result["tasks"])
        finally:
            core.DB = original
    return int(failed)


def check_writing_intent():
    """Reproduce the title + abstract conversation against real models in isolation."""
    import tempfile
    import core
    from unittest.mock import patch
    original = core.DB
    live_llm = core.llm
    plans = []
    def trace_plan(role, system, payload):
        response = live_llm(role, system, payload)
        if role == "planner":
            plans.append(response)
        return response
    title = "Can prompt engineering be a career option?"
    try:
        with tempfile.TemporaryDirectory() as directory:
            core.DB = core.Path(directory) / "writing-check.sqlite3"
            prompts = ["Lets work on a papper titled " + title,
                       "Update the title and also fill the abstract keep it clear and consice"]
            for index, prompt in enumerate(prompts):
                job = {"id": core.uid(), "prompt": prompt, "status": "queued", "tasks": []}
                core.put("job", job)
                with patch.object(core, "llm", side_effect=trace_plan):
                    core.run_job(job["id"])
                result = core.get("job", job["id"])
                print(f"Request {index + 1}: {result['status']} — {result.get('summary', '')}", flush=True)
                for task in result["tasks"]:
                    print(providers.redact(f"{task['operation']}: {task['status']} {task.get('reason', '')}"), flush=True)
                if result.get("error"):
                    print(providers.redact(result["error"]), flush=True)
                    print("Planner response: " + providers.redact(providers.json.dumps(plans[-1] if plans else {})), flush=True)
                if result["status"] != "complete" or core.paper()["title"].casefold() != title.casefold():
                    return 1
                if index == 0 and core.paper()["sections"]:
                    print("FAIL: title-only request created sections", flush=True)
                    return 1
            abstract = next((s for s in core.paper()["sections"] if s["heading"].casefold() == "abstract"), None)
            if not abstract or not abstract["blocks"]:
                print("FAIL: abstract was not saved", flush=True)
                return 1
            print(core.markdown(core.paper()), flush=True)
            return 0
    finally:
        core.DB = original


if __name__ == "__main__":
    raise SystemExit(main())
