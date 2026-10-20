import argparse, datetime, json, time, urllib.request
from pathlib import Path

BASE = "https://site.api.espn.com/apis/site/v2/sports/"
def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent":"sports-data-research/1.0"})
    with urllib.request.urlopen(request, timeout=15) as r: return json.load(r)
def save(fp, row):
    with open(fp,"a") as f: f.write(json.dumps(row, separators=(",",":"))+"\n")
def event_for(data, teams):
    for e in data.get("events",[]):
        comps = (e.get("competitions") or [{}])[0].get("competitors",[])
        if teams <= {c.get("team",{}).get("abbreviation") for c in comps}: return e
def slim(event):
    return {"id":event.get("id"),"status":event.get("status",{}).get("type",{}).get("name"),
            "competitors":[{"team":c.get("team",{}).get("abbreviation"),"score":c.get("score"),
                            "homeAway":c.get("homeAway"),"linescores":c.get("linescores")}
                            for c in (event.get("competitions") or [{}])[0].get("competitors",[])]}
def plays_from(summary):
    plays=summary.get("plays",[])
    if isinstance(plays,dict): plays=plays.get("plays",[])
    return plays if isinstance(plays,list) else []
def compact(p):
    return {"id":str(p.get("id") or p.get("sequenceNumber") or ""),"period":p.get("period"),
            "clock":p.get("clock"),"homeScore":p.get("homeScore"),
            "awayScore":p.get("awayScore"),"text":p.get("text")}
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--league",required=True);ap.add_argument("--date",required=True)
    ap.add_argument("--teams",required=True);ap.add_argument("--minutes",type=int,default=270)
    args=ap.parse_args()
    out=Path("results");out.mkdir(exist_ok=True)
    log=out/"observations.ndjson"
    teams=set(args.teams.split(","));root=BASE+args.league+"/"
    eid=None;seen=set();versions={};scores=[];counts={"success":0,"errors":0}
    stop=time.monotonic()+args.minutes*60;final_at=None
    while time.monotonic()<stop:
        start=time.monotonic()
        at=datetime.datetime.now(datetime.timezone.utc).isoformat()
        try:
            board=fetch(root+"scoreboard?dates="+args.date+"&limit=100")
            event=event_for(board,teams)
            if event:
                eid=event["id"];s=slim(event);scores.append(s)
                save(log,{"at":at,"type":"scoreboard","data":s})
                if s["status"]=="STATUS_FINAL":
                    if final_at is None: final_at=time.monotonic()
                else: final_at=None
            else: save(log,{"at":at,"type":"not_found"})
            counts["success"]+=1
        except Exception as ex:
            counts["errors"]+=1;save(log,{"at":at,"type":"error","endpoint":"scoreboard","message":str(ex)})
        if eid:
            try:
                plays=[compact(p) for p in plays_from(fetch(root+"summary?event="+eid))]
                save(log,{"at":at,"type":"plays","data":plays})
                for p in plays:
                    seen.add(p["id"]);versions.setdefault(p["id"],set()).add(json.dumps(p,sort_keys=True))
            except Exception as ex:
                counts["errors"]+=1;save(log,{"at":at,"type":"error","endpoint":"summary","message":str(ex)})
        if final_at and time.monotonic()-final_at>180: break
        time.sleep(max(0,7-(time.monotonic()-start)))
    report={"league":args.league,"date":args.date,"teams":args.teams,"event_id":eid,
            "scoreboard_requests_ok":counts["success"],"errors":counts["errors"],
            "scoreboard_observations":len(scores),"unique_plays_observed":len(seen),
            "changed_play_ids":sum(len(v)>1 for v in versions.values()),
            "final_status":scores[-1]["status"] if scores else "unavailable"}
    if eid:
        try:
            final=[compact(p) for p in plays_from(fetch(root+"summary?event="+eid))]
            final_ids={p["id"] for p in final}
            report.update(final_play_count=len(final),final_plays_never_observed=len(final_ids-seen),
                          observed_plays_missing_from_final=len(seen-final_ids))
            (out/"final_plays.json").write_text(json.dumps(final,indent=2))
        except Exception as ex: report["final_fetch_error"]=str(ex)
    (out/"report.json").write_text(json.dumps(report,indent=2))
    (out/"report.md").write_text("# ESPN feed test\n\n"+ "\n".join("- **"+k+"**: "+str(v) for k,v in report.items())+
        "\n\nCaution: no independent event-time ground truth; this does not measure true feed latency. "+
        "If final_status is not STATUS_FINAL, rerun reconciliation after the game.\n")
    print(json.dumps(report,indent=2))
if __name__=="__main__": main()
