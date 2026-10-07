"""Current HyperFrames owns timed clip visibility; GSAP may animate children."""
from html.parser import HTMLParser
from pathlib import Path
import re
import sys

owner = Path(__file__).resolve().parents[1]
if not (owner / "hfcomp.py").is_file():
    import taskfilm
    owner = Path(taskfilm.__file__).parent / "_vendor/video/capture-lane"
sys.path.insert(0, str(owner))
import hfcomp
import reel


class Clips(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        node = dict(attrs)
        if "clip" in node.get("class", "").split() and node.get("id"):
            self.ids.add(node["id"])


def check_visibility_ownership(markup):
    clips = Clips()
    clips.feed(markup)
    assert clips.ids
    calls = re.findall(r'(?:tl|gsap)\.(?:set|to|from|fromTo)\("(#[-\w]+)"\s*,\s*\{([^}]+)\}', markup)
    assert calls
    for target, props in calls:
        if "autoAlpha" in props or "visibility" in props:
            assert target[1:] not in clips.ids, f"animation competes with timed clip visibility: {target}"


def test_landscape_overlay_visibility_belongs_to_runtime():
    markup = hfcomp.build_html({"duration_s": 12, "name": "A task"}, "screen.mp4",
        [{"t": 1, "hold": 2, "title": "Add a task"}], [], 1280, 720, "Task lesson",
        notes=[{"t": 4, "hold": 2, "text": "Check the result"}])
    check_visibility_ownership(markup)


def test_portrait_overlay_visibility_belongs_to_runtime():
    shots = [{"vo": "Add a task", "vo_at": 1, "vo_s": 2, "show_from": 0, "at": 0,
              "explain": "Check the result", "scale": 1, "x": 0, "y": 0,
              "card_h": reel.CARD_WIDE_H, "end": 12}]
    markup = reel.build_html({"duration_s": 12, "name": "A task"}, "screen.mp4", shots, "Task lesson")
    check_visibility_ownership(markup)
