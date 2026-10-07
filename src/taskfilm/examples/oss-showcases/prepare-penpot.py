"""Open a native disposable Penpot demo and bind its private capture state.

Use a temporary self-hosted Penpot instance with demo users enabled. This helper
does not register a real account, contact email, or publish browser credentials.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit


def prepare(base: str, recipe: Path, output: Path, auth: Path, proof: Path) -> dict:
    from playwright.sync_api import sync_playwright
    parsed = urlsplit(base)
    if (parsed.scheme not in {"http", "https"} or parsed.username or parsed.password
            or parsed.hostname not in {"localhost", "127.0.0.1", "::1", "penpot-frontend"}):
        raise ValueError("use a temporary local Penpot instance, not a personal cloud account")
    if output.exists() or auth.exists():
        raise ValueError("execution recipe and private auth destination must be new")
    proof.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        executable = os.environ.get("CAPTURE_LANE_BROWSER_PATH")
        options = {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage",
            "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]}
        # A private Docker hostname lacks localhost's secure-context exemption.
        # Scope this exception to the disposable instance's exact origin so the
        # recorder can use its native OPFS upload staging there.
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if parsed.hostname == "penpot-frontend" and parsed.scheme == "http":
            options["args"].append(f"--unsafely-treat-insecure-origin-as-secure={origin}")
        if executable:
            options["executable_path"] = executable
        browser = pw.chromium.launch(**options)
        context = browser.new_context(viewport={"width": 1920, "height": 1080}, locale="en-US")
        page = context.new_page()
        try:
            page.goto(base.rstrip("/") + "/#/auth/register", wait_until="domcontentloaded", timeout=60000)
            page.get_by_text("Create demo account", exact=True).click(timeout=45000)
            page.get_by_text("Education", exact=True).click(timeout=30000)
            page.get_by_text("Select option", exact=True).click()
            page.get_by_text(re.compile(r"student.*teacher", re.I)).click()
            page.locator('button[name="submit"]').click()
            page.get_by_text("Other", exact=True).click()
            page.locator('input[name="experience-design-tool-other"]').fill("Original Taskfilm sample")
            page.locator('button[name="submit"]').click()
            page.get_by_text("Other", exact=True).click()
            page.locator('input[name="start-with-other"]').fill("Review original desktop and mobile layouts")
            page.locator('button[name="submit"]').click()
            page.get_by_text(re.compile(r"continue without", re.I)).click(timeout=30000)
            page.get_by_test_id("project-new-file").click(timeout=30000)
            page.get_by_test_id("viewport").wait_for(timeout=60000)
            page.locator("#image-upload").wait_for(state="attached", timeout=30000)
            page.wait_for_timeout(3000)
            controls = page.locator("button,input").evaluate_all("els => els.map(e => ({tag:e.tagName, id:e.id, aria:e.getAttribute('aria-label'), test:e.getAttribute('data-testid'), text:e.innerText}))")
            (proof / "editor-controls.json").write_text(json.dumps(controls, indent=2) + "\n")
            page.screenshot(path=str(proof / "editor.png"))
            data = json.loads(recipe.read_text())
            data["url"] = page.url
            data["stage"]["storage_state"] = str(auth.resolve())
            data["stage"]["chrome_args"] = options["args"]
            for seed in data["stage"].get("seed_files", []):
                source = recipe.parent / seed["path"]
                step = next(s for s in data["steps"] if s.get("do") == "upload" and s["seed"] == seed["as"])
                if source.is_symlink() or not source.is_file():
                    raise ValueError("upload sample must be a regular file")
                if source.stat().st_size != step["expected_bytes"] or hashlib.sha256(source.read_bytes()).hexdigest() != step["expected_sha256"]:
                    raise ValueError("the original layout differs from the checked upload proof")
                seed["path"] = str(source.resolve())
            auth.parent.mkdir(parents=True, exist_ok=True)
            with os.fdopen(os.open(auth, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
                json.dump(context.storage_state(), stream)
            # Verify the same fresh-context boundary the recorder will cross.
            # Keep cookie values in the private state file, never in evidence.
            restored = browser.new_context(storage_state=str(auth), viewport={"width": 1920, "height": 1080}, locale="en-US")
            target = page.url
            page = restored.new_page()
            page.goto(target, wait_until="domcontentloaded", timeout=60000)
            page.get_by_test_id("viewport").wait_for(timeout=60000)
            page.locator("#image-upload").wait_for(state="attached", timeout=30000)
            secure = page.evaluate("window.isSecureContext && !!navigator.storage?.getDirectory")
            if not secure:
                raise ValueError("native upload staging requires a secure browser context")
            (proof / "capture-readiness.json").write_text(json.dumps({
                "fresh_context_editor": True, "secure_upload_context": secure,
                "cookie_count": len(restored.cookies()), "private_auth_mode": "0600"}, indent=2) + "\n")
            page.screenshot(path=str(proof / "restored-editor.png"))
            restored.close()
            with output.open("x") as stream:
                stream.write(json.dumps(data, indent=2) + "\n")
            return {"execution_recipe": str(output.resolve()), "native_demo_account": True,
                "onboarding": "native UI with declared synthetic sample answers",
                "template_sha256": hashlib.sha256(recipe.read_bytes()).hexdigest(),
                "execution_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                "auth": "private 0600 file; must not be copied into release or take archives"}
        except Exception:
            (proof / "setup-body.log").write_text(page.locator("body").inner_text())
            (proof / "setup.html").write_text(page.content())
            page.screenshot(path=str(proof / "setup.png"))
            raise
        finally:
            browser.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default="http://localhost:9001")
    p.add_argument("--recipe", type=Path, default=Path(__file__).parent / "capture-penpot.json")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--auth-out", type=Path, required=True)
    p.add_argument("--proof", type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(prepare(args.url, args.recipe, args.out, args.auth_out, args.proof), indent=2))
