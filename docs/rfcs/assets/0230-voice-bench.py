import time, os, json, statistics as st
os.environ["HF_HUB_OFFLINE"]="1"
t=time.perf_counter()
from kokoro import KPipeline, KModel
imp=time.perf_counter()-t
t=time.perf_counter()
m = KModel(config="models/kokoro/config.json", model="models/kokoro/kokoro-v1_0.pth", repo_id="hexgrad/Kokoro-82M").eval()
p = KPipeline(lang_code="b", model=m, repo_id="hexgrad/Kokoro-82M")
load=time.perf_counter()-t
V="models/kokoro/voices/bm_daniel.pt"
def run(s):
    t=time.perf_counter(); a=[x.audio for x in p(s, voice=V)]; return time.perf_counter()-t, sum(len(x) for x in a)/24000
res={"import_s":round(imp,3),"model_plus_pipeline_load_s":round(load,3)}
first=run("Right away.")
res["first_call_right_away_s"]=round(first[0],3)
for label,s in [("right_away","Right away."),("sentence_57c","Right away. RAM is temporary, while storage is permanent.")]:
    xs=[run(s) for _ in range(7)]
    res[label]={"median_s":round(st.median(x[0] for x in xs),3),"min_s":round(min(x[0] for x in xs),3),"audio_s":round(xs[0][1],2)}
from faster_whisper import WhisperModel
loads=[];tr=[]
for _ in range(5):
    t=time.perf_counter(); w=WhisperModel("models/whisper-base", local_files_only=True); loads.append(time.perf_counter()-t)
    t=time.perf_counter(); seg,_=w.transcribe("utt.wav"); " ".join(x.text for x in seg); tr.append(time.perf_counter()-t)
res["whisper_base_load_per_call_s"]={"median":round(st.median(loads),3),"max":round(max(loads),3)}
res["whisper_base_transcribe_3p8s_audio_s"]={"median":round(st.median(tr),3),"min":round(min(tr),3)}
print(json.dumps(res))
