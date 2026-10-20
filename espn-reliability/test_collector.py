"""Offline regression checks for ESPN collector response schemas."""
import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location("collector",Path(__file__).with_name("collector.py"))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def play(id,score,period=1,clock="10:00"):
    return {"id":str(id),"homeScore":score,"awayScore":0,
            "period":{"number":period},"clock":{"displayValue":clock}}
nba={"plays":[play("later",4,1,"09:00"),play("first",2,1,"10:00")]}
cfb={"drives":{"previous":[{"plays":[play(1,6),play(2,9)]}],
               "current":{"plays":[play(2,9),play(3,12)]}}}
assert len(m.plays_from(nba))==2
assert len(m.plays_from(cfb))==3
assert [p["id"] for p in sorted(m.plays_from(nba),key=m.play_order)]==["first","later"]
assert m.plays_from({"drives":{}})==[]
event={"competitions":[{"competitors":[{"homeAway":"home","score":"4"},{"homeAway":"away","score":"0"}]}]}
assert m.compare_final(sorted(nba["plays"],key=m.play_order),event) is True
assert m.compare_final([],event) is None
assert m.compact(play("x",3))["sequenceNumber"] is None
print("PASS: NBA parsing; CFB drive deduplication; chronology; final-score checks")
