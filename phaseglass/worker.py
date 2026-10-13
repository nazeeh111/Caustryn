# SPDX-License-Identifier: MIT
"""Fixed subprocess operations. No arbitrary code, paths or commands accepted."""

import base64
import sys
from .io import MAX_INPUT, decode, encoded


def execute(request):
    if type(request) is not dict or set(request) != {"action", "payload"}:
        raise ValueError("Worker requires action and payload")
    action, payload = request["action"], request["payload"]
    if type(payload) is not dict:
        raise ValueError("Payload must be an object")
    if action == "sweep-solve" and set(payload) == {"training"}:
        from .coherent import solve_sweep

        return solve_sweep(payload["training"])
    if action == "sweep-evaluate" and set(payload) == {"training", "validation"}:
        from .coherent import evaluate_sweep

        return evaluate_sweep(payload["training"], payload["validation"])
    if action == "sweep-validate" and "training" in payload and not set(payload) - {"training", "validation"}:
        from .coherent import validate_sweep_inputs

        return validate_sweep_inputs(payload["training"], payload.get("validation"))
    if action == "sweep-export":
        from .coherent_export import export_sweep

        return {"zip_base64": base64.b64encode(export_sweep(payload)).decode("ascii")}
    if action == "simulate" and set(payload) == {"scene"}:
        from .simulation import simulate

        return simulate(payload["scene"])
    if action == "solve" and set(payload) == {"measurement"}:
        from .inverse import solve

        return solve(payload["measurement"])
    if action == "intervention" and set(payload) == {"measurement", "result"}:
        from .inverse import suggest_intervention

        return suggest_intervention(payload["measurement"], payload["result"])
    if action == "export":
        from .export import export_zip

        return {"zip_base64": base64.b64encode(export_zip(payload)).decode("ascii")}
    raise ValueError("Unsupported operation or fields")


def main():
    try:
        try:
            import resource

            soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
            ceiling = 8 * 1024 * 1024
            if soft != resource.RLIM_INFINITY:
                ceiling = min(ceiling, soft)
            if hard != resource.RLIM_INFINITY:
                ceiling = min(ceiling, hard)
            resource.setrlimit(resource.RLIMIT_FSIZE, (ceiling, hard))
        except (ImportError, OSError, ValueError):
            pass
        response = {
            "ok": True,
            "result": execute(decode(sys.stdin.buffer.read(MAX_INPUT + 1))),
        }
        data = encoded(response)
        if len(data) > 8 * 1024 * 1024:
            raise ValueError("Worker output exceeds 8 MiB")
        sys.stdout.buffer.write(data)
        return 0
    except Exception as exc:
        sys.stdout.buffer.write(encoded({"ok": False, "error": str(exc)[:500]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
