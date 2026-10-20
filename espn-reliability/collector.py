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
    """Extract all available ESPN play records. CFB stores plays within drives."""
    plays=summary.get("plays")
    if isinstance(plays,list): return plays
    if isinstance(plays,dict) and isinstance(plays.get("plays"),list):
        return plays["plays"]
    drives=summary.get("drives") or {}
    if isinstance(drives,dict):
        result=[]
        for section in ("previous","current"):
            items=drives.get(section) or []
            if isinstance(items,dict): items=[items]
            if isinstance(items,list):
                for drive in items:
                    if isinstance(drive,dict):
                        result.extend(p for p in (drive.get("plays") or []) if isinstance(p,dict))
        # Sections can overlap at a transition. Prefer ID deduplication.
        unique={}
        for p in result:
            key=str(p.get("id") or (p.get("sequenceNumber"),p.get("text")))
            unique[key]=p
        return list(unique.values())
    return []
def play_order(p):
    period=p.get("period") or {}
    clock=p.get("clock") or {}
    q=period.get("number",0) if isinstance(period,dict) else period
    stamp=clock.get("displayValue","") if isinstance(clock,dict) else str(clock)
    try: seconds=sum(float(x)*60**i for i,x in enumerate(reversed(stamp.split(":"))))
    except (TypeError,ValueError): seconds=0
    return (int(q or 0),-seconds)
def scoreboard_final(event):
    return event.get("status",{}).get("type",{}).get("name")=="STATUS_FINAL"
def compare_final(plays,event):
    comps=(event.get("competitions") or [{}])[0].get("competitors",[])
    scores={c.get("homeAway"):c.get("score") for c in comps}
    scored=[p for p in plays if p.get("homeScore") is not None and p.get("awayScore") is not None]
    if not scored:return None
    try:
        last=scored[-1]
        return int(last["homeScore"])==int(scores["home"]) and int(last["awayScore"])==int(scores["away"])
    except (TypeError,ValueError,KeyError):return None
def compact(p):
    return {"id":str(p.get("id") or p.get("sequenceNumber") or ""),"sequenceNumber":p.get("sequenceNumber"),"period":p.get("period"),
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
    eid=None;seen=set();versions={};scores=[];counts={"success":0,"errors":0,"summary_ok":0,"summary_empty":0};event_latest=None;last_play_source=None
    stop=time.monotonic()+args.minutes*60;final_at=None
    while time.monotonic()<stop:
        start=time.monotonic()
        at=datetime.datetime.now(datetime.timezone.utc).isoformat()
        try:
            board=fetch(root+"scoreboard?dates="+args.date+"&limit=100")
            event=event_for(board,teams)
            if event:
                eid=event["id"];event_latest=event;s=slim(event);scores.append(s)
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
                summary=fetch(root+"summary?event="+eid)
                raw=plays_from(summary)
                plays=sorted([compact(p) for p in raw],key=play_order)
                counts["summary_ok"]+=1
                if not raw:
                    counts["summary_empty"]+=1
                    save(log,{"at":at,"type":"warning","message":"No plays extracted from ESPN summary","summary_keys":list(summary)})
                save(log,{"at":at,"type":"plays","data":plays})
                for p in plays:
                    seen.add(p["id"]);versions.setdefault(p["id"],set()).add(json.dumps(p,sort_keys=True))
            except Exception as ex:
                counts["errors"]+=1;save(log,{"at":at,"type":"error","endpoint":"summary","message":str(ex)})
        if final_at and time.monotonic()-final_at>180: break
        time.sleep(max(0,7-(time.monotonic()-start)))
    report={"league":args.league,"date":args.date,"teams":args.teams,"event_id":eid,
            "scoreboard_requests_ok":counts["success"],"errors":counts["errors"],
            "summary_requests_ok":counts["summary_ok"],"empty_play_snapshots":counts["summary_empty"],
            "scoreboard_observations":len(scores),"unique_plays_observed":len(seen),
            "changed_play_ids":sum(len(v)>1 for v in versions.values()),
            "final_status":scores[-1]["status"] if scores else "unavailable"}
    if eid:
        try:
            final=sorted([compact(p) for p in plays_from(fetch(root+"summary?event="+eid))],key=play_order)
            final_ids={p["id"] for p in final}
            report.update(final_play_count=len(final),final_plays_never_observed=len(final_ids-seen),
                          observed_plays_missing_from_final=len(seen-final_ids),
                          final_score_matches_plays=compare_final(final,event_latest) if event_latest else None)
            (out/"final_plays.json").write_text(json.dumps(final,indent=2))
        except Exception as ex: report["final_fetch_error"]=str(ex)
    report["validation_status"]=("FAIL_NO_GAME" if not eid else
       "FAIL_NO_PLAYS" if len(seen)==0 or report.get("final_play_count",0)==0 else
       "WARN_FINAL_SCORE_MISMATCH" if report.get("final_status")=="STATUS_FINAL" and report.get("final_score_matches_plays") is False else
       "PASS_WITH_ERRORS" if counts["errors"] or counts["summary_empty"] else "PASS")
    (out/"report.json").write_text(json.dumps(report,indent=2))
    (out/"report.md").write_text("# ESPN feed test\n\n"+ "\n".join("- **"+k+"**: "+str(v) for k,v in report.items())+
        "\n\nCaution: no independent event-time ground truth; this does not measure true feed latency. "+
        "If final_status is not STATUS_FINAL, rerun reconciliation after the game.\n")
    print(json.dumps(report,indent=2))
    if report["validation_status"].startswith("FAIL"): raise SystemExit(1)
if __name__=="__main__": main()
