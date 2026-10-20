"""Smoke-test parsing against completed ESPN games without live waiting."""
import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location("collector",Path(__file__).with_name("collector.py"))
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
for league,event in [("football/college-football","401856723"),("basketball/nba","401898406")]:
    url=c.BASE+league+"/summary?event="+event
    data=c.fetch(url)
    plays=c.plays_from(data)
    assert len(plays)>50,(league,len(plays),list(data))
    ordered=sorted(plays,key=c.play_order)
    print("PASS",league,event,len(ordered),"first",ordered[0].get("id"),"last",ordered[-1].get("id"))
