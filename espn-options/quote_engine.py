"""Experimental ESPN exotic-options quote engine. All prices are simulated, NOT market quotes."""
import argparse, csv, datetime as dt, json, math, random, time, urllib.request
from pathlib import Path

ROOT="https://site.api.espn.com/apis/site/v2/sports/"
def get(url):
    req=urllib.request.Request(url,headers={"User-Agent":"ESPN-options-research/0.1"})
    with urllib.request.urlopen(req,timeout=20) as res: return json.load(res)
def competitors(event):
    return (event.get("competitions") or [{}])[0].get("competitors",[])
def number(v):
    try:return float(v or 0)
    except (ValueError,TypeError): return 0.0
def recent_plays(summary):
    p=summary.get("plays",[])
    return p.get("plays",[]) if isinstance(p,dict) else (p if isinstance(p,list) else [])
def observed_scores(plays,home,away):
    rows=[]
    for play in plays:
        h=play.get("homeScore");a=play.get("awayScore")
        if h is not None and a is not None:
            rows.append((number(h),number(a)))
    return [(0.,0.)]+rows if rows else [(0.,0.)]
def options(path,strike,quarter_scores,average_margin=None):
    hs,as_=path[-1];diffs=[h-a for h,a in path]; totals=[h+a for h,a in path]
    high=max(diffs);low=min(diffs);avg=(sum(diffs)/len(diffs) if average_margin is None else average_margin)
    final=diffs[-1];total=totals[-1]
    qh,qa=quarter_scores
    return {
      "home_win_digital_100":100.*(final>0),
      "away_win_digital_100":100.*(final<0),
      "home_comeback_15_100":100.*(low<=-15 and final>0),
      "away_comeback_15_100":100.*(high>=15 and final<0),
      "home_15_lead_one_touch_100":100.*(high>=15),
      "away_15_lead_one_touch_100":100.*(low<=-15),
      "home_margin_call_K5":max(final-5,0),
      "away_margin_call_K5":max(-final-5,0),
      "total_points_call_K"+str(strike):max(total-strike,0),
      "lookback_home_max_lead_call_K10":max(high-10,0),
      "lookback_away_max_lead_call_K10":max(-low-10,0),
      "average_margin_home_call_K0":max(avg,0),
      "double_no_touch_15_100":100.*(high<15 and low>-15),
      "home_rainbow_best_quarter":max(qh) if qh else 0,
      "away_rainbow_best_quarter":max(qa) if qa else 0,
      "home_cliquet_quarters_K7":sum(max(x-7,0) for x in qh),
      "away_cliquet_quarters_K7":sum(max(x-7,0) for x in qa),
      "quanto_home_win_times_max_lead":(high if final>0 else 0),
      "home_basket_points_plus_margin":max(hs+final-80,0),
    }
def simulate(home,away,paths,n,remaining,rate,period=4):
    rng=random.Random(337)
    result=[];ticks=max(1,min(120,int(remaining/2)))
    step=remaining/ticks
    for _ in range(n):
        h=home;a=away;p=paths[:]
        qh=[0.]*period;qa=[0.]*period
        for i in range(ticks):
            # Small-increment Poisson event model, tuned only to broad sport scoring scale.
            lam=max(0.01,rate*step/2)
            dh=sum(1 for _ in range(max(1,int(lam*7)))) if False else 0
            # Knuth Poisson sampler. Typical lambda < 3.
            for side in range(2):
                l=math.exp(-min(lam,40));k=0;prod=1.
                while prod>l:
                    k+=1;prod*=rng.random()
                x=k-1
                if side==0:h+=x;qh[min(period-1,int(i/ticks*period))]+=x
                else:a+=x;qa[min(period-1,int(i/ticks*period))]+=x
            p.append((h,a))
        result.append((p,(qh,qa)))
    return result
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--league",default="football/college-football")
    ap.add_argument("--date",default=dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d"))
    ap.add_argument("--teams",default="ALA,TENN;AUB,UGA;MIZ,MISS")
    ap.add_argument("--minutes",type=int,default=90)
    ap.add_argument("--interval",type=int,default=20)
    ap.add_argument("--samples",type=int,default=2500)
    args=ap.parse_args()
    out=Path("options-results");out.mkdir(exist_ok=True)
    fp=out/"quotes.ndjson"
    games=[set(x.strip().split(",")) for x in args.teams.split(";") if x.strip()]
    rate=0.8 if args.league.startswith("football/") else 4.5
    duration=60. if args.league.startswith("football/") else 48.
    target_total=50 if args.league.startswith("football/") else 225
    start=time.monotonic();done=set()
    while time.monotonic()-start<args.minutes*60:
        now=dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            board=get(ROOT+args.league+"/scoreboard?dates="+args.date+"&limit=150")
            for event in board.get("events",[]):
                competitors_=competitors(event)
                ids={c.get("team",{}).get("abbreviation") for c in competitors_}
                if not any(g<=ids for g in games):continue
                eid=str(event["id"])
                if eid in done:continue
                home=next((c for c in competitors_ if c.get("homeAway")=="home"),None)
                away=next((c for c in competitors_ if c.get("homeAway")=="away"),None)
                if not home or not away:continue
                h=number(home.get("score"));a=number(away.get("score"))
                status=event.get("status",{})
                typ=status.get("type",{}).get("name","unknown")
                period=int(status.get("period",0) or 0)
                clock=status.get("displayClock","")
                minute_left=duration if period<=0 else max(0.,duration-(period-1)*duration/4)
                if period>0:
                    minute_left=max(0.,duration-period*duration/4)
                    try:
                        mm,ss=clock.split(":")[:2]
                        minute_left+=float(mm)+float(ss)/60
                    except Exception:minute_left+=duration/8
                if typ=="STATUS_FINAL":minute_left=0
                try:summary=get(ROOT+args.league+"/summary?event="+eid)
                except Exception:summary={}
                past=observed_scores(recent_plays(summary),h,a)
                if len(past)<=1:past=[(0.,0.),(h,a)]
                if typ=="STATUS_FINAL":
                    scenarios=[(past,([0.]*4,[0.]*4))]
                    done.add(eid)
                else:
                    scenarios=simulate(h,a,past,args.samples,minute_left,rate)
                names=None;raw=[]
                for p,q in scenarios:
                    d=options(p,target_total,q)
                    if names is None:names=list(d)
                    raw.append(d)
                for name in names:
                    vals=sorted(v[name] for v in raw)
                    rec={"observed_at":now,"league":args.league,"event_id":eid,
                         "matchup":away["team"]["abbreviation"]+" @ "+home["team"]["abbreviation"],
                         "status":typ,"period":period,"clock":clock,"home_score":h,"away_score":a,
                         "historic_plays_with_scores":len(past)-1,"option":name,
                         "price":round(sum(vals)/len(vals),3),
                         "p_positive":round(sum(x>0 for x in vals)/len(vals),4),
                         "p05":round(vals[int(.05*(len(vals)-1))],3),
                         "p95":round(vals[int(.95*(len(vals)-1))],3),
                         "samples":len(vals),"model":"independent Poisson points, illustrative only"}
                    with fp.open("a") as f:f.write(json.dumps(rec)+"\n")
                print(now,eid,typ,"options",len(names),flush=True)
        except Exception as e:
            with (out/"errors.ndjson").open("a") as f:f.write(json.dumps({"at":now,"error":str(e)})+"\n")
            print("ERROR",str(e),flush=True)
        time.sleep(args.interval)
    if fp.exists():
        rows=[json.loads(line) for line in fp.read_text().splitlines()]
        with (out/"quotes_latest.csv").open("w",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader()
            latest={(r["event_id"],r["option"]):r for r in rows}
            writer.writerows(latest.values())
        (out/"README.md").write_text("# Experimental exotic-options quotes\n\n"+
            "These are **NOT real-money prices or calibrated forecasts**. Prices are sample-mean payoffs "+
            "from an intentionally simple independent-Poisson continuation model. Historical play arrays "+
            "may omit plays, and the sampled future path uses 2-minute increments, not actual scoring plays. "+
            "Options tied to 15-point barriers are only illustrative until verified against full play-by-play. "+
            "Football scoring is incorrectly modeled as point increments; use only as pipeline validation. "+
            "No bids/asks, transaction costs or uncertainty calibration are included.\n")
if __name__=="__main__":main()
