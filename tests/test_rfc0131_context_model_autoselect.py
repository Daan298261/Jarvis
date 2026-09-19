from app.inference.context_model_select import select_profile_for_context, profile_context_limit
from app.inference.runtime_profiles import RuntimeProfile
from app.persona.inference_context import model_lane_event_payload, runtime_role_for_lane

def _rt(n,c):
    return RuntimeProfile(id=n,name=n,label=n,model=n,provider="local-llama",endpoint="127.0.0.1:8088",context_limit=c,quantization="Q4",privacy_class="local-only",cost_ceiling_usd=0.0,model_profile=n,enabled=True)

def test_pick_larger():
    cur=_rt("fast",8192); big=_rt("balanced",32768)
    assert profile_context_limit(select_profile_for_context(20000,[cur,big],cur))==32768

def test_attribution():
    assert "front_responder" in model_lane_event_payload(lane="front",model="m",text="t")
    assert runtime_role_for_lane("worker")=="worker"
