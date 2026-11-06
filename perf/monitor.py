import sys, time, json, signal, psutil
p = psutil.Process(int(sys.argv[1])); out = sys.argv[2]
cpu, rss = [], []
stop = False
def h(*a):
    global stop; stop = True
signal.signal(signal.SIGINT, h)
p.cpu_percent(None); rss0 = p.memory_info().rss
while not stop:
    time.sleep(0.25)
    try:
        cpu.append(p.cpu_percent(None)); rss.append(p.memory_info().rss)
    except psutil.Error:
        break
busy = [c for c in cpu if c > 1]
res = {"rss_start_mb": round(rss0/2**20, 1), "rss_peak_mb": round(max(rss)/2**20, 1),
       "rss_end_mb": round(rss[-1]/2**20, 1), "cpu_mean_pct": round(sum(cpu)/len(cpu), 1),
       "cpu_p95_pct": round(sorted(cpu)[int(.95*len(cpu))], 1), "cpu_seconds": round(sum(cpu)/100*0.25, 1),
       "samples": len(cpu)}
json.dump(res, open(out, "w"))
