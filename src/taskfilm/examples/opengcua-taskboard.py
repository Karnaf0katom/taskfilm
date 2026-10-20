"""A real task through AX, Playwright and visual targets; no model or API key.

Serve taskboard/ locally, then:
taskfilm capture gcua opengcua-taskboard.py --url http://127.0.0.1:8765 --out take
"""
import asyncio


async def run(tab, film):
    film.beat("start", vo="Add one task, then mark it complete.")
    await asyncio.sleep(1)
    observation = await film.observe()
    field = next(node for node in observation.tree.nodes if node.name == "Task title")
    await tab.ui.ax.click(field, timeout_ms=15000)
    # Code can branch and batch operations in one program. Use the SDK's
    # Playwright bridge for exact field input, AX for accessible controls.
    await tab.playwright.get_by_label("Task title").fill("Ship the demo")
    observation = await film.observe()
    add = next(node for node in observation.tree.nodes if node.name == "Add task")
    await tab.ui.ax.click(add, timeout_ms=15000)
    await film.assert_text("#tasks li span", "Ship the demo", screenshot="added.png")

    film.beat("finish", vo="Complete the task and check the result.")
    await asyncio.sleep(1)
    complete = tab.playwright.get_by_role("button", name="Complete Ship the demo", exact=True)
    if await complete.is_visible():
        await complete.click()
    # Visual coordinates must come from the same delivered image; the SDK
    # checks its observation. Locate this fixture's filter before observing.
    box = await tab.playwright.get_by_role("button", name="Completed", exact=True).bounding_box()
    observation = await tab.ui.vision.observe(timeout_ms=15000)
    await film.mu.emit(observation)
    image = observation.images[0]
    await tab.ui.vision.click(image.point(box["x"] + box["width"] / 2,
                                          box["y"] + box["height"] / 2), timeout_ms=15000)
    await film.assert_text('#tasks li[data-done="true"] span', "Ship the demo", screenshot="completed.png")
    await film.assert_text("#count", "1 of 1 complete", screenshot="count.png")
    film.beat("result", vo="The completed view shows the task. One of one is finished.")
    await asyncio.sleep(2)
