"""Readiness-only fixtures: delayed pixels are distinct from a missing stream."""
import asyncio
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace


def owner():
    if 'webrec_readiness_owner' not in sys.modules:
        try:
            import taskfilm
            path=Path(taskfilm.__file__).parent/'_vendor/video/capture-lane/webrec.py'
        except ImportError:
            path=Path(__file__).parents[1]/'webrec.py'
        spec=importlib.util.spec_from_file_location('webrec_readiness_owner',path)
        module=importlib.util.module_from_spec(spec)
        sys.modules[spec.name]=module
        spec.loader.exec_module(module)
    return sys.modules['webrec_readiness_owner']


def test_wait_accepts_a_frame_that_arrives_after_startup():
    async def scenario():
        stream=SimpleNamespace(frames=[])
        async def arriving_frame():
            await asyncio.sleep(.02)
            stream.frames.append((123.0,Path('explicit-readiness-fixture.jpg')))
        producer=asyncio.create_task(arriving_frame())
        assert await owner().wait_for_first_frame(stream,1) is True
        await producer
        assert stream.frames[0][0]==123.0
    asyncio.run(scenario())


def test_wait_refuses_a_missing_frame_without_inventing_a_clock():
    stream=SimpleNamespace(frames=[])
    assert asyncio.run(owner().wait_for_first_frame(stream,.01)) is False
    assert stream.frames==[]


def test_already_retained_frame_needs_no_wait():
    stream=SimpleNamespace(frames=[(123.0,Path('explicit-readiness-fixture.jpg'))])
    assert asyncio.run(owner().wait_for_first_frame(stream,0)) is True
